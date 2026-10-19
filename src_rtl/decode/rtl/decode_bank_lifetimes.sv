// SPDX-License-Identifier: MIT
// Ownership scoreboard for two ping-pong operand banks.
module decode_bank_lifetimes (
    input wire clk, rst,
    input wire load_valid, load_bank,
    output wire load_ready,
    input wire complete_valid, complete_bank,
    input wire acquire_valid, acquire_bank,
    output wire acquire_ready,
    input wire release_valid, release_bank,
    output wire release_ready,
    output wire [3:0] states,
    output reg protocol_error
);
    localparam [1:0] EMPTY=0, LOADING=1, READY=2, IN_USE=3;
    reg [1:0] state [0:1];
    assign states = {state[1],state[0]};
    assign load_ready = !rst && state[load_bank]==EMPTY;
    assign acquire_ready = !rst && state[acquire_bank]==READY;
    assign release_ready = !rst && state[release_bank]==IN_USE;
    always @(posedge clk) begin
        if (rst) begin state[0]<=EMPTY; state[1]<=EMPTY; protocol_error<=0; end
        else begin
            protocol_error <= complete_valid && state[complete_bank]!=LOADING;
            if (load_valid && load_ready) state[load_bank] <= LOADING;
            if (complete_valid && state[complete_bank]==LOADING) state[complete_bank] <= READY;
            if (acquire_valid && acquire_ready) state[acquire_bank] <= IN_USE;
            if (release_valid && release_ready) state[release_bank] <= EMPTY;
        end
    end
endmodule
