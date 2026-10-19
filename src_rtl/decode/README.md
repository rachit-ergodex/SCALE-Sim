# Decode RTL implementation

This directory implements the parallel **one-row output-stationary INT8 compute
subsystem** of the optimized simulator. `generate.py` reads the selected ASIC/F2
configuration files and emits fixed-geometry compute wrappers and resource
manifests. It is separate from the older weight-stationary RTL in `../rtl`.

| Target | Physical arrays | Signed INT8 MACs | Modeled core clock | Modeled staging SRAM |
| --- | --- | ---: | ---: | ---: |
| ASIC | 32 × 1×64 | 2,048 | 1 GHz | 4.625 MiB |
| F2 | 64 × 1×64 | 4,096 | 250 MHz | 8.625 MiB |

The clocks and memory capacities above come from the simulator. They are not
place-and-route results. The generated wrappers instantiate the compute core;
the SRAM blocks below are separately verified integration components. The
simulator's 338.316/232.270 TPS results do not yet describe an end-to-end RTL run.

The F2 integration [reference notes](f2/README.md) pin and audit Alex's burst200 source while preserving this design's target architecture.

## Implemented blocks

- `decode_os_core.sv`: actual signed INT8 multipliers, INT32 accumulators and
  activation shift registers. Independent 1×C partitions run output columns in
  parallel. Idle column partitions can process distinct attention rows with the
  same B matrix. Partial K commands take explicit INT32 seeds. Accumulation wraps
  modulo 2^32; the model's valid W8A8 GEMMs avoid overflow.
- `decode_scratchpad.sv`: parameterized synchronous read, byte-enabled write SRAM.
  A response register holds data/error through backpressure. Concurrent reads
  and writes to the same word return the old value. Reset clears interface state,
  not the memory contents. Invalid addresses return an error without a write.
- `decode_bank_lifetimes.sv`: two independent operand-bank ownership machines,
  `EMPTY → LOADING → READY → IN_USE → EMPTY`, including unexpected DMA-completion
  detection. Acquiring and releasing banks uses ready/valid handshakes.
- `decode_hbm_map.sv`: the exact 34-bit HBM address permutation from the native
  timing backend, with a bypass mode.

The core's accumulator and activation registers use 10 KiB for ASIC and 20 KiB
for F2, separate from staging SRAM. The simulator also budgets 7 KiB of streaming
vector pipeline registers. Those FP32 vector registers and operators are not
instantiated by this compute wrapper.

The [32-port HBM read frontend](f2/README.md#implemented-32-port-read-frontend) is separately verified for simultaneous traffic, 2,048 credits and reordered responses.

## Core protocol

A command is accepted on `cmd_valid && cmd_ready`. It must satisfy `1 ≤ M ≤ 4`,
`1 ≤ K ≤ 8192` and `1 ≤ N ≤ PARTITIONS*COLS`; invalid commands pulse
`command_error` and leave the core idle. Software tiles wider N dimensions and
splits K as required by bank capacity. For K splits, `cmd_accumulate` selects an
external partial-sum seed on the first product of each output.

A and B addresses are row-major **element indices**, relative to the command's
M×K and K×N matrices. C addresses index M×N and also identify seed operands.
`a_valid` requests one INT8 activation per partition; `b_valid` requests one INT8
weight per physical column. Repeated B addresses for attention workers can be
broadcast by the memory adapter. `seed_valid` requests INT32 data only on the
first product of an accumulating command.

All operand consumption, PE shifts and C writes commit together when
`busy && cycle_ready`. Output `c_valid` is a pending write request, so consumers
must not write it repeatedly while stalled. Operands/seed data must remain
available for that pending cycle. `cycle_ready` must combine operand availability
and output capacity. The core holds its address schedule and PE state during a
stall. Reset aborts the command; `done` pulses once after the final drain cycle.

For one output tile, `column_parts = ceil(N/COLS)`. Parallel-row mode uses
`workers = min(M, floor(PARTITIONS/column_parts))`; otherwise it uses one worker.
Each wave takes `K + COLS - 1` committed cycles, including drain even for a ragged
last column group. Total cycles are `ceil(M/workers) * (K + COLS - 1)`.
`logical_cycles`, `elapsed_cycles` and `stall_cycles` reset per accepted command;
command acceptance is outside these counters. Tests compare every committed
A/B/C address and valid mask against native SCALE-Sim demand matrices.

## Verification

Use Python 3.12+, Verilator, a C++ compiler and Yosys. From the repository root:

```sh
python3 -m venv src_rtl/build/decode_venv
src_rtl/build/decode_venv/bin/pip install -r src_rtl/decode/requirements.txt
PY=src_rtl/build/decode_venv/bin/python
env -u PYTHONPATH "$PY" src_rtl/decode/generate.py --check
env -u PYTHONPATH "$PY" src_rtl/decode/tests/run_cocotb.py --full
env -u PYTHONPATH "$PY" src_rtl/decode/tests/run_switchboard.py
env -u PYTHONPATH "$PY" src_rtl/decode/tests/run_synthesis.py
```

Cocotb drives Verilator at compact and full 32×64/64×64 geometries. Independent
NumPy INT64 multiplication checks signed extremes, INT32 wrap, ragged dimensions,
parallel heads, three-way partial K accumulation, randomized stalls, aborted
commands and reset recovery. Separate tests exercise byte write enables,
read/write collisions, response backpressure, bank hazards and HBM mapping.

The Switchboard test uses **real shared-memory queues** between Python and a
standalone Verilated executable. It sends input matrices, partial sums and
commands, and checks RTL-produced results and cycle counters for 24 GEMMs.
The C++ adapter only supplies memory data and transports outputs; it performs no
GEMM arithmetic. Queue capacity is derived from the actual file, allowing native
Python and Rosetta Verilator to use different host page sizes. This test uses a
compact 4×8 geometry; full target geometries are exercised by cocotb.

Generic Yosys checks reject latches, verify 32 signed 8×8 multipliers in the
compact core, and retain the scratchpad as a memory. Full generated target
wrappers are also lintable with `verilator --lint-only -Wall --top-module
<top> src_rtl/decode/rtl/decode_os_core.sv src_rtl/decode/generated/<top>.sv`.
`python src_rtl/decode/verify.py` runs all checks above, including generated-target lint.
Machine-readable results live under `build/`; a retained verification manifest
records test versions and hashes of the tested sources.

## Remaining system integration

The complete transformer accelerator still needs synchronous SRAM adapters and
arbitration, the HBM write path, core/HBM CDC and integration of the multi-outstanding read frontends, the FP32 vector/SFU
pipeline with the original rounding semantics, and the full operator sequencer.
The generated manifests list these boundaries explicitly. There is no
full-transformer RTL equivalence result or FPGA bitstream yet. In particular,
clock closure, HBM bandwidth under these adapters, and exact FP32 division/SFU
throughput must be measured before projecting the simulator TPS onto hardware.
