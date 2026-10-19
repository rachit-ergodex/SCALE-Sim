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
