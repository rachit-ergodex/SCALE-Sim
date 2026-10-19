// SPDX-License-Identifier: MIT
// Core -> HBM descriptor CDC and HBM -> core two-response packet CDC.
// A descriptor expands to 1..16 consecutive 32-byte reads. Two return records
// per core cycle allow 512 GB/s across 32 ports at 250 MHz, ahead of HBM's
// nominal 460.8 GB/s at 450 MHz. Physical CDC timing constraints are required.
module decode_hbm_read_bridge #(
    parameter integer PORT=0,
    parameter integer TAG_WIDTH=32,
    parameter integer FIFO_DEPTH=16,
    parameter integer RECORD_WIDTH=257+TAG_WIDTH
)(
    input wire core_clk, core_rst, hbm_clk, hbm_rst, hbm_enable,
    input wire desc_valid,
    output wire desc_ready,
    input wire [23:0] desc_line,
    input wire [3:0] desc_len,
    input wire [TAG_WIDTH-1:0] desc_tag,
    output wire return_valid,
    input wire return_ready,
    output wire [1:0] return_mask,
    output wire [2*256-1:0] return_data,
    output wire [2*TAG_WIDTH-1:0] return_tag,
    output wire [1:0] return_error,
    output wire fault_core,
    output wire [6:0] outstanding,
    output wire [33:0] m_araddr,
    output wire [5:0] m_arid,
    output wire m_arvalid,
    input wire m_arready,
    input wire [255:0] m_rdata,
    input wire [5:0] m_rid,
    input wire [1:0] m_rresp,
    input wire m_rlast, m_rvalid,
    output wire m_rready
);
    localparam integer DESC_WIDTH=28+TAG_WIDTH;
    wire fifo_desc_valid,fifo_desc_ready;
    wire [DESC_WIDTH-1:0] fifo_desc;
    decode_async_fifo #(.WIDTH(DESC_WIDTH),.DEPTH(FIFO_DEPTH)) requests(
        .wr_clk(core_clk),.wr_rst(core_rst),.wr_valid(desc_valid),.wr_ready(desc_ready),
        .wr_data({desc_tag,desc_len,desc_line}),.rd_clk(hbm_clk),.rd_rst(hbm_rst),
        .rd_valid(fifo_desc_valid),.rd_ready(fifo_desc_ready),.rd_data(fifo_desc));
    reg active,bad_descriptor;
    reg [23:0] current_line;
    reg [TAG_WIDTH-1:0] current_tag;
    reg [3:0] remaining;
    wire [23:0] first_line=fifo_desc[23:0];
    wire [3:0] first_len=fifo_desc[27:24];
    wire [TAG_WIDTH-1:0] first_tag=fifo_desc[DESC_WIDTH-1:28];
    wire overflow=({1'b0,first_line}+25'(first_len))>25'h0ffffff;
    wire req_ready,port_fault;
    wire req_valid=!bad_descriptor && (active || (fifo_desc_valid && !overflow));
    wire [23:0] req_line=active?current_line:first_line;
    wire [TAG_WIDTH-1:0] req_tag=active?current_tag:first_tag;
    assign fifo_desc_ready=!active && !bad_descriptor && (overflow || req_ready);
    always @(posedge hbm_clk) begin
        if(hbm_rst) begin active<=0;remaining<=0;current_line<=0;current_tag<=0;bad_descriptor<=0;end
        else begin
            if(!active && fifo_desc_valid && overflow) bad_descriptor<=1;
            if(req_valid && req_ready) begin
                current_line<=req_line+1'b1;current_tag<=req_tag+1'b1;
                if(active) begin remaining<=remaining-1'b1;if(remaining==1) active<=0;end
                else begin remaining<=first_len;active<=first_len!=0;end
            end
        end
    end
    wire rsp_valid,rsp_ready,rsp_error;
    wire [255:0] rsp_data;
    wire [TAG_WIDTH-1:0] rsp_tag;
    decode_hbm_read_port #(.PORT(PORT),.TAG_WIDTH(TAG_WIDTH)) frontend(
        .clk(hbm_clk),.rst(hbm_rst),.enable(hbm_enable && !bad_descriptor),
        .req_valid(req_valid),.req_ready(req_ready),.req_line(req_line),.req_tag(req_tag),
        .rsp_valid(rsp_valid),.rsp_ready(rsp_ready),.rsp_data(rsp_data),.rsp_tag(rsp_tag),.rsp_error(rsp_error),
        .fault(port_fault),.outstanding(outstanding),.m_araddr(m_araddr),.m_arid(m_arid),.m_arvalid(m_arvalid),.m_arready(m_arready),
        .m_rdata(m_rdata),.m_rid(m_rid),.m_rresp(m_rresp),.m_rlast(m_rlast),.m_rvalid(m_rvalid),.m_rready(m_rready));
    // Register the complete output packet before presenting it to the FIFO;
    // both payload and mask remain stable while the FIFO is full.
    reg first_valid,packet_valid;
    reg [RECORD_WIDTH-1:0] first_record;
    reg [2*RECORD_WIDTH+1:0] packet;
    wire packet_ready;
    wire slot_free=!packet_valid || packet_ready;
    wire [RECORD_WIDTH-1:0] record_value={rsp_error,rsp_tag,rsp_data};
    assign rsp_ready=!first_valid || slot_free;
    always @(posedge hbm_clk) begin
        if(hbm_rst) begin first_valid<=0;packet_valid<=0;first_record<=0;packet<=0;end
        else begin
            if(packet_valid && packet_ready) packet_valid<=0;
            if(rsp_valid && rsp_ready) begin
                if(first_valid) begin packet<={2'b11,record_value,first_record};packet_valid<=1;first_valid<=0;end
                else begin first_record<=record_value;first_valid<=1;end
            end else if(first_valid && !rsp_valid && slot_free) begin
                packet<={2'b01,{RECORD_WIDTH{1'b0}},first_record};packet_valid<=1;first_valid<=0;
            end
        end
    end
    wire [2*RECORD_WIDTH+1:0] return_packet;
    decode_async_fifo #(.WIDTH(2*RECORD_WIDTH+2),.DEPTH(FIFO_DEPTH)) responses(
        .wr_clk(hbm_clk),.wr_rst(hbm_rst),.wr_valid(packet_valid),.wr_ready(packet_ready),.wr_data(packet),
        .rd_clk(core_clk),.rd_rst(core_rst),.rd_valid(return_valid),.rd_ready(return_ready),.rd_data(return_packet));
    assign return_mask=return_packet[2*RECORD_WIDTH +: 2];
    for(genvar lane=0;lane<2;lane=lane+1) begin:unpack_return
        assign return_data[lane*256 +: 256]=return_packet[lane*RECORD_WIDTH +: 256];
        assign return_tag[lane*TAG_WIDTH +: TAG_WIDTH]=return_packet[lane*RECORD_WIDTH+256 +: TAG_WIDTH];
        assign return_error[lane]=return_packet[lane*RECORD_WIDTH+RECORD_WIDTH-1];
    end
    (* ASYNC_REG="TRUE" *) reg fault_sync1,fault_sync2;
    always @(posedge core_clk) begin
        if(core_rst) begin fault_sync1<=0;fault_sync2<=0;end
        else begin fault_sync1<=port_fault || bad_descriptor;fault_sync2<=fault_sync1;end
    end
    assign fault_core=fault_sync2;
endmodule
