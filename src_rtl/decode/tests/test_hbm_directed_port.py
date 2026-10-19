"""Directed request lifetime and AXI response corner cases."""
import cocotb
from cocotb.triggers import Timer

async def settle():
    await Timer(1, unit='ns')

async def tick(d):
    d.clk.value=0
    await Timer(5, unit='ns')
    d.clk.value=1
    await Timer(5, unit='ns')

async def reset(d):
    d.clk.value=0; d.rst.value=1; d.enable.value=1
    for name in ('req_valid','req_line','req_tag','rsp_ready','m_arready','m_rdata','m_rid','m_rresp','m_rlast','m_rvalid'):
        getattr(d,name).value=0
    await tick(d)
    d.rst.value=0
    await settle()

async def offer(d,line,tag):
    d.req_valid.value=1; d.req_line.value=line; d.req_tag.value=tag
    await settle(); assert int(d.req_ready.value)
    await tick(d); d.req_valid.value=0
    await settle()
    assert int(d.m_arvalid.value)
    return int(d.m_arid.value)

@cocotb.test()
async def same_cycle_ar_and_r_with_next_request(d):
    await reset(d)
    ident=await offer(d,0xffffff,0xabcdef01)
    d.m_arready.value=1; d.m_rvalid.value=1; d.m_rlast.value=1
    d.m_rid.value=ident; d.m_rdata.value=(1<<255)|123; d.rsp_ready.value=1
    d.req_valid.value=1; d.req_line.value=0; d.req_tag.value=0xabcdef02
    await settle()
    assert int(d.rsp_valid.value) and int(d.req_ready.value)
    assert int(d.rsp_tag.value)==0xabcdef01
    assert int(d.rsp_data.value)==(1<<255)|123
    await tick(d)
    assert int(d.outstanding.value)==1 and not int(d.fault.value)
    ident2=int(d.m_arid.value)
    assert ident2!=ident and int(d.m_arvalid.value)
    d.req_valid.value=0; d.m_rid.value=ident2; d.m_rdata.value=456
    await settle()
    assert int(d.rsp_valid.value) and int(d.rsp_tag.value)==0xabcdef02
    await tick(d)
    assert int(d.outstanding.value)==0 and not int(d.fault.value)
    d.m_rvalid.value=0

@cocotb.test()
async def disable_preserves_stalled_ar_and_drains_response(d):
    await reset(d)
    ident=await offer(d,77,99)
    address=int(d.m_araddr.value)
    d.enable.value=0
    d.req_valid.value=1; d.req_line.value=88; d.req_tag.value=100
    for _ in range(5):
        await tick(d)
        assert not int(d.req_ready.value)
        assert int(d.m_arvalid.value) and int(d.m_arid.value)==ident and int(d.m_araddr.value)==address
    d.m_arready.value=1
    await tick(d)
    assert not int(d.m_arvalid.value)
    d.m_rvalid.value=1; d.m_rlast.value=1; d.m_rid.value=ident; d.m_rdata.value=0x1234
    d.rsp_ready.value=0
    for _ in range(5):
        await settle()
        assert int(d.rsp_valid.value) and not int(d.m_rready.value)
        assert int(d.rsp_tag.value)==99 and int(d.rsp_data.value)==0x1234
        await tick(d)
    d.rsp_ready.value=1
    await tick(d)
    assert int(d.outstanding.value)==0 and not int(d.fault.value)
    d.m_rvalid.value=0; d.req_valid.value=0; d.enable.value=1
    await settle(); assert int(d.req_ready.value)

@cocotb.test()
async def faults_drain_pending_transactions_without_id_reuse(d):
    for response,last in ((2,1),(0,0)):
        await reset(d)
        ids=[]
        for index in range(4):
            ids.append(await offer(d,100+index,200+index))
            d.m_arready.value=1
            await tick(d)
            d.m_arready.value=0
        assert int(d.outstanding.value)==4
        for index,ident in enumerate(reversed(ids)):
            d.m_rid.value=ident; d.m_rvalid.value=1; d.m_rlast.value=last if index==0 else 1
            d.m_rresp.value=response if index==0 else 0; d.m_rdata.value=index; d.rsp_ready.value=1
            await settle()
            assert int(d.rsp_valid.value)
            assert int(d.rsp_tag.value)==203-index
            assert bool(int(d.rsp_error.value))==(index==0)
            await tick(d)
            assert int(d.fault.value)==1
            assert not int(d.req_ready.value)
            assert int(d.outstanding.value)==3-index
        d.m_rvalid.value=0

@cocotb.test()
async def axi_inputs_do_not_bypass_response_backpressure(d):
    await reset(d)
    ident=await offer(d,123,456)
    # Toggle AXI inputs without a clock edge. None may create a combinational
    # bypass around the downstream ready state, including an unknown RID.
    d.rsp_ready.value=0
    for rid in (ident,(ident+1)%64):
        for arready in (0,1):
            for rvalid in (0,1):
                d.m_rid.value=rid;d.m_arready.value=arready;d.m_rvalid.value=rvalid
                await settle()
                assert not int(d.m_rready.value),'AXI input changed RREADY while downstream was stalled'
    d.m_arready.value=0;d.m_rid.value=(ident+1)%64;d.m_rvalid.value=1;d.m_rlast.value=1
    await tick(d)
    assert not int(d.fault.value),'A non-handshaken response must not fault'
    d.rsp_ready.value=1
    await settle()
    assert int(d.m_rready.value) and not int(d.rsp_valid.value)
    await tick(d)
    assert int(d.fault.value) and int(d.outstanding.value)==1

@cocotb.test()
async def stalled_unknown_rid_cannot_alias_a_new_request(d):
    d.rst.value=1;d.enable.value=1;d.clk.value=0
    for name in ('req_valid','req_line','req_tag','rsp_ready','m_arready',
                 'm_rdata','m_rid','m_rresp','m_rlast','m_rvalid'):
        getattr(d,name).value=0
    await tick(d);d.rst.value=0
    # With no allocated IDs, RID 0 is both unknown and the allocator's next
    # choice. Keep the malformed beat stalled while presenting a real request.
    d.m_rvalid.value=1;d.m_rid.value=0;d.m_rlast.value=1;d.m_rdata.value=0xdeadbeef
    d.rsp_ready.value=0;d.m_arready.value=1
    d.req_valid.value=1;d.req_line.value=123;d.req_tag.value=456
    await settle()
    for _ in range(4):
        assert not int(d.req_ready.value),'An unknown stalled RID must prevent new ID allocation'
        assert not int(d.m_rready.value) and not int(d.rsp_valid.value)
        assert int(d.outstanding.value)==0 and not int(d.m_arvalid.value)
        assert not int(d.fault.value),'Fault is reported when the malformed beat is consumed'
        await tick(d)
    # Draining the unknown beat must fault without ever delivering it under
    # the legitimate request's tag or allocating that request in the same cycle.
    d.rsp_ready.value=1
    await settle()
    assert int(d.m_rready.value) and not int(d.rsp_valid.value)
    assert not int(d.req_ready.value)
    await tick(d)
    d.m_rvalid.value=0
    await settle()
    assert int(d.fault.value) and int(d.outstanding.value)==0
    assert not int(d.req_ready.value) and not int(d.m_arvalid.value)

@cocotb.test()
async def premature_response_stays_unknown_after_ar_handshake(d):
    await reset(d)
    ident=await offer(d,100,200)
    # This RID is allocated, but its AR has not handshaken. An early response
    # sampled while ARREADY is low must remain invalid until it is consumed.
    d.m_arready.value=0;d.m_rvalid.value=1;d.m_rid.value=ident
    d.m_rlast.value=1;d.m_rdata.value=0xbad;d.rsp_ready.value=0
    await settle()
    assert not int(d.rsp_valid.value) and not int(d.m_rready.value)
    await tick(d)
    assert int(d.outstanding.value)==1 and not int(d.fault.value)
    d.m_arready.value=1
    await settle()
    assert not int(d.rsp_valid.value),'A previously unknown response was reclassified by the AR handshake'
    await tick(d)
    assert not int(d.m_arvalid.value) and not int(d.rsp_valid.value)
    assert int(d.outstanding.value)==1
    d.rsp_ready.value=1
    await settle()
    assert int(d.m_rready.value) and not int(d.rsp_valid.value)
    await tick(d)
    d.m_rvalid.value=0
    await settle()
    assert int(d.fault.value) and int(d.outstanding.value)==1
    # The malformed response did not retire the legitimate request. A later
    # genuine response still drains it, even though new requests are faulted.
    d.m_rvalid.value=1;d.m_rdata.value=0x600d
    await settle()
    assert int(d.rsp_valid.value) and int(d.rsp_tag.value)==200
    assert int(d.rsp_data.value)==0x600d and not int(d.rsp_error.value)
    await tick(d)
    assert int(d.outstanding.value)==0 and int(d.fault.value)
