"""Descriptor boundaries, wrapped tags and fault delivery across both clocks."""
from collections import deque
import hashlib
import os
import struct

import cocotb
from cocotb.triggers import Timer

MASK32=(1<<32)-1
RECORDS=int(os.environ.get('RETURN_RECORDS','2'))
CORE_PERIOD=int(os.environ.get('CORE_PERIOD_PS','4000'))

def payload(line,tag):
    return int.from_bytes(hashlib.sha256(struct.pack('<II',line,tag)).digest(),'little')

class Clocks:
    """Sample handshakes before either active edge, including coincident edges."""
    def __init__(self,d):
        self.d=d;self.now=0;self.next_core=CORE_PERIOD//2;self.next_hbm=1111
        self.core_level=0;self.hbm_level=0
        d.core_clk.value=0;d.hbm_clk.value=0

    async def step(self):
        when=min(self.next_core,self.next_hbm)
        if when>self.now:await Timer(when-self.now,unit='ps')
        self.now=when
        core=self.next_core==when;hbm=self.next_hbm==when
        result={}
        if core and not self.core_level:
            result['core']={name:int(getattr(self.d,name).value) for name in (
                'desc_valid','desc_ready','return_valid','return_ready','return_mask',
                'return_data','return_tag','return_error','fault_core')}
        if hbm and not self.hbm_level:
            result['hbm']={name:int(getattr(self.d,name).value) for name in (
                'm_arvalid','m_arready','m_araddr','m_arid','m_rvalid','m_rready','outstanding')}
        if core:
            self.core_level^=1;self.d.core_clk.value=self.core_level;self.next_core+=CORE_PERIOD//2
        if hbm:
            self.hbm_level^=1;self.d.hbm_clk.value=self.hbm_level;self.next_hbm+=1111
        await Timer(1,unit='ps');self.now+=1
        return result

async def scenario(d,descriptors,*,overflow=False,error=None,sparse=False,stall=False,expected_mask=None,fill_credits=False):
    """Lengths are numbers of lines; error is (tag, RRESP, RLAST)."""
    clocks=Clocks(d)
    d.core_rst.value=1;d.hbm_rst.value=1;d.hbm_enable.value=0
    for name in ('desc_valid','desc_line','desc_len','desc_tag','return_ready','m_arready',
                 'm_rdata','m_rid','m_rresp','m_rlast','m_rvalid'):
        getattr(d,name).value=0
    while clocks.now<30000:await clocks.step()
    d.core_rst.value=0;d.hbm_rst.value=0;d.hbm_enable.value=1
    pending=deque(descriptors);offered=None;accepted={};active={};held=None
    expected={};received=set();hbm_cycle=0;issued_count=0;fault_seen=False;packet_masks=set()
    issued_ids=[];returned_ids=[];max_outstanding=0;response_stalls=0;held_return=None
    for line,length,tag in descriptors:
        if line+length-1>0xffffff:continue
        for offset in range(length):
            actual_tag=(tag+offset)&MASK32
            assert actual_tag not in expected,'This test must use unique live tags'
            expected[actual_tag]=(payload(line+offset,actual_tag),
                int(error is not None and actual_tag==error[0]))
    if fill_credits:assert len(expected)==64,'Credit-fill scenario must issue all 64 IDs'
    for _ in range(30000):
        if offered is None and pending:offered=pending.popleft()
        d.desc_valid.value=int(offered is not None)
        if offered:
            d.desc_line.value=offered[0];d.desc_len.value=offered[1]-1;d.desc_tag.value=offered[2]
        d.m_arready.value=1
        d.return_ready.value=int(not stall or hbm_cycle>(300 if fill_credits else 100))
        # Fault tests defer responses until every valid request is outstanding,
        # making it possible to verify that a fault does not prevent draining.
        can_respond=(error is None and not fill_credits) or issued_count==len(expected)
        if held is None and active and can_respond and (not sparse or hbm_cycle%31==0):
            ident=next(reversed(active));line,tag=active[ident]
            resp,last=(error[1],error[2]) if error is not None and tag==error[0] else (0,1)
            held=(ident,tag,payload(line,tag),resp,last)
        d.m_rvalid.value=int(held is not None)
        if held:
            d.m_rid.value=held[0];d.m_rdata.value=held[2];d.m_rresp.value=held[3];d.m_rlast.value=held[4]
        observation=await clocks.step()
        if 'core' in observation:
            c=observation['core']
            if fault_seen:assert c['fault_core'],'Fault must remain sticky until coordinated reset'
            fault_seen|=bool(c['fault_core'])
            current_return=tuple(c[name] for name in ('return_valid','return_mask','return_data','return_tag','return_error'))
            if held_return is not None:
                assert current_return==held_return,'Return packet changed while the core was stalled'
            held_return=current_return if c['return_valid'] and not c['return_ready'] else None
            if c['desc_valid'] and c['desc_ready']:
                line,length,tag=offered
                if line+length-1<=0xffffff:
                    for offset in range(length):accepted[line+offset]=(tag+offset)&MASK32
                offered=None
            if c['return_valid'] and c['return_ready']:
                assert c['return_mask'] in [(1<<count)-1 for count in range(1,RECORDS+1)]
                packet_masks.add(c['return_mask'])
                for lane in range(RECORDS):
                    if c['return_mask']>>lane&1:
                        tag=(c['return_tag']>>(32*lane))&MASK32
                        value=(c['return_data']>>(256*lane))&((1<<256)-1)
                        err=(c['return_error']>>lane)&1
                        assert tag not in received and (value,err)==expected[tag]
                        received.add(tag)
        if 'hbm' in observation:
            hbm_cycle+=1;h=observation['hbm']
            max_outstanding=max(max_outstanding,h['outstanding'])
            response_stalls+=int(h['m_rvalid'] and not h['m_rready'])
            if h['m_rvalid'] and h['m_rready']:
                assert held is not None
                returned_ids.append(held[0])
                del active[held[0]];held=None
            if h['m_arvalid'] and h['m_arready']:
                assert h['m_araddr']>>29==31 and h['m_araddr']&31==0
                line=(h['m_araddr']&((1<<29)-1))>>5
                assert line in accepted,'Invalid or repeated physical read'
                assert h['m_arid'] not in active
                active[h['m_arid']]=(line,accepted.pop(line));issued_count+=1
                issued_ids.append(h['m_arid'])
        want_fault=overflow or error is not None
        if len(received)==len(expected) and not pending and offered is None and fault_seen==want_fault:
            # Let faults and any unwanted extra issue settle before declaring done.
            if hbm_cycle<150:continue
            assert not active and not accepted and issued_count==len(expected)
            assert int(d.outstanding.value)==0
            if sparse:assert 1 in packet_masks
            if expected_mask is not None:assert expected_mask in packet_masks
            if fill_credits:
                assert max_outstanding==64 and set(issued_ids)==set(range(64))
                assert returned_ids==list(reversed(issued_ids)),'Expected every ID in reverse issue order'
                assert response_stalls>0,'Return FIFO never exerted backpressure on HBM'
            return
    raise AssertionError(f'Bridge timeout: returned {len(received)}/{len(expected)}, fault={fault_seen}')

@cocotb.test()
async def aperture_end_and_wrapped_tags(d):
    await scenario(d,[(0xfffff0,16,0xfffffff8)],stall=True)

@cocotb.test()
async def descriptor_overflow_faults_without_partial_reads(d):
    await scenario(d,[(0,3,100),(0xffffff,2,200)],overflow=True,sparse=True)

@cocotb.test()
async def response_errors_cross_clocks_and_other_reads_drain(d):
    for resp,last in ((2,1),(0,0)):
        await scenario(d,[(0,7,100)],error=(106,resp,last),stall=True)
    # Fill every ID before any response, then reverse the complete response
    # order while the small return FIFO backs up. The first response faults;
    # all remaining IDs and the final partial packet must still drain exactly.
    descriptors=[(0x800+16*group,16,0x12340000+16*group) for group in range(4)]
    for resp,last in ((2,1),(0,0)):
        await scenario(d,descriptors,error=(0x1234003f,resp,last),stall=True,
                       fill_credits=True,expected_mask=(1<<(64%RECORDS or RECORDS))-1)
        # A coordinated reset must clear the sticky fault and both CDC paths,
        # with no stale tags/data leaking into a subsequent short transaction.
        await scenario(d,[(0x1234,RECORDS-1,0xdeadbeef)],
                       expected_mask=(1<<(RECORDS-1))-1)

@cocotb.test()
async def isolated_single_returns_flush(d):
    await scenario(d,[(0,1,1),(4,1,2),(8,1,3)],sparse=True)

@cocotb.test()
async def partial_packet_flushes_without_extra_responses(d):
    await scenario(d,[(0,RECORDS-1,1)],expected_mask=(1<<(RECORDS-1))-1)
