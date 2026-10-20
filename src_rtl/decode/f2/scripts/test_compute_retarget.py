"""Retarget provenance/CLI tests with synthetic files, not FPGA timing evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

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

    def test_run_cannot_be_nested_under_baseline(self):
        self.output = self.baseline / 'new-run'
        result = self.invoke()
        self.assertEqual(result.returncode, 2)
        self.assertIn('separate from', result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == '__main__':
    unittest.main()
