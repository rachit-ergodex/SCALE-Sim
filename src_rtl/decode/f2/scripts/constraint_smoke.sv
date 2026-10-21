// Exercises more than one 4096-port constraint chunk on each boundary.
module decode_constraint_smoke(input wire clk, rst,
    input wire [4096:0] din, output reg [4096:0] dout);
always @(posedge clk) if (rst) dout <= 0; else dout <= din;
endmodule
