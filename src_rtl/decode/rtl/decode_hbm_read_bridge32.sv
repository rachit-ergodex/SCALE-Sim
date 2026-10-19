// SPDX-License-Identifier: MIT
// 32 independent descriptor/response clock crossings and physical HBM ports.
module decode_hbm_read_bridge32 #(
    parameter integer TAG_WIDTH=32,
    parameter integer FIFO_DEPTH=16,
    parameter integer RETURN_RECORDS=2
)(
    input wire core_clk, core_rst, hbm_clk, hbm_rst, hbm_enable,
    input wire [31:0] desc_valid,
    output wire [31:0] desc_ready,
    input wire [32*24-1:0] desc_line,
    input wire [32*4-1:0] desc_len,
    input wire [32*TAG_WIDTH-1:0] desc_tag,
    output wire [31:0] return_valid,
    input wire [31:0] return_ready,
    output wire [32*RETURN_RECORDS-1:0] return_mask,
    output wire [32*RETURN_RECORDS*256-1:0] return_data,
    output wire [32*RETURN_RECORDS*TAG_WIDTH-1:0] return_tag,
    output wire [32*RETURN_RECORDS-1:0] return_error,
    output wire [31:0] fault_core,
    output wire [32*7-1:0] outstanding,
    output wire [32*34-1:0] m_araddr,
    output wire [32*6-1:0] m_arid,
    output wire [31:0] m_arvalid,
    input wire [31:0] m_arready,
    input wire [32*256-1:0] m_rdata,
    input wire [32*6-1:0] m_rid,
    input wire [32*2-1:0] m_rresp,
    input wire [31:0] m_rlast, m_rvalid,
    output wire [31:0] m_rready
);
    for(genvar p=0;p<32;p=p+1) begin:ports
        decode_hbm_read_bridge #(.PORT(p),.TAG_WIDTH(TAG_WIDTH),.FIFO_DEPTH(FIFO_DEPTH),.RETURN_RECORDS(RETURN_RECORDS)) bridge(
            .core_clk(core_clk),.core_rst(core_rst),.hbm_clk(hbm_clk),.hbm_rst(hbm_rst),.hbm_enable(hbm_enable),
            .desc_valid(desc_valid[p]),.desc_ready(desc_ready[p]),
            .desc_line(desc_line[p*24 +: 24]),.desc_len(desc_len[p*4 +: 4]),.desc_tag(desc_tag[p*TAG_WIDTH +: TAG_WIDTH]),
            .return_valid(return_valid[p]),.return_ready(return_ready[p]),.return_mask(return_mask[p*RETURN_RECORDS +: RETURN_RECORDS]),
            .return_data(return_data[p*RETURN_RECORDS*256 +: RETURN_RECORDS*256]),.return_tag(return_tag[p*RETURN_RECORDS*TAG_WIDTH +: RETURN_RECORDS*TAG_WIDTH]),.return_error(return_error[p*RETURN_RECORDS +: RETURN_RECORDS]),
            .fault_core(fault_core[p]),.outstanding(outstanding[p*7 +: 7]),
            .m_araddr(m_araddr[p*34 +: 34]),.m_arid(m_arid[p*6 +: 6]),.m_arvalid(m_arvalid[p]),.m_arready(m_arready[p]),
            .m_rdata(m_rdata[p*256 +: 256]),.m_rid(m_rid[p*6 +: 6]),.m_rresp(m_rresp[p*2 +: 2]),
            .m_rlast(m_rlast[p]),.m_rvalid(m_rvalid[p]),.m_rready(m_rready[p]));
    end
endmodule
