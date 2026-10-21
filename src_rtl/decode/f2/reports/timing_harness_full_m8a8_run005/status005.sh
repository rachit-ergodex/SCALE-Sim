set -eu
python3 - <<'STATUS'
from pathlib import Path
from datetime import datetime,timezone
import json,subprocess
r=Path('/home/ubuntu/rachit/scalesim-m8a8-20261021/full-100-pipeline-005')
result={'observed_utc':datetime.now(timezone.utc).isoformat()}
result['service']=subprocess.check_output(['systemctl','show','scalesim-full4096-100-m8a8-20261021-005.service','--property=ActiveState,SubState,MainPID,MemoryCurrent,MemoryPeak,Result,ActiveEnterTimestamp'],text=True)
for name in ['status.json','synth/manifest.json','route/manifest.json','route/audit.json']:
 p=r/name
 if p.exists():
  d=json.loads(p.read_text());result[name]={k:d[k] for k in ('status','stage','updated_utc','created_utc','finished_utc','error','resource_gate','resources','actual_dsp_mapping','vivado_returncode','component_routed_timing_pass','events','stages','problems') if k in d}
result['artifacts']={name:{'exists':(r/name).exists(),'bytes':(r/name).stat().st_size if (r/name).exists() else None} for name in ('synth/post_synth.dcp','synth/synth_utilization_flat.rpt','synth/dsp_mapping.tsv','route/post_place.dcp','route/post_route.dcp')}
for stage in ('synth','route'):
 p=r/stage/'vivado.log'
 if p.exists():
  lines=p.read_text().splitlines();result[stage+'_log']={'bytes':p.stat().st_size,'modified_utc':datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),'errors':[s for s in lines if s.startswith(('ERROR:','CRITICAL WARNING:'))][-10:],'progress':[s for s in lines if s.startswith(('Starting ','Finished ','Phase ','INFO: [Synth','INFO: [Common 17-349]','synth_design:','place_design:','route_design:'))][-15:],'tail':lines[-6:]}
print(json.dumps(result,indent=2))
STATUS
python3 - <<'LIMITS'
from pathlib import Path
import json
found=[]
for p in Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:args=p.joinpath('cmdline').read_bytes().split(b'\0')
 except OSError:continue
 if not args or args[0]!=b'/opt/Xilinx/2025.2/Vivado/bin/unwrapped/lnx64.o/vivado':continue
 if not any(b'full-100-pipeline-005/synth' in a for a in args):continue
 limits=p.joinpath('limits').read_text();found.append({'pid':p.name,'limits':[s for s in limits.splitlines() if 'stack size' in s or 'core file size' in s],'command':[a.decode() for a in args if a]})
print('ACTUAL_VIVADO_LIMITS',json.dumps(found))
LIMITS
