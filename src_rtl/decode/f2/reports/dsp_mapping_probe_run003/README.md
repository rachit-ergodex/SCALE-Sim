# Small FPGA DSP mapping experiment

The per-lane DSP implementation passed numerical RTL tests and mapped-netlist
comparison against the original verified core using Vivado 2025.2 and the actual
UNISIM DSP48E2 models. The controlled 4×8 synthesis experiment reduced total LUT
use by 22.66%, mapping all 32 MAC lanes to 32 DSP blocks.

| Variant | Total LUTs | Core LUTs | Registers | DSP48E2 |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 10,270 | 8,514 | 8,692 | 0 |
| Per-lane sum attribute | 7,943 | 6,187 | 8,471 | 32 |

Both synthesis variants use the same frozen `source-001` timing harness and
VU47P part. This harness has the original falling-edge serial output; the current
harness has since changed. These reports establish the small synthesis area
comparison and mapped functional behavior. They do not establish routed timing,
full 4,096-lane fit, F2 shell readiness, or inference throughput.

The candidate exposes each unchanged 32-bit MAC expression before the
output-valid mux and applies `USE_DSP=yes` under the F2-only
`SCALESIM_F2_USE_DSP` define. It saves 2,327 total LUTs. Every lane maps to one
DSP48E2 with multiplication enabled and CREG/MREG/PREG=0. Vivado absorbs
existing A-pipeline state into AREG=0/1/2; the mapped simulation checks the
resulting behavior through stalls, reset, accumulation, and command boundaries.

## Mapped correctness

[The passing result](mapped_verification/netlist-equivalence-002/summary.json)
records 221,934 comparisons of all 3,496 output and control bits over 110,991
clock ticks. It covers 520 legal commands, six illegal commands, four resets
during active commands, and 27,727 stalled cycles. Tests cover every M=1–4,
N=1–32, parallel/sequential and accumulate mode combination, signed INT8
extremes, INT32 seeds, short reductions, and K=8,192 corners. Outputs are checked
before and after rising edges, including while invalid or stalled.

The reference is the original verified core, SHA-256
`2e7d5384f8af62022356847b6bd0554bca932540f1559332a2a4a0539dcbdf9d`;
only its module name is changed. The mapped netlist is from candidate SHA-256
`5083d843fcd001d50044de27650489e1092f1ab09eb081516f83359c79d91aed`.
Actual installed UNISIM and `glbl` are used; the simulator version, library paths,
source hashes, commands, and coverage counts are recorded in the native results.
There is no SDF back-annotation or routed timing claim.

[Attempt 001](mapped_verification/netlist-equivalence-001/summary.json) is
preserved as a failure. Vivado merged 20 duplicate `c_address` bits into aliases
at the enclosing harness; extracting the optimized core alone omitted those
connections. [The capture proof](mapped_verification/output_capture_map.json)
accounts for every one of the 3,496 harness output capture bits, including its
mux, selector register, capture register, and shift connection. Attempt 002 uses
[a generated observation wrapper](mapped_verification/netlist-equivalence-002/observation_wrapper.v)
to reproduce those exact connections. The mapped core, reference, stimulus,
and unconditional comparisons are unchanged. No output bits are masked.
[A separate connection proof](mapped_verification/core_connection_proof.json)
checks all 27 core ports, widths, directions, and top-level connections.
The scripts and results of the independent boundary analysis are retained in
`mapped_verification/boundary-proof-scripts/`.

## Evidence

`baseline/` preserves the baseline mapping; `dsp/` preserves an invocation
failure; `dsp-002/` shows that an attribute on the packed output port alone
produced no DSPs; `dsp-003/` is the successful per-lane mapping. The exact
candidate source is `candidate3/decode_os_core.sv`. The root-level core source
belongs to the earlier packed-output experiment. The source-level numerical
results are in `candidate3/verification.json`.

Native reports and logs are unchanged. `collection_manifest.json` and
`transfer.json` bind the original synthesis archive; its scope text records that
mapped verification was pending at collection time. The later mapped archive
has its own manifest and transfer record under `mapped_verification/` and
contains both attempts plus the generated netlist. No UNISIM vendor source is
included. `dsp_instances_excerpt.v` contains generated instance connections,
not a vendor simulation model.
