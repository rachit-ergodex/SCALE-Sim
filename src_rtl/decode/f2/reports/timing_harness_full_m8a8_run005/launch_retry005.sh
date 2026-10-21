set -eu
TASK_ROOT=/home/ubuntu/rachit/scalesim-m8a8-20261021
python3 - <<'CHECK'
from pathlib import Path
import json,hashlib,shutil
root=Path('/home/ubuntu/rachit/scalesim-m8a8-20261021')
expected={'source_base_commit': '8c09ff2570f8dc830500879c4ff420956d6400d4', 'source_hashes': {'src_rtl/decode/rtl/decode_os_core.sv': '5083d843fcd001d50044de27650489e1092f1ab09eb081516f83359c79d91aed', 'src_rtl/decode/f2/harness/decode_compute_timing_harness.sv': '2488724ed4bbccce107bfd36149c2416f02c0c8283a838a508dc1116b5e53edd', 'src_rtl/decode/f2/harness/harness_constraints.tcl': '8367328a195997a34e3995c367d5efaee273ccb4625018da98100d918d3e735d', 'src_rtl/decode/f2/harness/bufg_sim.sv': 'c28a16d03f7e39c0dece0a772f0c53b6439430443cd0189016531df41917848e', 'src_rtl/decode/f2/harness/scan_core_fixture.sv': '0425d020143018169e8213d0f666101e30baa4c5b829c9d551864f63a6d76f6e', 'src_rtl/decode/f2/harness/test_timing_harness.py': 'a54162b491af8f96c80b99f600f45804844c4af9cb56bb282849d6e94bd713d5', 'src_rtl/decode/f2/harness/run_harness_tests.py': '5a3eb9bf9575f2ac2d34f7fa59177ffddcbb063781749bb768e31ceacaa3aaee', 'src_rtl/decode/verification.json': '4f2a9a8c6327199c9888a8e1c474f3d2691a334358f351fc11c61c02c8327627', 'src_rtl/decode/f2/harness/verification.json': '14e844c29a64249c9bc8704a165a1a8b80763c4a04903bb4f70bef5192532ef8', 'src_rtl/decode/f2/scripts/run_timing_harness.py': 'eb69e2213920ad88d421d11469b4f2f6bf1814786b270df3d9cf35542d672c08', 'src_rtl/decode/f2/scripts/timing_harness.tcl': '4fea79f9c69e94937966958bc9093fbf0ea24710b2ecfee8c906f7c403e88f76', 'src_rtl/decode/f2/scripts/audit_compute_ooc.py': '7ca2f9b9279629229584b8e48699bf5e908270491a298e1fd79864f85da83b6c'}, 'runner_files_sha256': {'src_rtl/decode/f2/scripts/run_full_timing_pipeline.py': 'ac97193289c433f7e4bbeb68529a373a4bee3e662a2c3ed29501ceb1b3404004', 'src_rtl/decode/f2/scripts/test_full_timing_pipeline.py': 'db195710f7c7b91ea8430b2f38ce6dfbb365d7408391a0b1346cd75ce3b06393', 'src_rtl/decode/f2/scripts/FULL_TIMING_PIPELINE.md': 'd17fa9d26cc4c02fac8d12e3945ad089a9688c32604dc1e5a9ba5d95b95e6022'}, 'prerequisite_audit_sha256': '2c7692ecfb45124d2ea845b27a602d74da7ec0e1c6e18b077acf9cdd395d99cf', 'prerequisite_audit_passed': True, 'scope': 'Full4096MAC100MHz compute-harness synthesis and resource-gated PnR; notF2image', 'vivado_build': '2025.2 SW6299465', 'instance_id': 'i-053000112615d30d5'}
for name,digest in {**expected['source_hashes'],**expected['runner_files_sha256']}.items():
 assert hashlib.sha256((root/'source-004'/name).read_bytes()).hexdigest()==digest,name
old=json.loads((root/'full-100-pipeline-004/status.json').read_text());assert old['status']=='failed' and old['stage']=='synth'
assert not (root/'full-100-pipeline-005').exists()
mem={k:int(v.split()[0]) for k,v in (line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())}
assert mem['MemAvailable']>110*1024*1024
assert shutil.disk_usage(root).free>150*1024**3
# Preserve this task's old crash report on EBS, allowing Apport to capture a new report.
crash=Path('/var/crash/_opt_Xilinx_2025.2_Vivado_bin_unwrapped_lnx64.o_vivado.1000.crash')
archive=root/'crash-004-original';archive.mkdir(exist_ok=False)
assert hashlib.sha256(crash.read_bytes()).hexdigest()=='8a97b1bbd2a28dd408cb90341e2d6ec37059f3218d51a3f9d5d3c325dbbf64b2'
shutil.move(str(crash),str(archive/crash.name))
(archive/'retention.txt').write_text('Original task crash report retained locally on encrypted EBS. Contains process metadata; not uploaded to GitHub.\n')
print('PASS: unchanged source, failedrunpreserved, fresh005path, >110GiBavailableRAM, >150GiBfreedisk')
CHECK
runuser -u ubuntu -- python3 "$TASK_ROOT/source-004/src_rtl/decode/f2/scripts/run_full_timing_pipeline.py" --output "$TASK_ROOT/full-100-pipeline-005" --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8 --dry-run > "$TASK_ROOT/pipeline-dry-run-005.json"
systemd-run --unit=scalesim-full4096-100-m8a8-20261021-005 --description="SCALE-Sim full4096MAC100MHz stack256MiB recovery with gatedPnR" --property=User=ubuntu --property=WorkingDirectory="$TASK_ROOT/source-004" --property=MemoryAccounting=yes --property=MemoryMax=100G --property=MemorySwapMax=4G --property=LimitSTACK=256M:infinity --property=LimitCORE=infinity --property=OOMPolicy=stop --property=KillMode=control-group --property=TimeoutStopSec=45 --property=StandardOutput=append:"$TASK_ROOT/pipeline-launcher-005.log" --property=StandardError=inherit /usr/bin/time -v /usr/bin/python3 -u src_rtl/decode/f2/scripts/run_full_timing_pipeline.py --output "$TASK_ROOT/full-100-pipeline-005" --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8
systemctl show scalesim-full4096-100-m8a8-20261021-005.service --property=ActiveState,SubState,MainPID,MemoryMax,MemorySwapMax,LimitSTACK,LimitSTACKSoft,LimitCORE,LimitCORESoft
