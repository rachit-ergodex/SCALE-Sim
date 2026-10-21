# Timing violations and repair — 2026-10-21

Both full 64×64 experiments finished on October 20 and **failed timing**.
The 100 MHz run finished at 20:47 IST after 3 h 11 min; the 50 MHz run finished
at 20:57 IST after 3 h 06 min. Neither produced a routed checkpoint or FPGA image.

| Experiment | Last setup WNS | Last hold WHS | Result |
|---|---:|---:|---|
| [50 MHz](compute_50_m7a8_result.json) | +0.738 ns | −0.180 ns | Setup met in terminal router summary; hold failed |
| [100 MHz](compute_100_m7a8_result.json) | −0.147 ns | −0.180 ns | Setup and hold failed |

These are terminal router/physical-optimization log values. The previous flow
aborted on `Route 35-39` before saving the final timing report and checkpoint.
The retained placement reports and separately regenerated **post-physical-opt,
pre-route** path reports identify the causes below, but their path-specific
slack must not be confused with the terminal routing values above.

Native split-path evidence is retained for [50 MHz](reports/compute_50_m7a8_run001/diagnostics_post_phys_opt/summary.tsv) and [100 MHz](reports/compute_100_m7a8_run002/diagnostics_post_phys_opt/summary.tsv), with full reports and checkpoint hashes beside each summary.

## Where the failures occur

### Row control to distant operand-address outputs: setup

At 100 MHz placement, `core/m_reg_reg[10]` drove the `row_index < m_reg`
comparison, then validity gating, then `b_address[28660]`. That output is
partition 13, column 63, address bit 20. The path took 9.770 ns, of which
**9.248 ns (94.7%) was routing**; it crossed SLR0 → SLR2 → SLR1 and included a
control net with fanout 1,055. This is primarily global control distribution,
not the INT8 multiply itself.

After the old run's physical optimization, a similar path remained from an
`m_reg[10]` replica to `b_address[10555]`, with only +0.008 ns estimated setup
slack before routing. An internal path from an `m_reg[0]` replica to partition
4, column 18's accumulator enable had +0.227 ns. These confirm that the row
comparison affects both output addresses and arithmetic enables.

**Implemented RTL repair:** `partition_used[p]` now stores current-wave row
activity. It is initialized at command acceptance and updated only when the
next row wave commits. The running output logic consumes that registered bit
instead of repeating the row comparison. This removes the global `m_reg` bus
from the combinational operand/result/valid cones without adding a cycle or
changing the arithmetic/stall protocol. See [core RTL](../rtl/decode_os_core.sv).

### Command boundary to command registers: hold

The worst identified boundary path is `cmd_accumulate` →
`core/accumulate_reg/D`, at **−0.180 ns** in both saved implementations.
`cmd_k` to its command registers is another example. The input minimum delay
is 0 ns, the standalone input connection contributes only about 11–12 ps,
and the capture requirement includes 100 ps hold uncertainty plus register
hold time and clock delay.

The old compute-only top exposes **164,453 input bits and 407,812 output bits**
without physical interface locations, and its clock has no actual clock buffer.
Vivado reports unlocated OOC boundary subnets and an unset clock route. Therefore
these boundary values are useful diagnostics but are not a valid integrated
F2 clock/memory-interface timing result. Output counters also show −0.050 ns
boundary hold, and the combinational reset-to-ready path shows −0.066 ns.

**Implemented diagnostic repair:** the separate [physical timing harness](harness/README.md)
adds a real BUFG and launch/capture registers around all core interface bits.
Its narrow serial controls use falling-edge registers, creating real half-cycle
external paths. The same 1/0 ns I/O budgets and 0.250/0.100 ns uncertainties apply.
No false paths, multicycle paths, relaxed input minimums, or timing waivers are
introduced. The harness is an analysis tool, not the production SRAM adapter.

### A-data shift pipeline: internal hold

There are also genuine short register-to-register paths in the saved
pre-route netlist; the boundary issue does not explain every violation.

| Saved checkpoint | Example path | Hold slack | Data delay |
|---|---|---:|---:|
| 50 MHz post-physical-opt | Partition 43, A pipeline stage 1 bit 7 → stage 2 bit 7 | −0.081 ns | 0.072 ns |
| 100 MHz post-physical-opt | Partition 43, A pipeline stage 0 bit 2 → stage 1 bit 2 | −0.079 ns | 0.074 ns |

The source statement is `a_pipe[p][c] <= a_pipe[p][c-1]`. Adjacent flip-flops
have almost no intervening logic. Hold requires data to remain stable briefly
**after the same clock edge**, so reducing 100 MHz to 50 MHz does not solve it.
This needs physical delay/routing repair under a real clock tree, not another
arithmetic pipeline stage that would change the computation schedule.

The previous `AggressiveExplore` physical-optimization run skipped hold repair
because its worst hold slack (−0.180 ns) did not cross that directive's −0.250 ns
trigger. The new harness implementation flow requests `-aggressive_hold_fix`
explicitly. Closure still requires measured nonnegative post-route hold slack.

The failed 50 MHz router additionally warned about a tight setup/hold window at
`c_data[102922]_INST_0/I4` (partition 50, column 16, result bit 10), and 213
result-path pins contributing to hold-repair congestion. These are warnings,
not a recovered final critical-path report; the old flow did not save that
failed routed design. Future route failures now preserve that evidence.

## Verification and remaining physical work

The complete canonical functional suite passed on the repaired core in 4 min
38 s. It includes nine cocotb tests, 24 Switchboard GEMMs, seven synthesis checks,
HBM/CDC and four-state checks, and 14 production commands checking **29,584 exact
integer outputs**. Added regression cases stall before and after partial-row
wave boundaries and check inactive outputs. A structural test confirms `m_reg`
no longer reaches the eight running operand/result/valid buses combinationally.
The previous RTL failed that structural check on all eight buses.

[Core verification](../verification.json) binds core SHA256
`2e7d5384f8af62022356847b6bd0554bca932540f1559332a2a4a0539dcbdf9d`.
The [harness verification](harness/verification.json) passed all eight tests,
including every-bit mapping and edge/commit/capture behavior.

A small physical harness experiment must establish clock, boundary and hold
behavior first. Full-size synthesis must then establish resource headroom
before full P&R: this analysis harness adds 736,718 wide flip-flops and hundreds
of thousands of output multiplexers. A small passing experiment is not proof
that all 4,096 MACs fit or close timing. The eventual production design still
needs banked SRAM adapters, legal AWS CL-region fit, HBM/shell integration and
full-system timing verification.

The retarget flow now preserves `failed_route.dcp`, the original route error,
setup/hold path reports, route/coverage/DRC/utilization reports and metrics after
routing fails. Its auditor refuses a pass whenever route failure is recorded,
even if copied reports or a checkpoint otherwise look positive. This prevents
future loss of the exact failing physical paths.

**Current claim:** the row-control RTL repair and functional verification are
complete. Physical hold repair and full-size timing closure remain to be
verified. No new inference TPS or ready-to-load F2 image is claimed.
