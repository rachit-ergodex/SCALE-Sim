// SPDX-License-Identifier: MIT
// Parallel 1 x COLS output-stationary INT8 arrays. All data ports share one
// commit enable; adapters must hold operand/psum data until cycle_ready.
// One command covers one output-column tile. Addresses are element indices.
module decode_os_core #(
    parameter integer PARTITIONS=4,
    parameter integer COLS=8,
    parameter integer MAX_M=4,
    parameter integer MAX_K=8192
)(
    input wire clk, rst,
    input wire cmd_valid,
    output wire cmd_ready,
    input wire [31:0] cmd_m, cmd_k, cmd_n,
    input wire cmd_parallel_rows, cmd_accumulate,
    output reg busy, done, command_error,
    input wire cycle_ready,
    output reg [PARTITIONS-1:0] a_valid,
    output reg [PARTITIONS*32-1:0] a_address,
    input wire [PARTITIONS*8-1:0] a_data,
    output reg [PARTITIONS*COLS-1:0] b_valid,
    output reg [PARTITIONS*COLS*32-1:0] b_address,
    input wire [PARTITIONS*COLS*8-1:0] b_data,
    output reg [PARTITIONS*COLS-1:0] seed_valid,
    input wire [PARTITIONS*COLS*32-1:0] seed_data,
    output reg [PARTITIONS*COLS-1:0] c_valid,
    output reg [PARTITIONS*COLS*32-1:0] c_address,
    output reg [PARTITIONS*COLS*32-1:0] c_data,
    output reg [63:0] logical_cycles, elapsed_cycles, stall_cycles
);
    // Test fixture, NEVER include in the Vivado design. The output pattern has
    // position-dependent bits and a complement mode so every capture bit is
    // exercised as both zero and one, independently of real-core reachability.
    localparam integer OUTPUT_BITS=196+33*PARTITIONS+99*PARTITIONS*COLS;
    reg [OUTPUT_BITS-1:0] pattern;
    reg [31:0] state;
    always @* begin
        state=cmd_m ^ 32'h9e3779b9;
        for (integer i=0; i<OUTPUT_BITS; i=i+1) begin
            state=state ^ (state << 13);
            state=state ^ (state >> 17);
            state=state ^ (state << 5);
            pattern[i]=state[0] ^ cmd_k[0];
        end
        {stall_cycles, elapsed_cycles, logical_cycles, c_data, c_address,
         c_valid, seed_valid, b_address, b_valid, a_address, a_valid,
         command_error, done, busy}=pattern[OUTPUT_BITS-1:1];
    end
    assign cmd_ready=pattern[0];
endmodule
