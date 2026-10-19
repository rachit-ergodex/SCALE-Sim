// SPDX-License-Identifier: MIT
// Dual-clock FIFO with Gray pointers and a registered read prefetch slot.
// DEPTH memory entries plus one read-output slot. Both domains must be reset
// together; reset deassertion must be synchronized to each domain externally.
module decode_async_fifo #(
    parameter integer WIDTH=64,
    parameter integer DEPTH=16,
    parameter integer AW=$clog2(DEPTH)
)(
    input wire wr_clk, wr_rst,
    input wire wr_valid,
    output wire wr_ready,
    input wire [WIDTH-1:0] wr_data,
    input wire rd_clk, rd_rst,
    output reg rd_valid,
    input wire rd_ready,
    output reg [WIDTH-1:0] rd_data
);
    reg [WIDTH-1:0] memory [0:DEPTH-1];
    reg [AW:0] wr_binary,wr_gray,rd_binary,rd_gray;
    (* ASYNC_REG="TRUE" *) reg [AW:0] rd_gray_sync1,rd_gray_sync2;
    (* ASYNC_REG="TRUE" *) reg [AW:0] wr_gray_sync1,wr_gray_sync2;
    wire [AW:0] full_mark={~rd_gray_sync2[AW:AW-1],rd_gray_sync2[AW-2:0]};
    wire [AW:0] next_write=wr_binary+1'b1,next_read=rd_binary+1'b1;
    wire empty=(rd_gray==wr_gray_sync2);
    assign wr_ready=!wr_rst && wr_gray!=full_mark;
    initial if(WIDTH<1 || DEPTH<4 || (1<<AW)!=DEPTH) $fatal(1,"Invalid async FIFO geometry");
    always @(posedge wr_clk) begin
        if(wr_rst) begin wr_binary<=0;wr_gray<=0;rd_gray_sync1<=0;rd_gray_sync2<=0;end
        else begin
            rd_gray_sync1<=rd_gray;rd_gray_sync2<=rd_gray_sync1;
            if(wr_valid && wr_ready) begin
                memory[wr_binary[AW-1:0]]<=wr_data;
                wr_binary<=next_write;wr_gray<=(next_write>>1)^next_write;
            end
        end
    end
    always @(posedge rd_clk) begin
        if(rd_rst) begin rd_binary<=0;rd_gray<=0;wr_gray_sync1<=0;wr_gray_sync2<=0;rd_valid<=0;rd_data<=0;end
        else begin
            wr_gray_sync1<=wr_gray;wr_gray_sync2<=wr_gray_sync1;
            if(!empty && (!rd_valid || rd_ready)) begin
                rd_data<=memory[rd_binary[AW-1:0]];
                rd_binary<=next_read;rd_gray<=(next_read>>1)^next_read;rd_valid<=1;
            end else if(rd_ready) rd_valid<=0;
        end
    end
endmodule
