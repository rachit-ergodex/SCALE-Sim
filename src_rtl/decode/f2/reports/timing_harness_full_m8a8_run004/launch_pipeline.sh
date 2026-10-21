set -eu
TASK_ROOT=/home/ubuntu/rachit/scalesim-m8a8-20261021
python3 - <<'CHECK'
from pathlib import Path
import hashlib,json
root=Path('/home/ubuntu/rachit/scalesim-m8a8-20261021')
provenance=json.loads((root/'launch_provenance.json').read_text())
for name,digest in {**provenance['source_hashes'], **provenance['runner_files_sha256']}.items():
 assert hashlib.sha256((root/'source-004'/name).read_bytes()).hexdigest()==digest,name
mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}
assert mem['MemAvailable']>110*1024*1024,mem['MemAvailable']
assert not (root/'full-100-pipeline-004').exists()
assert provenance['prerequisite_audit_passed'] is True
print('PASS: source/runner provenance, prerequisite audit and memory checked')
CHECK
runuser -u ubuntu -- python3 "$TASK_ROOT/source-004/src_rtl/decode/f2/scripts/run_full_timing_pipeline.py" --output "$TASK_ROOT/full-100-pipeline-004" --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8 --dry-run > "$TASK_ROOT/pipeline-dry-run-004.json"
systemd-run --unit=scalesim-full4096-100-m8a8-20261021-004 --description="SCALE-Sim full4096MAC100MHz synthesis then resource-gated PnR" --property=User=ubuntu --property=WorkingDirectory="$TASK_ROOT/source-004" --property=MemoryAccounting=yes --property=MemoryMax=100G --property=MemorySwapMax=4G --property=OOMPolicy=stop --property=KillMode=control-group --property=TimeoutStopSec=45 --property=StandardOutput=append:"$TASK_ROOT/pipeline-launcher-004.log" --property=StandardError=inherit /usr/bin/time -v /usr/bin/python3 -u src_rtl/decode/f2/scripts/run_full_timing_pipeline.py --output "$TASK_ROOT/full-100-pipeline-004" --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8
systemctl show scalesim-full4096-100-m8a8-20261021-004.service --property=ActiveState,SubState,MainPID,MemoryMax,MemorySwapMax,OOMPolicy,KillMode
