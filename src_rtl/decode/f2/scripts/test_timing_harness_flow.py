"""Fail-closed driver gates; these tests do not substitute for Vivado implementation."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('harness_flow', Path(__file__).with_name('run_timing_harness.py'))
flow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(flow)
FLAT = '''| Site Type | Used | Fixed | Prohibited | Available | Util% |
| CLB LUTs* | 10 | 0 | 0 | 100 | 10 |
| CLB Registers | 20 | 0 | 0 | 100 | 20 |
| Block RAM Tile | 0 | 0 | 0 | 100 | 0 |
| DSPs | 4 | 0 | 0 | 100 | 4 |
'''


def dsp_report(partitions, cols):
    return 'cell\tprimitive\tAREG\tBREG\tCREG\tMREG\tPREG\n' + ''.join(
        f'core/g_mac_partition[{p}].g_mac_column[{c}].lane_sum\tDSP48E2\t{c % 3}\t0\t0\t0\t0\n'
        for p in range(partitions) for c in range(cols))


class HarnessFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / 'repository'; self.root.mkdir()
        for name in flow.INPUTS:
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('source ' + str(name))
        (self.root / flow.VERIFICATION).write_text(json.dumps({'status': 'passed', 'sources_sha256': {
            str(flow.CORE): flow.sha(self.root / flow.CORE)}}))
        (self.root / flow.HARNESS_VERIFICATION).write_text(json.dumps({
            'status':'passed','tests_passed':8,
            'cases':[dict(partitions=p,cols=c,mapping_fixture=stub,status='passed',tests=2)
                     for p,c,stub in [(1,3,True),(2,5,True),(1,3,False),(2,5,False)]],
            'source_sha256':{str(name):flow.sha(self.root/name) for name in flow.HARNESS_INPUTS}}))
        self.out = Path(self.tmp.name) / 'output'
        self.patch = patch.object(flow, 'ROOT', self.root); self.patch.start()
        self.addCleanup(self.patch.stop); self.addCleanup(self.tmp.cleanup)

    def invoke(self, *args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return flow.main(['--output', str(self.out), *args])

    def baseline(self):
        hashes = flow.checked_inputs(self.root)
        run = Path(self.tmp.name) / 'synthesis'; run.mkdir()
        for name in hashes:
            path = run / 'source' / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((self.root / name).read_bytes())
        (run / 'post_synth.dcp').write_bytes(b'checkpoint')
        (run / 'synth_utilization_flat.rpt').write_text(FLAT)
        (run / 'dsp_mapping.tsv').write_text(dsp_report(64,64))
        manifest = {'status': 'synth_resource_pass', 'stage': 'synth', 'part': flow.PART,
                    'partitions': 64, 'cols': 64, 'clock_period_ns': 10.0,
                    'source_hashes': hashes, 'checkpoint_sha256': flow.sha(run / 'post_synth.dcp'),
                    'utilization_sha256': flow.sha(run / 'synth_utilization_flat.rpt'),
                    'dsp_mapping': flow.expected_dsp_mapping(64,64),
                    'dsp_mapping_sha256': flow.sha(run / 'dsp_mapping.tsv')}
        (run / 'manifest.json').write_text(json.dumps(manifest))
        return run, hashes

    def test_dry_run_validates_without_creating_output(self):
        self.assertEqual(self.invoke('--stage', 'route', '--compute-mhz', '50', '--dry-run'), 0)
        self.assertFalse(self.out.exists())

    def test_stale_or_failed_numerical_verification_rejected(self):
        (self.root / flow.CORE).write_text('changed core')
        with self.assertRaises(ValueError): flow.checked_inputs(self.root)
        with self.assertRaises(SystemExit): self.invoke('--dry-run')
        self.assertFalse(self.out.exists())

    def test_stale_harness_verification_rejected(self):
        (self.root / flow.HARNESS).write_text('changed harness')
        with self.assertRaisesRegex(ValueError,'Harness verification is stale'): flow.checked_inputs(self.root)
        with self.assertRaises(SystemExit): self.invoke('--dry-run')

    def test_incomplete_harness_cases_rejected(self):
        path=self.root/flow.HARNESS_VERIFICATION
        record=json.loads(path.read_text());record['tests_passed']=7;path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError,'eight passing'): flow.checked_inputs(self.root)

    def test_invalid_arguments_rejected(self):
        for args in [('--threads','9'),('--threads','0'),('--partitions','0'),('--cols','65'),
                     ('--compute-mhz','nan'),('--compute-mhz','200'),('--max-utilization-percent','nan'),
                     ('--max-utilization-percent','101')]:
            with self.subTest(args=args), self.assertRaises(SystemExit): self.invoke(*args,'--dry-run')

    def test_existing_output_rejected(self):
        self.out.mkdir()
        with self.assertRaises(SystemExit): self.invoke('--dry-run')

    def test_large_route_requires_synth_resource_gate(self):
        with self.assertRaises(SystemExit): self.invoke('--partitions','64','--cols','64','--stage','route','--dry-run')
        self.assertEqual(self.invoke('--partitions','64','--cols','64','--stage','synth','--dry-run'), 0)

    def test_actual_capacity_gate(self):
        gate = flow.resource_gate(FLAT,90)
        self.assertEqual(gate['status'],'passed')
        self.assertEqual(gate['resources']['CLB LUTs']['available'],100)
        self.assertFalse(gate['physical_timing_closed'])
        self.assertEqual(flow.resource_gate(FLAT.replace('| 10 |','| 91 |',1),90)['status'],'failed')
        for bad in [FLAT.replace('DSPs','missing'), FLAT.replace('| 100 |','| 0 |'),FLAT.replace('| 10 |','| nan |',1)]:
            with self.assertRaises(ValueError): flow.resource_gate(bad,90)

    def test_baseline_hash_geometry_and_period_checked(self):
        run, hashes = self.baseline()
        checkpoint, digest = flow.checked_synthesis(run,hashes,64,64,10.0,90)
        self.assertEqual(digest,flow.sha(checkpoint))
        for p,c,period in [(32,64,10),(64,32,10),(64,64,20)]:
            with self.assertRaises(ValueError): flow.checked_synthesis(run,hashes,p,c,period,90)
        checkpoint.write_bytes(b'tampered')
        with self.assertRaises(ValueError): flow.checked_synthesis(run,hashes,64,64,10,90)

    def test_baseline_source_and_report_mutation_rejected(self):
        run, hashes = self.baseline()
        report = run / 'synth_utilization_flat.rpt'; report.write_text(FLAT+'changed')
        with self.assertRaises(ValueError): flow.checked_synthesis(run,hashes,64,64,10,90)
        report.write_text(FLAT)
        (run / 'source' / flow.CORE).write_text('changed')
        with self.assertRaises(ValueError): flow.checked_synthesis(run,hashes,64,64,10,90)

    def test_dsp_mapping_covers_every_exact_lane(self):
        report=Path(self.tmp.name)/'dsp_mapping.tsv'
        report.write_text(dsp_report(4,8))
        result=flow.validate_dsp_report(report,4,8)
        self.assertEqual(result['count'],32)
        self.assertTrue(result['lane_identity_set_verified'])
        self.assertEqual(sum(result['areg_counts'].values()),32)
        self.assertEqual(flow.expected_dsp_mapping(4,8)['define'],'SCALESIM_F2_USE_DSP')

    def test_zero_missing_and_extra_dsps_rejected(self):
        report=Path(self.tmp.name)/'dsp_mapping.tsv'
        lines=dsp_report(2,3).splitlines(keepends=True)
        for bad in [lines[:1],lines[:-1],lines+[lines[-1]]]:
            report.write_text(''.join(bad))
            with self.assertRaises(ValueError): flow.validate_dsp_report(report,2,3)

    def test_missing_lane_replaced_by_unrelated_dsp_rejected(self):
        report=Path(self.tmp.name)/'dsp_mapping.tsv'
        valid=dsp_report(2,3)
        for other in ['core/control_dsp','core/g_mac_partition[2].g_mac_column[0].lane_sum',
                      'core/g_mac_partition[0].g_mac_column[1].lane_sum']:
            report.write_text(valid.replace('core/g_mac_partition[0].g_mac_column[0].lane_sum',other))
            with self.assertRaisesRegex(ValueError,'lane identity'): flow.validate_dsp_report(report,2,3)

    def test_dsp_register_and_primitive_guards(self):
        report=Path(self.tmp.name)/'dsp_mapping.tsv'
        for column,value in [(1,'DSP48E1'),(2,'3'),(3,'3'),(4,'1'),(5,'1'),(6,'1')]:
            lines=dsp_report(1,1).splitlines(); row=lines[1].split('\t');row[column]=value
            report.write_text(lines[0]+'\n'+'\t'.join(row)+'\n')
            with self.subTest(column=column), self.assertRaises(ValueError): flow.validate_dsp_report(report,1,1)
        # Legal input-register absorption is explicit; equivalence is verified separately.
        report.write_text(dsp_report(1,1).replace('\t0\t0\t0\t0\t0\n','\t2\t2\t0\t0\t0\n'))
        self.assertEqual(flow.validate_dsp_report(report,1,1)['breg_counts']['2'],1)

    def test_baseline_dsp_mapping_and_report_bound(self):
        run,hashes=self.baseline(); manifest_path=run/'manifest.json'
        manifest=json.loads(manifest_path.read_text());manifest['dsp_mapping']['define']='other'
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'dsp_mapping'): flow.checked_synthesis(run,hashes,64,64,10,90)
        manifest['dsp_mapping']=flow.expected_dsp_mapping(64,64);manifest_path.write_text(json.dumps(manifest))
        report=run/'dsp_mapping.tsv';report.write_text(dsp_report(64,64).replace('DSP48E2','DSP48E1',1))
        with self.assertRaisesRegex(ValueError,'report hash'): flow.checked_synthesis(run,hashes,64,64,10,90)
        manifest['dsp_mapping_sha256']=flow.sha(report);manifest_path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError,'primitive'): flow.checked_synthesis(run,hashes,64,64,10,90)

    def test_zero_exit_without_readiness_is_failure(self):
        def fake(command, **kwargs):
            if '-version' not in command:
                (self.out/'dsp_mapping.tsv').write_text(dsp_report(4,8))
            return subprocess.CompletedProcess(command,0,stdout='Vivado test version')
        with patch.object(flow.shutil,'which',return_value='/fake/vivado'), patch.object(flow.subprocess,'run',side_effect=fake):
            with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(json.loads((self.out/'manifest.json').read_text())['status'],'interrupted_or_failed')

    def test_failed_vivado_never_certifies_timing(self):
        audit = self.root / flow.BASE / 'f2/scripts/audit_compute_ooc.py'
        audit.write_text("def audit(*args, **kwargs): return {'status':'passed','problems':[]}\n")
        self.out.mkdir()
        result=flow.route_audit(self.out,self.root,10.0,1)
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['component_routed_timing_pass'])
        self.assertFalse(result['f2_shell_timing_closed'])
        self.assertIn('registered compute harness',result['scope'])

    def test_tcl_dsp_guard_checks_identity_and_registers(self):
        text=Path(__file__).with_name('timing_harness.tcl').read_text()
        procedure=text[text.index('proc assert_dsp_mapping '):text.index('proc assert_constraints ')]
        script=procedure + r"""
set cells {{core/g_mac_partition[0].g_mac_column[0].lane_sum} {core/g_mac_partition[0].g_mac_column[1].lane_sum}}
set bad_creg 0
proc get_cells {args} {return $::cells}
proc get_property {property cell} {
    switch $property {
        NAME {return $cell}
        REF_NAME {return DSP48E2}
        CREG {return $::bad_creg}
        default {return 0}
    }
}
set run [lindex $argv 0]
assert_dsp_mapping $run 1 2
set saved $cells
lset cells 0 core/control_dsp
if {![catch {assert_dsp_mapping $run 1 2} message]} {error "unrelated DSP accepted"}
if {![string match {*lane/register*} $message]} {error $message}
set cells $saved
set bad_creg 1
if {![catch {assert_dsp_mapping $run 1 2} message]} {error "CREG accepted"}
puts VERIFIED
"""
        path=Path(self.tmp.name)/'dsp_guard.tcl';path.write_text(script)
        result=subprocess.run(['tclsh',str(path),self.tmp.name],text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.splitlines()[-1],'VERIFIED')

    def test_tcl_is_complete_and_uses_explicit_hold_fix(self):
        path=Path(__file__).with_name('timing_harness.tcl')
        script='set fp [open {'+str(path)+'} r]; set data [read $fp]; close $fp; if {![info complete $data]} {error incomplete}; puts complete\n'
        result=subprocess.run(['tclsh'],input=script,text=True,capture_output=True,check=True)
        self.assertEqual(result.stdout.strip(),'complete')
        data=path.read_text()
        self.assertIn('phys_opt_design -aggressive_hold_fix',data)
        self.assertIn('-verilog_define SCALESIM_F2_USE_DSP',data)
        self.assertNotIn('read_verilog -define',data)
        self.assertIn('assert_dsp_mapping $run $partitions $cols',data)
        self.assertNotIn('all_registers',data)
        self.assertNotIn('read_verilog -sv $source_root/src_rtl/decode/f2/harness/bufg_sim.sv',data)


if __name__ == '__main__': unittest.main()
