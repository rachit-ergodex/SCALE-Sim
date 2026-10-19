# Real-weight Gemma3-1B numerical execution and HBM2 timing

This path executes the **actual locally available Google Gemma 3 1B IT weights**,
including all transformer operators and token selection. It then runs a matching
operator graph against native Ramulator2 HBM2 at the requested simulated clock.
The numerical and timing runs are separate: numerical outputs establish the
workload, while dependent memory callbacks determine its simulated schedule.
This is not a full-transformer RTL implementation or a hardware benchmark.

## Intermediate SRAM, parallel attention heads and streaming vectors

This revision targets over 325 TPS at 1 GHz and over 200 TPS at 250 MHz with
the same W8A8/KV8 numerical operations and unchanged HBM clocks/timings.

Measured native Ramulator2 results for three batch-one decode steps at contexts 513–515:

| Profile | TPS | Compute ms/token | Exposed memory wait ms/token | Average HBM GB/s |
| --- | ---: | ---: | ---: | ---: |
| `decode_asic_resident` | 304.835 | 1.274 | 2.007 | 312.42 |
| `decode_asic_stream` | 321.391 | 1.106 | 2.005 | 329.39 |
| `decode_asic_small_tiles` | 319.024 | 1.224 | 1.911 | 326.96 |
| `decode_asic_stream256` | 338.316 | 0.954 | 2.002 | 346.73 |
| `decode_f2_resident` | 178.925 | 4.237 | 1.352 | 183.38 |
| `decode_f2_stream` | 202.736 | 3.561 | 1.372 | 207.78 |
| `decode_f2_small_tiles` | 201.604 | 3.905 | 1.055 | 206.62 |
| `decode_f2_stream256` | 232.270 | 2.950 | 1.355 | 238.05 |

The selected `stream256` profiles reach **338.316 TPS on the 1 GHz ASIC** and **232.270 TPS on 250 MHz F2**. Every measured token exceeds its target. They use 4.625 MiB and 8.625 MiB of staging SRAM respectively, plus 7 KiB of modeled pipeline registers. HBM remains 16 GiB with a nominal 460.8 GB/s interface.

Verification passed 21 regression tests and 142 native timing checks across eight configurations. For each selected profile, the real checkpoint validator checked 1,173 GEMMs and 104 cache conversions, with all 262,144 logits matching exactly at each of three decode steps. The retained [optimized study](optimized_decode_study.json) includes configuration, source/input hashes, numerical evidence and per-stage timings. These are architectural simulation results; RTL integration and physical timing closure are separate work.

The optimization profiles add three independently configurable mechanisms:

- `intermediate_sram_bytes`: a separate, bounded 128 KiB SRAM retains short
  intermediate tensors. A static lifetime allocator selects initialized
  tensors no larger than 32 KiB and reuses slots only after their last access.
  Parameters, KV, tensors read by asynchronous operand DMA, large tensors and
  the externally visible selected token remain in HBM. Every local read/write
  pays a copy cost at `vector_lanes * 4` bytes/core cycle; there is no free
  inter-operator transfer or implicit unlimited cache. `residency.json` records
  allocations and every relocated logical access.
- `parallel_head_rows`: otherwise idle output-array partitions process separate
  attention rows. Each worker receives its activation row and a broadcast of
  the common weight/cache tile. The critical path is the maximum of the
  independent native array schedules. The MAC count is unchanged.
- `stream_value_cache`: FP32 multiply, absolute value/max, divide, round and
  clamp intermediates stay in pipeline registers. Only incoming INT8 values,
  token scales and outgoing INT8 values use the scratch port. Arithmetic issue
  costs, exact division throughput and pipeline fill/drain remain charged.
  Feature maxima/scales use a dedicated 2 KiB state bank within the existing
  vector-storage budget; pipeline registers are additional. Every FP32 operation must preserve its
  original rounding; fused multiply-add or approximate reciprocals are not
  assumed. The numerical transformation remains the original two-pass algorithm.

The `resident` profiles enable only intermediate SRAM. `stream` adds the
head-row and register-pipeline changes. `small_tiles` also quarters each weight
bank to test the transfer-size tradeoff. `stream256` keeps the original weight
bank capacity and expands from 128 vector/32 SFU lanes to 256 vector/64 SFU
lanes. This is an explicit hardware resource increase; neither MAC count nor
core/HBM frequency increases. Register storage is reported separately from
staging SRAM. FPGA synthesis and timing closure remain outstanding.

### Optimized verification and reproduction

`test_decode_optimizations.py` replays every relocated access in the three-step
F2 graph using arbitrary byte values, checking each read against independent
logical storage. It also checks uninitialized/DMA users are excluded, verifies
native parallel-head schedules for ragged rows/columns, and checks streaming
resource costs. The numerical validator checks the complete real model for each
selected profile; the allocator changes only storage, with its separate byte
preservation checks applying to arbitrary numerical values.

```sh
HERE=experiments/gemma3_1b_int8/hbm2/full_model
env -u PYTHONPATH .venv/bin/python "$HERE/run_partition_study.py" decode_asic_resident decode_asic_stream decode_asic_small_tiles decode_asic_stream256 decode_f2_resident decode_f2_stream decode_f2_small_tiles decode_f2_stream256 --workers 3
for profile in decode_asic_resident decode_asic_stream decode_asic_small_tiles decode_asic_stream256 decode_f2_resident decode_f2_stream decode_f2_small_tiles decode_f2_stream256
do
  env -u PYTHONPATH .venv/bin/python "$HERE/test_timing.py" --run-dir "$HERE/build/$profile"
done
env -u PYTHONPATH .venv/bin/python "$HERE/validate_decode_fusion.py" --config "$HERE/configs/decode_asic_stream256.json" --out "$HERE/build/optimized_asic_validation.json"
env -u PYTHONPATH .venv/bin/python "$HERE/validate_decode_fusion.py" --config "$HERE/configs/decode_f2_stream256.json" --out "$HERE/build/optimized_f2_validation.json"
env -u PYTHONPATH .venv/bin/python "$HERE/summarize_optimization_study.py"
```

The final verifier checks run inputs, native timing output, source/binary hashes,
SRAM capacity, numerical evidence for the selected configurations, and that every
measured token clears its platform's target. It retains `optimized_decode_study.json`.
Earlier sections below document the preceding revisions and their measurements.

## Parallel arrays for ASIC and F2 inference

The partition study adds independent output-stationary arrays that consume
separate output-column slices of the same activation. `array_cols` is the
physical width of each array; `array_partitions` multiplies the number of arrays.
The group completes at the maximum of its constituent native SCALE-Sim schedules.
It does not pay the fill/drain latency of one equally wide systolic array.
Partial INT32 sums persist across balanced K tiles. Prepacked weights and tied
embedding gathers use the aggregate output width.

Two finite weight banks overlap native HBM reads with array work. The optimized
profiles use 128 FP32 vector lanes, 32 SFU lanes, 512 KiB shared activation/partial
sum/vector scratch, a shared 2,048-request window, and 128-read/64-write controller
queues. All requests still share the original 16-admissions-per-DRAM-tick limit.
The new bijective address layout interleaves pseudochannels and bank groups ahead
of column addresses, preserving every data byte and the full memory capacity.
These changes apply to the architectural simulator; they do not create an FPGA
bitstream or modify the separate sample RTL datapath.

Completed native Ramulator2 measurements for batch-one Gemma3-1B decode at
contexts 513–515 (three tokens, same numerical trace):

| Profile | Core | Arrays | MACs | SRAM MiB | TPS | Average HBM GB/s |
| --- | ---: | --- | ---: | ---: | ---: | ---: |
| `decode_4arrays_only` | 1000 MHz | 4 × 1×256 | 1,024 | 2.125 | **120.82** | 126.09 |
| `decode_asic_4arrays` | 1000 MHz | 4 × 1×256 | 1,024 | 2.5 | **260.37** | 271.72 |
| `decode_asic_8arrays` | 1000 MHz | 8 × 1×256 | 2,048 | 4.5 | **276.77** | 288.83 |
| `decode_asic_32x64` | 1000 MHz | 32 × 1×64 | 2,048 | 4.5 | **284.32** | 296.71 |
| `decode_f2_4arrays` | 250 MHz | 4 × 1×256 | 1,024 | 2.5 | **104.74** | 109.30 |
| `decode_f2_8arrays` | 250 MHz | 8 × 1×256 | 2,048 | 4.5 | **149.53** | 156.04 |
| `decode_f2_16arrays` | 250 MHz | 16 × 1×256 | 4,096 | 8.5 | **160.35** | 167.33 |
| `decode_f2_64x64` | 250 MHz | 64 × 1×64 | 4,096 | 8.5 | **173.55** | 181.12 |

The arrays-only case retains the original vector/SFU resources and memory
mapping/window, while increasing weight-bank capacity to feed four arrays.
The other profiles include the memory and vector changes described above.
Smaller 64-column arrays improve the ASIC result from 276.77 to 284.32 TPS
at 2,048 MACs and improve the F2 result from 160.35 to 173.55 TPS at 4,096
MACs. **Neither target reaches 400 TPS.**

`decode_asic_32x64` spends 1.235 ms/token in modeled compute and 2.282 ms/token in exposed memory waits. Its GEMMs take 2.828 ms and V-cache conversion takes 0.330 ms.

`decode_f2_64x64` spends 4.081 ms/token in modeled compute and 1.681 ms/token in exposed memory waits. Its GEMMs take 3.933 ms and V-cache conversion takes 1.195 ms.

The retained [study evidence](partitioned_decode_study.json) includes all eight
configurations, stage timings, physical traffic, verified run hashes and both
real-checkpoint correctness reports. All 16 architecture/configuration tests
and 154 native timing checks passed. Each real-checkpoint layout check passed
1,173 GEMM comparisons, 104 cache checks, and every logit for all three decode
steps, plus prefill.


### What remains for 400 tokens/s

400 TPS allows 2.5 ms per token. The unchanged W8A8/KV8 graph moves about
1.0436 GB per token, requiring 417.4 GB/s averaged over the entire decode.
The completed streaming transport benchmark sustains 412.1 GB/s with the new
layout and request window, versus 195.6 GB/s with the original mapping. This is
89.4% of nominal peak for a long read stream; it is neither a model-decode result
nor a universal bandwidth ceiling. Short transfers, writes and dependent work
lower the full-model average further.

Further work should first retain vector intermediates in SRAM and fuse producer/
consumer operations, then prefetch the next independent weight tile across
operator boundaries with explicit buffer ownership. The F2 profile also needs
more effective attention/vector throughput: idle partitions could process
separate attention heads, and the V-cache conversion needs a faster verified
FP32 pipeline. None of those improvements is included in the measured results.
If traffic still exceeds the usable bandwidth budget, measure lossless INT8
weight compression or use more memory bandwidth. INT4 would change the numerical
baseline and require a new accuracy evaluation. Multi-request batching could
increase aggregate TPS but would not establish 400 TPS for one sequence.

### F2 clock and memory contract

The F2 profiles run arrays, vector operations and dispatch at **250 MHz**. The
HBM AXI interface remains **450 MHz**, with the pinned F2-derived 900 MHz DRAM
clock / 1,800 Mbps data rate. These are distinct clock domains. AWS documents
this combination and all 32 HBM interfaces in its
[CL_MEM_PERF reference](https://github.com/aws/aws-fpga/blob/f2/hdk/cl/examples/cl_mem_perf/README.md).
The resulting nominal aggregate peak is **460.8 GB/s**. The simulator does not
scale the HBM bandwidth down when reducing the core clock to 250 MHz.

The 64-array F2 candidate contains 64 independent 1x64 INT8 arrays, or 4,096 MACs.
Its two 4 MiB weight banks plus 512 KiB scratch total **8.5 MiB staging SRAM**.
It assumes banked operand reads of 4,096 bytes/core cycle in aggregate; the
vector scratch budget is 512 bytes/core cycle. At 250 MHz these correspond to
1,024 GB/s and 128 GB/s of local bandwidth respectively. The three-step graph
allocates 1,050,053,188 bytes of HBM address space, including parameters, KV,
scales and intermediates, within the 16 GiB modeled capacity. This is the
allocator footprint for this workload, not a long-context memory estimate.

For an actual F2 implementation, each array needs local SRAM banking, activation
broadcast and INT32 accumulation; a multiport DMA must fill those banks through
clock-domain crossings from the HBM interfaces. The current aggregate frontend
assumes those resources. The 128 FP32 lanes and 32 pipelined SFU lanes also need
resource accounting. Synthesis, placement, routing and hardware HBM measurements
are required before claiming these profiles fit or meet 250/450 MHz. Host I/O,
accelerator prefill/TTFT and end-to-end serving latency remain outside this study.

### Correctness and reproduction

`test_array_partitions.py` compares parallel-group durations with native array
schedules, checks all three packed/attention layouts against independent INT64
products, verifies the compiled address permutation is reversible, and tests
ragged four-row attention stores. Contiguous outputs that share a 32-byte line
are coalesced before submission, retaining the native write-recovery guard.
`test_timing.py` checks every workload tile shape, group critical path and both
clock domains for each measured configuration.

`validate_decode_fusion.py` runs the real checkpoint through the generated tile
addresses. Both the 32x64 ASIC layout and 64x64 F2 layout must preserve every
INT32 GEMM and all saved logits exactly against the existing W8A8/KV8 numerical
baseline. This does not claim equivalence to unquantized FP32 model outputs.
The numerical and timing executions remain separate matched graphs.

From the repository root, after the existing numerical checkpoint run:

```sh
HERE=experiments/gemma3_1b_int8/hbm2/full_model
env -u PYTHONPATH .venv/bin/python "$HERE/run_partition_study.py" --workers 3
for profile in decode_4arrays_only decode_asic_4arrays decode_asic_8arrays decode_asic_32x64 decode_f2_4arrays decode_f2_8arrays decode_f2_16arrays decode_f2_64x64
do
  env -u PYTHONPATH .venv/bin/python "$HERE/test_timing.py" --run-dir "$HERE/build/$profile"
done
env -u PYTHONPATH .venv/bin/python "$HERE/test_array_partitions.py"
env -u PYTHONPATH .venv/bin/python "$HERE/benchmark_bandwidth.py" --skip-build
env -u PYTHONPATH .venv/bin/python "$HERE/validate_decode_fusion.py" --config "$HERE/configs/decode_asic_32x64.json" --out "$HERE/build/partitioned_numerical_validation.json"
env -u PYTHONPATH .venv/bin/python "$HERE/validate_decode_fusion.py" --config "$HERE/configs/decode_f2_64x64.json" --out "$HERE/build/f2_partitioned_numerical_validation.json"
env -u PYTHONPATH .venv/bin/python "$HERE/summarize_partition_study.py"
```

The summary verifies completed-run input, timing and current source hashes before
retaining `partitioned_decode_study.json`. Earlier 112-TPS reports below remain
historical measurements of the preceding architecture revision.

## Decode-focused architecture: 112.38 simulated tokens/s

`configs/decode_100tps.json` reaches **112.3817 decode tokens/s**, averaging
**8.8982 ms/token** over contexts 513–515. Individual steps are 112.3756,
112.4007 and 112.3689 TPS. This is a completed native Ramulator2 run, not the
previous analytical projection. It is **2.6988x** the 41.6419 TPS configuration.
The core clock, numerical token trace, HBM2 configuration, 512-request window
and 16-request-per-DRAM-tick admission limit are unchanged.

| Measured configuration | TPS | Compute ms/token | Exposed memory wait ms/token |
| --- | ---: | ---: | ---: |
| Previous 256x256 WS, 128 vector lanes | 41.6419 | 13.5693 | 10.4450 |
| 1x256 OS, 32 vector lanes, balanced tiles | 56.4884 | 7.1275 | 10.5753 |
| OS plus callback-gated double buffering | 79.3113 | 7.1275 | 5.4811 |
| OS plus double buffering and V-cache fusion | **112.3817** | **7.5930** | **1.3052** |

The new design uses **256 MACs**, **32 FP32 vector lanes**, **four SFU lanes**
and **640 KiB staging SRAM**. Compared with the previous fast configuration,
that is 256x fewer MACs, four times fewer vector lanes, and the same SRAM size.
These counts are architectural assumptions; SRAM port width and SFU area are
not included in a synthesized resource or timing-closure estimate.

The implementation adds three explicit configuration switches and OS dataflow:

- `dataflow: "os"` selects native output-stationary demand schedules. Each
  staged K tile pays its complete fill/drain schedule. INT32 partial sums
  persist across K tiles; all input elements and outputs are accounted for.
- `balance_k_tiles: true` balances K chunks within the configured capacity.
  For example, K=1152 uses 576+576 instead of 1024+128. The latter left the
  short compute tile unable to hide the following large weight fetch; an
  initial unbalanced fused run reached only 90.9104 TPS.
- `gemm_prefetch: true` reuses the former A/B banks as two 256 KiB weight
  banks. A and INT32 partials occupy the 128 KiB shared scratch. The graph
  checks live capacity. `P0/P1` queue reads, `J` waits for actual callbacks,
  and `F` releases a consumed bank. Foreground stores and both banks share
  one admission budget and one outstanding-request window. Write recovery,
  refresh, rejected admissions and operator-boundary drains remain modeled.
- `fuse_value_cache: true` computes feature maxima/scales and requantizes V
  in two bounded streaming passes. It preserves the original FP32
  dequantization, per-feature scaling and round-to-even semantics. FP32 V
  and both transpose intermediates stay off HBM; final INT8 V and scales
  are still written to HBM. The model charges scratch bandwidth and
  four-lane FP32 division throughput, so fusion **increases** modeled
  compute time while reducing exposed memory waits.

The two operand banks assume 256-byte array reads per core cycle and a
512-byte DMA fill port per DRAM tick. Fused vector scratch is limited to
128 bytes/core cycle (32 lanes x 4 bytes). These are explicit hardware port
assumptions, not measurements of the existing RTL DMA. No asynchronous work
crosses an operator's lifetime. Operators still execute in dependency order.
Long contexts that cannot retain A and partials in scratch are rejected;
this profile does not implement general long-context attention tiling.

The completed run contains 3,228 physical operations covering the same logical
decode computation, 123,783 commands, 97,836,267 memory callbacks and
26,694,736 core cycles. Physical HBM traffic falls from 1,116,987,637 to
1,043,586,848 bytes/token. The previous default remains available as
`configs/fast_decode.json`; select the new architecture explicitly.

### Reproduce the architecture study

From the repository root, with the existing Python environment and pinned
Ramulator dependency:

```sh
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/run.py --config experiments/gemma3_1b_int8/hbm2/full_model/configs/decode_100tps.json
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/test_timing.py --run-dir experiments/gemma3_1b_int8/hbm2/full_model/build/decode_100tps
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/test_decode_architecture.py
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/validate_decode_fusion.py
```

Use `configs/decode_os.json` and `configs/decode_overlap.json` with `run.py`
to reproduce the two intermediate stages. Run `test_timing.py --run-dir`
for each stage, then `summarize_decode_study.py` to verify input/source hashes,
correctness reports and the >100 TPS threshold. It retains
[`decode_100tps_result.json`](decode_100tps_result.json) and
[`decode_100tps_study.json`](decode_100tps_study.json).

`test_decode_architecture.py` checks bounded scratch, all three physical
weight layouts, partial K/N tiles, independent INT64 arithmetic, and native
OS wavefront arithmetic for single-row and four-head matrices. Native DMA
tests check overlap, real callback waits, bank reuse, write recovery and
invalid lifetimes. The old baseline command stream remains byte-for-byte
identical. `validate_decode_fusion.py` executes the fused numerical operation
on the real checkpoint and routes every decode GEMM through the generated
tile addresses, checking each INT32 result and all saved logits exactly.

These correctness checks establish numerical and schedule contracts separately.
Ramulator transports timing requests; it does not execute a data-carrying
full-transformer RTL datapath. The TPS measurement covers batch-one cached
decode on this three-step workload, excluding prefill/TTFT and host IO.

## Configurations and measurements

The completed default run reports **41.6419 decode tokens/s**, or
**24.0142 ms/token**, over the same three cached decode steps at contexts
513–515 after a 512-token prompt. This is **4.6338x** the original 8.9865 TPS.
Individual steps reached 41.6336, 41.6359 and 41.6563 TPS. The result is saved
in `build/fast_decode/result.json`, with a retained copy in
[`fast_decode_result.json`](fast_decode_result.json).

| Measurement | Original 32x32 | Default fast decode |
| --- | ---: | ---: |
| Decode tokens/s | 8.9865 | 41.6419 |
| Total ms/token | 111.2776 | 24.0142 |
| Compute ms/token | 94.7512 | 13.5693 |
| Memory wait ms/token | 16.5264 | 10.4450 |
| Assumed core clock | 1 GHz | 1 GHz |

The native run completed all 3,462 operators, 482,253 commands and
104,717,591 memory callbacks over 64,844,950 DRAM ticks. The dependent
schedule took 72,042,740 core cycles. All 17 configured timing checks and
three configuration regression checks passed. The original operator sequence,
705 GEMM shapes and logical GEMM read/write byte counts are preserved; the
numerical trace and HBM2 configuration hashes match the baseline. Regenerating
the baseline configuration produces its original 808,197 commands byte for byte.

The default timing configuration is `configs/fast_decode.json`. It uses a
256x256 WS array, separate 256 KiB A/B buffers, 128 FP32 vector lanes and a
128 KiB vector buffer. The assumed core clock remains 1 GHz, with the same
four SFU lanes, HBM2 profile, memory admission limits and serial dependency
policy. This is a larger simulated accelerator: 65,536 MAC units versus the
baseline's 1,024, and 640 KiB of operand/vector staging versus 96 KiB.
These resource counts do not establish FPGA fit or timing closure.

`run.py` now accepts an architecture JSON via `--config`. Its resolved values
are saved in `configuration.json`, `manifest.json` and `result.json`. Array
dimensions control the native WS schedules, packed weight layout, tied embedding
gather and SRAM tile sizes. K chunks end on array-row boundaries so splitting
a matrix does not silently remove or add partial compute folds. Every
transformer operator and the original real-weight token trace remain included.

The original configuration is retained as `configs/baseline_32x32.json`.

The original saved run in `build/full_1ghz/result.json` reports **8.9865 decode tokens/s**
or **111.2776 ms/token**, averaging three cached decode steps at contexts 513–515.
It includes the non-GEMM operations under the explicit architecture assumptions
below. Native Ramulator completed 104,719,475 memory callbacks over 300,479,515
DRAM ticks; the dependent schedule took 333,832,742 core cycles in total.

The separate real-weight numerical execution generated `The sky looks blue`.
The FP32 implementation matched Hugging Face exactly for the saved 512-token
prefill and one cached decode step. INT8 quantization changes logits and can
change greedy tokens; this is not an accuracy evaluation. All eight numerical
checks and thirteen original timing checks passed. Simulated prefill/TTFT and
full-model RTL cycle equivalence remain outside these results.

## Reproduce

From the SCALE-Sim repository root:

```sh
env -u PYTHONPATH .venv/bin/python -m pip install -r experiments/gemma3_1b_int8/hbm2/full_model/requirements.txt
# The existing pinned native HBM2 setup is required:
bash experiments/gemma3_1b_int8/hbm2/setup_ramulator2.sh

env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/test_numerical.py
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/run_numerical.py --prompt-tokens 512 --decode-steps 3
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/test_configuration.py
# Uses configs/fast_decode.json and saves results under build/fast_decode:
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/run.py
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/test_timing.py
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/validate_checkpoint.py

# Reproduce the baseline separately, preserving its original saved result:
env -u PYTHONPATH .venv/bin/python experiments/gemma3_1b_int8/hbm2/full_model/run.py --config experiments/gemma3_1b_int8/hbm2/full_model/configs/baseline_32x32.json
```

`run_numerical.py --checkpoint PATH` selects a **BF16/FP32 Hugging Face checkpoint**
to quantize. The default is the complete local snapshot at revision
`dcc83ea841ab6100d6b47a070329e1ba4cf78752`. The loader uses local files only. It
never replaces missing trained weights with random values. Externally quantized
checkpoint formats need their own format-specific loader; this is our explicit
post-training quantization scheme, not RedHatAI's calibrated checkpoint.

`run.py --numerical PATH/result.json --out PATH` selects a numerical run and
output directory. `--prepare-only` writes and validates the complete command
stream without running memory simulation. `--summarize-only` verifies and
summarizes an already-completed native run, using its recorded configuration.
It rejects a different clock/configuration, changed input artifacts or changed
timing output. `--core-hz` overrides the assumed clock for a new simulation.
`test_timing.py --run-dir PATH` validates every distinct tile shape actually
used by that run against SCALE-Sim's native demand generator.

## Numerical execution

`numerical.py` implements all 26 decoder layers, tied embedding/head weights,
Q/K normalization, local/global RoPE, five-local/one-global attention, KV writes
and reads, stable masked softmax, gated tanh-GELU MLPs, all four block RMSNorms,
residual additions, final normalization and greedy token selection.

- Weights: symmetric INT8, scale per output channel.
- Linear activations: dynamic symmetric INT8, scale per input row.
- GEMMs: **exact INT8 inputs / INT32 accumulation** through `torch._int_mm`.
- KV cache: INT8 with a separate scale for each token/head.
- QK: query and key scales applied to INT32 products.
- AV: cached V is dequantized and requantized per output feature before its
  INT8 product. Per-token V scales cannot simply be applied after the dot product,
  because they vary along the reduction dimension.
- Norms, RoPE, masking, softmax, GELU, residuals and scale arithmetic: FP32.
- Generation: greedy argmax. No stochastic top-k/top-p sampler is enabled.

There is no learned quantization calibration. V feature scales depend on the
available prompt block, so prefill chunking can affect quantization. The checks
report differences from FP32, not bitwise equality to the original model or
model-wide accuracy guarantees.

The real run numerically prefills 512 tokens, then executes three cached decode
steps at contexts 513–515. The first generated token comes from prefill; the
three decode steps produce the next three. The prompt, actual token IDs, logits,
operator trace, checkpoint hash and FP32 comparison are saved. CPU wall-clock
measurements are explicitly separate from simulated accelerator time.

## Timing and memory contract

SCALE-Sim's bundled GPT/Llama topologies describe GEMMs. Its native Ramulator
example uses trace generation, memory replay and a second simulator pass.
`code-examples/systolic-array-rtl` supplies sample arithmetic RTL without control
logic. Those examples do not supply a complete non-GEMM decoder executor.

This extension uses their WS scheduling convention, with native-demand validation
for the tile shapes, and adds an explicit operator/traffic scheduler:

| Component | Modeled implementation |
|---|---|
| Array | Configured WS array; baseline 32x32, default 256x256; assumed 1 GHz |
| Vector unit | Baseline 32 / default 128 FP32 lanes; assumed one elementwise instruction/lane/clock |
| Special functions | Four pipelined lanes, issue interval 1; exp/tanh latency 12, sin/cos and rsqrt 16, reciprocal 8 clocks |
| Dispatch | Four core clocks per operator |
| Operand staging | Separate A/B buffers, baseline 32 KiB / default 256 KiB each; A retained across output tiles |
| Vector staging | Baseline 32 KiB / default 128 KiB across live input/output chunks; reductions use scalar state |
| Partial sums | Retained locally across K chunks for one output tile |
| Memory | Real pinned Ramulator2 HBM2, F2-derived 16 GiB / 16 physical channels |
| Frontend | Aggregate 16 admissions/DRAM tick, finite 512 in-flight requests |
| Scheduling | Serial dependent operations; serial tile load, compute and store |
| Intermediates | HBM-resident FP32 tensors, INT8 tensors, scales, KV and layout conversions |

Weights are prepacked into array-column-width tiles. The embedding gathers actual
token rows from the same tied storage. Attention uses strided reads/transposes,
not a minimum weight/KV byte count substituted for real requests. Identical input
quantizations for Q/K/V and gate/up are shared. Four attention heads are fused
as M=4 GEMMs, preserving their numerical products. Every matrix shape is checked
against the executed numerical operator trace.

Every native DRAM clock is stepped, including refresh during compute. There is
no idle-time fast-forward or fixed-bandwidth replacement. A dependent phase
starts only after its actual callbacks complete; writes also wait
`nCWL+nBL+nWR`. The program has no source timestamps fixed before memory delays.
Byte-enabled partial writes are assumed, without ECC read-modify-write traffic.

The vector/SFU costs and 1 GHz frequency are **architecture assumptions**. The
array durations come from native-validated WS schedules with staged operands;
this is not the existing RTL's clocked-SRAM/byte-unpacking policy. The aggregate
frontend is also different from that RTL's single AXI master. Neither full RTL
cycle equivalence nor AMD F2 controller/PHY equivalence is claimed.

The measurement covers device-side cached decode. Tokenization and host I/O are
outside the accelerator timing model. Numerical prefill is executed, but its
accelerator timing is not simulated here, so this run does not establish TTFT.
Softcapping is disabled in the actual 1B config, inference dropout is disabled,
training loss and vision are inapplicable, and contiguous views/GQA sharing need
no physical copies. These cases are listed in the manifest rather than silently
charged as GEMMs or omitted.

## Artifacts and checks

- `build/numerical_512/result.json`: checkpoint identity, generated text/token
  IDs, numerical scheme, host timing, FP32 comparisons and source hashes.
- `build/numerical_512/operator_trace.json`: executed numerical operations.
- `build/full_1ghz/result.json`: simulated decode throughput and category totals.
- `build/fast_decode/result.json`: throughput and category totals for the default
  larger array/vector configuration.
- `fast_decode_result.json`: retained copy of that completed result outside the
  ignored build directory.
- `build/fast_decode/configuration.json`: resolved architecture inputs.
- `build/fast_decode/execution.json`: completion status and hashes of run inputs
  and the native timing output.
- `build/fast_decode/timing_tests.json`: native tile, operator coverage and HBM
  timing validation for the configured run.
- `build/full_1ghz/manifest.json`: every timed operator, tensor address and cost.
- `build/full_1ghz/commands.txt`: dependency-ordered compute and memory commands.
- `build/full_1ghz/timing.csv`: native per-operator start/end clocks, transactions
  and admission retries; `operations.json` adds names and memory wait cycles.
- `build/numerical_tests.json`: exact integer checks and independent Hugging Face
  checks of prefill/cached decoding, local masks and global layers.
- `build/checkpoint_validation.json`: full real-weight FP32 comparison with
  Hugging Face on the 512-token prompt and a cached decode step.
- `build/timing_tests.json`: native WS tile schedules, executed matrix shapes,
  read/write completion checks against the existing live bridge, and clock phase.

The memory run persists HBM state across all layers and all three decode steps.
This small sample is a measured simulator run for one prompt and one specified
architecture, not an average over 127 decode steps or a general quality benchmark.
