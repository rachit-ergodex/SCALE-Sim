"""Static lifetime allocation for bounded, byte-addressed intermediate SRAM.

Only complete, initialized transient tensors without asynchronous DMA users are
eligible. External parameters/KV, selected-token output and large tensors stay
in HBM. No arithmetic or logical memory access is reordered or dropped.
"""
from bisect import bisect_right
from collections import defaultdict
from math import ceil

MAX_TENSOR_BYTES=32768


def plan_residency(commands, manifest, capacity, bytes_per_cycle):
    if capacity<0 or capacity%32 or bytes_per_cycle<=0:
        raise ValueError('Invalid SRAM capacity or port width')
    lines=[line.split() for line in commands.splitlines()]
    tensors=manifest['tensors'];bases=[t['address'] for t in tensors]
    accesses=defaultdict(list);invalid=set()
    for index,line in enumerate(lines):
        action=line[3]
        if action not in ('R','W','P0','P1'):continue
        address,size,count,stride=map(int,line[4:]);slot=bisect_right(bases,address)-1
        if slot<0:continue
        t=tensors[slot];end=t['address']+t['size']*t['width']
        if address+(count-1)*stride+size>end:invalid.add(slot)
        if action.startswith('P'):invalid.add(slot)
        accesses[slot].append((index,action,address-t['address'],size,count,stride))
    candidates=[]
    for slot,events in accesses.items():
        t=tensors[slot];size=t['size']*t['width']
        if slot in invalid or t['address']<manifest['preallocated_parameter_and_cache_bytes'] or size>MAX_TENSOR_BYTES or t['name']=='selected_token':continue
        written=bytearray(size);safe=True
        for _,action,offset,width,count,stride in events:
            for row in range(count):
                start=offset+row*stride
                if action=='W':written[start:start+width]=b'\1'*width
                elif not all(written[start:start+width]):safe=False;break
            if not safe:break
        if safe:candidates.append((events[0][0],events[-1][0],slot,ceil(size/32)*32))
    free=[(0,capacity)] if capacity else [];active=[];allocations=[];replacements={};peak=0
    for first,last,slot,size in sorted(candidates):
        expired=[a for a in active if a['last_command']<first]
        active=[a for a in active if a['last_command']>=first]
        free.extend((a['sram_offset'],a['allocated_bytes']) for a in expired)
        merged=[]
        for offset,length in sorted(free):
            if merged and merged[-1][0]+merged[-1][1]==offset:
                old,n=merged[-1];merged[-1]=(old,n+length)
            else:merged.append((offset,length))
        free=merged
        chosen=next((i for i,(_,length) in enumerate(free) if length>=size),None)
        if chosen is None:continue
        offset,length=free.pop(chosen)
        if length>size:free.append((offset+size,length-size))
        allocation=dict(tensor=slot,address=tensors[slot]['address'],name=tensors[slot]['name'],
                        first_command=first,last_command=last,sram_offset=offset,allocated_bytes=size)
        allocations.append(allocation);active.append(allocation)
        peak=max(peak,sum(a['allocated_bytes'] for a in active))
        for index,action,relative,width,count,stride in accesses[slot]:
            replacements[index]=dict(action=action,address=tensors[slot]['address']+relative,
                bytes=width,count=count,stride=stride,sram_offset=offset+relative,
                cycles=ceil(width*count/bytes_per_cycle),tensor=slot)
    total=0
    for index,access in replacements.items():
        line=lines[index];op=manifest['ops'][int(line[1])];amount=access['bytes']*access['count']
        key='write_bytes' if access['action']=='W' else 'read_bytes'
        op[key]-=amount;assert op[key]>=0
        op['sram_'+key]=op.get('sram_'+key,0)+amount
        op['compute_cycles']+=access['cycles'];total+=amount
        lines[index]=line[:3]+['C',str(access['cycles']),'0','0','0']
    report=dict(capacity_bytes=capacity,peak_live_bytes=peak,bytes_per_cycle=bytes_per_cycle,
                max_tensor_bytes=MAX_TENSOR_BYTES,allocations=allocations,
                local_accesses={str(k):v for k,v in replacements.items()},avoided_logical_HBM_bytes=total)
    return '\n'.join(' '.join(line) for line in lines)+'\n',report
