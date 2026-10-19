// SPDX-License-Identifier: MIT
// One 450-MHz-domain HBM read frontend. Each request is one aligned 32-byte
// AXI3 transaction. 64 IDs track independent, potentially reordered responses.
// Reset must also reset/drain the downstream AXI fabric before reuse.
module decode_hbm_read_port #(
    parameter integer PORT=0,
    parameter integer TAG_WIDTH=32
)(
    input wire clk, rst, enable,
    input wire req_valid,
    output wire req_ready,
    input wire [23:0] req_line,
    input wire [TAG_WIDTH-1:0] req_tag,
    output wire rsp_valid,
    input wire rsp_ready,
    output wire [255:0] rsp_data,
    output wire [TAG_WIDTH-1:0] rsp_tag,
    output wire rsp_error,
    output reg fault,
    output reg [6:0] outstanding,
    output reg [33:0] m_araddr,
    output reg [5:0] m_arid,
    output reg m_arvalid,
    input wire m_arready,
    input wire [255:0] m_rdata,
    input wire [5:0] m_rid,
    input wire [1:0] m_rresp,
    input wire m_rlast, m_rvalid,
    output wire m_rready
);
    reg [63:0] allocated, issued;
    reg [TAG_WIDTH-1:0] tags [0:63];
    reg free_found;
    reg [5:0] free_id;
    wire ar_fire=m_arvalid && m_arready;
    wire known=allocated[m_rid] && (issued[m_rid] || (ar_fire && m_arid==m_rid));
    wire retire=m_rvalid && m_rready && known;
    wire accept=req_valid && req_ready;
    initial if(PORT<0 || PORT>31 || TAG_WIDTH<1) $fatal(1,"Invalid HBM port geometry");
    always @* begin
        free_found=0;free_id=0;
        for(integer i=0;i<64;i=i+1)
            if(!allocated[i] && !free_found) begin free_found=1;free_id=6'(i);end
    end
    assign req_ready=!rst && enable && !fault && free_found && (!m_arvalid || m_arready);
    assign rsp_valid=!rst && m_rvalid && known;
    assign rsp_data=m_rdata;
    assign rsp_tag=tags[m_rid];
    assign rsp_error=(m_rresp!=0) || !m_rlast;
    assign m_rready=!rst && (rsp_ready || !known);
    always @(posedge clk) begin
        if(rst) begin
            allocated<=0;issued<=0;fault<=0;outstanding<=0;
            m_arvalid<=0;m_araddr<=0;m_arid<=0;
        end else begin
            if(ar_fire) begin m_arvalid<=0;issued[m_arid]<=1;end
            if(accept) begin
                allocated[free_id]<=1;tags[free_id]<=req_tag;
                m_arvalid<=1;m_arid<=free_id;
                // Direct PC aperture: 32 windows of 512 MiB in the 16-GiB HBM.
                m_araddr<={5'(PORT),req_line,5'b0};
            end
            if(retire) begin allocated[m_rid]<=0;issued[m_rid]<=0;end
            case({accept,retire})
                2'b10:outstanding<=outstanding+1;
                2'b01:outstanding<=outstanding-1;
                default:;
            endcase
            if(m_rvalid && m_rready && (!known || m_rresp!=0 || !m_rlast)) fault<=1;
        end
    end
endmodule
