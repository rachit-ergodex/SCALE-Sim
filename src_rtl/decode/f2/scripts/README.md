# F2 200 MHz compute synthesis

From the repository root, with licensed Vivado and VU47P device support loaded:

```sh
python3 src_rtl/decode/f2/scripts/run_compute_ooc.py \
  --output /path/to/new/compute-200-run --dry-run
python3 src_rtl/decode/f2/scripts/run_compute_ooc.py \
  --output /path/to/new/compute-200-run
```

Use `--stage synth` for a synthesis-only characterization or `--vivado` to
select an executable. The default runs synthesis, optimization, placement,
physical optimization and routing. The full **64×64 / 4,096-MAC** generated
compute wrapper is the top; there is no reduced array hidden in this flow.
The driver refuses an existing output directory, checks that both RTL sources
match their functional-verification hashes, snapshots its inputs, and records
the command, device, constraints, tool version, reports and checkpoints. Follow
`console.log` or `vivado.log` while running. A nonzero exit means either Vivado
failed or the report audit did not pass; the artifacts are retained in either
case. Rerun the independent report audit with:

```sh
python3 src_rtl/decode/f2/scripts/audit_compute_ooc.py /path/to/compute-200-run
python3 -m unittest discover -s src_rtl/decode/f2/scripts -p 'test_*.py'
```

The target is `xcvu47p-fsvh2892-2-e`, matching the pinned Alex burst200
reference. `compute_200mhz.tcl` sets a 5 ns clock, 0.25 ns setup uncertainty and
0.1 ns hold uncertainty. Every data/control boundary, including synchronous
reset, has explicit min/max delays. The provisional 1 ns input and output
budgets must be replaced or substantiated when the banked SRAM adapter exists.
The boundary file uses unmanaged Tcl, applies delays in chunks of at most 4,096
bits, and includes reset. Critical warnings stop synthesis; timing coverage and
full-interface bit counts are checked before placement. No timing paths are waived. The giant operand/address buses are internal
component boundaries, not package I/O pins.

The audit requires nonnegative setup, hold and pulse-width slack, zero total
negative slack and failing endpoints, timing coverage (including no unconstrained
internal endpoints), no DRC errors/critical warnings and, after route, no
unrouted/partially routed/conflicting nets. Unrecognized or missing reports fail
closed. Synthesis-only success never sets `component_routed_timing_pass`.
Even a routed component pass always sets `f2_shell_timing_closed: false`.

## Insights taken from Alex burst200

Alex's source at `06c169cbcd1721ae8b167de992a93461697a397d` targets Vivado 2025.2.
Its `create_clocks.tcl` derives 200 MHz compute from the 250 MHz shell clock and
450 MHz HBM from a separate 100 MHz reference. Its implementation scripts save
checkpoints before and after placement/physical optimization and collect both
setup and hold paths. Those reproducibility and reporting practices are used
here. The future board top should use that clock separation; lowering compute
to 200 MHz does not require lowering HBM.

Alex places state and wide datapaths close to HBM in SLR0, with the shell-facing
host endpoint in SLR1. That is useful guidance for a floorplan after resource
characterization, but its pblocks and hierarchy do not fit this 32-port design
automatically. This component experiment uses the whole device without the
static shell and therefore cannot establish that the design fits the legal CL
region. The real AWS shell checkpoint must be linked for that next stage.
Its related 400 MHz TMEM multicycles, two-port SmartConnect, shell bank-74 Vref
setting and leaf-clock-optimizer workaround are specific to that implementation
and are not imported here.

The existing simulator profile and historical 232.270 TPS result remain at
250 MHz. This flow only changes the physical characterization target. It does
not estimate 200 MHz TPS or verify full inference. HBM IP, all-port integration,
memory banking, CDC constraints, host loading, vector/SFU blocks and the
sequencer must be present before full-board timing or FPGA inference can be
claimed. The separate memory path must still sustain all 32 ports at 450 MHz.

## Constraint regression

The first run exposed that managed XDC rejects `remove_from_collection`, losing
input delay budgets. It was stopped and marked invalid; its snapshot and logs
remain intact. The corrected file is loaded as unmanaged OOC Tcl and was tested
with Vivado 2025.2 on 4,098 input / 4,097 output bits, forcing two chunks on both
boundaries. All timing-coverage checks were zero and resolved min/max delays and
clock uncertainty matched the intended budgets. Evidence is retained in
`../constraint_smoke_verification.json`; the driver checks its source hashes.

To reproduce the regression with the current sources:

```sh
vivado -mode batch -source src_rtl/decode/f2/scripts/constraint_smoke.tcl \
  -tclargs "$PWD" /path/to/new/constraint-smoke
```

A smoke pass validates constraint application, not full-compute timing closure.


## M7a build host and thread limit

The current dedicated build host is `m7a.8xlarge`: 32 CPU cores and 128 GiB RAM,
with the FPGA Developer AMI, Vivado 2025.2, and encrypted gp3 storage. Access is
through SSM. See [the launch record](../compute_200_m7a8_run001.json) for the
instance and source provenance. Use `--threads 8` for the maximum supported
per-run setting. The earlier F2 run used four threads; the M7a run uses eight.

Vivado's documented `general.maxThreads` range is **1–8**, including placement,
routing, physical optimization and timing analysis. More CPU cores do not
increase this per-run limit. Independent component builds or implementation
strategies can run in parallel, subject to their combined memory requirements;
they do not make one RTL elaboration use 32 threads. This first full-size run
records peak RSS with `/usr/bin/time -v` before choosing a safe concurrency.
See [AMD's Vivado 2025.2 threading documentation](https://docs.amd.com/r/2025.2-English/ug904-vivado-implementation/Multithreading-with-the-Vivado-Tools).


## 100 MHz checkpoint retarget

The first 200 MHz M7a attempt completed synthesis and placement, but routing
failed with congestion level 7 after 9 h 28 min. Preserve that experiment and
reuse its verified `post_synth.dcp` for a distinct 100 MHz placement/routing run:

```sh
python3 src_rtl/decode/f2/scripts/run_compute_retarget.py \
  --baseline /path/to/compute-200-run \
  --output /path/to/new/compute-100-run \
  --compute-mhz 100 --threads 8
```

`--dry-run` validates the baseline source hashes and checkpoint provenance
without creating an output directory. `--stage preflight` performs only the
actual Vivado checkpoint and constraint checks. The default route stage runs
those checks before optimization, placement, physical optimization and routing.
The new directory contains hash-checked copies of the synthesis checkpoint,
baseline sources/manifest and the new flow sources; the original run is preserved.

The retarget keeps all 4,096 MACs and changes the sole `decode_core` clock to
10 ns. It explicitly reapplies the original 1/0 ns maximum/minimum input and
output delays and 0.25/0.1 ns setup/hold uncertainty. It checks full boundary
widths, rejects timing exceptions and requires complete timing coverage before
placement. The final audit is called with `--expected-period-ns 10`; omitting
this option still selects the original 5 ns requirement. A 100 MHz result
cannot pass the default 200 MHz audit, and a stale 5 ns clock cannot pass the
100 MHz audit.

Checkpoint reuse skips the original five-hour synthesis stage. It does not
remap LUT arithmetic into DSPs or reduce interface/control routing demand, so
this lower-frequency experiment can still fail congestion or timing. It remains
a compute-only OOC experiment, without the AWS shell, HBM or SRAM adapters.
