from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,re
root=Path(__file__).resolve().parent
binpath=Path('/opt/Xilinx/2025.2/Vivado/bin')
vendor_glbl=Path('/opt/Xilinx/2025.2/Vivado/data/verilog/src/glbl.v')
vendor_dsp=Path('/opt/Xilinx/2025.2/Vivado/data/verilog/src/unisims/DSP48E2.v')
inputs=[root/'tb.sv',root/'reference.sv',root/'core_netlist.v',root/'observation_wrapper.v',root/'output_capture_map.json',vendor_glbl]
sha=lambda p:hashlib.file_digest(p.open('rb'),'sha256').hexdigest()
hashes={str(p):sha(p) for p in inputs}
result={'status':'running','scope':'4x8 mapped-netlist functional equivalence against original verified RTL, using installed UNISIM and glbl; no SDF or routed timing claim','started_utc':datetime.now(timezone.utc).isoformat(),'source_sha256':hashes,'vendor_glbl_path':str(vendor_glbl),'vendor_dsp_model_path':str(vendor_dsp),'vendor_dsp_model_sha256':sha(vendor_dsp) if vendor_dsp.is_file() else None,'libraries':['unisims_ver','secureip'],'physical_timing_closed':False,'stages':[]}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
commands=[
 ('xvlog',[str(binpath/'xvlog'),'--sv','--work','work','core_netlist.v','observation_wrapper.v','reference.sv','tb.sv',str(vendor_glbl)]),
 ('xelab',[str(binpath/'xelab'),'--debug','typical','--relax','--mt','8','-L','unisims_ver','-L','secureip','work.tb','work.glbl','-s','netlist_equiv']),
 ('xsim',[str(binpath/'xsim'),'netlist_equiv','-runall','-onfinish','quit','-log','xsim.log'])]
try:
 version=subprocess.run([str(binpath/'xsim'),'-version'],cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,check=True)
 result['simulator_version']=version.stdout.strip();(root/'xsim_version.txt').write_text(version.stdout)
 for name,command in commands:
  stage={'name':name,'command':command,'started_utc':datetime.now(timezone.utc).isoformat()}
  result['stages'].append(stage)
  with (root/f'{name}.console.log').open('w') as log:
   proc=subprocess.run(command,cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
  stage.update(returncode=proc.returncode,finished_utc=datetime.now(timezone.utc).isoformat())
  (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
  if proc.returncode:raise RuntimeError(f'{name} failed: {proc.returncode}')
  print(name,'completed',flush=True)
 log=(root/'xsim.console.log').read_text()
 if 'TB_PASS ' not in log or 'TB_MISMATCH' in log or re.search(r'(?m)^(?:ERROR|FATAL|Error:|Fatal:)',log):raise RuntimeError('Simulation has no clean explicit pass')
 rows=dict(line.split('\t',1) for line in (root/'results.tsv').read_text().splitlines())
 if rows.get('status')!='passed':raise RuntimeError('Missing passing result marker')
 expected={'valid_commands':520,'invalid_commands':6,'mid_command_resets':4,'observed_output_bits':3496}
 for key,value in expected.items():
  if int(rows[key])!=value:raise RuntimeError(f'Coverage mismatch: {key}')
 if int(rows['all_output_comparisons'])!=2*(int(rows['clock_ticks'])-24) or int(rows['stall_cycles_checked'])<1:raise RuntimeError('Incomplete edge/stall coverage')
 if hashes!={str(p):sha(p) for p in inputs}:raise RuntimeError('Simulation source changed')
 result.update(status='passed',results=rows)
except BaseException as exc:
 result.update(status='failed',error=str(exc));raise
finally:
 result['finished_utc']=datetime.now(timezone.utc).isoformat()
 result['artifacts_sha256']={f.name:sha(f) for f in root.iterdir() if f.is_file() and f.name!='summary.json' and f.suffix in ('.sv','.v','.tsv','.log','.txt','.json','.py')}
 (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'status':result['status'],'results':result.get('results'),'error':result.get('error')},indent=2),flush=True)
