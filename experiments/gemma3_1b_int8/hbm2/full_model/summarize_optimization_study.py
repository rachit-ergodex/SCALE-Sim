"""Validate the optimized decode study and retain measured target evidence."""
import hashlib
import json
import unittest
from collections import defaultdict
from pathlib import Path
from test_configuration import ConfigurationChecks
from test_decode_architecture import DecodeArchitectureChecks
from test_array_partitions import PartitionChecks
from test_decode_optimizations import OptimizationChecks

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[3]
PROFILES=[f'decode_{platform}_{stage}' for platform in ('asic','f2')
          for stage in ('resident','stream','small_tiles','stream256')]

def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(cls)
        for cls in (ConfigurationChecks,DecodeArchitectureChecks,PartitionChecks,OptimizationChecks))
    tests=unittest.TextTestRunner(verbosity=1).run(suite);assert tests.wasSuccessful()
    rows=[];trace=None
    for name in PROFILES:
        folder=HERE/'build'/name
        r=json.loads((folder/'result.json').read_text());e=json.loads((folder/'execution.json').read_text())
        t=json.loads((folder/'timing_tests.json').read_text());cache=json.loads((folder/'residency.json').read_text())
        assert r['status']=='passed' and e['status']=='completed' and t['status']=='passed'
        assert r['configuration']==e['configuration']==t['configuration']
        for file,value in e['inputs_sha256'].items():assert digest(folder/file)==value,(name,file)
        assert digest(folder/'timing.csv')==e['timing_sha256']
        for file,value in r['source_sha256'].items():assert digest(ROOT/file)==value,(name,file)
        assert digest(HERE/'build/runner')==r['native_binary_sha256']
        if trace is None:trace=r['numerical_trace_sha256']
        assert trace==r['numerical_trace_sha256']
        c=r['configuration'];steps=r['decode_steps'];hz=c['core_hz']
        traffic=sum(x['dram_transaction_bytes'] for x in r['tokens'])/steps
        stages=defaultdict(lambda:dict(total_ms=0.,compute_ms=0.))
        for op in json.loads((folder/'operations.json').read_text()):
            stages[op['kind']]['total_ms']+=(int(op['end_core'])-int(op['start_core']))/hz/steps*1000
            stages[op['kind']]['compute_ms']+=int(op['compute_cycles'])/hz/steps*1000
        assert cache['peak_live_bytes']<=c['intermediate_sram_bytes']
        rows.append(dict(profile=name,configuration=c,decode_tps=r['mean_decode_tps'],token_tps=[x['tps'] for x in r['tokens']],
            milliseconds=r['mean_decode_ms'],compute_ms=sum(x['compute_cycles'] for x in r['tokens'])/hz/steps*1000,
            exposed_memory_wait_ms=sum(x['memory_wait_cycles'] for x in r['tokens'])/hz/steps*1000,
            physical_bytes_per_token=traffic,average_GB_s=traffic*r['mean_decode_tps']/1e9,
            total_staging_bytes=r['architecture']['total_staging_bytes'],
            pipeline_register_bytes=r['architecture']['stream_pipeline_register_bytes'],
            intermediate_peak_bytes=cache['peak_live_bytes'],avoided_logical_HBM_bytes_per_token=cache['avoided_logical_HBM_bytes']/steps,
            stages=dict(stages),timing_checks=len(t['checks']),execution=e,source_sha256=r['source_sha256']))
    best={platform:max((r for r in rows if r['profile'].startswith('decode_'+platform+'_')),key=lambda r:r['decode_tps']) for platform in ('asic','f2')}
    validation={}
    for platform,target in [('asic',325),('f2',200)]:
        report=json.loads((HERE/'build'/f'optimized_{platform}_validation.json').read_text())
        assert report['status']=='passed'
        for file,value in report['sources'].items():assert digest(HERE/file)==value,file
        assert report['configuration']==best[platform]['configuration'], 'Numerical validation must match selected configuration'
        assert min(best[platform]['token_tps'])>target,(platform,best[platform]['decode_tps'])
        validation[platform]=report
    result=dict(status='passed',targets=dict(asic=325,f2=200),selected={k:v['profile'] for k,v in best.items()},
        scope='Three batch-one Gemma3-1B cached decode steps at contexts 513-515. Native HBM timing; separate verified numerical execution; not hardware measurements.',
        regression_tests=tests.testsRun,measurements=rows,real_checkpoint_validation=validation,
        verification_source_sha256={p.name:digest(p) for p in [Path(__file__),HERE/'test_decode_optimizations.py',HERE/'test_timing.py']},
        numerical_trace_sha256=trace)
    (HERE/'optimized_decode_study.json').write_text(json.dumps(result,indent=2)+'\n')
    for row in rows:print(row['profile'],round(row['decode_tps'],3),'TPS')

if __name__=='__main__':main()
