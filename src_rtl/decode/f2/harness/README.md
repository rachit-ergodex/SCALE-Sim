# Physical compute timing harness

This is an **analysis-only physical timing experiment** around `decode_os_core`.
It is not the production F2 top, an HBM adapter, or a model-inference image. Its
scan latency cannot be used to estimate tokens per second. The core's ports and
cycle protocol are unchanged.

The earlier core-only OOC design had 164,453 input bits and 407,812 output bits,
with an ideal external clock and no physical endpoints for the interface. This
harness gives every core input a real positive-edge launch register and every
core output a real positive-edge capture register. One actual `BUFG` drives the
core and the harness. Each external control/data input is sampled on the falling
edge; the serial output launches on the rising edge. Input paths therefore have
half a cycle and the output has a full cycle under the original 1 ns maximum /
0 ns minimum I/O delays and 0.250 ns setup / 0.100 ns hold uncertainty.
No timing exceptions, relaxed minimum delays, or disabled timing arcs are used.

Only these synthesizable files belong in Vivado: the real `decode_os_core.sv`,
`decode_compute_timing_harness.sv`, and `harness_constraints.tcl`. The Tcl file
expects `period_ns` to be set explicitly. **Never include `bufg_sim.sv` or
`scan_core_fixture.sv` in synthesis**: they are simulation models only.

## Serial protocol

All control pins settle before a falling clock edge. Their sampled values act at
the following rising edge. Input and output chains are independent.

1. Assert `harness_reset` for at least one falling edge followed by a rising edge.
   This disarms the harness and holds the core in synchronous reset. Wide banks
   are deliberately not reset; their contents are invalid until loaded/captured.
2. Shift exactly `INPUT_BITS` bits, least significant bit first, by holding
   `input_shift=1` and supplying one `scan_in` bit per cycle. The core's launched
   operands remain unchanged while this staging bank shifts.
3. Pulse `input_commit`. The complete staged vector transfers to the launch bank
   atomically at the next rising edge. The core sees that vector after the edge
   and consumes it on its next active edge. This first commit also arms the core.
4. Pulse `output_capture`. The complete core-output vector is sampled at the next
   rising edge, using values **before** that edge. If commit and capture coincide,
   capture sees the previous launch vector. Capture wins over output shifting.
5. For each output bit, set `output_shift=1` before the falling edge and observe
   `scan_out` after the following rising edge. That edge samples the old chain
   head into `scan_out` and shifts the chain simultaneously. Read exactly
   `OUTPUT_BITS` bits, least significant bit first. The chain shifts zeros in
   after its last bit. Ignore `scan_out` on the capture edge itself: it contains
   the previous snapshot's head, since capture and serial launch use old state.

Commit and input shift may coincide: commit receives the **previous** staging
value, not the bit arriving on that edge. Keep `cycle_ready=0` in the launch
vector to stall a busy core while loading its next operands; the harness does
not gate its clock or silently change its handshake. Holding `cmd_valid=1` after
completion can resubmit a command, exactly as with the unwrapped core.

Input fields, in least-to-most-significant order:

| Field | Width |
|---|---:|
| reset, command valid | 1 each |
| command M, K, N | 32 each |
| parallel rows, accumulate, cycle ready | 1 each |
| A data | `8 * PARTITIONS` |
| B data | `8 * PARTITIONS * COLS` |
| seed data | `32 * PARTITIONS * COLS` |

Output fields, in least-to-most-significant order: command ready, busy, done,
command error (one bit each); A valid, A address; B valid, B address; seed valid;
C valid, C address, C data; logical cycles, elapsed cycles, stall cycles. Their
widths exactly match the core, including all 32 bits of each address and result.

## Resource gate before a large build

For `PARTITIONS=64, COLS=64`, `INPUT_BITS=164453`, `OUTPUT_BITS=407812`.
The harness adds **736,718 wide flip-flops** (two input banks plus one output
bank), and eight scalar flip-flops including sampled controls, serial output,
and armed state. `shreg_extract=no` keeps the scan chains as physical registers.
The core remains optimizable; no broad `DONT_TOUCH` is applied.

Every output bit needs a capture-versus-shift multiplexer. The conservative
single-LUT-per-multiplexer estimate is **407,812 additional LUTs**; actual packing
may share compatible functions, and distribution of control signals costs more.
Therefore a small routed example must first prove clock/boundary behavior, then
full-size **synthesis** must demonstrate enough device headroom before full P&R.
Use hierarchical reports to separate harness cost from core cost. Do not infer
full-size fit or 4,096-MAC timing closure from the small example. Confirm the real
core survives synthesis, all interfaces remain connected, and arithmetic/DSP
counts agree with the separately synthesized core before approving a long run.

This harness intentionally costs more than a practical banked-memory interface.
It isolates physical clock and boundary behavior without inventing a production
memory system. Passing its timing audit still does not establish AWS shell/HBM
integration, board timing, or inference throughput.

## Verification

Run using an environment containing Verilator and cocotb 2.x:

```sh
python src_rtl/decode/f2/harness/run_harness_tests.py --output /tmp/new-harness-test-run
```

The runner refuses an existing output directory and records all source hashes.
It runs two tests at both 1x3 and 2x5 geometry against both an independent mapping
fixture and the real core (eight cocotb tests total). The fixture emits a
position-dependent output pattern and its complement so **every output bit** is
captured and scanned both as zero and one; all-zero/all-one input patterns also
exercise every input bit. The real-core cases verify atomic input launch,
unchanged phase under stalls, immutable output snapshots while counters advance,
capture priority, and reset/disarm. Separate edge tests change controls after the
falling edge to ensure they cannot alter the immediately following rising edge,
then verify coincident commit/capture semantics. Every cycle checks that the
serial output remains unchanged at the falling edge and launches the pre-shift
head at the rising edge. These verify the harness; the real numerical MAC
correctness suite remains independently required.

## First physical experiment and output phase correction

The first small 4x8 physical harness passed routed timing at 50 MHz. At 100 MHz,
its only setup failure was the serial output: the former falling-edge
`scan_out_reg` had a 5 ns external budget, while 3.903 ns of source clock
insertion, 0.079 ns clock-to-output delay, 1 ns output delay and 0.485 ns total
uncertainty required 5.467 ns. The resulting slack was -0.467 ns. Hold timing
passed at +0.018 ns, and the next worst internal setup path passed at +0.296 ns.

The correction moves only serial-output launch to the rising edge and updates
the read protocol above. It provides a full external cycle through real RTL
behavior; all clock, I/O-delay and uncertainty constraints are unchanged. This
is not a timing exception or a change to the compute core. Both corrected 32-MAC physical runs passed routed timing: 100 MHz at
+0.715 ns setup / +0.017 ns hold, and 50 MHz at +5.284 ns / +0.019 ns.
See [source-bound evidence](../timing_harness_small_m7a8_result002.json).
These measurements precede the separate DSP mapping revision. Fresh 32-MAC
DSP runs also passed at 100 MHz (+0.449 ns setup / +0.020 ns hold) and 50 MHz
(+5.172 ns / +0.016 ns); see [DSP evidence](../timing_harness_small_m7a8_result003.json).
The full 64×64 build host was terminated at 19:05 IST on October 21; synthesis
completion and the resource gate are unknown, and full-size timing remains
unverified. See the [lifecycle observation](../timing_harness_full_m7a8_interruption003.json).
