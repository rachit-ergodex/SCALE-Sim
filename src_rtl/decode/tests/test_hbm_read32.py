"""All-port concurrency, credit exhaustion, reordering and protocol errors."""
from collections import deque
import hashlib
import random
import struct

import cocotb
from cocotb.triggers import Timer

ALL=(1<<32)-1

def pack(values,width):return sum(int(value)<<(i*width) for i,value in enumerate(values))
def unpack(signal,width):
    value=int(signal.value);mask=(1<<width)-1
    return [(value>>(i*width))&mask for i in range(32)]
def data_for(port,line,tag):return int.from_bytes(hashlib.sha256(struct.pack('<III',port,line,tag)).digest(),'little')

async def edge(d):
    d.clk.value=0;await Timer(5,unit='ns');d.clk.value=1;await Timer(5,unit='ns')

async def reset(d):
    for name in ('req_valid','req_line','req_tag','m_arready','m_rdata','m_rid','m_rresp','m_rlast','m_rvalid'):
        getattr(d,name).value=0
    d.rsp_ready.value=0;d.enable.value=0;d.rst.value=1
    await edge(d);d.rst.value=0;d.enable.value=1;await Timer(1,unit='ns')
    assert int(d.fault.value)==0 and int(d.outstanding.value)==0

async def workload(d,count,stress):
    await reset(d);rng=random.Random(0xA11+stress)
    sent=[0]*32;received=[0]*32;accepted=[deque() for _ in range(32)]
    active=[{} for _ in range(32)];held=[None]*32;ar_held=[None]*32;peaks=[0]*32
    max_parallel=full_rate_cycles=0
    for cycle in range(3000):
        request_lines=[((sent[p]*53+p*97)&((1<<24)-1)) for p in range(32)]
        # Exercise the final line of every physical 512-MiB aperture.
        request_lines=[(1<<24)-1 if sent[p]==0 else request_lines[p] for p in range(32)]
        tags=[(p<<24)|sent[p] for p in range(32)]
        valid=sum((sent[p]<count)<<p for p in range(32))
        d.req_valid.value=valid;d.req_line.value=pack(request_lines,24);d.req_tag.value=pack(tags,32)
        arready=ALL if not stress or cycle<100 else sum((rng.random()<.75)<<p for p in range(32))
        rspready=ALL if not stress else sum((rng.random()<.7)<<p for p in range(32))
        for p in range(32):
            if held[p] is None and active[p] and (not stress or cycle>=100) and (not stress or rng.random()<.8):
                ident=rng.choice(list(active[p])) if stress else next(iter(active[p]))
                held[p]=(ident,active[p][ident][1])
        rvalid=sum((held[p] is not None)<<p for p in range(32))
        d.m_arready.value=arready;d.rsp_ready.value=rspready
        d.m_rvalid.value=rvalid;d.m_rlast.value=rvalid;d.m_rresp.value=0
        d.m_rid.value=pack([h[0] if h else 0 for h in held],6)
        d.m_rdata.value=pack([h[1] if h else 0 for h in held],256)
        await Timer(1,unit='ns')
        reqready=int(d.req_ready.value);arvalid=int(d.m_arvalid.value)
        arids=unpack(d.m_arid,6);addresses=unpack(d.m_araddr,34)
        rspvalid=int(d.rsp_valid.value);rready=int(d.m_rready.value)
        rsptags=unpack(d.rsp_tag,32);rspdata=unpack(d.rsp_data,256)
        assert int(d.fault.value)==0 and (int(d.rsp_error.value)&rspvalid)==0
        assert int(d.m_arlen.value)==0
        assert unpack(d.m_arsize,3)==[5]*32 and unpack(d.m_arburst,2)==[1]*32
        parallel=0
        for p in range(32):
            if ar_held[p] is not None:assert (arids[p],addresses[p])==ar_held[p] and arvalid>>p&1
            ar_held[p]=(arids[p],addresses[p]) if arvalid>>p&1 and not arready>>p&1 else None
            if rspvalid>>p&1 and rspready>>p&1:
                ident,value=held[p];tag,expected=active[p].pop(ident)
                assert rsptags[p]==tag and rspdata[p]==expected==value
                received[p]+=1;held[p]=None;parallel+=1
            assert bool(rspvalid>>p&1)==bool(rvalid>>p&1)
            if arvalid>>p&1 and arready>>p&1:
                line,tag=accepted[p].popleft();ident=arids[p]
                assert ident not in active[p]
                assert addresses[p]==(p<<29)|(line<<5)
                active[p][ident]=(tag,data_for(p,line,tag))
            if valid>>p&1 and reqready>>p&1:
                accepted[p].append((request_lines[p],tags[p]));sent[p]+=1
        max_parallel=max(max_parallel,parallel);full_rate_cycles+=parallel==32
        await edge(d)
        outstanding=unpack(d.outstanding,7)
        for p in range(32):
            assert outstanding[p]==sent[p]-received[p] and outstanding[p]<=64
            peaks[p]=max(peaks[p],outstanding[p])
        if all(x==count for x in received):break
    else:raise AssertionError('All-port workload timeout')
    assert all(not x for x in active) and all(not x for x in accepted)
    if stress:assert peaks==[64]*32 and max_parallel>1
    else:assert max_parallel==32 and full_rate_cycles==count and cycle<count+8
    d._log.info('32-port workload: count=%d stress=%s cycles=%d full-rate=%d',count,stress,cycle+1,full_rate_cycles)

@cocotb.test()
async def all_ports_and_faults(d):
    await workload(d,256,False)
    await workload(d,160,True)
    # A stray response must be drained, flagged, and never delivered as valid data.
    await reset(d);d.rsp_ready.value=ALL;d.m_rvalid.value=1<<7;d.m_rlast.value=1<<7
    await Timer(1,unit='ns');assert int(d.rsp_valid.value)==0 and int(d.m_rready.value)&(1<<7)
    await edge(d);assert int(d.fault.value)==1<<7
    d.m_rvalid.value=0;await Timer(1,unit='ns')
    assert int(d.req_ready.value)==ALL^(1<<7)
    # Known responses with RRESP errors or missing RLAST return error to the owner.
    for response,last in [(2,1),(0,0)]:
        await reset(d);d.req_valid.value=1;d.req_line.value=123;d.req_tag.value=456
        await edge(d);d.req_valid.value=0;d.m_arready.value=1
        ident=int(d.m_arid.value)&63;await edge(d)
        d.m_rvalid.value=1;d.m_rlast.value=last;d.m_rresp.value=response;d.m_rid.value=ident
        d.m_rdata.value=789;d.rsp_ready.value=1
        await Timer(1,unit='ns')
        assert int(d.rsp_valid.value)&1 and int(d.rsp_error.value)&1
        assert int(d.rsp_tag.value)&((1<<32)-1)==456 and int(d.rsp_data.value)&((1<<256)-1)==789
        await edge(d);assert int(d.fault.value)==1 and int(d.outstanding.value)==0
    await reset(d)
