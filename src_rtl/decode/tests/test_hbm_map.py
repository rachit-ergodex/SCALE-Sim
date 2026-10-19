import random
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def complete_bank_column_bijection(d):
    destinations=[14,16,17,9,10,11,12,13,15]
    rng=random.Random(18);seen=set()
    for value in [x<<9 for x in range(512)]+[rng.randrange(1<<34) for _ in range(500)]:
        expected=value&~(511<<9)
        for bit,dest in enumerate(destinations):expected|=((value>>(bit+9))&1)<<dest
        for enabled in (0,1):
            d.logical_address.value=value;d.interleave.value=enabled;await Timer(1,unit='ns')
            assert int(d.physical_address.value)==(expected if enabled else value)
        if value<1<<18:seen.add(expected)
    assert len(seen)>=512
