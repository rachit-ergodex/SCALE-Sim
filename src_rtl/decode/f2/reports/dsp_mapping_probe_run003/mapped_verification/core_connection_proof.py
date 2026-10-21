from pathlib import Path
import hashlib,json,re
base=Path(__file__).resolve().parent
netlist=base/'dsp-003/post_synth.v'
s=netlist.read_text()
modules={name:body for name,body in re.findall(r'\bmodule\s+(\w+)\b(.*?)\bendmodule\b',s,re.S)}
assert 'decode_compute_timing_harness' in modules and 'decode_os_core' in modules
core=modules['decode_os_core'];top=modules['decode_compute_timing_harness']
instances=re.findall(r'\bdecode_os_core\s+core\s*\((.*?)\);',top,re.S)
assert len(instances)==1
connections=re.findall(r'\.([a-zA-Z_][a-zA-Z_0-9]*)\(([^()]*)\)',instances[0])
assert len(connections)==len({name for name,_ in connections})
actual={name:re.sub(r'\s+','',expression) for name,expression in connections}
expected={}
for direction,width,names in [
 ('input',1,'clk rst cmd_valid cmd_parallel_rows cmd_accumulate cycle_ready'),
 ('input',32,'cmd_m cmd_k cmd_n a_data'),('input',256,'b_data'),('input',1024,'seed_data'),
 ('output',1,'cmd_ready busy done command_error'),('output',4,'a_valid'),
 ('output',128,'a_address'),('output',32,'b_valid seed_valid c_valid'),
 ('output',1024,'b_address c_address c_data'),('output',64,'logical_cycles elapsed_cycles stall_cycles')]:
 for name in names.split():expected[name]={'direction':direction,'width':width,'expression':name}
expected['clk']['expression']='core_clk'
expected['c_address']['expression']='{c_address,NLW_core_c_address_UNCONNECTED[0]}'
assert set(actual)==set(expected),(set(actual)-set(expected),set(expected)-set(actual))
formal=set(re.findall(r'\b(?:input|output)\s+(?:\[[^]]+\]\s*)?(\w+)\s*;',core))
assert formal==set(expected),(formal-set(expected),set(expected)-formal)
rows=[]
for name,item in expected.items():
 assert actual[name]==item['expression'],(name,actual[name],item)
 declaration=re.search(r'\b'+item['direction']+r'\s*(\[[^]]+\])?\s*'+name+r'\s*;',core)
 assert declaration,(name,'formal declaration missing')
 dimensions=declaration[1]
 if dimensions:
  hi,lo=map(int,re.findall(r'\d+',dimensions));width=abs(hi-lo)+1
 else:width=1
 assert width==item['width'],(name,width,item)
 if name!='c_address':
  actual_name=item['expression']
  wire=re.search(r'\bwire\s*(\[[^]]+\])?\s*'+actual_name+r'\s*;',top)
  assert wire,(name,'top wire missing')
  dims=wire[1]
  if dims:
   hi,lo=map(int,re.findall(r'\d+',dims));assert lo==0 and hi+1==width,(name,dims)
  else:assert width==1,name
 rows.append(dict(port=name,**item,formal_declaration=declaration[0]))
assert re.search(r'\bwire\s*\[1023:1\]\s*c_address\s*;',top)
assert re.search(r'\bwire\s*\[928:0\]\s*NLW_core_c_address_UNCONNECTED\s*;',top)
result={'status':'passed','scope':'Exact synthesized core instance port correspondence; capture aliases are separately reconstructed without masking any compared bit',
 'post_synth_v_sha256':hashlib.sha256(netlist.read_bytes()).hexdigest(),
 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
 'instance_count':1,'formal_port_count':len(formal),'connected_port_count':len(actual),
 'every_formal_port_checked':True,'all_direct_bus_widths_checked':True,
 'exceptions':{'clk':'Direct core clock wire core_clk','c_address':'Formal [1023:1] maps directly to top c_address[1023:1]; formal bit0 maps to unused bit0. Captured bit0 is reconstructed from the independently proved top capture mux.'},
 'connections':sorted(rows,key=lambda row:row['port'])}
out=base/'core_connection_proof.json';out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='connections'},indent=2,sort_keys=True))
print('proof_sha256='+hashlib.sha256(out.read_bytes()).hexdigest())
