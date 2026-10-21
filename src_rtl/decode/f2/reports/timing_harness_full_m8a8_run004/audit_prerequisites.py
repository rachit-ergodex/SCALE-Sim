#!/usr/bin/env python3
"""Read frozen prerequisite evidence; writes only the requested audit JSON."""
import argparse,hashlib,importlib.util,json,re,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
sys.dont_write_bytecode=True
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
root=a.root.resolve();problems=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(rel):return json.loads((root/rel).read_text())
def check_file(rel,expected,expected_bytes=None):
 path=root/rel;actual=sha(path) if path.is_file() else None
 result={'expected_sha256':expected,'actual_sha256':actual,'matches':actual==expected}
 if expected_bytes is not None:
  result.update(expected_bytes=expected_bytes,actual_bytes=path.stat().st_size if path.is_file() else None)
  result['matches'] &= result['actual_bytes']==expected_bytes
 if not result['matches']:problems.append('File binding mismatch: '+str(rel))
 return result
def require(value,problem):
 if not value:problems.append(problem)
base=Path('src_rtl/decode');core=base/'rtl/decode_os_core.sv';hbase=base/'f2/harness';reports=base/'f2/reports'
flow_path=base/'f2/scripts/run_timing_harness.py'
spec=importlib.util.spec_from_file_location('audited_frozen_harness_flow',root/flow_path);flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)
hashes=flow.checked_inputs(root)
require(len(hashes)==12,'Expected exactly 12 frozen flow inputs')
canonical=read(base/'verification.json')
canonical_checks={name:check_file(Path(name),expected) for name,expected in canonical['sources_sha256'].items()}
require(canonical['status']=='passed' and len(canonical_checks)==38,'Expected passing canonical verification with 38 source bindings')
harness=read(hbase/'verification.json')
require(harness['status']=='passed' and harness['tests_passed']==8,'Expected eight passing harness tests')
harness_checks={name:check_file(Path(name),expected) for name,expected in harness['source_sha256'].items()}
small={}
for mhz in (50,100):
 rel=reports/f'timing_harness_small_{mhz}_run003';collection=read(rel/'collection_manifest.json');manifest=read(rel/'manifest.json');audit=read(rel/'audit.json')
 native={name:check_file(rel/name,value['sha256'],value['bytes']) for name,value in collection['native_files'].items()}
 source={name:check_file(Path(name),expected) for name,expected in manifest['source_hashes'].items()}
 require(len(native)==38,f'{mhz} MHz expected 38 native evidence files')
 require(manifest['source_hashes']==hashes,f'{mhz} MHz does not match all 12 frozen flow inputs')
 require(manifest['status']=='route_pass' and audit['status']=='passed' and audit['component_routed_timing_pass'] is True,f'{mhz} MHz route/audit status is not passing')
 require(manifest['part']==flow.PART and manifest['partitions']==4 and manifest['cols']==8 and manifest['clock_period_ns']==1000/mhz,f'{mhz} MHz design geometry/part/clock mismatch')
 dsp=flow.validate_dsp_report(root/rel/'dsp_mapping.tsv',4,8)
 require(sha(root/rel/'dsp_mapping.tsv')==manifest['dsp_mapping_sha256'],f'{mhz} MHz DSP map hash mismatch')
 timing=(root/rel/'route_timing.rpt').read_text()
 require('Slow    Yes        Yes' in timing and 'Fast    Yes        Yes' in timing,f'{mhz} MHz missing slow/fast min/max corners')
 require('No timing exceptions found.' in (root/rel/'exceptions.rpt').read_text(),f'{mhz} MHz unexpected timing exceptions')
 small[str(mhz)]={'status':audit['status'],'native_file_count':len(native),'native_hash_matches':sum(v['matches'] for v in native.values()),'native_files':native,'source_input_count':len(source),'source_hash_matches':sum(v['matches'] for v in source.values()),'source_inputs':source,'audit_sha256':sha(root/rel/'audit.json'),'manifest_sha256':sha(root/rel/'manifest.json'),'collection_manifest_sha256':sha(root/rel/'collection_manifest.json'),'metrics':audit['metrics'],'timing_summary_values':audit['timing_summary_values'],'timing_checks':audit['timing_checks'],'dsp_mapping':dsp,'post_route_checkpoint_provenance':collection['checkpoints_not_archived']['post_route.dcp'],'methodology_report_available':False,'methodology_note':'Native timing report states report_methodology was not run; narrow component timing evidence only.','slow_fast_max_min_enabled':True,'timing_exceptions_present':False}
 require('report_methodology has not been run prior' in timing,f'{mhz} MHz methodology note changed; review required')
probe=reports/'dsp_mapping_probe_run003';mapped=read(probe/'mapped_dsp_verification.json');native_result=probe/mapped['native_result'];summary=read(native_result)
require(mapped['status']=='passed' and summary['status']=='passed','Mapped UNISIM comparison has not passed')
require(mapped['candidate_sha256']==sha(root/core),'Mapped candidate does not bind current core')
result_binding=check_file(native_result,mapped['native_result_sha256'])
collection_path=probe/'mapped_verification/mapped_equivalence_collection_manifest.json';mc=read(collection_path)
mapped_files={name:check_file(probe/'mapped_verification'/name,value) for name,value in mc['files_sha256'].items()}
require(len(mapped_files)==48,'Expected 48 mapped native archive file bindings')
require(mapped['results']==summary['results'],'Mapped summary result counts disagree')
expected={'valid_commands':'520','invalid_commands':'6','mid_command_resets':'4','clock_ticks':'110991','all_output_comparisons':'221934','stall_cycles_checked':'27727','observed_output_bits':'3496'}
require(all(summary['results'].get(k)==v for k,v in expected.items()),'Mapped coverage counts changed')
require(all(stage.get('returncode')==0 for stage in summary['stages']) and [s['name'] for s in summary['stages']]==['xvlog','xelab','xsim'],'Mapped simulator stages not all successful')
require('Compiling module unisims_ver.DSP48E2' in (root/native_result.parent/'xelab.console.log').read_text(),'Missing actual UNISIM DSP elaboration evidence')
key_paths=[core,hbase/'decode_compute_timing_harness.sv',hbase/'harness_constraints.tcl',base/'verification.json',hbase/'verification.json',flow_path,base/'f2/scripts/timing_harness.tcl',base/'f2/scripts/audit_compute_ooc.py',probe/'mapped_dsp_verification.json',native_result,probe/'mapped_verification/output_capture_map.json',probe/'mapped_verification/core_connection_proof.json',collection_path]
result={'status':'passed' if not problems else 'failed','recorded_utc':datetime.now(timezone.utc).isoformat(),'repository_root':str(root),'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'audit_script_sha256':sha(Path(__file__)),'scope':'Read-only source and prerequisite-evidence binding for a new full 4096-MAC 100 MHz compute-harness synthesis then resource-gated P&R run. Does not establish full-size fit, full-size timing, F2 shell/HBM readiness, throughput, or new runner correctness.','canonical':{'status':canonical['status'],'manifest_sha256':sha(root/base/'verification.json'),'source_count':len(canonical_checks),'source_hash_matches':sum(v['matches'] for v in canonical_checks.values()),'sources':canonical_checks},'frozen_flow':{'input_count':len(hashes),'input_sha256':hashes,'matches_both_small003_runs':all(s['source_hash_matches']==12 for s in small.values())},'harness':{'status':harness['status'],'tests_passed':harness['tests_passed'],'source_hash_matches':sum(v['matches'] for v in harness_checks.values()),'sources':harness_checks},'small003_runs':small,'mapped_unisim':{'status':summary['status'],'candidate_sha256':mapped['candidate_sha256'],'reference_original_sha256':mapped['reference_original_sha256'],'netlist_sha256':mapped['netlist_sha256'],'native_result_binding':result_binding,'native_archive_file_count':len(mapped_files),'native_archive_hash_matches':sum(v['matches'] for v in mapped_files.values()),'native_files':mapped_files,'results':summary['results'],'simulator_version':summary['simulator_version'],'vendor_library_note':'Native log proves installed actual UNISIM DSP48E2 elaboration; vendor source bytes are not present or independently rehashed on this local host.'},'key_evidence_sha256':{str(p):sha(root/p) for p in key_paths},'methodology_note':'report_methodology was not run in small003; maintain narrow component routed-timing claims. Broader signoff requires methodology review. The harness has one clock and no bus-skew constraints.','pending_checks':['New-host Python/Vivado 2025.2 availability and selected VU47P part','Root launch record must bind this audit and the finalized new runner hash','Fresh 64x64 synthesis must pass exact 4096-lane DSP identity checks and <=90% actual-capacity resource gate','Route must bind its synthesis checkpoint/report/source hashes and pass routed timing, pulse width, coverage, DRC and route-error checks'],'problems':problems}
a.output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({'status':result['status'],'canonical_matches':result['canonical']['source_hash_matches'],'flow_inputs':len(hashes),'small_native_matches':{k:v['native_hash_matches'] for k,v in small.items()},'mapped_native_matches':result['mapped_unisim']['native_archive_hash_matches'],'output':str(a.output),'sha256':sha(a.output),'problems':problems},indent=2))
sys.exit(bool(problems))
