from pathlib import Path
import hashlib,json,re,shutil
p=Path('/home/ubuntu/rachit/scalesim-harness-20261021/dsp-probe')
out=p/'netlist-equivalence-002';out.mkdir()
old=p/'netlist-equivalence-001'
sha=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
assert sha(p/'dsp-003/post_synth.v')=='3de89e7c93571b758306a0cc48a72e542fa2e91ecbc9cb16ad84fb27380cf330'
assert sha(p/'output_capture_map.json')=='cee57b84f4fd316479cb06e6f049c39af83f29113a60055e89f519a53e898bf3'
for f in ['core_netlist.v','reference.sv','generate_tb.py']:
 shutil.copyfile(old/f,out/f)
assert sha(out/'reference.sv')=='5e946085a5b050b768206b10e6cf92890d4a4b750b32cdb5a86a8fc69bbdc21c'
tb=(old/'tb.sv').read_text()
inputs=[(width or '',name) for width,name in re.findall(r'^  logic (\[\d+:0\] )?(\w+);',tb,re.M)]
outputs=[(width or '',name) for width,name in re.findall(r'^  wire (\[\d+:0\] )?(\w+)_got;',tb,re.M)]
assert len(inputs)==12 and len(outputs)==15,(inputs,outputs)
output_names={name for _,name in outputs}
expected_bits={name if not width else f'{name}[{i}]' for width,name in outputs for i in range(int(width[1:].split(':')[0])+1 if width else 1)}
assert len(expected_bits)==3496
mapping=json.loads((p/'output_capture_map.json').read_text())
assert len(mapping['rows'])==3496
assert {r['expected'] for r in mapping['rows']}==expected_bits
assert all(r['capture_source'] in expected_bits for r in mapping['rows'])
assert mapping['proof']['nonidentity_aliases']==20
lines=['`timescale 1ps/1ps','// Observation boundary reproduced from all 3,496 synthesized harness capture muxes.',
       '// The mapped core module and all of its primitives are unchanged.',
       'module mapped_core_observed (',',\n'.join(['  input wire '+w+n for w,n in inputs]+['  output wire '+w+n for w,n in outputs]),');']
lines += ['  wire '+w+'raw_'+n+';' for w,n in outputs]
lines += ['  decode_os_core mapped (',',\n'.join(['    .'+n+'('+n+')' for w,n in inputs]+['    .'+n+'(raw_'+n+')' for w,n in outputs]),'  );']
for r in mapping['rows']:
 lines += [f'  assign {r["expected"]} = raw_{r["capture_source"]}; // capture bit {r["bit"]}']
lines += ['endmodule','']
(out/'observation_wrapper.v').write_text('\n'.join(lines))
assert tb.count('decode_os_core dut_got')==1
(out/'tb.sv').write_text(tb.replace('decode_os_core dut_got','mapped_core_observed dut_got'))
runner=(old/'run_equivalence.py').read_text().replace("root/'core_netlist.v',vendor_glbl", "root/'core_netlist.v',root/'observation_wrapper.v',root/'output_capture_map.json',vendor_glbl").replace("'core_netlist.v','reference.sv','tb.sv'", "'core_netlist.v','observation_wrapper.v','reference.sv','tb.sv'")
(out/'run_equivalence.py').write_text(runner)
shutil.copyfile(p/'output_capture_map.json',out/'output_capture_map.json')
record=json.loads((old/'provenance.json').read_text())
record.update(attempt='002',previous_attempt='001 failed strict comparison because direct raw optimized submodule pins omitted aliases preserved by enclosing synthesized harness; no DSP arithmetic mismatch was established',observation_boundary='Every original output bit reconstructed from its actual synthesized harness capture-data source, with proven mux, selector, register, and shift connectivity; comparisons remain unconditional over all 3,496 bits',observation_aliases=mapping['aliases'],observation_proof=mapping['proof'],output_map_sha256=sha(out/'output_capture_map.json'),testbench_change='Only DUT module identifier replaced with generated observation wrapper; stimulus and comparison unchanged',probe_harness_scope='Original source-001 harness used for both area probes; simulation excludes scan storage but reconstructs exact captured core observable bits')
record['attempt_files_sha256']={f.name:sha(f) for f in out.iterdir() if f.is_file()}
(out/'provenance.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'attempt':'002','assignments':len(mapping['rows']),'aliases':len(mapping['aliases']),'wrapper_sha256':sha(out/'observation_wrapper.v')},indent=2))
