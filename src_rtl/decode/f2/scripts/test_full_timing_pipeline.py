"""Exercise the sequential supervisor with real, cheap child processes; no Vivado."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('pipeline', Path(__file__).with_name('run_full_timing_pipeline.py'))
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)
FIXTURE = Path('fixture.json')
FAKE_DRIVER = r'''
import argparse,hashlib,json,os,signal,subprocess,sys,time
from pathlib import Path
root=Path(__file__).resolve().parents[4]; parent=root.parent
p=argparse.ArgumentParser();p.add_argument('--output',type=Path);p.add_argument('--stage');p.add_argument('--dry-run',action='store_true')
a,_=p.parse_known_args(); mode=json.loads((root/'fixture.json').read_text())['mode']
name=a.stage+('_preflight' if a.dry_run else '')
with (parent/'calls.txt').open('a') as f:f.write(name+'\n')
print('native diagnostic '+name,flush=True)
if name=='route_preflight' and mode=='preflight_failure':sys.exit(5)
if a.dry_run:sys.exit(0)
a.output.mkdir()
if a.stage=='synth' and mode in ('orphan_failure','interrupt'):
 child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])
 (parent/'descendant.json').write_text(json.dumps({'pid':child.pid,'group':os.getpgrp()}))
 if mode=='orphan_failure':sys.exit(7)
 def stopped(signum,frame):
  child.wait();sys.exit(128+signum)
 signal.signal(signal.SIGTERM,stopped)
 time.sleep(60)
if a.stage=='synth' and mode=='synth_failure':sys.exit(7)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
hashes={str(p):sha(root/p) for p in [Path('src_rtl/decode/f2/scripts/run_timing_harness.py'),Path('fixture.json')]}
if a.stage=='synth':
 (a.output/'post_synth.dcp').write_bytes(b'synth checkpoint')
 (a.output/'manifest.json').write_text(json.dumps({'status':'running' if mode=='bad_synth' else 'synth_resource_pass','source_hashes':hashes,'checkpoint_sha256':sha(a.output/'post_synth.dcp')}))
 if mode=='source_mutation':(root/'fixture.json').write_text('{}')
else:
 manifest={'status':'route_pass','stage':'route','part':'testpart','partitions':64,'cols':64,'clock_period_ns':10.0,'source_hashes':hashes,'vivado_returncode':0,'baseline_checkpoint_sha256':sha(parent/'synth/post_synth.dcp'),'component_routed_timing_pass':True,'f2_shell_timing_closed':False}
 audit={'status':'failed' if mode=='bad_audit' else 'passed','component_routed_timing_pass':True,'f2_shell_timing_closed':False,'vivado_returncode':0}
 (a.output/'manifest.json').write_text(json.dumps(manifest));(a.output/'audit.json').write_text(json.dumps(audit))
 if mode!='missing_route_dcp':(a.output/'post_route.dcp').write_bytes(b'route checkpoint')
 if mode=='route_failure':sys.exit(6)
'''


class FakeFlow:
    SCOPE = 'test harness scope'
    PART = 'testpart'

    @staticmethod
    def checked_inputs(root):
        return {str(path): pipeline.digest(root/path) for path in (pipeline.DRIVER, FIXTURE)}

    @staticmethod
    def checked_synthesis(run, hashes, partitions, cols, period, ceiling):
        if (partitions,cols,period)!=(64,64,10.0):raise ValueError('wrong geometry/clock')
        record=json.loads((run/'manifest.json').read_text())
        checkpoint=run/'post_synth.dcp'
        if (record['status']!='synth_resource_pass' or record['source_hashes']!=hashes or
                record['checkpoint_sha256']!=pipeline.digest(checkpoint)):
            raise ValueError('synthesis gate rejected')
        return checkpoint,record['checkpoint_sha256']


class FullTimingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'repository';self.root.mkdir()
        for name,contents in [(pipeline.DRIVER,FAKE_DRIVER),(pipeline.RUNNER,'frozen runner'),(FIXTURE,json.dumps({'mode':'success'}))]:
            p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(contents)
        self.args=argparse.Namespace(output=Path(self.tmp.name)/'run',vivado=sys.executable,threads=8,
                    max_utilization_percent=90.0,heartbeat_seconds=.02,terminate_grace_seconds=.1,dry_run=False)
        self.job=pipeline.Pipeline(self.args,FakeFlow,self.root)

    def run_job(self,mode='success'):
        (self.root/FIXTURE).write_text(json.dumps({'mode':mode}))
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):return self.job.run()

    def calls(self):return (self.args.output/'calls.txt').read_text().splitlines()
    def status(self):return json.loads((self.args.output/'status.json').read_text())

    def test_success_runs_exact_sequence_and_preserves_provenance(self):
        self.assertEqual(self.run_job(),0)
        self.assertEqual(self.calls(),['synth_preflight','synth','route_preflight','route'])
        status=self.status();self.assertEqual(status['status'],'route_pass')
        self.assertTrue(status['component_routed_timing_pass']);self.assertFalse(status['f2_shell_timing_closed'])
        self.assertEqual(status['route_checkpoint_sha256'],pipeline.digest(self.args.output/'route/post_route.dcp'))
        provenance=json.loads((self.args.output/'provenance.json').read_text())
        self.assertEqual(status['provenance_sha256'],pipeline.digest(self.args.output/'provenance.json'))
        self.assertEqual(provenance['source_hashes'],FakeFlow.checked_inputs(self.root))
        for name in self.calls():self.assertIn('native diagnostic', (self.args.output/(name+'.log')).read_text())

    def test_dry_run_creates_nothing(self):
        self.args.dry_run=True;self.assertEqual(self.run_job(),0);self.assertFalse(self.args.output.exists())

    def test_existing_output_and_dangling_symlink_are_rejected(self):
        self.args.output.mkdir()
        with self.assertRaisesRegex(ValueError,'already exists'):self.run_job()
        self.args.output.rmdir();self.args.output.symlink_to(Path(self.tmp.name)/'absent')
        self.job=pipeline.Pipeline(self.args,FakeFlow,self.root)
        with self.assertRaisesRegex(ValueError,'already exists'):self.run_job()

    def test_failed_synthesis_stops_before_route(self):
        self.assertEqual(self.run_job('synth_failure'),1)
        self.assertEqual(self.calls(),['synth_preflight','synth']);self.assertEqual(self.status()['status'],'failed')
        self.assertFalse((self.args.output/'route').exists())

    def test_zero_exit_without_synthesis_gate_stops(self):
        self.assertEqual(self.run_job('bad_synth'),1)
        self.assertEqual(self.calls(),['synth_preflight','synth'])

    def test_route_dry_run_failure_never_launches_route(self):
        self.assertEqual(self.run_job('preflight_failure'),1)
        self.assertEqual(self.calls(),['synth_preflight','synth','route_preflight'])
        self.assertFalse((self.args.output/'route').exists())

    def test_route_failure_overrides_optimistic_manifest(self):
        self.assertEqual(self.run_job('route_failure'),1)
        self.assertFalse(self.status()['component_routed_timing_pass'])
        self.assertEqual(self.status()['stages']['route']['returncode'],6)

    def test_zero_exit_with_bad_route_audit_fails(self):
        self.assertEqual(self.run_job('bad_audit'),1)
        self.assertFalse(self.status()['component_routed_timing_pass'])

    def test_missing_final_checkpoint_fails(self):
        self.assertEqual(self.run_job('missing_route_dcp'),1)
        self.assertFalse(self.status()['component_routed_timing_pass'])

    def test_snapshot_mutation_stops_before_route(self):
        self.assertEqual(self.run_job('source_mutation'),1)
        self.assertEqual(self.calls(),['synth_preflight','synth'])
        self.assertIn('snapshot changed',self.status()['error'])

    def assert_descendant_stopped(self):
        row=json.loads((self.args.output/'descendant.json').read_text());pid=row['pid']
        # Orphans can briefly remain zombies before init reaps them; zombies are not running.
        deadline=time.monotonic()+3
        while time.monotonic()<deadline:
            result=pipeline.subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True)
            if not result.stdout.strip() or result.stdout.strip().startswith('Z'):return
            time.sleep(.05)
        self.fail(f'descendant {pid} is still running')

    def test_failed_driver_terminates_its_orphan_descendant(self):
        self.assertEqual(self.run_job('orphan_failure'),1)
        self.assert_descendant_stopped();self.assertEqual(self.calls(),['synth_preflight','synth'])

    def test_interruption_terminates_group_and_records_status(self):
        def stop_when_running():
            deadline=time.monotonic()+5
            while time.monotonic()<deadline and not (self.args.output/'descendant.json').exists():time.sleep(.01)
            self.job.signal_requested(signal.SIGTERM,None)
        thread=threading.Thread(target=stop_when_running);thread.start()
        try:self.assertEqual(self.run_job('interrupt'),143)
        finally:thread.join()
        status=self.status()
        # Sandboxed macOS may deny a final killpg probe after the children die.
        # That remains a recorded cleanup failure, never a success claim.
        self.assertEqual(status['status'],'failed' if status['cleanup_error'] else 'interrupted')
        self.assertEqual(status['process_group_cleanup_confirmed'],status['cleanup_error'] is None)
        self.assertIn('Received signal 15',status['error'])
        self.assert_descendant_stopped()
        self.assertFalse((self.args.output/'route').exists())

    def test_late_interrupt_cannot_claim_pass(self):
        validate=self.job.validate_route
        def stop_after_validation(checkpoint):
            answer=validate(checkpoint);self.job.signal_requested(signal.SIGTERM,None);return answer
        with patch.object(self.job,'validate_route',side_effect=stop_after_validation):
            self.assertEqual(self.run_job(),143)
        self.assertEqual(self.status()['status'],'interrupted');self.assertFalse(self.status()['component_routed_timing_pass'])

    def test_cleanup_error_still_records_failure(self):
        with patch.object(self.job,'stop_child',side_effect=PermissionError('cleanup denied')):
            self.assertEqual(self.run_job('synth_failure'),1)
        self.assertEqual(self.status()['status'],'failed')
        self.assertIn('cleanup denied',self.status()['cleanup_error'])
        self.assertFalse(self.status()['component_routed_timing_pass'])

    def test_atomic_status_preserves_previous_record_on_replace_failure(self):
        path=Path(self.tmp.name)/'record.json';pipeline.atomic_json(path,{'old':True})
        with patch.object(pipeline.os,'replace',side_effect=OSError('simulated disk failure')):
            with self.assertRaises(OSError):pipeline.atomic_json(path,{'new':True})
        self.assertEqual(json.loads(path.read_text()),{'old':True})
        self.assertFalse(list(path.parent.glob('.record.json*.tmp')))


if __name__=='__main__':unittest.main()
