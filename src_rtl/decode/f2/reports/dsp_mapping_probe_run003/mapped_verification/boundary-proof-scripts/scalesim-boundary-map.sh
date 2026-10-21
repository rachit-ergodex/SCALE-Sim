set -eu
python3 - <<'PY'
from pathlib import Path
import re,json,hashlib
base=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
s=(base/'mapped_harness_module.v').read_text()
rx=re.compile(r"LUT([1-6])\s*#\(\s*\.INIT\(([0-9]+'h[0-9A-Fa-f]+)\)\)\s*\\output_scan\[([0-9]+)\]_i_([0-9]+)\s*\((.*?)\);",re.S)
rows=[]
expected={};start=0
for name,width in [('cmd_ready',1),('busy',1),('done',1),('command_error',1),('a_valid',4),('a_address',128),('b_valid',32),('b_address',1024),('seed_valid',32),('c_valid',32),('c_address',1024),('c_data',1024),('logical_cycles',64),('elapsed_cycles',64),('stall_cycles',64)]:
 for i in range(width): expected[start+i]=f'{name}[{i}]' if width>1 else name
 start+=width
for width,init,bit,index,body in rx.findall(s):
 ports={k:v.strip() for k,v in re.findall(r'\.([A-Z][0-9]?)\(([^()]*)\)',body)}
 if ports.get('O')!=f'p_0_in[{bit}]':continue
 rows.append(dict(bit=int(bit),width=int(width),init=init,ports=ports,expected=expected[int(bit)]))
print('COUNT',len(rows),'UNIQUE',len({r['bit'] for r in rows}),'MISSING',sorted(set(range(3496))-{r['bit'] for r in rows}))
print('PATTERNS',sorted({(r['width'],r['init']) for r in rows}))
for r in rows:
 if r['width']!=3 or r['init']!="8'hB8" or r['ports']['I0']!=r['expected']:
  print(json.dumps(r,sort_keys=True))
print('MULTIPLEXER_EXPECTED_SELECT_DIFFERENCES',[r['bit'] for r in rows if r['width']==3 and not r['ports']['I1'].startswith('output_capture_q')])
(base/'output_capture_map.json').write_text(json.dumps({'top_sha256':hashlib.sha256(s.encode()).hexdigest(),'rows':sorted(rows,key=lambda r:r['bit'])},indent=2)+'\n')
PY
