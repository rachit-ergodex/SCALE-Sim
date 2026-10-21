// SPDX-License-Identifier: MIT
// One synchronous read port and one byte-enabled write port; read-first collision.
module decode_scratchpad #(
    parameter integer DATA_WIDTH = 256,
    parameter integer DEPTH = 4096,
    parameter integer ADDR_WIDTH = (DEPTH > 1) ? $clog2(DEPTH) : 1
) (
    input wire clk, rst,
    input wire wr_valid,
    output wire wr_ready,
    input wire [ADDR_WIDTH-1:0] wr_addr,
    input wire [DATA_WIDTH-1:0] wr_data,
    input wire [DATA_WIDTH/8-1:0] wr_strb,
    output reg wr_error,
    input wire rd_valid,
    output wire rd_ready,
    input wire [ADDR_WIDTH-1:0] rd_addr,
    output reg rsp_valid,
    input wire rsp_ready,
    output reg [DATA_WIDTH-1:0] rsp_data,
    output reg rsp_error
);
    reg [DATA_WIDTH-1:0] memory [0:DEPTH-1];
    initial begin
        if (DATA_WIDTH < 8 || DATA_WIDTH % 8 != 0 || DEPTH < 1)
            $fatal(1,"Invalid scratchpad geometry");
    end
    assign wr_ready = !rst;
    assign rd_ready = !rst && (!rsp_valid || rsp_ready);
    always @(posedge clk) begin
        if (rst) begin
            rsp_valid <= 0; rsp_error <= 0; rsp_data <= 0; wr_error <= 0;
        end else begin
            wr_error <= 0;
            if (wr_valid && wr_ready) begin
                wr_error <= 32'(wr_addr) >= 32'(DEPTH);
                if (32'(wr_addr) < 32'(DEPTH))
                    for (integer byte_index=0; byte_index<DATA_WIDTH/8; byte_index=byte_index+1)
                        if (wr_strb[byte_index]) memory[wr_addr][byte_index*8 +: 8] <= wr_data[byte_index*8 +: 8];
            end
            if (rsp_valid && rsp_ready) rsp_valid <= 0;
            if (rd_valid && rd_ready) begin
                rsp_valid <= 1; rsp_error <= 32'(rd_addr) >= 32'(DEPTH);
                rsp_data <= (32'(rd_addr) < 32'(DEPTH)) ? memory[rd_addr] : {DATA_WIDTH{1'b0}};
            end
        end
    end
endmodule
