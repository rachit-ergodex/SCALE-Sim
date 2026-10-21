import random
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def byte_writes_stalls_and_collisions(d):
    rng=random.Random(199);gold=[0]*13;pending=None
    d.clk.value=0;d.rst.value=1;d.wr_valid.value=0;d.rd_valid.value=0;d.rsp_ready.value=0
    async def edge():
        d.clk.value=0;await Timer(5,unit='ns');d.clk.value=1;await Timer(5,unit='ns')
    await edge();d.rst.value=0
    # Reset does not initialize SRAM; software initializes every byte first.
    for addr in range(13):
        d.wr_valid.value=1;d.wr_addr.value=addr;d.wr_data.value=0;d.wr_strb.value=(1<<32)-1
        await edge()
    for cycle in range(600):
        wvalid=rng.randrange(2);rvalid=rng.randrange(2);ready=rng.randrange(2)
        wa=rng.randrange(16);ra=wa if cycle%3==0 else rng.randrange(16)
        wd=rng.getrandbits(256);mask=rng.getrandbits(32)
        d.wr_valid.value=wvalid;d.wr_addr.value=wa;d.wr_data.value=wd;d.wr_strb.value=mask
        d.rd_valid.value=rvalid;d.rd_addr.value=ra;d.rsp_ready.value=ready
        await Timer(1,unit='ns')
        assert int(d.rsp_valid.value)==(pending is not None)
        if pending is not None:
            assert (int(d.rsp_data.value),int(d.rsp_error.value))==pending
        rready=pending is None or ready
        assert bool(d.rd_ready.value)==bool(rready)
        if pending is not None and ready:pending=None
        if rvalid and rready:pending=(gold[ra] if ra<13 else 0,int(ra>=13))
        if wvalid and wa<13:
            for b in range(32):
                if mask>>b&1:gold[wa]=(gold[wa]&~(255<<(b*8)))|(wd&(255<<(b*8)))
        await edge()
        assert int(d.wr_error.value)==int(wvalid and wa>=13)
    # Reset drops an outstanding response while preserving stored data.
    d.rst.value=1;await edge();assert not int(d.rsp_valid.value)
    d.rst.value=0;d.wr_valid.value=0;d.rsp_ready.value=1;d.rd_valid.value=1
    for addr in range(13):
        d.rd_addr.value=addr;await edge();assert int(d.rsp_data.value)==gold[addr]
