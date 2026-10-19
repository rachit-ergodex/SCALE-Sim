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
    reg [31:0] m_reg, k_reg, n_reg, column_parts, workers, wave, phase;
    reg accumulate;
    reg signed [7:0] a_pipe [0:PARTITIONS-1][0:COLS-1];
    reg signed [31:0] accumulator [0:PARTITIONS-1][0:COLS-1];
    wire [31:0] requested_parts=(cmd_n+32'(COLS)-1)/32'(COLS);
    wire [31:0] available_workers=32'(PARTITIONS)/((requested_parts==0)?32'd1:requested_parts);
    wire [31:0] requested_workers=cmd_parallel_rows ? ((cmd_m<available_workers)?cmd_m:available_workers) : 32'd1;
    assign cmd_ready=!rst && !busy;
    initial begin
        if (PARTITIONS<1 || COLS<1 || MAX_M<1 || MAX_K<1) $fatal(1,"Invalid array geometry");
    end
    // Constant partition/column loop bounds describe actual physical MACs.
    // Runtime division is in address/control logic, not the MAC datapath.
    always @* begin
        a_valid='0; a_address='0; b_valid='0;
        seed_valid='0; c_valid='0;
        for(integer lane=0;lane<PARTITIONS*COLS;lane=lane+1) begin
            b_address[lane*32 +: 32]=0;c_address[lane*32 +: 32]=0;c_data[lane*32 +: 32]=0;
        end
        for (integer p=0;p<PARTITIONS;p=p+1) begin
            if (busy && !rst && column_parts!=0 &&
                (32'(p)/column_parts)<workers &&
                (wave*workers+32'(p)/column_parts)<m_reg) begin
                a_address[p*32 +: 32]=(wave*workers+32'(p)/column_parts)*k_reg+phase;
                a_valid[p]=phase<k_reg;
                for (integer c=0;c<COLS;c=c+1) begin
                    c_address[(p*COLS+c)*32 +: 32]=(wave*workers+32'(p)/column_parts)*n_reg+
                        (32'(p)%column_parts)*32'(COLS)+32'(c);
                    if ((32'(p)%column_parts)*32'(COLS)+32'(c)<n_reg &&
                        phase>=32'(c) && phase<k_reg+32'(c)) begin
                        b_valid[p*COLS+c]=1;
                        b_address[(p*COLS+c)*32 +: 32]=(phase-32'(c))*n_reg+
                            (32'(p)%column_parts)*32'(COLS)+32'(c);
                        seed_valid[p*COLS+c]=accumulate && phase==32'(c);
                        c_valid[p*COLS+c]=phase==k_reg-1+32'(c);
                        c_data[(p*COLS+c)*32 +: 32]=
                            ((phase==32'(c)) ? (accumulate ? seed_data[(p*COLS+c)*32 +: 32] : 32'b0) :
                             accumulator[p][c]) + 32'($signed((c==0)?a_data[p*8 +: 8]:a_pipe[p][c-1]) *
                                $signed(b_data[(p*COLS+c)*8 +: 8]));
                    end
                end
            end
        end
    end
    always @(posedge clk) begin
        if (rst) begin
            busy<=0;done<=0;command_error<=0;
            m_reg<=0;k_reg<=0;n_reg<=0;column_parts<=1;workers<=1;wave<=0;phase<=0;accumulate<=0;
            logical_cycles<=0;elapsed_cycles<=0;stall_cycles<=0;
            for(integer p=0;p<PARTITIONS;p=p+1)
                for(integer c=0;c<COLS;c=c+1) begin a_pipe[p][c]<=0;accumulator[p][c]<=0;end
        end else begin
            done<=0;command_error<=0;
            if(cmd_valid && cmd_ready) begin
                if(cmd_m==0 || cmd_m>32'(MAX_M) || cmd_k==0 || cmd_k>32'(MAX_K) ||
                   cmd_n==0 || cmd_n>32'(PARTITIONS*COLS)) command_error<=1;
                else begin
                    busy<=1;m_reg<=cmd_m;k_reg<=cmd_k;n_reg<=cmd_n;
                    column_parts<=requested_parts;workers<=requested_workers;
                    accumulate<=cmd_accumulate;wave<=0;phase<=0;
                    logical_cycles<=0;elapsed_cycles<=0;stall_cycles<=0;
                end
            end
            if(busy) begin
                elapsed_cycles<=elapsed_cycles+1;
                if(!cycle_ready) stall_cycles<=stall_cycles+1;
                else begin
                    logical_cycles<=logical_cycles+1;
                    for(integer p=0;p<PARTITIONS;p=p+1) begin
                        a_pipe[p][0]<=a_valid[p]?$signed(a_data[p*8 +: 8]):8'sd0;
                        for(integer c=1;c<COLS;c=c+1) a_pipe[p][c]<=a_pipe[p][c-1];
                        for(integer c=0;c<COLS;c=c+1)
                            if(b_valid[p*COLS+c]) accumulator[p][c]<=c_data[(p*COLS+c)*32 +: 32];
                    end
                    if(phase==k_reg+32'(COLS)-2) begin
                        phase<=0;
                        if((wave+1)*workers>=m_reg) begin busy<=0;done<=1;end
                        else wave<=wave+1;
                    end else phase<=phase+1;
                end
            end
        end
    end
endmodule
