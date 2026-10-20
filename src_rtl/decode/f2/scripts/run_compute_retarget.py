#!/usr/bin/env python3
"""Retarget an immutable, verified full-compute synthesis checkpoint for OOC P&R."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = Path('src_rtl/decode')
RTL = (BASE / 'rtl/decode_os_core.sv', BASE / 'generated/decode_f2_compute.sv')
FLOW = tuple(BASE / 'f2/scripts' / name for name in
             ('run_compute_retarget.py', 'compute_retarget.tcl', 'audit_compute_ooc.py'))
PART = 'xcvu47p-fsvh2892-2-e'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def baseline_inputs(baseline):
    """Validate the saved source snapshot and its numerical verification binding."""
    manifest_path = baseline / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('part') != PART or manifest.get('macs') != 4096:
        raise ValueError('Baseline must be the full 4096-MAC VU47P compute run')
    if manifest.get('compute_mhz') != 200:
        raise ValueError('Expected the verified 200 MHz synthesis baseline')
    hashes = manifest['source_hashes']
    if not hashes:
        raise ValueError('Missing baseline source hashes')
    for name, digest in hashes.items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError(f'Unsafe baseline source path: {name}')
        if sha(baseline / 'source' / relative) != digest:
            raise ValueError(f'Baseline source snapshot does not match: {name}')
    verification_name = str(BASE / 'verification.json')
    if verification_name not in hashes:
        raise ValueError('Baseline does not bind its functional verification record')
    verification = json.loads((baseline / 'source' / verification_name).read_text())
    if verification.get('status') != 'passed':
        raise ValueError('Baseline functional verification does not pass')
    for path in RTL:
        name = str(path)
        if hashes.get(name) != verification['sources_sha256'].get(name):
            raise ValueError(f'Baseline numerical verification is stale for {name}')
    checkpoint = baseline / 'post_synth.dcp'
    if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
        raise ValueError('Missing or empty baseline post_synth.dcp')
    return manifest, sha(manifest_path), sha(checkpoint)


def copy_checked(source, destination, digest):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sha(destination) != digest:
        raise ValueError(f'Input changed while snapshotting: {source}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True, help='Existing run with post_synth.dcp and source manifest')
    parser.add_argument('--output', type=Path, required=True, help='New experiment directory; never overwrite a run')
    parser.add_argument('--compute-mhz', type=float, default=100.0)
    parser.add_argument('--baseline-source-git', help='Optional provenance label; source hashes are validated independently')
    parser.add_argument('--stage', choices=('preflight', 'route'), default='route')
    parser.add_argument('--vivado', default='vivado')
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if not math.isfinite(args.compute_mhz) or not 0 < args.compute_mhz <= 200:
        parser.error('--compute-mhz must be finite, positive, and at most 200')
    if not 1 <= args.threads <= 8:
        parser.error('--threads must be between 1 and 8')
    baseline, output = args.baseline.resolve(), args.output.resolve()
    if output.exists():
        parser.error('--output must not already exist')
    if baseline == output or baseline in output.parents or output in baseline.parents:
        parser.error('--output must be separate from the preserved baseline directory')
    try:
        prior, manifest_sha, checkpoint_sha = baseline_inputs(baseline)
        flow_hashes = {str(path): sha(ROOT / path) for path in FLOW}
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    period = 1000.0 / args.compute_mhz
    executable = shutil.which(args.vivado) or args.vivado
    snapshot = output / 'flow_source'
    command = [executable, '-mode', 'batch', '-nojournal', '-log', str(output / 'vivado.log'),
               '-source', str(snapshot / BASE / 'f2/scripts/compute_retarget.tcl'),
               '-tclargs', str(output / 'baseline/post_synth.dcp'), str(output),
               format(period, '.12g'), args.stage, str(args.threads)]
    manifest = {
        'status': 'planned', 'created_utc': datetime.now(timezone.utc).isoformat(),
        'part': PART, 'macs': 4096, 'compute_mhz': args.compute_mhz,
        'clock_period_ns': period, 'stage': args.stage, 'threads': args.threads,
        'command': command, 'flow_source_hashes': flow_hashes,
        'source_hashes': prior['source_hashes'],
        'baseline': {'directory': str(baseline), 'manifest_sha256': manifest_sha,
                     'checkpoint': 'post_synth.dcp', 'checkpoint_sha256': checkpoint_sha,
                     'compute_mhz': prior['compute_mhz'],
                     'source_git_label': args.baseline_source_git},
        'boundary_budget_ns': {'input_max': 1, 'input_min': 0, 'output_max': 1,
                               'output_min': 0, 'setup_uncertainty': 0.25, 'hold_uncertainty': 0.1},
        'scope': 'Compute-only OOC checkpoint retarget; full-device placement without AWS shell, HBM or SRAM adapter',
        'synthesis_rerun': False, 'f2_shell_timing_closed': False,
        'component_routed_timing_pass': False,
    }
    print(shlex.join(command), flush=True)
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    if not shutil.which(args.vivado):
        parser.error(f'Vivado executable not found: {args.vivado}')
    output.mkdir(parents=True)
    manifest_path = output / 'manifest.json'
    manifest['status'] = 'snapshotting'
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    try:
        copy_checked(baseline / 'manifest.json', output / 'baseline/manifest.json', manifest_sha)
        copy_checked(baseline / 'post_synth.dcp', output / 'baseline/post_synth.dcp', checkpoint_sha)
        for name, digest in prior['source_hashes'].items():
            copy_checked(baseline / 'source' / name, output / 'baseline/source' / name, digest)
        for name, digest in flow_hashes.items():
            copy_checked(ROOT / name, snapshot / name, digest)
        version = subprocess.run([executable, '-version'], text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        (output / 'vivado_version.txt').write_text(version.stdout)
        manifest['status'] = 'running'
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        with (output / 'console.log').open('w') as log:
            result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT)
        manifest['vivado_returncode'] = result.returncode
        if result.returncode:
            manifest['status'] = 'vivado_failed'
            return result.returncode
        if args.stage == 'preflight':
            if not (output / 'preflight_passed.txt').is_file():
                raise ValueError('Vivado exited without completing retarget preflight')
            manifest['status'] = 'preflight_passed'
            return 0
        audit = subprocess.run([sys.executable, str(snapshot / BASE / 'f2/scripts/audit_compute_ooc.py'),
                                str(output), '--expected-period-ns', format(period, '.12g')], cwd=output)
        manifest['status'] = 'passed' if audit.returncode == 0 else 'audit_failed'
        manifest['component_routed_timing_pass'] = audit.returncode == 0
        return audit.returncode
    except BaseException:
        manifest['status'] = 'interrupted_or_failed'
        raise
    finally:
        manifest['finished_utc'] = datetime.now(timezone.utc).isoformat()
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
        print(f'Run artifacts: {output}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
