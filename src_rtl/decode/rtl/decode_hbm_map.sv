// SPDX-License-Identifier: MIT
// Same bijection as full_model/address_map.h for the fixed 16-GiB HBM profile.
module decode_hbm_map (
    input wire [33:0] logical_address,
    input wire interleave,
    output wire [33:0] physical_address
);
    wire [33:0] mapped;
    assign mapped[8:0] = logical_address[8:0];
    assign mapped[14] = logical_address[9];
    assign mapped[16] = logical_address[10];
    assign mapped[17] = logical_address[11];
    assign mapped[13:9] = logical_address[16:12];
    assign mapped[15] = logical_address[17];
    assign mapped[33:18] = logical_address[33:18];
    assign physical_address = interleave ? mapped : logical_address;
endmodule
