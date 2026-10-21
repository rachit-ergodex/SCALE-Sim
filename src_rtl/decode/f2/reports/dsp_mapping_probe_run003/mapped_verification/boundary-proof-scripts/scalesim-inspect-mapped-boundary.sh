set -eu
python3 - <<'PY'
from pathlib import Path
import re,json
p=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
s=(p/'dsp-003/post_synth.v').read_text()
match=re.search(r'\bdecode_os_core\s+core\s*\(',s);assert match
end=s.index(');',match.start())+2
instance=s[match.start():end]
(p/'core_instance_connection.v').write_text(instance+'\n')
print('CORE_INSTANCE_START',instance[:900])
for port in ['c_address','c_data','a_address','b_address']:
 m=re.search(r'\.'+port+r'\((.*?)\),?\s*\n',instance,re.S)
 if m: print(port,'chars',len(m[1]),'start',m[1][:1600],'end',m[1][-300:])
core=(p/'netlist-equivalence-001/core_netlist.v').read_text()
lines=core.splitlines()
for i,line in enumerate(lines):
 if re.search(r'c_address\[32\]',line): print('CORE_LINE',i+1,'\n'.join(lines[max(0,i-4):i+3]))
PY
