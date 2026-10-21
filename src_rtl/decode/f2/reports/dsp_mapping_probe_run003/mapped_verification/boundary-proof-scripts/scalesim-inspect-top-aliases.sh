set -eu
python3 - <<'PY'
from pathlib import Path
import re,json,base64,gzip
p=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
s=(p/'dsp-003/post_synth.v').read_text()
m=re.search(r'(?ms)^module decode_compute_timing_harness\b.*?^endmodule\s*',s);assert m
h=m[0];(p/'mapped_harness_module.v').write_text(h)
lines=h.splitlines()
for i,line in enumerate(lines):
 if 'core_outputs' in line or re.search(r'\b(?:assign|wire).*c_address',line):print(i+1,line)
print('c_address32 occurrences')
for i,line in enumerate(lines):
 if re.search(r'c_address\[32\]',line): print(i+1,'\n'.join(lines[max(0,i-6):i+7]))
print('c_address[0] assignments core')
core=(p/'netlist-equivalence-001/core_netlist.v').read_text()
i=core.index('assign c_address');print(core[i:i+2800])
PY
