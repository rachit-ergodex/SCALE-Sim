# F2 platform integration reference

The implementation target remains the simulator's `decode_f2_stream256` profile:
64 independent 1×64 INT8 arrays, a 250 MHz core target, 32 HBM AXI3 ports at
450 MHz, and 16 GiB of HBM. Alex's burst200 source is a reference for platform
integration; it does not replace these architecture parameters.

## Official AWS F2 reference

The requested AWS `cl_dram_hbm_dma` source and the all-port `cl_mem_perf`
reference are pinned and audited in [AWS_HBM_INTEGRATION.md](AWS_HBM_INTEGRATION.md)
and [aws_reference.json](aws_reference.json). Use the performance example
`cl_mem_hbm_wrapper` for our 32-port datapath; its port mapping and clock/reset
contract differ from the DMA example wrapper.

## Verified OpenTPU reference

The supplied archive is
`s3://ergodex-bonsai-on-chip-438374459156-us-east-1/opentpu-alex/alex-burst200-branch.tar`.
Its SHA-256 is
`fdd38e2be3e87fe80d73b9af111911c2d26f8a699b767dfc37b62b8c5a1505dc`.
All 850 tracked files were compared byte-for-byte with an isolated checkout of
openTPU commit `06c169cbcd1721ae8b167de992a93461697a397d`. The reference's 16
seeded native-to-AXI adapter trials also passed locally. See `reference.json`.

The archive contains source, not a bitstream or checkpoint. Its README records
the historical image `agfi-0d06cb48544a02106` and final DCP SHA-256
`0f600fd7fecd2028a6db7767d1de5a2230e62c265baa545b749866b9e9ff15ed`.
Those identify the documented experiment; no image was loaded or requalified
as part of this source audit.

Useful reference components:

| Reference path | What it informs |
| --- | --- |
| `rtl/boards/f2/cl_opentpu.sv` | Small Shell port wiring, OCL/PCIS separation, calibration and reset synchronization |
| `rtl/boards/f2/otpu_native_axi.sv` | Bounded read coalescing, 4 KiB boundaries, response credits, direction barriers, RLAST checks |
| `rtl/boards/f2/otpu_hbm_geometry.sv` | 32-byte HBM address alignment while preserving byte strobes |
| `boards/f2/scripts/create_f2_ip.tcl` | Private HBM IP generation, SmartConnect AXI4/AXI3 conversion, CDC and address apertures |
| `boards/f2/constraints/` | Legal shell floorplan and platform timing constraints |
| `opentpu/host/f2_transport.py`, `f2_mmio.c` | OCL BAR0 control and PCIS BAR4 transfers on Small Shell |
| `boards/f2/scripts/{implement,refine_route,audit_route}.tcl` | Full-shell implementation and report collection |

## Differences that must remain explicit

- Burst200 has a 200 MHz core, related 400 MHz TMEM clock and two 512-bit native
  channels feeding HBM ports 0 and 4. It exposes two 2-GiB windows. Its measured
  bandwidth and timing do not qualify a 250 MHz, 32-port design.
- The new design needs enough independently serviced HBM streams to use all
  32 ports. Reusing a two-port data path would invalidate the throughput goal.
- `decode_hbm_map.sv` mirrors the native Ramulator address permutation. It is
  **not** the AMD HBM AXI address map. Hardware needs an explicit logical-address
  to port/AXI-address mapping, a matching host loader, and inverse/readback tests.
  The native simulator itself documents this distinction in `f2_config.py`.
- OpenTPU uses INT48/block-scaled arithmetic and its own FP32 contract, including
  flush-to-zero and fixed approximation sequences. The current simulator's
  INT32 W8A8 and PyTorch FP32 reference must not silently adopt those semantics.
- The new design must verify SRAM bank conflicts, outstanding-request limits,
  AXI error/ordering behavior, CDC, and reset recovery with actual RTL. Vendor
  memory-fabric simulation and full-shell timing are subsequent checks.

The AWS reference [F2 HDK guide](https://github.com/aws/aws-fpga/blob/f2/User_Guide_AWS_EC2_FPGA_Development_Kit.md)
and [HBM example](https://github.com/aws/aws-fpga/blob/f2/hdk/cl/examples/cl_dram_hbm_dma/README.md)
describe Small Shell integration and the 32-port AXI3 interface. The pinned
burst200 sources provide concrete implementation examples, while the new RTL
and its numerical model remain separately versioned in this repository.

## Implemented 32-port read frontend

`rtl/decode_hbm_read32.sv` instantiates 32 independent
`decode_hbm_read_port` frontends. Every frontend has 64 unique six-bit AXI IDs,
64 destination tags, explicit allocated/issued state, and a registered AR
channel. Requests and responses never arbitrate through a single shared port.
The 2,048 aggregate slots include accepted requests awaiting AR handshake.

All signals in this component use the HBM AXI clock domain. Each request reads
one 32-byte aligned line (`ARLEN=0`, `ARSIZE=5`, `ARBURST=INCR`). Port p accesses
its 512-MiB aperture at `(p << 29) | (local_line << 5)`. An upstream address
mapper and host loader must use this same physical layout. This component does
not apply the simulator's Ramulator-specific permutation.

Return data is delivered with the original destination tag, even when IDs
return out of order. Backpressure propagates independently to each R channel.
A consumed response error, missing RLAST or unknown ID sets a sticky fault only
on that port. RREADY depends only on reset and downstream capacity, with no
combinational path from AXI input signals. An unknown response waits for
capacity before being discarded; new ID allocation stops while it is pending.
A response sampled as unknown stays quarantined until consumed, even if its
AR later handshakes. It never retires a legitimate request. New requests stop on the faulted port; outstanding valid responses can
still drain. Reset must reset/drain the connected AXI fabric too, so old
responses cannot be confused with reused IDs. HBM calibration gates acceptance
through `enable`; deasserting it does not cancel an already presented AR.

Tag storage plus allocation/issued bitmaps consumes 8.5 KiB across the 32 ports,
with additional small AR/control registers. This is bookkeeping storage beyond
the simulator's staging-SRAM budget. The read CDC FIFOs below and write channels still
need system integration; this frontend alone is not a complete memory subsystem.

```sh
env -u PYTHONPATH src_rtl/build/decode_venv/bin/python src_rtl/decode/tests/run_hbm_read32.py
```

The Verilator/cocotb test checks 13,312 reads. It exercises all 32 ports
simultaneously for 256 consecutive response cycles against an ideal AXI target,
fills all 2,048 slots under stalled returns, then checks random AR/consumer
stalls, out-of-order IDs, aperture-end addresses and fault isolation. The
retained `hbm_read_verification.json` binds the tested source hashes.
The ideal-target result establishes frontend issue/return capacity, not actual
HBM bandwidth, PHY behavior, clock closure or CDC throughput.

## Implemented core/HBM read clock crossings

`decode_hbm_read_bridge32.sv` connects 32 independent core-side descriptor and
return interfaces to the 32 HBM read ports. Each descriptor specifies a local
32-byte line address, a four-bit length minus one (1–16 reads), and a base tag.
The bridge increments both line and tag, issues single-beat AXI reads, and
rejects descriptors that cross the port's 512-MiB aperture. Tag arithmetic wraps
at `TAG_WIDTH`; the issuer must avoid ambiguous live destination tags.
Wire `ARLEN=0`, `ARSIZE=5`, `ARBURST=INCR` at the platform boundary.

Return packing is configurable with `RETURN_RECORDS`. The default of two tagged
256-bit records preserves the 250 MHz interface: **512 GB/s aggregate capacity**.
For the **200 MHz target, set `RETURN_RECORDS=3`**. This permits 96 bytes per
port per core cycle, or **614.4 GB/s aggregate capacity**, above the **460.8 GB/s**
32-byte × 32-port × 450 MHz HBM interface peak. Two records at 200 MHz would cap
returns at 409.6 GB/s. Each packet has one validity bit per record; partial
packets flush when the HBM input becomes idle. Downstream SRAM banks must accept
the resulting packets to sustain this rate.

`decode_async_fifo.sv` uses Gray pointers, two-stage synchronizers marked
`ASYNC_REG`, dual-clock memory, and a registered read-prefetch slot. With depth
16, descriptor/return FIFO memories total **40 KiB** across 32 ports for two
records or **58.125 KiB** for three, plus read-prefetch, packet and pointer
registers. This is in addition to the frontends' 8.5 KiB of tag/ID bookkeeping
and the compute staging SRAM.
Both clock domains and the external AXI fabric must reset together; synchronize
reset deassertion separately in each domain. `outstanding` remains in the HBM
clock domain; use synchronized snapshots for core-side telemetry. Sticky faults
are synchronized to the core and require coordinated reset for recovery.

```sh
env -u PYTHONPATH src_rtl/build/decode_venv/bin/python src_rtl/decode/tests/run_hbm_bridge.py
```

Verilator/cocotb tests use 4,000 ps and 5,000 ps core periods with a 2,222 ps
HBM period and multiple relative phases. The 200 MHz three-record test checks
65,536 reads across 32 ports with 2,048 consecutive HBM response cycles; a
two-record negative control at 200 MHz exposes the expected return bottleneck. They check descriptor expansion, continuous ideal
AR issue across descriptor boundaries, out-of-order returns, tag/data integrity,
backpressure stability, prolonged stalls, and reset during active traffic for
both a single port and all 32 ports. Generic synthesis retains the asynchronous
FIFO memory and synchronizer attributes and checks all 32 bridge instances.
`hbm_bridge_verification.json` records the tested source hashes.
These are digital functional checks. Board-specific Gray-bus skew/max-delay
constraints, synchronizer placement, reset checks, vendor HBM simulation and
full-shell timing closure remain required before hardware use. This is not a
measured HBM bandwidth result or a complete inference RTL implementation.

See [SYNTHESIS_READINESS.md](SYNTHESIS_READINESS.md) for the current functional
verification gate and the distinction between component and full-board synthesis.

## 200 MHz physical implementation

The [Vivado component flow](scripts/README.md) targets the full 4,096-MAC compute
core at 200 MHz and saves synthesis, placement and routing checkpoints. The
historical 250 MHz simulator profile and TPS evidence retain their original
clock. The 200 MHz target is a new physical experiment, not a relabeling of that
performance result.

Alex's burst200 source is used for separate compute/HBM clocks, reproducible
checkpointing and routed timing reports. Its two-port native return limit also
motivates the three-record change above. Its 16-beat AXI bursts demonstrate a
further opportunity: our current read descriptors still expand to single-beat
transactions, so interface capacity is not a measurement of real HBM bandwidth.
