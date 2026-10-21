"""Serial boundary verification; the independent fixture exercises every output bit."""
import os
import random
import cocotb
from cocotb.triggers import Timer

P=int(os.environ['HARNESS_PARTITIONS'])
C=int(os.environ['HARNESS_COLS'])
STUB=os.environ['HARNESS_STUB']=='1'
INPUT_FIELDS=[('vector_rst',1),('cmd_valid',1),('cmd_m',32),('cmd_k',32),
              ('cmd_n',32),('cmd_parallel_rows',1),('cmd_accumulate',1),
              ('cycle_ready',1),('a_data',8*P),('b_data',8*P*C),('seed_data',32*P*C)]
OUTPUT_FIELDS=[('cmd_ready',1),('busy',1),('done',1),('command_error',1),
               ('a_valid',P),('a_address',32*P),('b_valid',P*C),
               ('b_address',32*P*C),('seed_valid',P*C),('c_valid',P*C),
               ('c_address',32*P*C),('c_data',32*P*C),('logical_cycles',64),
               ('elapsed_cycles',64),('stall_cycles',64)]
IB=sum(n for _,n in INPUT_FIELDS)
OB=sum(n for _,n in OUTPUT_FIELDS)
CONTROLS=('harness_reset','scan_in','input_shift','input_commit','output_capture','output_shift')

def pack(values, fields):
    word=0
    shift=0
    for name,width in fields:
        word |= (values.get(name,0)&((1<<width)-1)) << shift
        shift += width
    return word

def inspect(dut, fields):
    return pack({name:int(getattr(dut,name).value) for name,_ in fields},fields)

async def cycle(dut, **values):
    # External controls settle before the falling edge; wide banks operate at
    # the following rising edge. Serial data is sampled before a shift occurs.
    for name in CONTROLS:
        getattr(dut,name).value=values.get(name,0)
    dut.clk.value=1
    await Timer(5,unit='ns')
    dut.clk.value=0
    await Timer(5,unit='ns')
    serial=int(dut.scan_out.value)
    dut.clk.value=1
    await Timer(5,unit='ns')
    return serial

async def load(dut, word, previous=None):
    for index in range(IB):
        await cycle(dut,input_shift=1,scan_in=(word>>index)&1)
        if previous is not None:
            assert inspect(dut,INPUT_FIELDS)==previous, 'Staging changed launched operands'
    assert int(dut.input_scan.value)==word, 'Serial input staging ordering'
    if previous is not None:
        assert inspect(dut,INPUT_FIELDS)==previous
    await cycle(dut,input_commit=1)
    assert inspect(dut,INPUT_FIELDS)==word, 'Atomic commit mapping'

async def unload(dut, expected):
    result=0
    for bit in range(OB):
        result |= await cycle(dut,output_shift=1) << bit
    assert result==expected, f'Output scan mismatch: xor={result^expected:x}'
    assert int(dut.output_scan.value)==0, 'Scan did not shift every output bit'

async def capture(dut):
    # Read the actual core signals before the edge that takes the snapshot.
    expected=inspect(dut,OUTPUT_FIELDS)
    await cycle(dut,output_capture=1,output_shift=1)
    assert int(dut.output_scan.value)==expected, 'Capture priority or field packing'
    return expected

def fixture_pattern(seed, invert):
    state=seed ^ 0x9e3779b9
    result=0
    for bit in range(OB):
        state ^= (state<<13)&0xffffffff
        state ^= state>>17
        state ^= (state<<5)&0xffffffff
        result |= ((state&1)^invert)<<bit
    return result

@cocotb.test()
async def scan_mapping_atomic_commit_and_snapshot(dut):
    dut.clk.value=1
    for name in CONTROLS: getattr(dut,name).value=0
    await cycle(dut,harness_reset=1)
    await cycle(dut,harness_reset=1)
    rng=random.Random(0x5ca1e+P*100+C)
    previous=None
    patterns=[]
    if STUB:
        # Each seeded pair is complemented, exercising all output bits both
        # ways. Distinct xorshift positions detect field swaps/reordering.
        for seed in [0,0xffffffff,rng.getrandbits(32),rng.getrandbits(32)]:
            for inverse in [0,1]:
                values={name:(((1<<width)-1) if inverse else 0)
                        if seed in (0,0xffffffff) else rng.getrandbits(width)
                        for name,width in INPUT_FIELDS}
                values.update(cmd_m=seed,cmd_k=0xffffffff if inverse else 0)
                patterns.append(values)
    else:
        # Real core runs a command but stalls while the scan staging bank is
        # changed; its operands must remain atomic and its phase must not move.
        patterns=[dict(vector_rst=1),dict(vector_rst=0,cmd_valid=1,cmd_m=1,
                   cmd_k=3,cmd_n=C,cmd_accumulate=1,cycle_ready=0,
                   a_data=rng.getrandbits(8*P),b_data=rng.getrandbits(8*P*C),
                   seed_data=rng.getrandbits(32*P*C))]
    for values in patterns:
        word=pack(values,INPUT_FIELDS)
        await load(dut,word,previous)
        previous=word
        await cycle(dut)
        expected=await capture(dut)
        if STUB:
            assert expected==fixture_pattern(values['cmd_m'],values['cmd_k']&1)
        await unload(dut,expected)
        assert inspect(dut,INPUT_FIELDS)==word
    if not STUB:
        assert int(dut.busy.value)==1
        phase=int(dut.core.phase.value)
        values=patterns[-1].copy()
        values.update(cmd_valid=0,a_data=rng.getrandbits(8*P),
                      b_data=rng.getrandbits(8*P*C),seed_data=rng.getrandbits(32*P*C))
        await load(dut,pack(values,INPUT_FIELDS),previous)
        assert int(dut.core.phase.value)==phase, 'Core advanced despite cycle_ready=0'
        expected=await capture(dut)
        # Busy-cycle counters continue to change; the captured snapshot must not.
        for _ in range(7): await cycle(dut)
        assert int(dut.output_scan.value)==expected
        await unload(dut,expected)
    await cycle(dut,harness_reset=1)
    assert int(dut.armed.value)==0
    assert int(dut.rst.value)==1


@cocotb.test()
async def controls_sample_on_falling_edge(dut):
    dut.clk.value=1
    for name in CONTROLS: getattr(dut,name).value=0
    await cycle(dut,harness_reset=1)
    await cycle(dut,harness_reset=1)
    initial=pack(dict(vector_rst=0,cmd_m=1,cmd_k=1,cmd_n=1),INPUT_FIELDS)
    await load(dut,initial)
    await cycle(dut)
    snapshot=await capture(dut)
    await cycle(dut,output_shift=1)
    saved_output=int(dut.output_scan.value)
    assert saved_output!=snapshot, 'Edge test requires distinguishable capture state'
    await cycle(dut,input_shift=1,scan_in=1)
    pending=int(dut.input_scan.value)
    assert pending!=initial
    for name in CONTROLS: getattr(dut,name).value=0
    dut.clk.value=1
    await Timer(5,unit='ns')
    dut.clk.value=0
    await Timer(5,unit='ns')
    # Pulsing controls after the falling edge must NOT affect the imminent
    # positive edge. This also tests commit/capture atomicity at that edge.
    dut.input_commit.value=1
    dut.output_capture.value=1
    dut.clk.value=1
    await Timer(5,unit='ns')
    assert inspect(dut,INPUT_FIELDS)==initial
    assert int(dut.output_scan.value)==saved_output
    expected=inspect(dut,OUTPUT_FIELDS)
    await cycle(dut,input_commit=1,output_capture=1)
    assert inspect(dut,INPUT_FIELDS)==pending
    assert int(dut.output_scan.value)==expected, 'Capture must see the pre-commit vector'
