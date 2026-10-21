#!/usr/bin/env python3
"""Run fresh 4096-MAC synthesis, then gated 100 MHz routing; never an F2 image."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[4]
DRIVER = Path('src_rtl/decode/f2/scripts/run_timing_harness.py')
RUNNER = Path('src_rtl/decode/f2/scripts/run_full_timing_pipeline.py')


def utc():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def atomic_json(path, data):
    """Readers see one complete record; fsync the file and directory on POSIX."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, prefix='.' + path.name,
                                         suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_flow(root):
    spec = importlib.util.spec_from_file_location('harness_flow', root / DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PipelineStopped(Exception):
    pass


class Pipeline:
    def __init__(self, args, flow, root=ROOT):
        self.args, self.flow, self.root = args, flow, root
        self.output = args.output.resolve()
        self.snapshot = self.output / 'source'
        self.child = None
        self.stop_signal = None
        self.record = {'status': 'initializing', 'created_utc': utc(), 'updated_utc': utc(),
                       'host': platform.node(), 'pid': os.getpid(), 'stage': None,
                       'child_pid': None, 'events': [], 'stages': {},
                       'partitions': 64, 'cols': 64, 'macs': 4096, 'compute_mhz': 100,
                       'component_routed_timing_pass': False, 'f2_shell_timing_closed': False,
                       'scope': flow.SCOPE}

    def save(self, status=None, **fields):
        self.record.update(fields)
        if status is not None:
            self.record['status'] = status
            self.record['events'].append({'status': status, 'utc': utc(),
                                          'stage': self.record['stage']})
            print(f'{utc()} {status} stage={self.record["stage"]}', flush=True)
        self.record['updated_utc'] = utc()
        atomic_json(self.output / 'status.json', self.record)

    def command(self, stage, dry_run=False):
        command = [sys.executable, '-u', str(self.snapshot / DRIVER),
                   '--output', str(self.output / stage), '--partitions', '64', '--cols', '64',
                   '--compute-mhz', '100', '--threads', str(self.args.threads),
                   '--max-utilization-percent', str(self.args.max_utilization_percent),
                   '--vivado', self.args.vivado, '--stage', stage]
        if stage == 'route':
            command += ['--synthesis-run', str(self.output / 'synth')]
        if dry_run:
            command += ['--dry-run']
        return command

    def signal_requested(self, signum, _frame):
        self.stop_signal = signum

    def check_stop(self):
        if self.stop_signal is not None:
            raise PipelineStopped(f'Received signal {self.stop_signal}')

    def stop_child(self):
        if self.child is None:
            return
        group = self.child.pid
        try:
            os.killpg(group, signal.SIGTERM)
        except ProcessLookupError:
            self.child.wait()
            return
        deadline = time.monotonic() + self.args.terminate_grace_seconds
        while time.monotonic() < deadline:
            self.child.poll()  # Reap the direct child; descendants remain in this group.
            try:
                os.killpg(group, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        try:
            os.killpg(group, signal.SIGKILL)
        except ProcessLookupError:
            pass
        self.child.wait()

    def run_command(self, name, command):
        self.check_stop()
        stage = {'command': command, 'started_utc': utc(), 'log': str(self.output / (name + '.log'))}
        self.record['stages'][name] = stage
        self.save(name + '_running', stage=name)
        with (self.output / (name + '.log')).open('x') as log:
            self.child = subprocess.Popen(command, cwd=self.snapshot, stdout=log,
                                          stderr=subprocess.STDOUT, start_new_session=True)
            stage['pid'] = self.child.pid
            self.save(child_pid=self.child.pid)
            heartbeat = time.monotonic() + self.args.heartbeat_seconds
            while True:
                self.check_stop()
                try:
                    returncode = self.child.wait(timeout=min(1.0, self.args.heartbeat_seconds))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= heartbeat:
                        self.save()
                        heartbeat = time.monotonic() + self.args.heartbeat_seconds
        stage.update(returncode=returncode, finished_utc=utc(), log_sha256=digest(Path(stage['log'])))
        self.save(child_pid=None)
        self.check_stop()
        if returncode != 0:
            raise RuntimeError(f'{name} failed with exit status {returncode}; see {stage["log"]}')
        self.child = None
        self.save(name + '_passed')

    def unchanged_snapshot(self):
        actual = self.flow.checked_inputs(self.snapshot)
        if actual != self.hashes or digest(self.snapshot / RUNNER) != self.runner_hash:
            raise ValueError('Pipeline source snapshot changed during execution')

    def validate_route(self, checkpoint_hash):
        manifest = json.loads((self.output / 'route/manifest.json').read_text())
        for key, expected in {'status': 'route_pass', 'stage': 'route', 'part': self.flow.PART,
                              'partitions': 64, 'cols': 64, 'clock_period_ns': 10.0,
                              'source_hashes': self.hashes, 'vivado_returncode': 0,
                              'baseline_checkpoint_sha256': checkpoint_hash,
                              'component_routed_timing_pass': True,
                              'f2_shell_timing_closed': False}.items():
            if manifest.get(key) != expected:
                raise ValueError(f'Route completion manifest mismatch: {key}')
        audit = json.loads((self.output / 'route/audit.json').read_text())
        if (audit.get('status') != 'passed' or audit.get('component_routed_timing_pass') is not True
                or audit.get('f2_shell_timing_closed') is not False or audit.get('vivado_returncode') != 0):
            raise ValueError('Route completion audit did not pass')
        checkpoint = self.output / 'route/post_route.dcp'
        if not checkpoint.is_file() or checkpoint.stat().st_size == 0:
            raise ValueError('Missing final route checkpoint')
        return digest(checkpoint)

    def run(self):
        if os.path.lexists(self.args.output) or os.path.lexists(self.output):
            raise ValueError('Pipeline output already exists; select a new directory. No automatic resume.')
        self.hashes = self.flow.checked_inputs(self.root)
        self.runner_hash = digest(self.root / RUNNER)
        if self.args.dry_run:
            print(json.dumps({'source_hashes': self.hashes, 'runner_sha256': self.runner_hash,
                              'commands': [self.command('synth', True), self.command('synth'),
                                           self.command('route', True), self.command('route')],
                              'output_created': False}, indent=2))
            return 0
        if not shutil.which(self.args.vivado):
            raise ValueError(f'Vivado executable not found: {self.args.vivado}')
        self.output.mkdir(parents=True, exist_ok=False)
        handlers = {sig: signal.signal(sig, self.signal_requested) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            self.save('snapshotting')
            for name, expected in {**self.hashes, str(RUNNER): self.runner_hash}.items():
                destination = self.snapshot / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(self.root / name, destination)
                if digest(destination) != expected:
                    raise ValueError(f'Source changed while copying: {name}')
            self.unchanged_snapshot()
            provenance = {'created_utc': utc(), 'source_root': str(self.root),
                          'snapshot_root': str(self.snapshot), 'source_hashes': self.hashes,
                          'runner_sha256': self.runner_hash, 'python': sys.version,
                          'executable': sys.executable, 'host': platform.node(),
                          'part': self.flow.PART, 'partitions': 64, 'cols': 64,
                          'compute_mhz': 100, 'threads': self.args.threads,
                          'maximum_utilization_percent': self.args.max_utilization_percent,
                          'commands': [self.command('synth', True), self.command('synth'),
                                       self.command('route', True), self.command('route')]}
            atomic_json(self.output / 'provenance.json', provenance)
            self.save(provenance_sha256=digest(self.output / 'provenance.json'))
            self.run_command('synth_preflight', self.command('synth', True))
            self.run_command('synth', self.command('synth'))
            self.unchanged_snapshot()
            _, checkpoint_hash = self.flow.checked_synthesis(
                self.output / 'synth', self.hashes, 64, 64, 10.0, self.args.max_utilization_percent)
            self.save('synth_resource_pass', synthesis_checkpoint_sha256=checkpoint_hash,
                      synthesis_manifest_sha256=digest(self.output / 'synth/manifest.json'))
            self.run_command('route_preflight', self.command('route', True))
            self.unchanged_snapshot()
            self.run_command('route', self.command('route'))
            self.unchanged_snapshot()
            routed_hash = self.validate_route(checkpoint_hash)
            self.check_stop()
            self.save('route_pass', stage='complete', child_pid=None, finished_utc=utc(),
                      route_checkpoint_sha256=routed_hash,
                      route_manifest_sha256=digest(self.output / 'route/manifest.json'),
                      route_audit_sha256=digest(self.output / 'route/audit.json'),
                      component_routed_timing_pass=True)
            return 0
        except BaseException as exc:
            cleanup_group = self.child.pid if self.child is not None else None
            cleanup_error = None
            try:
                self.stop_child()
            except Exception as cleanup:
                cleanup_error = f'{type(cleanup).__name__}: {cleanup}'
            self.child = None
            interrupted = isinstance(exc, (PipelineStopped, KeyboardInterrupt))
            self.save('interrupted' if interrupted and cleanup_error is None else 'failed',
                      error=f'{type(exc).__name__}: {exc}', cleanup_error=cleanup_error,
                      process_group_cleanup_confirmed=cleanup_error is None,
                      remaining_process_group=cleanup_group if cleanup_error is not None else None,
                      child_pid=None, finished_utc=utc())
            print(self.record['error'], file=sys.stderr, flush=True)
            return 128 + self.stop_signal if self.stop_signal is not None else 1
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--vivado', default='vivado')
    parser.add_argument('--threads', type=int, choices=range(1, 9), default=8)
    parser.add_argument('--max-utilization-percent', type=float, default=90.0)
    parser.add_argument('--heartbeat-seconds', type=float, default=30.0)
    parser.add_argument('--terminate-grace-seconds', type=float, default=30.0)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    for name, limit in [('max_utilization_percent', 100), ('heartbeat_seconds', 60),
                        ('terminate_grace_seconds', 60)]:
        value = getattr(args, name)
        if not math.isfinite(value) or not 0 < value <= limit:
            parser.error(f'{name} must be finite and in (0, {limit}]')
    try:
        return Pipeline(args, load_flow(ROOT)).run()
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
