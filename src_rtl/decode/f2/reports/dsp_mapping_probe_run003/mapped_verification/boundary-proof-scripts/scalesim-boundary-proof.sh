set -eu
python3 - <<'PY'
from pathlib import Path
import re,json,hashlib
base=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
s=(base/'mapped_harness_module.v').read_text()
r=json.loads((base/'output_capture_map.json').read_text())
assert len(r['rows'])==3496
assert [v['bit'] for v in r['rows']]==list(range(3496))
controls=set();aliases={}
for v in r['rows']:
 bit=v['bit'];ports=v['ports']
 assert ports['O']==f'p_0_in[{bit}]'
 if bit<3495:
  assert v['width']==3 and v['init']=="8'hB8"
  assert ports['I2']==f'\\output_scan_reg_n_0_[{bit+1}]'
  assert ports['I1'].startswith('output_capture_q')
  controls.add(ports['I1']);source=ports['I0']
 else:
  assert v['width']==2 and v['init']=="4'h8"
  assert ports['I0']=='output_capture_q' and ports['I1']=='stall_cycles[63]'
  controls.add(ports['I0']);source=ports['I1']
 v['capture_source']=source
 if source!=v['expected']:aliases[v['expected']]=source
 # Exact output shift/capture register endpoint, clock, reset, and enable.
 pat=r'FDRE\s+\\output_scan_reg\['+str(bit)+r'\]\s*\((.*?)\);'
 m=re.search(pat,s,re.S);assert m,bit
 rp={k:x.strip() for k,x in re.findall(r'\.([A-Z][A-Z0-9]?)\(([^()]*)\)',m[1])}
 assert rp=={'C':'core_clk','CE':r'\output_scan[3495]_i_1_n_0','D':f'p_0_in[{bit}]','Q':f'\\output_scan_reg_n_0_[{bit}]','R':"1'b0"},(bit,rp)
# Prove every selector comes from one negative-edge register of output_capture.
found={}
rx=re.compile(r"FDRE\s*#\(\s*\.IS_C_INVERTED\(1'b1\)\)\s*(output_capture_q_reg[^\s]*)\s*\((.*?)\);",re.S)
for name,body in rx.findall(s):
 ports={k:v.strip() for k,v in re.findall(r'\.([A-Z][A-Z0-9]?)\(([^()]*)\)',body)}
 assert ports['C']=='core_clk' and ports['CE']=="1'b1" and ports['D']=='output_capture' and ports['R']=="1'b0"
 found[ports['Q']]=name
assert controls==set(found),(controls-set(found),set(found)-controls)
r['proof']={'captured_bits':3496,'unique_bits':3496,'lut3_capture_muxes':3495,'last_bit_zero_fill_lut2':1,'capture_selectors':len(controls),'all_selectors_negative_edge_output_capture':True,'all_output_scan_endpoints_exact':True,'shift_successor_mapping_exact':True,'nonidentity_aliases':len(aliases),'all_other_capture_bits_identity':3496-len(aliases)}
r['aliases']=aliases
r['post_synth_v_sha256']=hashlib.sha256((base/'dsp-003/post_synth.v').read_bytes()).hexdigest()
(base/'output_capture_map.json').write_text(json.dumps(r,indent=2,sort_keys=True)+'\n')
print(json.dumps({'proof':r['proof'],'aliases':aliases,'top_sha256':r['top_sha256'],'post_synth_v_sha256':r['post_synth_v_sha256'],'map_sha256':hashlib.sha256((base/'output_capture_map.json').read_bytes()).hexdigest()},indent=2,sort_keys=True))
PY
