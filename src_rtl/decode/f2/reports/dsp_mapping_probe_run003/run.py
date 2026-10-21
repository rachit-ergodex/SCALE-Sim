from pathlib import Path
import json, subprocess, hashlib
from datetime import datetime, timezone
root=Path(__file__).resolve().parent
result={'scope':'Synthesis-only mapping experiment', 'functional_verification_pass':False,'physical_timing_closed':False,'variants':{}}
for name in ('baseline','dsp'):
 out=root/name; out.mkdir()
 cmd=['/opt/Xilinx/2025.2/Vivado/bin/vivado','-mode','batch','-nojournal','-log',str(out/'vivado.log'),'-source',str(root/'probe.tcl'),'-tclargs',str(root),name]
 record={'command':cmd,'started_utc':datetime.now(timezone.utc).isoformat()}
 result['variants'][name]=record
 with (out/'console.log').open('w') as stream:
  completed=subprocess.run(cmd,cwd=out,stdout=stream,stderr=subprocess.STDOUT)
 record.update(returncode=completed.returncode,finished_utc=datetime.now(timezone.utc).isoformat(),complete=(out/'complete.txt').is_file())
 record['files_sha256']={f.name:hashlib.file_digest(f.open('rb'),'sha256').hexdigest() for f in out.iterdir() if f.is_file() and f.suffix in ('.rpt','.tsv','.v','.dcp')}
 (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
 print(name,record['returncode'],record['complete'],flush=True)
 if completed.returncode or not record['complete']:
  raise SystemExit(completed.returncode or 1)
print(json.dumps(result,indent=2))
