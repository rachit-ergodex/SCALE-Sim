// SPDX-License-Identifier: MIT
// All 32 HBM ports are independent: no shared request or return arbitration.
// This module is entirely in the HBM AXI clock domain. Core-side CDC and memory
// write channels are separate integration components. ARLEN=0, ARSIZE=5,
// ARBURST=INCR at every physical AXI3 port; expose these constants explicitly.
module decode_hbm_read32 #(
    parameter integer TAG_WIDTH=32
)(
    input wire clk, rst, enable,
    input wire [31:0] req_valid,
    output wire [31:0] req_ready,
    input wire [32*24-1:0] req_line,
    input wire [32*TAG_WIDTH-1:0] req_tag,
    output wire [31:0] rsp_valid,
    input wire [31:0] rsp_ready,
    output wire [32*256-1:0] rsp_data,
    output wire [32*TAG_WIDTH-1:0] rsp_tag,
    output wire [31:0] rsp_error, fault,
    output wire [32*7-1:0] outstanding,
    output wire [32*34-1:0] m_araddr,
    output wire [32*6-1:0] m_arid,
    output wire [32*4-1:0] m_arlen,
    output wire [32*3-1:0] m_arsize,
    output wire [32*2-1:0] m_arburst,
    output wire [31:0] m_arvalid,
    input wire [31:0] m_arready,
    input wire [32*256-1:0] m_rdata,
    input wire [32*6-1:0] m_rid,
    input wire [32*2-1:0] m_rresp,
    input wire [31:0] m_rlast, m_rvalid,
    output wire [31:0] m_rready
);
    for(genvar p=0;p<32;p=p+1) begin:ports
        assign m_arlen[p*4 +: 4]=0;
        assign m_arsize[p*3 +: 3]=5;
        assign m_arburst[p*2 +: 2]=1;
        decode_hbm_read_port #(.PORT(p),.TAG_WIDTH(TAG_WIDTH)) frontend(
            .clk(clk),.rst(rst),.enable(enable),
            .req_valid(req_valid[p]),.req_ready(req_ready[p]),
            .req_line(req_line[p*24 +: 24]),.req_tag(req_tag[p*TAG_WIDTH +: TAG_WIDTH]),
            .rsp_valid(rsp_valid[p]),.rsp_ready(rsp_ready[p]),
            .rsp_data(rsp_data[p*256 +: 256]),.rsp_tag(rsp_tag[p*TAG_WIDTH +: TAG_WIDTH]),
            .rsp_error(rsp_error[p]),.fault(fault[p]),.outstanding(outstanding[p*7 +: 7]),
            .m_araddr(m_araddr[p*34 +: 34]),.m_arid(m_arid[p*6 +: 6]),
            .m_arvalid(m_arvalid[p]),.m_arready(m_arready[p]),
            .m_rdata(m_rdata[p*256 +: 256]),.m_rid(m_rid[p*6 +: 6]),
            .m_rresp(m_rresp[p*2 +: 2]),.m_rlast(m_rlast[p]),.m_rvalid(m_rvalid[p]),.m_rready(m_rready[p])
        );
    end
endmodule
