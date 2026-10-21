#!/usr/bin/env python3
"""Build an analysis-only registered compute harness; never an F2 image or TPS claim."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[4]
BASE = Path('src_rtl/decode')
PART = 'xcvu47p-fsvh2892-2-e'
CORE = BASE / 'rtl/decode_os_core.sv'
HARNESS = BASE / 'f2/harness/decode_compute_timing_harness.sv'
CONSTRAINTS = BASE / 'f2/harness/harness_constraints.tcl'
VERIFICATION = BASE / 'verification.json'
HARNESS_VERIFICATION = BASE / 'f2/harness/verification.json'
HARNESS_INPUTS = (CORE, HARNESS, CONSTRAINTS, *(BASE / 'f2/harness' / name for name in
                  ('bufg_sim.sv', 'scan_core_fixture.sv', 'test_timing_harness.py', 'run_harness_tests.py')))
FLOW = tuple(BASE / 'f2/scripts' / name for name in
             ('run_timing_harness.py', 'timing_harness.tcl', 'audit_compute_ooc.py'))
INPUTS = (*HARNESS_INPUTS, VERIFICATION, HARNESS_VERIFICATION, *FLOW)
SCOPE = 'Analysis-only registered compute harness on VU47P; not AWS shell/HBM integration or inference throughput'


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked_inputs(root):
    hashes = {str(name): sha(root / name) for name in INPUTS}
    evidence = json.loads((root / VERIFICATION).read_text())
    if evidence.get('status') != 'passed':
        raise ValueError('Numerical verification has not passed')
    if evidence.get('sources_sha256', {}).get(str(CORE)) != hashes[str(CORE)]:
        raise ValueError('Numerical verification does not bind the current core RTL')
    harness = json.loads((root / HARNESS_VERIFICATION).read_text())
    expected_cases = {(1, 3, True), (2, 5, True), (1, 3, False), (2, 5, False)}
    cases = harness.get('cases', [])
    actual_cases = {(case.get('partitions'), case.get('cols'), case.get('mapping_fixture')) for case in cases}
    if (harness.get('status') != 'passed' or harness.get('tests_passed') != 8 or
        len(cases) != 4 or actual_cases != expected_cases or
        any(case.get('status') != 'passed' or case.get('tests') != 2 for case in cases)):
        raise ValueError('Expected eight passing functional harness tests across four cases')
    evidence_hashes = harness.get('source_sha256', {})
    if set(evidence_hashes) != {str(name) for name in HARNESS_INPUTS}:
        raise ValueError('Harness verification source set does not match required inputs')
    for name in HARNESS_INPUTS:
        if evidence_hashes.get(str(name)) != hashes[str(name)]:
            raise ValueError(f'Harness verification is stale for {name}')
    return hashes


def resource_gate(report, ceiling):
    """Use actual device capacities from Vivado's flat report, not a device table."""
    resources = {}
    header = None
    required = {'CLB LUTs', 'CLB Registers', 'Block RAM Tile', 'DSPs'}
    for line in report.splitlines():
        if not line.strip().startswith('|'):
            continue
        fields = [field.strip() for field in line.strip().strip('|').split('|')]
        if {'Used', 'Available'}.issubset(fields):
            header = fields
            continue
        label = fields[0].rstrip('*').strip()
        if label not in required or not header:
            continue
        try:
            used = float(fields[header.index('Used')].replace(',', ''))
            available = float(fields[header.index('Available')].replace(',', ''))
        except (ValueError, IndexError) as exc:
            raise ValueError(f'Unrecognized utilization for {label}') from exc
        if not math.isfinite(used) or not math.isfinite(available) or used < 0 or available <= 0:
            raise ValueError(f'Invalid resource capacity/usage for {label}')
        if label in resources:
            raise ValueError(f'Duplicate resource row: {label}')
        resources[label] = {'used': used, 'available': available, 'percent': 100 * used / available}
    if set(resources) != required:
        raise ValueError(f'Missing actual device capacities: {sorted(required-set(resources))}')
    failures = [name for name, row in resources.items() if row['percent'] > ceiling]
    return {'status': 'failed' if failures else 'passed', 'maximum_utilization_percent': ceiling,
            'policy': 'Explicit conservative utilization ceiling, not a hardware capacity assertion',
            'resources': resources, 'over_policy_limit': failures,
            'physical_timing_closed': False, 'f2_shell_timing_closed': False}


def checked_synthesis(run, hashes, partitions, cols, period, ceiling):
    manifest = json.loads((run / 'manifest.json').read_text())
    if manifest.get('status') != 'synth_resource_pass' or manifest.get('stage') != 'synth':
        raise ValueError('Route prerequisite is not a successful synth-only resource-gated run')
    for key, expected in [('part', PART), ('partitions', partitions), ('cols', cols),
                          ('clock_period_ns', period), ('source_hashes', hashes)]:
        if manifest.get(key) != expected:
            raise ValueError(f'Synthesis prerequisite mismatch: {key}')
    for name, digest in hashes.items():
        if sha(run / 'source' / name) != digest:
            raise ValueError(f'Synthesis source snapshot changed: {name}')
    checkpoint = run / 'post_synth.dcp'
    if not checkpoint.is_file() or not checkpoint.stat().st_size:
        raise ValueError('Missing synthesis checkpoint')
    if manifest.get('checkpoint_sha256') != sha(checkpoint):
        raise ValueError('Synthesis checkpoint hash mismatch')
    report = run / 'synth_utilization_flat.rpt'
    if manifest.get('utilization_sha256') != sha(report):
        raise ValueError('Synthesis utilization report hash mismatch')
    if resource_gate(report.read_text(), ceiling)['status'] != 'passed':
        raise ValueError('Synthesis resource use exceeds this run policy')
    return checkpoint, manifest['checkpoint_sha256']


def route_audit(output, snapshot, period, returncode):
    location = snapshot / BASE / 'f2/scripts/audit_compute_ooc.py'
    spec = importlib.util.spec_from_file_location('harness_auditor', location)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    try:
        result = module.audit(output, expected_period_ns=period)
    except (OSError, ValueError, KeyError) as exc:
        result = {'status': 'failed', 'problems': [f'Incomplete reports: {exc}']}
    result.update(scope=SCOPE, f2_shell_timing_closed=False, vivado_returncode=returncode)
    if returncode:
        result['status'] = 'failed'
        result.setdefault('problems', []).append(f'Vivado failed with status {returncode}')
    result['component_routed_timing_pass'] = result['status'] == 'passed' and not returncode
    result['diagnostic_reports_only'] = bool(returncode)
    (output / 'audit.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partitions', type=int, default=4)
    parser.add_argument('--cols', type=int, default=8)
    parser.add_argument('--compute-mhz', type=float, choices=(50.0, 100.0), default=100.0)
    parser.add_argument('--stage', choices=('synth', 'route'), default='synth')
    parser.add_argument('--synthesis-run', type=Path, help='Required for routing more than 32 MACs')
    parser.add_argument('--max-utilization-percent', type=float, default=90.0)
    parser.add_argument('--threads', type=int, default=8)
    parser.add_argument('--vivado', default='vivado')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    if not (1 <= args.partitions <= 64 and 1 <= args.cols <= 64):
        parser.error('partitions and cols must each be in 1..64')
    if not 1 <= args.threads <= 8:
        parser.error('threads must be in 1..8')
    if not math.isfinite(args.max_utilization_percent) or not 0 < args.max_utilization_percent <= 100:
        parser.error('utilization ceiling must be finite and in (0,100]')
    output = args.output.resolve()
    if output.exists():
        parser.error('output already exists; choose a new run directory')
    if args.stage == 'synth' and args.synthesis_run:
        parser.error('synthesis-run is only valid for stage route')
    if args.stage == 'route' and args.partitions * args.cols > 32 and not args.synthesis_run:
        parser.error('route above 32 MACs requires a prior synth-only resource gate via --synthesis-run')
    period = 1000.0 / args.compute_mhz
    try:
        hashes = checked_inputs(ROOT)
        checkpoint = None
        checkpoint_digest = None
        if args.synthesis_run:
            prior = args.synthesis_run.resolve()
            if prior == output or prior in output.parents or output in prior.parents:
                raise ValueError('Output must be separate from preserved synthesis run')
            checkpoint, checkpoint_digest = checked_synthesis(prior, hashes, args.partitions, args.cols,
                                           period, args.max_utilization_percent)
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    snapshot = output / 'source'
    executable = shutil.which(args.vivado) or args.vivado
    command = [executable, '-mode', 'batch', '-nojournal', '-log', str(output / 'vivado.log'),
               '-source', str(snapshot / BASE / 'f2/scripts/timing_harness.tcl'), '-tclargs',
               str(snapshot), str(output), str(args.partitions), str(args.cols), format(period, '.12g'),
               args.stage, str(args.threads), str(output / 'baseline/post_synth.dcp') if checkpoint else 'none']
    manifest = dict(status='planned', created_utc=datetime.now(timezone.utc).isoformat(),
                    scope=SCOPE, part=PART, partitions=args.partitions, cols=args.cols,
                    macs=args.partitions*args.cols, max_m=4, max_k=8192, threads=args.threads,
                    compute_mhz=args.compute_mhz, clock_period_ns=period, stage=args.stage,
                    maximum_utilization_percent=args.max_utilization_percent, source_hashes=hashes,
                    synthesis_run=str(args.synthesis_run.resolve()) if checkpoint else None,
                    baseline_checkpoint_sha256=checkpoint_digest,
                    command=command, component_routed_timing_pass=False, f2_shell_timing_closed=False,
                    boundary_budget_ns=dict(input_max=1, input_min=0, output_max=1, output_min=0,
                                            setup_uncertainty=0.25, hold_uncertainty=0.1))
    print(shlex.join(command), flush=True)
    if args.dry_run:
        print(json.dumps(manifest, indent=2))
        return 0
    if not shutil.which(args.vivado):
        parser.error(f'Vivado executable not found: {args.vivado}')
    output.mkdir(parents=True)
    manifest_path = output / 'manifest.json'
    def save():
        manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    manifest['status'] = 'snapshotting'; save()
    try:
        for name, digest in hashes.items():
            destination = snapshot / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
            if sha(destination) != digest:
                raise ValueError(f'Source changed while snapshotting: {name}')
        if checkpoint:
            destination = output / 'baseline/post_synth.dcp'; destination.parent.mkdir()
            shutil.copy2(checkpoint, destination)
            if sha(destination) != checkpoint_digest:
                raise ValueError('Checkpoint changed while snapshotting')
        version = subprocess.run([executable, '-version'], text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, check=True)
        (output / 'vivado_version.txt').write_text(version.stdout)
        manifest['status'] = 'running'; save()
        with (output / 'console.log').open('w') as log:
            result = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT)
        manifest['vivado_returncode'] = result.returncode
        if args.stage == 'route':
            audit = route_audit(output, snapshot, period, result.returncode)
            manifest['component_routed_timing_pass'] = audit['component_routed_timing_pass']
            manifest['status'] = 'route_pass' if audit['status'] == 'passed' else 'route_failed'
            return 0 if manifest['status'] == 'route_pass' else 1
        if result.returncode:
            manifest['status'] = 'vivado_failed'; return result.returncode
        if not (output / 'synth_ready.txt').is_file() or not (output / 'post_synth.dcp').is_file():
            raise ValueError('Vivado exited without completing synthesis readiness checks')
        report = output / 'synth_utilization_flat.rpt'
        gate = resource_gate(report.read_text(), args.max_utilization_percent)
        (output / 'resource_gate.json').write_text(json.dumps(gate, indent=2) + '\n')
        manifest.update(checkpoint_sha256=sha(output / 'post_synth.dcp'), utilization_sha256=sha(report))
        manifest['status'] = 'synth_resource_pass' if gate['status'] == 'passed' else 'resource_gate_failed'
        return 0 if gate['status'] == 'passed' else 1
    except BaseException:
        manifest['status'] = 'interrupted_or_failed'
        raise
    finally:
        manifest['finished_utc'] = datetime.now(timezone.utc).isoformat(); save()
        print(f'Run artifacts: {output}', flush=True)


if __name__ == '__main__':
    raise SystemExit(main())
