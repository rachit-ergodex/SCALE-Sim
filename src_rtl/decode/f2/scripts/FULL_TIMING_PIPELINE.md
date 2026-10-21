# Sequential 4,096-MAC timing run

`run_full_timing_pipeline.py` runs fresh 64×64 synthesis and then automatically
routes the successful synthesis checkpoint at 100 MHz. It uses the existing
`run_timing_harness.py` gates without changing RTL, Tcl, constraints, DSP mapping,
or timing budgets. This remains a registered compute-harness experiment on
VU47P; it does not establish AWS shell/HBM timing or inference throughput.

From the source repository on a prepared build host:

```sh
python3 src_rtl/decode/f2/scripts/run_full_timing_pipeline.py \
  --output /home/ubuntu/rachit/scalesim-m8a8-20261021/full-100-pipeline-004 \
  --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8 --dry-run
```

The dry run validates source evidence and prints the planned commands. It creates
no output and launches no tools. The run directory must be new, including when
restarting after a failure. There is no implicit resume, overwrite, or retry.

Run under systemd as `ubuntu` to survive an SSM or terminal disconnection:

```sh
sudo systemd-run --unit=scalesim-full-100-pipeline-004 \
  --uid=ubuntu --gid=ubuntu \
  --property=WorkingDirectory=/home/ubuntu/rachit/scalesim-m8a8-20261021/source-004 \
  --property=Restart=no --property=KillMode=control-group \
  --property=TimeoutStopSec=45s \
  /usr/bin/python3 -u \
  /home/ubuntu/rachit/scalesim-m8a8-20261021/source-004/src_rtl/decode/f2/scripts/run_full_timing_pipeline.py \
  --output /home/ubuntu/rachit/scalesim-m8a8-20261021/full-100-pipeline-004 \
  --vivado /opt/Xilinx/2025.2/Vivado/bin/vivado --threads 8
```

Host provisioning, licenses, environment setup, memory limits, and separate
approval/evidence for the small routed and mapped-netlist runs belong in the
launch record. This runner validates the existing driver's twelve inputs; it
does not replace that separate release-evidence review. A systemd service does
not preserve files if the backing storage is destroyed.

The runner snapshots those inputs and itself, then executes:

1. Synthesis dry run using the frozen driver.
2. Full 64×64 synthesis at a 10 ns period.
3. Existing synthesis source/checkpoint/DSP/resource gate, including one DSP per
   exact MAC lane. Negative unplaced slack alone is not a resource-gate failure.
4. Existing route dry run against the preserved synthesis checkpoint.
5. Optimization, placement, explicit hold repair, and routing with the existing
   flow, followed by its setup/hold/coverage/DRC/route audit.

The default resource-policy ceiling is 90% against device capacities reported by
Vivado. `--max-utilization-percent` explicitly changes that policy. Threads are
limited to 1–8 by the existing flow. Geometry and frequency are fixed here.

`status.json` and `provenance.json` are written using atomic replacement, with
file and directory fsync. Status includes stage transitions, commands, child PIDs,
return codes, source and result hashes, and a heartbeat every 30 seconds. Sources
are rechecked before the transition to routing and before final success.

- `source/`: frozen driver inputs and the runner.
- `synth/`, `route/`: separate native driver runs, reports, logs, and checkpoints.
- `synth_preflight.log`, `synth.log`, `route_preflight.log`, `route.log`: complete
  driver stdout/stderr, including failures.
- `status.json`: current state and stage history; only `route_pass` means the
  component audit passed. `f2_shell_timing_closed` always remains false.

A failed command, prerequisite, final audit, or missing final checkpoint stops
progress. SIGTERM/SIGINT terminate the active process group, record interruption,
and do not launch the next stage. The default termination grace is 30 seconds;
systemd's stop timeout should be longer. SIGKILL, power loss, or host termination
cannot write a final status; a stale heartbeat must be checked against the service
state and is never evidence of completion. Preserve the old run and use a new
output directory for an explicitly requested rerun.

```sh
systemctl status scalesim-full-100-pipeline-004
journalctl -u scalesim-full-100-pipeline-004
cat /home/ubuntu/rachit/scalesim-m8a8-20261021/full-100-pipeline-004/status.json
python3 -m unittest discover -s src_rtl/decode/f2/scripts -p 'test_full_timing_pipeline.py' -v
```
