"""Check native array/group schedules, numerical-to-timing coverage, and HBM timing."""
import argparse,csv,json,subprocess,sys
from dataclasses import replace
from math import ceil
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3];sys.path.insert(0,str(ROOT))
from run import verify_trace
from config import Architecture
from scalesim.scale_config import scale_config
from scalesim.compute.systolic_compute_ws import systolic_compute_ws
from scalesim.compute.systolic_compute_os import systolic_compute_os
from experiments.gemma3_1b_int8.study import demand_cycles
from src_rtl.cosim.build import ensure
from src_rtl.cosim.runtime import Library,HBM


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--run-dir',type=Path,default=HERE/'build/fast_decode')
    args=parser.parse_args();folder=args.run_dir
    manifest=json.loads((folder/'manifest.json').read_text())
    architecture=Architecture(**manifest.get('configuration',{}))
    shapes=set();groups={}
    def subarrays(m,k,n):
        columns=ceil(n/architecture.array_cols)
        workers=min(ceil(m/architecture.array_rows),architecture.array_partitions//columns) if architecture.parallel_head_rows else 1
        rows=[sum(min(architecture.array_rows,m-start) for start in range(worker*architecture.array_rows,m,workers*architecture.array_rows)) for worker in range(workers)]
        return [(rows_per_worker,k,min(architecture.array_cols,n-offset)) for rows_per_worker in rows for offset in range(0,n,architecture.array_cols)]
    for op in manifest['ops']:
        if op['kind']!='gemm':continue
        for n0 in range(0,op['n'],architecture.output_tile_cols):
            nt=min(architecture.output_tile_cols,op['n']-n0)
            for k0,kt in architecture.k_tiles(op['k']):
                parts=subarrays(op['m'],kt,nt)
                groups[op['m'],kt,nt]=parts
                shapes.update(parts)
    checks=[];native_cycles={}
    for m,k,n in sorted(shapes):
        cfg=scale_config();cfg.valid_conf_flag=True;cfg.array_rows=architecture.array_rows;cfg.array_cols=architecture.array_cols
        engine=(systolic_compute_os() if architecture.dataflow=='os' else systolic_compute_ws());engine.set_params(config_obj=cfg,ifmap_op_mat=np.arange(m*k).reshape(m,k),
                     filter_op_mat=np.arange(k*n).reshape(k,n),ofmap_op_mat=np.arange(m*n).reshape(m,n))
        durations=[len(mat) for mat in engine.get_demand_matrices()]
        assert all(value==replace(architecture,parallel_head_rows=False,array_partitions=1).demand_cycles(m,n,k) for value in durations)
        native_cycles[m,k,n]=durations[0]
        checks.append(dict(check='native_'+architecture.dataflow.upper()+'_tile',m=m,k=k,n=n,array=[cfg.array_rows,cfg.array_cols]))
    for m,k,n in sorted(groups):
        critical=max(native_cycles[part] for part in groups[m,k,n])
        assert critical==architecture.demand_cycles(m,n,k)
    checks.append(dict(check='parallel_group_critical_paths_match_native_arrays',groups=len(groups)))
    native_options=[str(architecture.max_inflight_requests),str(int(architecture.hbm_address_mapping=='pc_bankgroup'))]
    validation=verify_trace(json.loads((folder/'numerical_result.json').read_text()),manifest,
                            json.loads((folder/'numerical_operator_trace.json').read_text()))
    checks.append(dict(check='executed_numerical_matrix_shapes_match_every_timing_GEMM',**validation))
    # Compare a cold read and write completion against the separately tested live
    # AXI/HBM transport. One transaction removes frontend bandwidth differences.
    library=Library(ensure());native=HERE/'build/runner';cfg=folder/'hbm2.json';hz=architecture.core_hz
    check_folder=folder/'checks';check_folder.mkdir(exist_ok=True)
    for kind in ('R','W'):
        bridge=HBM(library,cfg,hz,{})
        ident=bridge.submit(0,kind=='W',0)
        try:
            for cycle in range(10000):
                bridge.advance(cycle)
                if bridge.ready(ident):break
            else:raise AssertionError('Native callback timed out')
        finally:bridge.close()
        commands=check_folder/f'check_{kind}.txt';output=check_folder/f'check_{kind}.csv'
        commands.write_text(f'0 0 memory {kind} 0 32 1 0\n')
        subprocess.run([str(native),str(cfg),str(commands),str(output),str(hz),'16','100',*native_options],check=True,stdout=subprocess.DEVNULL)
        with output.open() as f:row=next(csv.DictReader(f))
        assert int(row['end_core'])==cycle,(kind,row,cycle)
        checks.append(dict(check='native_completion_matches_live_bridge',kind=kind,core_cycles=cycle))
    commands=check_folder/'check_compute.txt';output=check_folder/'check_compute.csv'
    commands.write_text('0 0 vector C 17 0 0 0\n0 0 vector C 23 0 0 0\n')
    subprocess.run([str(native),str(cfg),str(commands),str(output),str(hz),'16','100',*native_options],check=True,stdout=subprocess.DEVNULL)
    with output.open() as f:row=next(csv.DictReader(f))
    dram_ticks=40*10**12//(hz*1111)
    assert int(row['end_core'])==40 and int(row['end_dram'])==dram_ticks and int(row['reads'])==int(row['writes'])==0
    checks.append(dict(check='compute_time_preserves_native_DRAM_clock_phase',core_cycles=40,dram_ticks=dram_ticks))
    result=dict(status='passed',configuration=architecture.to_dict(),checks=checks)
    (folder/'timing_tests.json').write_text(json.dumps(result,indent=2)+'\n')
    print('PASS',len(checks),'timing checks')
if __name__=='__main__':main()
