// SPDX-License-Identifier: MIT
// Physical timing experiment, NOT a production FPGA/HBM or inference top.
// Scan ordering and edge protocol are specified in this directory's README.md.
module decode_compute_timing_harness #(
    parameter integer PARTITIONS=64,
    parameter integer COLS=64,
    parameter integer MAX_M=4,
    parameter integer MAX_K=8192,
    parameter integer INPUT_BITS=101+8*PARTITIONS+40*PARTITIONS*COLS,
    parameter integer OUTPUT_BITS=196+33*PARTITIONS+99*PARTITIONS*COLS
)(
    input wire clk,
    input wire harness_reset,
    input wire scan_in,
    input wire input_shift,
    input wire input_commit,
    input wire output_capture,
    input wire output_shift,
    output reg scan_out
);
    wire core_clk;
    BUFG core_clock_buffer (.I(clk), .O(core_clk));

    // External pins have half a cycle to/from the registered wide boundary.
    // These are real negative-edge registers, not timing exceptions.
    reg reset_q, scan_q, input_shift_q, input_commit_q;
    reg output_capture_q, output_shift_q;
    always @(negedge core_clk) begin
        reset_q <= harness_reset;
        scan_q <= scan_in;
        input_shift_q <= input_shift;
        input_commit_q <= input_commit;
        output_capture_q <= output_capture;
        output_shift_q <= output_shift;
        scan_out <= output_scan[0];
    end

    // No reset tree across the wide banks. Before the first commit, armed=0
    // holds the core in synchronous reset. A complete vector must be shifted
    // before committing. Capture must precede the first output scan.
    (* shreg_extract = "no" *) reg [INPUT_BITS-1:0] input_scan;
    (* shreg_extract = "no" *) reg [INPUT_BITS-1:0] input_launch;
    (* shreg_extract = "no" *) reg [OUTPUT_BITS-1:0] output_scan;
    reg armed;
    wire [OUTPUT_BITS-1:0] core_outputs;
    always @(posedge core_clk) begin
        if (reset_q) begin
            armed <= 1'b0;
        end else begin
            if (input_shift_q) input_scan <= {scan_q, input_scan[INPUT_BITS-1:1]};
            if (input_commit_q) begin
                input_launch <= input_scan;
                armed <= 1'b1;
            end
            // Capture wins if capture and shift are asserted together.
            if (output_capture_q) output_scan <= core_outputs;
            else if (output_shift_q) output_scan <= {1'b0, output_scan[OUTPUT_BITS-1:1]};
        end
    end

    wire vector_rst, cmd_valid, cmd_parallel_rows, cmd_accumulate, cycle_ready;
    wire [31:0] cmd_m, cmd_k, cmd_n;
    wire [PARTITIONS*8-1:0] a_data;
    wire [PARTITIONS*COLS*8-1:0] b_data;
    wire [PARTITIONS*COLS*32-1:0] seed_data;
    // LSB-first order: rst, cmd_valid, m, k, n, parallel, accumulate,
    // cycle_ready, A bytes, B bytes, seed INT32 words.
    assign {seed_data, b_data, a_data, cycle_ready, cmd_accumulate,
            cmd_parallel_rows, cmd_n, cmd_k, cmd_m, cmd_valid, vector_rst} = input_launch;
    wire rst = reset_q || !armed || vector_rst;
    wire cmd_ready, busy, done, command_error;
    wire [PARTITIONS-1:0] a_valid;
    wire [PARTITIONS*32-1:0] a_address;
    wire [PARTITIONS*COLS-1:0] b_valid, seed_valid, c_valid;
    wire [PARTITIONS*COLS*32-1:0] b_address, c_address, c_data;
    wire [63:0] logical_cycles, elapsed_cycles, stall_cycles;
    assign core_outputs = {stall_cycles, elapsed_cycles, logical_cycles,
            c_data, c_address, c_valid, seed_valid, b_address, b_valid,
            a_address, a_valid, command_error, done, busy, cmd_ready};

    decode_os_core #(.PARTITIONS(PARTITIONS), .COLS(COLS),
                    .MAX_M(MAX_M), .MAX_K(MAX_K)) core (
        .clk(core_clk), .rst(rst), .cmd_valid(cmd_valid), .cmd_ready(cmd_ready),
        .cmd_m(cmd_m), .cmd_k(cmd_k), .cmd_n(cmd_n),
        .cmd_parallel_rows(cmd_parallel_rows), .cmd_accumulate(cmd_accumulate),
        .busy(busy), .done(done), .command_error(command_error),
        .cycle_ready(cycle_ready), .a_valid(a_valid), .a_address(a_address),
        .a_data(a_data), .b_valid(b_valid), .b_address(b_address), .b_data(b_data),
        .seed_valid(seed_valid), .seed_data(seed_data), .c_valid(c_valid),
        .c_address(c_address), .c_data(c_data), .logical_cycles(logical_cycles),
        .elapsed_cycles(elapsed_cycles), .stall_cycles(stall_cycles)
    );
    initial begin
        if (INPUT_BITS != 101+8*PARTITIONS+40*PARTITIONS*COLS ||
            OUTPUT_BITS != 196+33*PARTITIONS+99*PARTITIONS*COLS)
            $fatal(1, "Timing harness vector width override is invalid");
    end
endmodule
