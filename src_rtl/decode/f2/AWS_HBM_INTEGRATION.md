# AWS F2 HBM integration contract

Audited the requested `cl_dram_hbm_dma` example and its full-bandwidth companion
`cl_mem_perf` at AWS commit **`c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82`** (`rc/2.3.5`).
The source-only sparse checkout is at
`/private/tmp/scalesim-aws-fpga-f2-reference`; file hashes are retained in
[aws_reference.json](aws_reference.json). No AWS source was vendored, no HDK/IP
setup scripts were run, and no vendor simulation or FPGA build was performed.
Existing decode RTL and its numerical verification are unchanged by this audit.

## Reference choice

Use [cl_dram_hbm_dma](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_dram_hbm_dma/README.md) for
shell, OCL and PCIS connectivity. Its datapath enables one HBM port, and its
AXI4 converter uses a shared host-width path with fixed IDs. It is not the
32-port accelerator datapath.

Use [cl_mem_perf](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_mem_perf/README.md) and its
[cl_mem_hbm_wrapper](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_mem_perf/design/cl_mem_hbm_wrapper.sv)
for the accelerator-facing connection. Configure:

```systemverilog
.NUM_OF_AXI_PORTS(32), .AXI4_INTERFACE(0), .AXLEN_WIDTH(4)
```

The wrapper's 34-bit addresses, 256-bit data and 6-bit IDs match our
`decode_hbm_read_bridge32`. Each flattened port slice must connect to the
same-index wrapper array element; preserve all ID bits and response status.
Drive `ARLEN=0`, `ARSIZE=5`, `ARBURST=1` for the current single-beat frontend.
The complete design still needs host writes and inference writeback; tying
writes off is only appropriate for a read-only component bench.

## Port and address mapping

| Boundary | Mapping in the pinned source | Integration consequence |
| --- | --- | --- |
| `cl_mem_hbm_wrapper` | Logical port p → physical AXI port p | Use this identity mapping for our 32-port path |
| DMA example `cl_hbm_wrapper` | Logical ports 0–15 → physical 15–0; 16–31 unchanged | This wrapper is not interchangeable with the performance wrapper |
| Native HBM address | Port p aperture starts at `p * 0x20000000` | Our `(p << 29) \| (local_line << 5)` matches |
| Example host PCIS map | HBM starts at `0x10_0000_0000`, size 16 GiB | Host addresses add this base; native HBM addresses do not |
| Performance-example host mux | `MAP_PORT=15` in RTL | Older README text saying port 0 is stale |

The direct address scheme is visible in
[cl_hbm_perf_kernel.sv](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_mem_perf/design/cl_hbm_perf_kernel.sv).
The two wrapper implementations explicitly differ in physical stack mapping.
All 32 ports remain available during decode; do not permanently reserve one
port for the host. The host can access other HBM apertures through the HBM
switch while loading, but decode should keep traffic local to matching ports.
Our Ramulator address permutation is not part of this hardware mapping.

The host/accelerator mux must change ownership only after pending AR/AW/W/R/B
transactions and downstream bridge packets have drained. Merely toggling the
example's kernel-enable mux is not a safe ownership protocol for inference.
Use an explicit load/drain/decode/drain sequence, or an arbiter with separate
transaction ownership. Do not strand host traffic while decode runs: the
shell's PCIS timeout is 8 microseconds. Small Shell does not provide the XDMA
engine assumed by some sample runtime programs; use BAR4/PCIS MMIO or an
implemented DMA path. See the
[shell specification](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/docs/AWS_Shell_Interface_Specification.md).

## Clocks, initialization and reset

The [performance top](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_mem_perf/design/cl_mem_perf.sv)
uses AWS clock generation for the 450 MHz HBM domain, a 250 MHz control/core
domain, and a 100 MHz HBM reference/APB clock. Our bridge accepts active-high
resets; the AWS wrapper uses active-low resets. A common reset intent must
produce synchronized resets for both bridge domains and the memory fabric.

Important details in the wrapper's actual RTL:

- `o_hbm_ready` is in the 250 MHz domain. Synchronize it into the HBM domain
  before using it as our frontend's enable. Gate new decode commands until
  both stacks are initialized. Loss of readiness requires controlled recovery.
- Ready bits are **[2:1]**: poll `(status & 0x6) == 0x6` with reset bit 0
  cleared. The header comment asking for `[3:1] == 111` is stale: bit 3 is zero.
- Software HBM reset drives APB reset, while actual AXI reset is piped from
  external `i_rst_450m_n`. The computed `axi_rst_sync_n` does not drive AXI
  reset. Writing OCL reset alone does not reset descriptors, outstanding IDs
  or return FIFOs. Drain or coordinate reset across the whole path before
  reusing IDs.
- The performance wrapper takes external `i_clk_450m` and `i_rst_450m_n`;
  the DMA wrapper instead generates/exports its HBM clock and reset.

## Shell and physical implementation

Both stacks' HBM monitor APB bundles must reach the shell. Enable
`USER_MON_APB_EN` in the HBM IP and connect the shell's monitor resets directly
to the IP's monitor reset pins, as AWS specifies. These resets are distinct
from normal synchronized datapath resets. Missing monitor wiring prevents
AFI creation. Keep `sh_ddr` instantiated with `DDR_PRESENT=0` even without DDR.

The [shell errata](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/docs/AWS_Shell_ERRATA.md) prohibit HBM ECC scrubbing
and ECC initialization on Small Shell `0x10212415`; use a supported IP
configuration. ECC correction is separate, and memory must be initialized
before reads.

The performance reference pipelines each HBM kernel port through register
slices and supplies hierarchy-specific placement/timing constraints. Preserve
that physical-design intent, but do not copy its false-path or multicycle
exceptions blindly onto our FIFOs or counters. Our Gray-pointer crossings need
their own max-delay/skew and synchronizer-placement review.

## Bandwidth and verification

The interface ceiling remains **32 ports × 32 bytes × 450 MHz = 460.8 GB/s**.
Our two-record return interface has 512 GB/s of core-side capacity at 250 MHz.
These capacities do not establish sustained DRAM bandwidth.

AWS's [performance runtime](https://github.com/aws/aws-fpga/blob/c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82/hdk/cl/examples/cl_mem_perf/software/runtime/test_hbm_perf32.c)
configures **16-beat bursts** (`AXLEN=15`). Our current bridge expands each
descriptor into individual one-beat transactions. The reference's reported
bandwidth does not validate our traffic pattern. Burst support needs per-ID
beat tracking, per-beat destination tags, RLAST validation, boundary splitting
and sufficient return buffering. Compare single-beat and burst traffic with
the same 32-port layout before selecting it. AWS's kernel carries completion
pulses across its control CDC; our engine must carry actual read data.

Next integration gates:

1. Establish the AWS reference toolchain and run its HBM test with the vendor
   model. AWS recommends VCS or Questa; the DMA example's `make test_hbm`
   defaults to VCS after HDK setup. This sparse audit checkout is not that setup.
2. Connect our 32-port bridge to the performance wrapper, retaining shell
   monitoring, clocking and an explicit reset/ownership controller.
3. Test all physical ports, host-load/readback layout, errors, in-flight resets,
   ownership transitions and return data in the integrated model. Measure
   representative one-beat and burst bandwidth.
4. Complete Vivado resource mapping and 250/450 MHz timing closure before
   projecting simulator TPS onto an F2 image.

## Reproduce the source checkout

Use a new destination directory. This retrieves source only:

```sh
git clone --filter=blob:none --no-checkout https://github.com/aws/aws-fpga.git aws-fpga-f2
git -C aws-fpga-f2 sparse-checkout init --cone
git -C aws-fpga-f2 sparse-checkout set hdk/cl/examples/cl_dram_hbm_dma hdk/cl/examples/cl_mem_perf hdk/common/lib hdk/common/verif hdk/docs
git -C aws-fpga-f2 fetch --depth 1 origin c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82
git -C aws-fpga-f2 checkout --detach c34f88e97eaf8a9b6ea7a3516ab65ee64690ab82
```

Use official HDK setup on the build host to obtain matching shell and IP
assets. The [synthesis readiness assessment](SYNTHESIS_READINESS.md) continues
to apply; this source audit does not qualify a full F2 build.
