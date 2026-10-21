// Simulation model only; the Vivado source set must use the device BUFG primitive.
module BUFG(input wire I, output wire O);
    assign O = I;
endmodule
