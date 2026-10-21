"""Independent integer golden model, cycle accounting, stalls and reset."""
import math
import os
import random
import sys
from functools import lru_cache
from pathlib import Path

import cocotb
from cocotb.triggers import Timer
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from scalesim.scale_config import scale_config
from scalesim.compute.systolic_compute_os import systolic_compute_os

P=int(os.environ['DECODE_PARTITIONS']); C=int(os.environ['DECODE_COLS'])

@lru_cache(maxsize=64)
def native_demands(m,k,n,parallel):
    column_parts=math.ceil(n/C);workers=min(m,P//column_parts) if parallel else 1
    refs={}
    for p in range(workers*column_parts):
        rows=np.arange(p//column_parts,m,workers)
        columns=np.arange((p%column_parts)*C,min((p%column_parts+1)*C,n))
        cfg=scale_config();cfg.valid_conf_flag=True;cfg.array_rows=1;cfg.array_cols=C
        native=systolic_compute_os()
        native.set_params(config_obj=cfg,ifmap_op_mat=rows[:,None]*k+np.arange(k)[None,:],
            filter_op_mat=np.arange(k)[:,None]*n+columns[None,:],
            ofmap_op_mat=rows[:,None]*n+columns[None,:])
        refs[p]=native.get_demand_matrices()
    return refs

def pack(values,width):
    return int.from_bytes(np.asarray(values,dtype=np.int64).astype(f'<u{width//8}').tobytes(),'little')

def words(signal,count,width):
    return np.frombuffer(int(signal.value).to_bytes(count*(width//8),'little'),dtype=f'<u{width//8}').tolist()

async def edge(d):
    d.clk.value=0;await Timer(5,unit='ns')
    d.clk.value=1;await Timer(5,unit='ns')

async def reset(d):
    d.rst.value=1;d.cmd_valid.value=0;d.cycle_ready.value=0
    d.a_data.value=0;d.b_data.value=0;d.seed_data.value=0
    await edge(d);d.rst.value=0;await Timer(1,unit='ns')
    assert not int(d.busy.value)

async def run(d,a,b,parallel,seed=None,abort=False):
    m,k=a.shape;n=b.shape[1]
    d.cmd_m.value=m;d.cmd_k.value=k;d.cmd_n.value=n
    d.cmd_parallel_rows.value=parallel;d.cmd_accumulate.value=seed is not None
    d.cmd_valid.value=1;await edge(d);d.cmd_valid.value=0
    assert int(d.busy.value) and not int(d.command_error.value)
    result=np.zeros((m,n),dtype=np.int64);written=set()
    rng=random.Random(m*10000+k*100+n+parallel);commits=stalls=0
    column_parts=math.ceil(n/C);workers=min(m,P//column_parts) if parallel else 1
    expected_cycles=math.ceil(m/workers)*(k+C-1)
    native=native_demands(m,k,n,parallel)
    assert max(len(x[0]) for x in native.values())==expected_cycles
    while int(d.busy.value):
        d.clk.value=0
        await Timer(1,unit='ns')
        av=int(d.a_valid.value);bv=int(d.b_valid.value);sv=int(d.seed_valid.value);cv_initial=int(d.c_valid.value)
        aa=words(d.a_address,P,32);ba=words(d.b_address,P*C,32);ca=words(d.c_address,P*C,32)
        # The independent schedule catches wrong addresses even if a MAC result happens to match.
        phase=commits%(k+C-1);wave=commits//(k+C-1)
        for p in range(P):
            row=wave*workers+p//column_parts;active=p//column_parts<workers and row<m
            assert bool(av>>p&1)==(active and phase<k)
            if av>>p&1:assert aa[p]==row*k+phase
            native_a=native[p][0][commits,0] if p in native and commits<len(native[p][0]) else -1
            assert (aa[p] if av>>p&1 else -1)==native_a
            for c in range(C):
                lane=p*C+c;col=(p%column_parts)*C+c
                valid=active and col<n and c<=phase<k+c
                assert bool(bv>>lane&1)==valid
                if valid:
                    assert ba[lane]==(phase-c)*n+col
                    assert ca[lane]==row*n+col
                assert bool(sv>>lane&1)==(valid and phase==c and seed is not None)
                native_b=native[p][1][commits,c] if p in native and commits<len(native[p][1]) else -1
                native_c=native[p][2][commits,c] if p in native and commits<len(native[p][2]) else -1
                assert (ba[lane] if bv>>lane&1 else -1)==native_b
                assert (ca[lane] if cv_initial>>lane&1 else -1)==native_c
        d.a_data.value=pack([a.flat[x] if av>>p&1 else 0 for p,x in enumerate(aa)],8)
        d.b_data.value=pack([b.flat[x] if bv>>p&1 else 0 for p,x in enumerate(ba)],8)
        d.seed_data.value=pack([seed.flat[x] if seed is not None and sv>>p&1 else 0 for p,x in enumerate(ca)],32)
        ready=rng.random()>0.3;d.cycle_ready.value=ready
        await Timer(1,unit='ns')
        cv=int(d.c_valid.value);cd=words(d.c_data,P*C,32)
        if ready:
            for lane,x in enumerate(ca):
                if cv>>lane&1:
                    assert x not in written and x<m*n
                    written.add(x);result.flat[x]=cd[lane]-(1<<32) if cd[lane]>>31 else cd[lane]
            commits+=1
        else:stalls+=1
        snapshot=(int(d.a_address.value),int(d.b_address.value),cv,int(d.c_data.value))
        await edge(d)
        if not ready:
            assert snapshot==(int(d.a_address.value),int(d.b_address.value),int(d.c_valid.value),int(d.c_data.value))
        if abort and commits>=max(1,expected_cycles//2):
            await reset(d);return
        assert commits<=expected_cycles and stalls<expected_cycles*10+100
    assert int(d.done.value) and commits==expected_cycles
    assert int(d.logical_cycles.value)==commits
    assert int(d.elapsed_cycles.value)==commits+stalls and int(d.stall_cycles.value)==stalls
    golden=a.astype(np.int64)@b.astype(np.int64)
    if seed is not None:golden+=seed
    golden=((golden+(1<<31))%(1<<32))-(1<<31)
    assert len(written)==m*n
    np.testing.assert_array_equal(result,golden)
    return result

@cocotb.test()
async def integer_datapath_and_protocol(d):
    await reset(d)
    rng=np.random.default_rng(0xDEC0DE)
    shapes=[(1,1,1),(1,17,P*C),(4,13,C-1 if C>1 else 1),(4,19,min(P*C,C+1)),(3,7,min(P*C,2*C)),(4,1,P*C-1)]
    for i in range(12):shapes.append((int(rng.integers(1,5)),int(rng.integers(1,40)),int(rng.integers(1,P*C+1))))
    for m,k,n in shapes:
        a=rng.integers(-128,128,(m,k),dtype=np.int8);b=rng.integers(-128,128,(k,n),dtype=np.int8)
        for parallel in (False,True):await run(d,a,b,parallel)
    # Overflow behavior, negative extremes, and explicitly carried partial sums.
    a=np.full((4,41),-128,dtype=np.int8);b=np.full((41,min(P*C,C+1)),-128,dtype=np.int8)
    seed=np.full((4,b.shape[1]),(1<<31)-100,dtype=np.int64)
    await run(d,a,b,True,seed)
    a=rng.integers(-128,128,(4,53),dtype=np.int8);b=rng.integers(-128,128,(53,C),dtype=np.int8)
    partial=None
    for lo,hi in [(0,1),(1,18),(18,53)]:partial=await run(d,a[:,lo:hi],b[lo:hi],True,partial)
    np.testing.assert_array_equal(partial,a.astype(np.int64)@b.astype(np.int64))
    await run(d,a,b,True,abort=True)
    await run(d,a,b,False)
    # All rejected commands must leave the core idle and accept a later legal command.
    for m,k,n in [(0,1,1),(5,1,1),(1,0,1),(1,8193,1),(1,1,0),(1,1,P*C+1)]:
        d.cmd_m.value=m;d.cmd_k.value=k;d.cmd_n.value=n;d.cmd_valid.value=1
        await edge(d);d.cmd_valid.value=0
        assert int(d.command_error.value) and not int(d.busy.value)
    await run(d,a,b,True)

@cocotb.test()
async def every_partition_layout_and_wave_base(d):
    """Exhaust the command decoder's constant layouts and row-base advances.

    The main test checks complete native/NumPy traces. This directed test
    covers every possible column-partition count, including both ragged and
    exact boundaries, and every resulting wave for four rows.
    """
    await reset(d)
    for parts in range(1,P+1):
        for n in sorted({(parts-1)*C+1,parts*C}):
            for parallel in (False,True):
                m=4;k=1
                workers=min(m,P//parts) if parallel else 1
                d.cmd_m.value=m;d.cmd_k.value=k;d.cmd_n.value=n
                d.cmd_parallel_rows.value=parallel;d.cmd_accumulate.value=0
                d.cmd_valid.value=1;d.cycle_ready.value=1
                await edge(d);d.cmd_valid.value=0
                assert int(d.busy.value) and not int(d.command_error.value)
                for wave in range(math.ceil(m/workers)):
                    aa=words(d.a_address,P,32);ba=words(d.b_address,P*C,32)
                    ca=words(d.c_address,P*C,32)
                    av=int(d.a_valid.value);bv=int(d.b_valid.value)
                    for p in range(P):
                        row=wave*workers+p//parts
                        active=p//parts<workers and row<m
                        assert bool(av>>p&1)==active,(parts,n,parallel,wave,p)
                        if active:
                            assert aa[p]==row
                            assert ba[p*C]==(p%parts)*C
                            for c in range(C):
                                assert ca[p*C+c]==row*n+(p%parts)*C+c
                        assert bool(bv>>(p*C)&1)==active
                    for _ in range(C):await edge(d)
                assert not int(d.busy.value) and int(d.done.value)
                assert int(d.logical_cycles.value)==math.ceil(m/workers)*C
