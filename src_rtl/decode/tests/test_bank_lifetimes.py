import random
import cocotb
from cocotb.triggers import Timer

@cocotb.test()
async def ownership_and_illegal_completions(d):
    rng=random.Random(188);state=[0,0]
    async def edge():
        d.clk.value=0;await Timer(5,unit='ns');d.clk.value=1;await Timer(5,unit='ns')
    d.rst.value=1
    for action in ('load','complete','acquire','release'):
        getattr(d,action+'_valid').value=0;getattr(d,action+'_bank').value=0
    await edge();d.rst.value=0
    for cycle in range(1000):
        actions={a:(rng.randrange(2),rng.randrange(2)) for a in ('load','complete','acquire','release')}
        for a,(valid,bank) in actions.items():
            getattr(d,a+'_valid').value=valid;getattr(d,a+'_bank').value=bank
        await Timer(1,unit='ns');new=state.copy()
        for a,before,after in [('load',0,1),('complete',1,2),('acquire',2,3),('release',3,0)]:
            valid,bank=actions[a]
            if a!='complete':assert int(getattr(d,a+'_ready').value)==int(state[bank]==before)
            if valid and state[bank]==before:new[bank]=after
        valid,bank=actions['complete'];error=valid and state[bank]!=1
        await edge();state=new
        assert int(d.states.value)==state[0]+(state[1]<<2)
        assert int(d.protocol_error.value)==int(error)
    d.rst.value=1;await edge();assert int(d.states.value)==0
