# F2 RTL synthesis readiness — 2026-10-22

**Functional gate: PASS for the implemented components.** The compute core and
32-port HBM read subsystem can proceed to **out-of-context component synthesis**.
This is not approval for a complete F2 accelerator image: a connected board top
and several inference blocks do not yet exist in this implementation.


**Original full-size OOC timing results:** both 50 and 100 MHz runs finished and failed
timing. The 50 MHz terminal summary had setup +0.738 ns / hold −0.180 ns; 100 MHz
had setup −0.147 ns / hold −0.180 ns. The registered row-activity RTL fix passed
the complete functional suite, and a separate physical-boundary harness passed
eight functional tests. The corrected 32-MAC harness subsequently passed routed
timing at 100 MHz (+0.715 ns setup / +0.017 ns hold) and 50 MHz (+5.284 ns /
+0.019 ns). Full 4,096-MAC and F2 shell closure remain pending. See
[timing causes, exact locations and repairs](TIMING_VIOLATIONS.md).

The subsequent F2 mapping revision exposes each lane's sum to DSP inference.
A controlled 32-MAC synthesis comparison uses 32 DSP48E2s and reduces LUT use
from 10,270 to 7,943. The complete functional suite passes on the new source,
and a strict mapped-netlist comparison with actual Vivado UNISIM models passed
520 legal commands, including long reductions, stalls and resets. All 3,496
observable bits remain checked after reconstructing proven synthesis boundary
aliases. Fresh DSP physical runs passed at 100 MHz (+0.449 ns setup / +0.020 ns hold)
and 50 MHz (+5.172 ns / +0.016 ns). The full 64×64 build host was terminated at 19:05 IST on October 21.
The last retained observation showed synthesis running at 16:47 IST; completion
and resource-gate status are unknown, and full-size P&R has not started in this
flow. [DSP physical evidence](timing_harness_small_m7a8_result003.json) remains
valid; the [termination observation](timing_harness_full_m7a8_interruption003.json)
supersedes the running status in the [launch record](timing_harness_full_m7a8_run003.json).

**M8a recovery:** run004 crashed inside Vivado synthesis with **SIGSEGV / exit 139**
at 22:56:54 IST on October 21; the supervisor recorded failure at 23:04:17 IST.
No final checkpoint or resource-gate result was produced, and P&R did not start.
Peak resident memory was 53.5 GiB against the 100 GiB limit; no OOM event was
observed. This is a tool-process failure, not a measured resource-fit failure.
[Crash result and native evidence](timing_harness_full_m8a8_result004.json).

Fresh **run005 started at 00:00 IST on October 22** on the same `m8a.8xlarge`.
It raises the process stack soft limit from 8 to 256 MiB and the core-dump size
limit to unlimited; both were verified on the actual Vivado process. Stack exhaustion is
unconfirmed, so this is a controlled recovery experiment. The exact verified RTL,
constraints, eight-thread setting and Vivado 2025.2 remain unchanged. Synthesis
has started, but resource fit and full-size timing remain pending. The persistent
service automatically starts **100 MHz P&R** only after a matching checkpoint,
exact 4,096-DSP mapping and the 90% resource checks pass. The earlier ETA is
withdrawn. Both runs remain on the retained encrypted build disk.
[Retry launch evidence](timing_harness_full_m8a8_run005.json).


## Verified behavior

A fresh baseline suite passed, followed by targeted reruns of all HBM and
synthesis checks after the AXI correction. Unchanged compute tests were not
substituted for tests of modified HBM RTL. `../verification.json` records the
final source hashes and component results; `../hbm_directed_verification.json`
records the sixteen directed HBM cases.

| Check | Result and scope |
| --- | --- |
| Full-size compute | Verilator/cocotb passed at 4×8, 32×64 and **64×64 / 4,096 MACs**; independent integer golden results and native SCALE-Sim demand addresses |
| Production-sized compute | Four additional 64×64 tests, 14 commands and 29,584 outputs checked against NumPy; FFN/attention tiles, carried partials, 200 MHz cycle accounting and backpressure |
| Compute limits | K=8191/8192, both INT32 wrap directions, signed INT8 corners, unsigned invalid command fields, held-valid and successive commands passed |
| Four-state simulation | Standalone Icarus passed three command scenarios with unused operands/seeds set to X, including stalls and reset |
| Queue integration | 24 Switchboard/Verilator GEMMs passed |
| Memory primitives | Byte writes, read-first collisions, invalid addresses, stalled responses, reset preservation and bank ownership passed |
| All-port HBM reads | 13,312 reads passed; 32 simultaneous responses for 256 consecutive ideal-target cycles; all 2,048 request slots exercised |
| Clock crossings | Single-port and all-32-port tests passed at 4,000/5,000 ps core / 2,222 ps HBM periods with varied phase, reordering, stalls and coordinated reset |
| Directed HBM protocols | Sixteen tests passed, including partial-packet flushing: legal same-cycle AR/R, disable under stalled AR, error/drain behavior, aperture end/overflow, tag wrap, sparse returns, and malformed-response isolation |
| Structural checks | Seven generic Yosys checks passed; no latches, compact signed INT8 multipliers and memory retained, 32 independent bridges, and no AXI input-to-RREADY combinational cone |
| Target lint | Generated ASIC and F2 compute wrappers passed Verilator lint |

The numerical results above verify the implemented integer compute block.
They do not verify a complete transformer RTL run or an FP32 vector/SFU pipeline.
The simulator's 232.270 F2 TPS remains a modeled result, not measured RTL/FPGA TPS.

## AXI correction made during this audit

The old read frontend allowed RID and ARREADY to influence RREADY through its
response classification. RREADY now depends only on reset and downstream
capacity. This removes the AXI input-to-output combinational path required to
be absent by the [Arm AXI specification](https://developer.arm.com/documentation/ihi0022/c/).

Unknown responses wait for downstream capacity before being discarded. While
one is pending, new ID allocation stops. A response observed as unknown remains
quarantined until consumed, so a later AR handshake cannot reclassify malformed
data as a legitimate result. It never retires the legitimate request. Faults
latch on consumption, and valid outstanding responses can still drain.
Directed failing-before/passing-after cases and a structural cone check cover
these invariants. The normal all-port throughput tests continue to pass.

## Synthesis boundaries

`generated/decode_f2_compute.sv` is a **compute-only** top with large internal
operand, address and result buses. Use it for out-of-context synthesis; do not
map those internal buses to package pins. The read bridges and scratchpad are
separate components, not a connected board-level accelerator.

The [official AWS source audit](AWS_HBM_INTEGRATION.md) identifies the matching
32-port wrapper and records the required shell/reset/address contracts. It does
not implement those connections or change this functional-verification scope.

Before a full F2 implementation, the following remain:

- A Small Shell top, HBM IP wiring, calibration/reset integration, host interface
  and a verified logical-to-physical HBM layout/loader.
- Banked SRAM adapters and arbitration connecting the compute core to the HBM
  read subsystem; the model requires 4,096 operand bytes/core cycle and 8.625 MiB
  staging SRAM. A standalone single-read-port scratchpad does not prove that banking.
- HBM writes, the operator sequencer and the FP32 vector/SFU arithmetic contract.
- Physical CDC constraints and review: Gray-bus skew/max-delay, synchronizer
  placement, and coordinated reset with per-domain synchronized deassertion.
- Vendor HBM simulation, DSP/BRAM/URAM mapping, resource fit, and timing closure
  at the new **200 MHz core / 450 MHz HBM** target. Vivado 2025.2 is available
  on the existing `opentpu-f2` host; the component flow is described below.

An exploratory full 64×64 Yosys run reached process conversion but was stopped
after its five-minute budget (317 seconds including termination). It did not
complete optimization or the final structural check, so full-size generic
synthesis is **inconclusive** and is not included in the seven passing checks.
Full-size component area/resource characterization remains a Vivado task.

The compute address/control path now decodes constant partition layouts at
command acceptance and advances registered row bases with additions. Generic
synthesis checks reject variable divide/modulo and non-MAC variable multipliers.
This preserves the native simulator's accepted-cycle addresses and arithmetic;
physical timing still needs Vivado measurement. Generic memory retention does
not establish BRAM/URAM mapping.

## 200 MHz synthesis experiment

Use the [reproducible Vivado flow](scripts/README.md) for the full 64×64 compute
component on `xcvu47p-fsvh2892-2-e`. It snapshots functionally verified RTL,
constrains the clock to 5 ns, and retains native timing, utilization and DRC
reports. Its 1 ns boundary budgets are provisional SRAM-adapter contracts.
Even a successful routed component result does not establish legal AWS CL-region
fit or full-system closure: the experiment does not include the static shell.

For the separate HBM bridge, use `RETURN_RECORDS=3` at 200 MHz. The default of
two records would limit aggregate returns to 409.6 GB/s. Three records provide
614.4 GB/s interface capacity; a digital all-port test sustains 65,536 returns
at one per port per HBM cycle. This is functional throughput evidence, not
physical HBM timing or measured memory bandwidth.

## Reproduce

From the repository root, using the environment described in `../README.md`:

```sh
env -u PYTHONPATH src_rtl/build/decode_venv/bin/python src_rtl/decode/verify.py
```

This runs generated-target checks, all compute/memory tests, Switchboard,
generic synthesis, all-port and directed HBM tests, maximum-K tests and Icarus.
Only proceed on the exact source snapshot whose verification manifest passes.

The first Vivado 2025.2 run was launched on the existing `opentpu-f2` host using
verified commit `cca6fb1`. [Launch observation](compute_200_launch.json) records
the exact source hashes, host, run directory and command. At that observation,
synthesis was running; no completed synthesis, routed timing or resource-fit
result is claimed. Inspect the remote run's `manifest.json`, `console.log`,
`audit.json` and native reports for its eventual result.


The initial run was subsequently **stopped before PnR** because managed XDC
rejected its input-port collection command, omitting the input delay budgets.
Its logs and snapshot are retained; it does not count as a timing result.
The fix uses unmanaged OOC Tcl, 4,096-bit delay chunks, critical-warning errors
and a timing-coverage gate before placement. An actual Vivado 2025.2 regression
passed with 4,098 input and 4,097 output bits, zero missing/partial timing budgets,
and the intended clock and uncertainty values; see
[constraint regression](constraint_smoke_verification.json).

The corrected full-size **run-002** was launched from commit `0834501`;
[its launch observation](compute_200_run002.json) records the new inputs and
remote directory. At that observation synthesis was running, PnR had not started,
and no area/timing closure result was available.


The build was then moved to the requested **m7a.8xlarge** (32 CPU cores,
128 GiB RAM) using the same FPGA Developer AMI and Vivado 2025.2. The M7a
constraint regression passed, including the VU47P synthesis license checkout;
its resolved constraints are byte-for-byte identical to the validated F2
regression. [M7a launch evidence](compute_200_m7a8_run001.json) binds the source
hashes, instance, tool build, preflight checks and command. The full 4,096-MAC
compute build started with eight threads and was observed in RTL elaboration.
The F2 run-002 process was stopped after its M7a replacement was running; its
source and logs are preserved. No completed synthesis or routed timing result
is claimed by this launch record.


The M7a 200 MHz run subsequently **failed routing** after 9 h 28 min 38 s.
Synthesis, placement and physical optimization completed and their checkpoints
are preserved. Routing reported global congestion level 7. Placement used
1,023,322 LUTs, 175,661 flip-flops and zero DSP blocks; its setup WNS was
−5.213 ns and hold WHS was −0.180 ns. Neither timing closure nor a runnable
image was produced. [Failure evidence](compute_200_m7a8_result.json) and the
retained native reports supersede the earlier launch observation. The saved
synthesis checkpoint is the basis for a separate 100 MHz implementation
experiment; lowering the clock does not by itself remove routing congestion.


The subsequent **100 MHz run-002** and **50 MHz run-001** both completed with
`Route 35-39` timing failures. Their final observations supersede the earlier
running launch records: [100 MHz result](compute_100_m7a8_result.json) and
[50 MHz result](compute_50_m7a8_result.json). Both retained zero router-counted
unrouted nets, but the unlocated OOC boundary and negative hold slack prevent
signoff. Neither failure was an out-of-memory termination.

The [repair analysis](TIMING_VIOLATIONS.md) explains the global row-control setup
path, command-boundary hold paths and short internal A-data shift paths. The
updated core passes the complete functional suite with a fresh source-bound
manifest. A [registered timing harness](harness/README.md) provides physical
launch/capture points and a BUFG for the next implementation experiment; it
requires small-scale physical validation and a full-size resource gate before
long P&R. It does not replace the missing production SRAM/HBM/shell integration.
