"""Verify completed native ASIC/F2 runs and retain reproducible study evidence."""
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from run_partition_study import DEFAULTS

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    validations=[]
    for filename in ('partitioned_numerical_validation.json','f2_partitioned_numerical_validation.json'):
        validation=json.loads((HERE/'build'/filename).read_text())
        assert validation['status']=='passed'
        for name,value in validation['sources'].items():assert digest(HERE/name)==value,name
        validations.append(validation)
    bandwidth=json.loads((HERE/'build/bandwidth_study/results.json').read_text())
    for name,value in bandwidth['sources'].items():assert digest(HERE/name)==value,name
    rows=[];trace=None
    for name in DEFAULTS:
        folder=HERE/'build'/name
        report=json.loads((folder/'result.json').read_text())
        execution=json.loads((folder/'execution.json').read_text())
        tests=json.loads((folder/'timing_tests.json').read_text())
        assert report['status']=='passed' and execution['status']=='completed' and tests['status']=='passed'
        assert tests['configuration']==report['configuration']==execution['configuration']
        for file,value in execution['inputs_sha256'].items():assert digest(folder/file)==value,(name,file)
        assert digest(folder/'timing.csv')==execution['timing_sha256']
        for file,value in report['source_sha256'].items():assert digest(ROOT/file)==value,(name,file)
        assert digest(HERE/'build/runner')==report['native_binary_sha256']==bandwidth['native_binary_sha256']
        if trace is None:trace=report['numerical_trace_sha256']
        assert trace==report['numerical_trace_sha256']
        c=report['configuration'];steps=report['decode_steps'];hz=c['core_hz']
        traffic=sum(t['dram_transaction_bytes'] for t in report['tokens'])/steps
        stages=defaultdict(lambda:dict(total_ms=0.,compute_ms=0.,bytes=0.))
        for op in json.loads((folder/'operations.json').read_text()):
            stage=stages[op['kind']]
            stage['total_ms']+=(int(op['end_core'])-int(op['start_core']))*1000/hz/steps
            stage['compute_ms']+=int(op['compute_cycles'])*1000/hz/steps
            stage['bytes']+=(int(op['reads'])+int(op['writes']))*32/steps
        average_bw=traffic*report['mean_decode_tps']/1e9
        rows.append(dict(profile=name,configuration=c,macs=c['array_rows']*c['array_cols']*c['array_partitions'],
            staging_MiB=(2*c['operand_staging_bytes']+c['vector_staging_bytes'])/1024**2,
            decode_tps=report['mean_decode_tps'],milliseconds=report['mean_decode_ms'],
            compute_ms=sum(t['compute_cycles'] for t in report['tokens'])/steps/hz*1000,
            exposed_memory_wait_ms=sum(t['memory_wait_cycles'] for t in report['tokens'])/steps/hz*1000,
            physical_bytes_per_token=traffic,average_GB_s=average_bw,nominal_peak_percent=average_bw/460.8*100,
            stages=dict(stages),timing_checks=len(tests['checks']),execution=execution,
            source_sha256=report['source_sha256']))
    result=dict(status='passed',target_tps=400,target_reached={platform:any(r['decode_tps']>400 for r in rows if r['profile'].startswith('decode_'+platform+'_')) for platform in ('asic','f2')},
        scope='Batch-one W8A8/KV8 Gemma3-1B, 512-token prompt, contexts 513-515; simulated device decode, not FPGA hardware measurements.',
        measurements=rows,bandwidth_microbenchmark=bandwidth,real_checkpoint_validation=validations,
        numerical_trace_sha256=trace)
    (HERE/'partitioned_decode_study.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print(row['profile'],round(row['decode_tps'],3),round(row['average_GB_s'],3),'GB/s')

if __name__=='__main__':main()
