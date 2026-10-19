"""Independent clock domains, descriptor expansion and lossless return packing."""
from collections import deque
import hashlib
import json
from pathlib import Path
import os
import random
import struct
import cocotb
from cocotb.triggers import Timer

PORTS=int(os.environ.get('HBM_PORTS','1'))
RECORDS=int(os.environ.get('RETURN_RECORDS','2'))
CORE_PERIOD=int(os.environ.get('CORE_PERIOD_PS','4000'))
HBM_PERIOD=int(os.environ.get('HBM_PERIOD_PS','2222'))
EXPECT_SATURATION=os.environ.get('EXPECT_SATURATION','0')=='1'

def pack(values,width):return sum(int(x)<<(i*width) for i,x in enumerate(values))
def unpack(signal,width):
    value=int(signal.value);return [(value>>(i*width))&((1<<width)-1) for i in range(PORTS)]
def bits(values):return sum(int(x)<<p for p,x in enumerate(values))
def golden(p,line,tag):return int.from_bytes(hashlib.sha256(struct.pack('<III',p,line,tag)).digest(),'little')

async def scenario(d,stress,phase,abort=False):
    rng=random.Random(211+stress);descriptors=[];expected=[];total=[]
    for p in range(PORTS):
        desc=[];gold={}
        for i in range(24 if stress else 128):
            length=int(rng.randrange(1,17)) if stress else 16
            line=i*32;tag=(p<<20)+i*32
            desc.append((line,length-1,tag))
            for j in range(length):gold[tag+j]=golden(p,line+j,tag+j)
        descriptors.append(deque(desc));expected.append(gold);total.append(len(gold))
    offered=[None]*PORTS;accepted=[{} for _ in range(PORTS)];active=[{} for _ in range(PORTS)];held=[None]*PORTS
    returned=[set() for _ in range(PORTS)];issued=[[] for _ in range(PORTS)]
    responses=[[] for _ in range(PORTS)];packet_counts=[{} for _ in range(PORTS)]
    d.core_clk.value=0;d.hbm_clk.value=0;d.core_rst.value=1;d.hbm_rst.value=1;d.hbm_enable.value=0
    for name in ('desc_valid','desc_line','desc_len','desc_tag','return_ready','m_arready','m_rdata','m_rid','m_rresp','m_rlast','m_rvalid'):
        getattr(d,name).value=0
    now=0;next_core=CORE_PERIOD//2;next_hbm=HBM_PERIOD//2+phase;core_level=hbm_level=0;running=False;hbm_cycle=0
    core_stalled=[None]*PORTS;ar_stalled=[None]*PORTS
    for step in range(50000):
        when=min(next_core,next_hbm)
        if when>now:await Timer(when-now,unit='ps')
        else:assert when==now
        now=when
        core_event=next_core==when;hbm_event=next_hbm==when
        if not running and now>=30000:
            d.core_rst.value=0;d.hbm_rst.value=0;d.hbm_enable.value=1;running=True
        # All handshake observations precede this time's active clock edges.
        if core_event and not core_level and running:
            dv=int(d.desc_valid.value);dr=int(d.desc_ready.value)
            rv=int(d.return_valid.value);rr=int(d.return_ready.value)
            masks=unpack(d.return_mask,RECORDS);datas=unpack(d.return_data,RECORDS*256);tags=unpack(d.return_tag,RECORDS*32);errors=unpack(d.return_error,RECORDS)
            assert int(d.fault_core.value)==0
            for p in range(PORTS):
                snapshot=(masks[p],datas[p],tags[p],errors[p])
                if core_stalled[p] is not None:assert rv>>p&1 and snapshot==core_stalled[p]
                core_stalled[p]=snapshot if rv>>p&1 and not rr>>p&1 else None
                if dv>>p&1 and dr>>p&1:
                    line,length,tag=offered[p]
                    for j in range(length+1):accepted[p][line+j]=tag+j
                    offered[p]=None
                if rv>>p&1 and rr>>p&1:
                    assert masks[p] in [(1<<count)-1 for count in range(1,RECORDS+1)]
                    packet_counts[p][masks[p]]=packet_counts[p].get(masks[p],0)+1
                    for lane in range(RECORDS):
                        if masks[p]>>lane&1:
                            tag=(tags[p]>>(32*lane))&((1<<32)-1)
                            value=(datas[p]>>(256*lane))&((1<<256)-1)
                            assert not(errors[p]>>lane&1) and tag not in returned[p]
                            assert value==expected[p][tag];returned[p].add(tag)
        if hbm_event and not hbm_level and running:
            hbm_cycle+=1;av=int(d.m_arvalid.value);ar=int(d.m_arready.value)
            addresses=unpack(d.m_araddr,34);ids=unpack(d.m_arid,6)
            rv=int(d.m_rvalid.value);rr=int(d.m_rready.value)
            for p in range(PORTS):
                if ar_stalled[p] is not None:assert av>>p&1 and (addresses[p],ids[p])==ar_stalled[p]
                ar_stalled[p]=(addresses[p],ids[p]) if av>>p&1 and not ar>>p&1 else None
                if rv>>p&1 and rr>>p&1:
                    ident=held[p][0];active[p].pop(ident);held[p]=None;responses[p].append(hbm_cycle)
                if av>>p&1 and ar>>p&1:
                    physical_port=p if PORTS==32 else 31
                    assert addresses[p]>>29==physical_port and addresses[p]&31==0
                    line=(addresses[p]&((1<<29)-1))>>5
                    tag=accepted[p].pop(line);assert ids[p] not in active[p]
                    active[p][ids[p]]=(tag,expected[p][tag]);issued[p].append(hbm_cycle)
        # Falling edges set up the next cycle; pending offers remain stable.
        if core_event and core_level and running:
            for p in range(PORTS):
                if offered[p] is None and descriptors[p] and (not stress or rng.random()<.85):offered[p]=descriptors[p].popleft()
            d.desc_valid.value=bits(x is not None for x in offered)
            d.desc_line.value=pack([x[0] if x else 0 for x in offered],24)
            d.desc_len.value=pack([x[1] if x else 0 for x in offered],4)
            d.desc_tag.value=pack([x[2] if x else 0 for x in offered],32)
            d.return_ready.value=bits(not stress or (hbm_cycle>130 and rng.random()<.6) for _ in range(PORTS))
        if hbm_event and hbm_level and running:
            for p in range(PORTS):
                if held[p] is None and active[p] and (not stress or rng.random()<.8):
                    ident=rng.choice(list(active[p])) if stress else next(iter(active[p]))
                    held[p]=(ident,active[p][ident][1])
            d.m_arready.value=bits(not stress or rng.random()<.8 for _ in range(PORTS))
            rvalid=bits(x is not None for x in held)
            d.m_rvalid.value=rvalid;d.m_rlast.value=rvalid
            d.m_rid.value=pack([x[0] if x else 0 for x in held],6)
            d.m_rdata.value=pack([x[1] if x else 0 for x in held],256)
        if core_event:core_level^=1;d.core_clk.value=core_level;next_core+=CORE_PERIOD//2
        if hbm_event:hbm_level^=1;d.hbm_clk.value=hbm_level;next_hbm+=HBM_PERIOD//2
        await Timer(1,unit='ps');now+=1
        if abort and hbm_cycle>=150:
            assert any(len(returned[p])<total[p] for p in range(PORTS))
            return
        if all(len(returned[p])==total[p] for p in range(PORTS)):
            assert all(not x for x in active) and all(not x for x in accepted)
            spans=[times[-1]-times[0]+1 for times in responses]
            if not stress:
                if EXPECT_SATURATION:
                    assert all(span>len(times) for span,times in zip(spans,responses)), 'Negative control did not saturate'
                else:
                    for times in issued:assert times[-1]-times[0]+1==len(times),'Descriptor CDC starved the HBM port'
                    for span,times in zip(spans,responses):
                        assert span==len(times),'Return CDC throttled a continuous HBM response stream'
                    assert all((1<<RECORDS)-1 in masks for masks in packet_counts),'Full packets were not exercised'
            d._log.info('PASS %d ports, stress=%s, phase=%d ps, %d returned reads',PORTS,stress,phase,sum(total))
            return dict(stress=stress,phase_ps=phase,reads_per_port=total,
                        response_span_cycles=spans,
                        response_utilization=[len(times)/span for times,span in zip(responses,spans)],
                        packet_mask_counts=packet_counts)
    raise AssertionError('CDC bridge timeout')

@cocotb.test()
async def clocks_descriptors_and_returns(d):
    ideal=await scenario(d,False,137)
    stress=await scenario(d,True,811)
    await scenario(d,True,0,abort=True)
    reset=await scenario(d,True,0)
    metrics=os.environ.get('HBM_METRICS_PATH')
    if metrics:Path(metrics).write_text(json.dumps(dict(ideal=ideal,stress=stress,after_reset=reset),indent=2)+'\n')
