"""Retarget provenance/CLI tests with synthetic files, not FPGA timing evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).with_name('run_compute_retarget.py')
SPEC = importlib.util.spec_from_file_location('retarget', SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(data):
    return hashlib.sha256(data).hexdigest()


class RetargetTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.baseline = self.root / 'baseline'
        self.output = self.root / 'new-run'
        self.baseline.mkdir()
        hashes = {}
        for relative in MODULE.RTL:
            data = f'Synthetic fixture for {relative}\n'.encode()
            path = self.baseline / 'source' / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            hashes[str(relative)] = digest(data)
        verification = {'status': 'passed', 'sources_sha256': hashes.copy()}
        relative = MODULE.BASE / 'verification.json'
        data = json.dumps(verification).encode()
        (self.baseline / 'source' / relative).write_bytes(data)
        hashes[str(relative)] = digest(data)
        self.manifest = {'part': MODULE.PART, 'macs': 4096, 'compute_mhz': 200,
                         'source_hashes': hashes}
        self.write_manifest()
        (self.baseline / 'post_synth.dcp').write_bytes(b'SYNTHETIC CHECKPOINT FIXTURE; NOT VIVADO DATA')

    def write_manifest(self):
        (self.baseline / 'manifest.json').write_text(json.dumps(self.manifest))

    def test_valid_baseline_binds_checkpoint_and_all_sources(self):
        manifest, manifest_sha, checkpoint_sha = MODULE.baseline_inputs(self.baseline)
        self.assertEqual(manifest, self.manifest)
        self.assertEqual(manifest_sha, MODULE.sha(self.baseline / 'manifest.json'))
        self.assertEqual(checkpoint_sha, MODULE.sha(self.baseline / 'post_synth.dcp'))

    def test_tampered_source_is_rejected(self):
        (self.baseline / 'source' / MODULE.RTL[0]).write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'snapshot does not match'):
            MODULE.baseline_inputs(self.baseline)

    def test_stale_numerical_verification_is_rejected_even_with_rehashed_snapshot(self):
        relative = MODULE.RTL[0]
        path = self.baseline / 'source' / relative
        path.write_text('new RTL without new numerical verification')
        self.manifest['source_hashes'][str(relative)] = MODULE.sha(path)
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'verification is stale'):
            MODULE.baseline_inputs(self.baseline)

    def test_empty_checkpoint_and_incorrect_geometry_are_rejected(self):
        (self.baseline / 'post_synth.dcp').write_bytes(b'')
        with self.assertRaisesRegex(ValueError, 'Missing or empty'):
            MODULE.baseline_inputs(self.baseline)
        self.manifest['macs'] = 32
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, '4096-MAC'):
            MODULE.baseline_inputs(self.baseline)

    def test_source_path_cannot_escape_snapshot(self):
        self.manifest['source_hashes'] = {'../outside': 'unused'}
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, 'Unsafe baseline source path'):
            MODULE.baseline_inputs(self.baseline)

    def invoke(self, *args):
        return subprocess.run([sys.executable, str(SCRIPT), '--baseline', str(self.baseline),
                               '--output', str(self.output), '--dry-run', *args],
                              text=True, capture_output=True)

    def test_100mhz_dry_run_preserves_baseline_and_does_not_create_output(self):
        before = MODULE.sha(self.baseline / 'post_synth.dcp')
        result = self.invoke('--compute-mhz', '100', '--stage', 'preflight')
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout.split('\n', 1)[1])
        self.assertEqual(plan['compute_mhz'], 100)
        self.assertEqual(plan['clock_period_ns'], 10)
        self.assertEqual(plan['baseline']['checkpoint_sha256'], before)
        self.assertFalse(plan['synthesis_rerun'])
        self.assertFalse(plan['component_routed_timing_pass'])
        self.assertFalse(plan['f2_shell_timing_closed'])
        self.assertFalse(self.output.exists())
        self.assertEqual(MODULE.sha(self.baseline / 'post_synth.dcp'), before)

    def test_invalid_frequency_and_thread_arguments_fail_before_writing(self):
        for args in [('--compute-mhz', 'nan'), ('--compute-mhz', 'inf'),
                     ('--compute-mhz', '0'), ('--compute-mhz', '201'),
                     ('--threads', '0'), ('--threads', '9')]:
            with self.subTest(args=args):
                self.assertEqual(self.invoke(*args).returncode, 2)
                self.assertFalse(self.output.exists())

    def test_tcl_identity_uses_top_property_not_checkpoint_alias(self):
        # Execute the exact production Tcl guard with probed Vivado properties.
        # This is a guard regression, not a substitute for opening a real DCP.
        script = SCRIPT.with_name('compute_retarget.tcl').read_text()
        guard = script.split('# Arguments:', 1)[0]
        fixture = r"""
proc get_property {key design} {global properties; return [dict get $properties $key]}
foreach {part top name should_fail} {
    xcvu47p-fsvh2892-2-e decode_f2_compute checkpoint_post_synth 0
    xcvu47p-fsvh2892-2-e decode_f2_compute unrelated_session_alias 0
    xcvu47p-fsvh2892-2-e wrong_top decode_f2_compute 1
    xcvu47p-fsvh2892-2-e {} checkpoint_post_synth 1
    wrong_part decode_f2_compute checkpoint_post_synth 1
} {
    set properties [dict create PART $part TOP $top NAME $name]
    set failed [catch {assert_checkpoint_identity design_object} message]
    if {$failed != $should_fail} {puts stderr "Identity guard mismatch: $properties $message"; exit 1}
}
puts "PASS checkpoint identity guard"
"""
        result = subprocess.run(['tclsh'], input=guard + fixture, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('PASS checkpoint identity guard', result.stdout)

    def test_failed_vivado_still_writes_audit_and_preserves_failure(self):
        executable = self.root / 'fake-vivado'
        executable.write_text('#!/bin/sh\nif [ "$1" = "-version" ]; then echo "SYNTHETIC TEST TOOL"; exit 0; fi\nexit 17\n')
        executable.chmod(0o755)
        result = subprocess.run([sys.executable, str(SCRIPT), '--baseline', str(self.baseline),
                                 '--output', str(self.output), '--vivado', str(executable),
                                 '--compute-mhz', '50'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 17, result.stderr)
        manifest = json.loads((self.output / 'manifest.json').read_text())
        audit = json.loads((self.output / 'audit.json').read_text())
        self.assertEqual(manifest['status'], 'vivado_failed')
        self.assertEqual(manifest['vivado_returncode'], 17)
        self.assertEqual(manifest['audit_returncode'], 1)
        self.assertFalse(manifest['component_routed_timing_pass'])
        self.assertFalse(manifest['f2_shell_timing_closed'])
        self.assertEqual(audit['status'], 'failed')
        self.assertTrue(audit['diagnostic_reports_only'])
        self.assertFalse(audit['component_routed_timing_pass'])
        self.assertTrue(any('Incomplete' in problem for problem in audit['problems']))
        self.assertTrue(any('status 17' in problem for problem in audit['problems']))

    def test_failed_tool_cannot_be_reclassified_by_passing_reports(self):
        self.output.mkdir()
        audit_path = self.output / 'audit.json'
        # Simulate an otherwise passing report audit after a failed tool exit.
        # Tool success and report success are both necessary for closure.
        audit_path.write_text(json.dumps({'status': 'passed', 'problems': [],
                                         'component_routed_timing_pass': True}))
        with patch.object(MODULE.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            MODULE.audit_result(self.output, self.root, 20, 17)
        audit = json.loads(audit_path.read_text())
        self.assertEqual(audit['status'], 'failed')
        self.assertFalse(audit['component_routed_timing_pass'])
        self.assertEqual(audit['vivado_returncode'], 17)

    def test_tcl_failed_route_collects_independent_evidence_and_rethrows_original_error(self):
        # Execute the production recovery functions, injecting failures from
        # route_design, checkpoint saving and individual report generation.
        # Synthetic objects and text files are not Vivado timing evidence.
        script = SCRIPT.with_name('compute_retarget.tcl').read_text().split('# Arguments:', 1)[0]
        fixture = r"""
proc fake_report {command args} {
    global inject_failure
    set index [lsearch -exact $args -file]
    if {$index < 0} {error "Missing report output for $command"}
    set path [lindex $args [expr {$index + 1}]]
    if {$inject_failure eq "setup" && [file tail $path] eq "setup_paths.rpt"} {
        error "SYNTHETIC setup report failure"
    }
    set fp [open $path w]; puts $fp "$command $args"; close $fp
}
foreach command {report_timing_summary check_timing report_utilization report_drc
                 report_timing report_route_status report_clock_interaction
                 report_methodology report_exceptions report_design_analysis} {
    interp alias {} $command {} fake_report $command
}
proc fake_write {args} {
    global inject_failure
    set path [lindex $args end]
    if {$inject_failure eq "checkpoint" && [file extension $path] eq ".dcp"} {
        error "SYNTHETIC checkpoint save failure"
    }
    set fp [open $path w]; puts $fp "SYNTHETIC TEST FILE"; close $fp
}
interp alias {} write_checkpoint {} fake_write
interp alias {} write_xdc {} fake_write
proc all_registers {args} {error "Oversized register selection is forbidden"}
proc get_timing_paths {args} {
    if {[lsearch -exact $args -from] >= 0 || [lsearch -exact $args -to] >= 0 ||
        [lindex $args [expr {[lsearch -exact $args -max_paths]+1}]] != 200} {
        error "Timing query is not a bounded global sample"
    }
    return {input_path output_path feedthrough_path internal_path}
}
proc get_property {property path} {
    set endpoints [dict create input_path {input_a register_a/D} \
        output_path {register_b/C output_a} feedthrough_path {input_a output_a} \
        internal_path {register_a/C register_b/D}]
    set index [expr {$property eq "STARTPOINT_PIN" ? 0 : 1}]
    return [lindex [dict get $endpoints $path] $index]
}
proc get_ports {args} {
    if {[string match *OUT* $args]} {return {output_a}}
    return {input_a}
}
proc write_route_metrics {run completed} {
    if {$completed != 0} {error "Failed route marked complete"}
    set fp [open $run/metrics.tsv w]; puts $fp "route_command_completed\t$completed"; close $fp
}
proc route_design {args} {
    return -code error -errorcode {VIVADO ROUTE35-39} "SYNTHETIC original routing failure"
}
foreach inject_failure {none checkpoint setup} {
    set run [file join [lindex $argv 0] $inject_failure]
    file mkdir $run
    set failed [catch {route_with_failure_capture $run} message options]
    if {!$failed || $message ne "SYNTHETIC original routing failure" ||
        [dict get $options -errorcode] ne {VIVADO ROUTE35-39}} {
        puts stderr "Original route failure was lost: $message $options"; exit 1
    }
    foreach name {route_failure.txt route_failure_capture.tsv route_status.rpt
                  hold_paths.rpt setup_internal_sample.rpt hold_internal_sample.rpt
                  setup_input_boundary_sample.rpt hold_input_boundary_sample.rpt
                  setup_output_boundary_sample.rpt hold_output_boundary_sample.rpt
                  setup_input_to_output_sample.rpt hold_input_to_output_sample.rpt
                  sampled_path_reports.tsv sampled_path_scope.txt
                  metrics.tsv failed_route_resolved.xdc} {
        if {![file exists $run/$name]} {puts stderr "Missing recovery artifact: $name"; exit 1}
    }
    if {[file exists $run/post_route.dcp]} {puts stderr "Failed route created closure checkpoint"; exit 1}
    if {$inject_failure ne "checkpoint" && ![file exists $run/failed_route.dcp]} {
        puts stderr "Failed route state was not preserved"; exit 1
    }
    set fp [open $run/route_failure_capture.tsv r]; set status [read $fp]; close $fp
    if {$inject_failure ne "none" && ![string match *\tfailed\t* $status]} {
        puts stderr "Report/checkpoint failure not recorded"; exit 1
    }
    set fp [open $run/hold_internal_sample.rpt r]; set internal [read $fp]; close $fp
    if {![string match {*-of_objects internal_path*} $internal]} {
        puts stderr "Internal sample contains boundary paths"; exit 1
    }
}
proc route_design {args} {return "SYNTHETIC route success"}
set run [file join [lindex $argv 0] success]
file mkdir $run
route_with_failure_capture $run
if {[llength [glob -nocomplain -directory $run *]]} {
    puts stderr "Successful route unexpectedly captured a failure"; exit 1
}
puts "PASS failed-route capture preserves original error and independent diagnostics"
"""
        test_tcl = self.root / 'route_failure_test.tcl'
        test_tcl.write_text(script + fixture)
        result = subprocess.run(['tclsh', str(test_tcl), str(self.root / 'diagnostics')],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS failed-route capture', result.stdout)

    def test_tcl_sample_classification_is_bounded_and_report_failures_are_independent(self):
        script = SCRIPT.with_name('compute_retarget.tcl').read_text().split('# Arguments:', 1)[0]
        fixture = r"""
set calls {}
set sample {input_path output_path feedthrough_path internal_path}
set inject 1
proc get_ports {args} {
    if {[string match *OUT* $args]} {return {output_a}}
    return {input_a clk}
}
proc all_registers {args} {error "Register collections are forbidden"}
proc get_timing_paths {args} {
    global sample
    if {[lsearch -exact $args -from] >= 0 || [lsearch -exact $args -to] >= 0 ||
        [lindex $args [expr {[lsearch -exact $args -max_paths]+1}]] != 200} {
        error "Query exceeded the bounded global sampling contract"
    }
    return $sample
}
proc get_property {property path} {
    set endpoints [dict create input_path {input_a register_a/D} \
        output_path {register_b/C output_a} feedthrough_path {input_a output_a} \
        internal_path {register_a/C register_b/D}]
    return [lindex [dict get $endpoints $path] [expr {$property eq "STARTPOINT_PIN" ? 0 : 1}]]
}
proc report_timing {args} {
    global calls inject
    set file [lindex $args [expr {[lsearch -exact $args -file]+1}]]
    set paths [lindex $args [expr {[lsearch -exact $args -of_objects]+1}]]
    if {[lsearch -exact $args -path_type] >= 0} {error "Incompatible path_type with of_objects"}
    lappend calls [file tail $file]
    if {$inject && ([string match *internal* $file] || [string match *setup_input_boundary* $file])} {
        error "SYNTHETIC report failure"
    }
    set fp [open $file w]; puts $fp $paths; close $fp
}
set failed [collect_scoped_path_reports [lindex $argv 0]]
if {$failed != 3 || [llength $calls] != 8} {
    puts stderr "Sample report failure interrupted later reports"; exit 1
}
set fp [open [file join [lindex $argv 0] sampled_path_reports.tsv] r]
set rows [split [string trim [read $fp]] "\n"]; close $fp
if {[llength $rows] != 9} {puts stderr "Incomplete sampled report status"; exit 1}
# Missing categories are reported as absent from the sample, never as passing.
set inject 0
set sample {feedthrough_path}
collect_scoped_path_reports [lindex $argv 0]
set fp [open [file join [lindex $argv 0] hold_internal_sample.rpt] r]
set empty [read $fp]; close $fp
if {![string match {*NOT evidence*} $empty]} {puts stderr "Empty sample implies passing"; exit 1}
set fp [open [file join [lindex $argv 0] hold_input_to_output_sample.rpt] r]
set feedthrough [string trim [read $fp]]; close $fp
if {$feedthrough ne "feedthrough_path"} {puts stderr "Wrong endpoint classification"; exit 1}
puts "PASS bounded endpoint classification and independent sample reports"
"""
        test_tcl = self.root / 'sample_reports.tcl'
        test_tcl.write_text(script + fixture)
        result = subprocess.run(['tclsh', str(test_tcl), str(self.root)], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('PASS bounded endpoint classification', result.stdout)

    def test_run_cannot_be_nested_under_baseline(self):
        self.output = self.baseline / 'new-run'
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn('separate from', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
