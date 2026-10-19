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
