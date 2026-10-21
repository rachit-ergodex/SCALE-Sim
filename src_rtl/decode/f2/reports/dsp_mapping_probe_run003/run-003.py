from pathlib import Path
import json,subprocess,hashlib
from datetime import datetime,timezone
root=Path(__file__).resolve().parent;out=root/'dsp-003'
command=['/opt/Xilinx/2025.2/Vivado/bin/vivado','-mode','batch','-nojournal','-log',str(out/'vivado.log'),'-source',str(root/'probe-003.tcl'),'-tclargs',str(root),'dsp']
result={'scope':'Synthesis-only mapping experiment','command':command,'started_utc':datetime.now(timezone.utc).isoformat(),'functional_verification_pass':False,'physical_timing_closed':False}
with (out/'console.log').open('w') as stream:
 rc=subprocess.run(command,cwd=out,stdout=stream,stderr=subprocess.STDOUT).returncode
result.update(returncode=rc,finished_utc=datetime.now(timezone.utc).isoformat(),complete=(out/'complete.txt').is_file())
result['files_sha256']={f.name:hashlib.file_digest(f.open('rb'),'sha256').hexdigest() for f in out.iterdir() if f.is_file() and f.suffix in ('.rpt','.tsv','.v','.dcp')}
(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
raise SystemExit(rc or (0 if result['complete'] else 1))
