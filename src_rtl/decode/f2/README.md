# F2 platform integration reference

The implementation target remains the simulator's `decode_f2_stream256` profile:
64 independent 1×64 INT8 arrays, a 250 MHz core target, 32 HBM AXI3 ports at
450 MHz, and 16 GiB of HBM. Alex's burst200 source is a reference for platform
integration; it does not replace these architecture parameters.

## Verified reference

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
A response error, missing RLAST or unknown ID sets a sticky fault only on that
port. New requests stop on the faulted port; outstanding valid responses can
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

Each return carries up to two independent tagged 256-bit records with a valid
mask (`01` or `11`). This permits 64 bytes per port per 250 MHz core cycle:
**512 GB/s aggregate interface capacity**, above the **460.8 GB/s** aggregate
32-byte × 32-port × 450 MHz HBM interface capacity. Data placement must sustain
this rate in the downstream SRAM banks. Descriptor expansion avoids a new
core-domain request for every HBM cycle. Sparse single returns flush without
waiting indefinitely for a second record.

`decode_async_fifo.sv` uses Gray pointers, two-stage synchronizers marked
`ASYNC_REG`, dual-clock memory, and a registered read-prefetch slot. The default
16-entry descriptor/return FIFO memories total **40 KiB across 32 ports**, plus
read-prefetch, packet and pointer registers. This is in addition to the read
frontends' 8.5 KiB of tag/ID bookkeeping and the compute staging SRAM.
Both clock domains and the external AXI fabric must reset together; synchronize
reset deassertion separately in each domain. `outstanding` remains in the HBM
clock domain; use synchronized snapshots for core-side telemetry. Sticky faults
are synchronized to the core and require coordinated reset for recovery.

```sh
env -u PYTHONPATH src_rtl/build/decode_venv/bin/python src_rtl/decode/tests/run_hbm_bridge.py
```

Verilator/cocotb tests use a 4,000 ps core period and a 2,222 ps HBM period with
multiple relative phases. They check descriptor expansion, continuous ideal
AR issue across descriptor boundaries, out-of-order returns, tag/data integrity,
backpressure stability, prolonged stalls, and reset during active traffic for
both a single port and all 32 ports. Generic synthesis retains the asynchronous
FIFO memory and synchronizer attributes and checks all 32 bridge instances.
`hbm_bridge_verification.json` records the tested source hashes.
These are digital functional checks. Board-specific Gray-bus skew/max-delay
constraints, synchronizer placement, reset checks, vendor HBM simulation and
full-shell timing closure remain required before hardware use. This is not a
measured HBM bandwidth result or a complete inference RTL implementation.
