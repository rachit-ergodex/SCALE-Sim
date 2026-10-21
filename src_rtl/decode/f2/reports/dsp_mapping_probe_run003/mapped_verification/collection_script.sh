set -eu
python3 - <<'PY'
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,tarfile
root=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
passed=json.loads((root/'netlist-equivalence-002/summary.json').read_text())
assert passed['status']=='passed'
assert json.loads((root/'netlist-equivalence-001/summary.json').read_text())['status']=='failed'
assert passed['results']['all_output_comparisons']=='221934'
assert passed['results']['observed_output_bits']=='3496'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(root/'netlist-equivalence-001/core_netlist.v')==sha(root/'netlist-equivalence-002/core_netlist.v')
assert sha(root/'netlist-equivalence-001/reference.sv')==sha(root/'netlist-equivalence-002/reference.sv')
old=(root/'netlist-equivalence-001/tb.sv').read_text()
new=(root/'netlist-equivalence-002/tb.sv').read_text()
assert old.replace('decode_os_core dut_got','mapped_core_observed dut_got')==new
files=[]
for name in ('netlist-equivalence-001','netlist-equivalence-002','boundary-proof-scripts'):
 for f in (root/name).iterdir():
  if f.is_file() and f.suffix in ('.json','.py','.v','.sv','.tsv','.txt','.log','.sh'):files.append(f)
for name in ('dsp-003/post_synth.v','mapped_harness_module.v','core_instance_connection.v','output_capture_map.json','build_observation_wrapper.py','netlist-equivalence-001-launcher.log','netlist-equivalence-002-launcher.log'):
 f=root/name;assert f.is_file(),f;files.append(f)
for f in root.glob('*connection*proof*'):
 if f.is_file() and f.suffix in ('.json','.py','.sh','.txt'):files.append(f)
files=sorted(set(files))
manifest={'collected_utc':datetime.now(timezone.utc).isoformat(),'remote_root':str(root),'scope':'Actual 4x8 DSP48E2 mapped netlist functional equivalence against original verified RTL, with faithful reconstruction of all synthesized harness captured output bits. No SDF, full-size mapping, physical timing closure, F2 shell, or throughput claim.','status':'passed','previous_attempt_status':'failed_raw_optimized_boundary_comparison','same_mapped_core_both_attempts':True,'same_reference_both_attempts':True,'same_stimulus_comparison_both_attempts':True,'vendor_models_included':False,'files_sha256':{str(f.relative_to(root)):sha(f) for f in files}}
out=root/'mapped_equivalence_collection_manifest.json';assert not out.exists();out.write_text(json.dumps(manifest,indent=2)+'\n');files.append(out)
archive=root/'mapped-equivalence-evidence-002.tar.gz';assert not archive.exists()
with tarfile.open(archive,'w:gz') as tar:
 for f in sorted(files):tar.add(f,arcname=str(f.relative_to(root)),recursive=False)
print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'sha256':sha(archive),'files':len(files),'uncompressed_bytes':sum(f.stat().st_size for f in files)},indent=2))
PY
