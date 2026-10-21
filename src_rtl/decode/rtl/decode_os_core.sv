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
    reg [31:0] m_reg, k_reg, n_reg, workers, wave_row, phase;
    reg accumulate;
    reg signed [7:0] a_pipe [0:PARTITIONS-1][0:COLS-1];
    reg signed [31:0] accumulator [0:PARTITIONS-1][0:COLS-1];
    reg [31:0] row_index [0:PARTITIONS-1];
    reg [31:0] a_row_base [0:PARTITIONS-1];
    reg [31:0] c_row_base [0:PARTITIONS-1];
    reg [31:0] column_base [0:PARTITIONS-1];
    // Current-wave row activity. Register the row bound at wave transitions so
    // the global M bus and row comparison do not gate every operand/result bit.
    reg [PARTITIONS-1:0] partition_used;
    reg [31:0] b_row_base [0:COLS-1];
    reg [31:0] a_wave_stride, c_wave_stride;
    wire [31:0] requested_parts=(cmd_n+32'(COLS)-1)/32'(COLS);
    reg [31:0] requested_workers;
    reg [31:0] requested_row [0:PARTITIONS-1];
    reg [31:0] requested_column [0:PARTITIONS-1];
    reg [31:0] requested_a_base [0:PARTITIONS-1];
    reg [31:0] requested_c_base [0:PARTITIONS-1];
    reg [31:0] requested_a_stride, requested_c_stride;
    // Temporary F2 DSP mapping experiment; identical combinational arithmetic.
    wire [PARTITIONS*COLS*32-1:0] mac_result;
    generate
        for (genvar mac_p=0;mac_p<PARTITIONS;mac_p=mac_p+1) begin: g_mac_partition
            for (genvar mac_c=0;mac_c<COLS;mac_c=mac_c+1) begin: g_mac_column
                wire signed [7:0] lane_a;
                if (mac_c==0) begin: g_first
                    assign lane_a=$signed(a_data[mac_p*8 +: 8]);
                end else begin: g_delayed
                    assign lane_a=a_pipe[mac_p][mac_c-1];
                end
`ifdef SCALESIM_F2_USE_DSP
                (* use_dsp = "yes" *)
`endif
                wire [31:0] lane_sum;
                assign lane_sum=
                    ((phase==32'(mac_c)) ? (accumulate ? seed_data[(mac_p*COLS+mac_c)*32 +: 32] : 32'b0) :
                     accumulator[mac_p][mac_c]) + 32'($signed(lane_a) *
                        $signed(b_data[(mac_p*COLS+mac_c)*8 +: 8]));
                assign mac_result[(mac_p*COLS+mac_c)*32 +: 32]=lane_sum;
            end
        end
    endgenerate
    assign cmd_ready=!rst && !busy;
    initial begin
        if (PARTITIONS<1 || COLS<1 || MAX_M<1 || MAX_K<1) $fatal(1,"Invalid array geometry");
    end
    // Decode the finite set of partition layouts only at command acceptance.
    // Every divide/modulo below has constant operands at elaboration; none is
    // a variable divider in the running address path. Constant row products
    // are shared by synthesis and selected by the decoded row number.
    always @* begin
        requested_workers=1;
        for(integer p=0;p<PARTITIONS;p=p+1) begin
            requested_row[p]=0;requested_column[p]=0;
        end
        for(integer parts=1;parts<=PARTITIONS;parts=parts+1) begin
            if(requested_parts==32'(parts)) begin
                if(cmd_parallel_rows)
                    requested_workers=(cmd_m<32'(PARTITIONS/parts))?cmd_m:32'(PARTITIONS/parts);
                for(integer p=0;p<PARTITIONS;p=p+1) begin
                    requested_row[p]=32'(p/parts);
                    requested_column[p]=32'((p%parts)*COLS);
                end
            end
        end
        requested_a_stride=cmd_k;requested_c_stride=cmd_n;
        for(integer rows=2;rows<=MAX_M && rows<=PARTITIONS;rows=rows+1) begin
            if(requested_workers==32'(rows)) begin
                requested_a_stride=32'(rows)*cmd_k;
                requested_c_stride=32'(rows)*cmd_n;
            end
        end
        for(integer p=0;p<PARTITIONS;p=p+1) begin
            requested_a_base[p]=0;requested_c_base[p]=0;
            for(integer row=1;row<MAX_M && row<PARTITIONS;row=row+1) begin
                if(requested_row[p]==32'(row)) begin
                    requested_a_base[p]=32'(row)*cmd_k;
                    requested_c_base[p]=32'(row)*cmd_n;
                end
            end
        end
    end
    // Running address generation uses registered row bases and additions.
    // Shared B row counters advance with the same global commit as the MACs,
    // preserving both the native OS schedule and address stability on stalls.
    always @* begin
        a_valid='0; a_address='0; b_valid='0;
        seed_valid='0; c_valid='0;
        for(integer lane=0;lane<PARTITIONS*COLS;lane=lane+1) begin
            b_address[lane*32 +: 32]=0;c_address[lane*32 +: 32]=0;c_data[lane*32 +: 32]=0;
        end
        for (integer p=0;p<PARTITIONS;p=p+1) begin
            if (busy && !rst && partition_used[p]) begin
                a_address[p*32 +: 32]=a_row_base[p]+phase;
                a_valid[p]=phase<k_reg;
                for (integer c=0;c<COLS;c=c+1) begin
                    c_address[(p*COLS+c)*32 +: 32]=c_row_base[p]+column_base[p]+32'(c);
                    if (column_base[p]+32'(c)<n_reg &&
                        phase>=32'(c) && phase<k_reg+32'(c)) begin
                        b_valid[p*COLS+c]=1;
                        b_address[(p*COLS+c)*32 +: 32]=b_row_base[c]+column_base[p]+32'(c);
                        seed_valid[p*COLS+c]=accumulate && phase==32'(c);
                        c_valid[p*COLS+c]=phase==k_reg-1+32'(c);
                        c_data[(p*COLS+c)*32 +: 32]=mac_result[(p*COLS+c)*32 +: 32];
                    end
                end
            end
        end
    end
    always @(posedge clk) begin
        if (rst) begin
            busy<=0;done<=0;command_error<=0;
            m_reg<=0;k_reg<=0;n_reg<=0;workers<=1;wave_row<=0;phase<=0;accumulate<=0;
            a_wave_stride<=0;c_wave_stride<=0;partition_used<='0;
            logical_cycles<=0;elapsed_cycles<=0;stall_cycles<=0;
            for(integer c=0;c<COLS;c=c+1) b_row_base[c]<=0;
            for(integer p=0;p<PARTITIONS;p=p+1) begin
                row_index[p]<=0;a_row_base[p]<=0;c_row_base[p]<=0;column_base[p]<=0;
                for(integer c=0;c<COLS;c=c+1) begin a_pipe[p][c]<=0;accumulator[p][c]<=0;end
            end
        end else begin
            done<=0;command_error<=0;
            if(cmd_valid && cmd_ready) begin
                if(cmd_m==0 || cmd_m>32'(MAX_M) || cmd_k==0 || cmd_k>32'(MAX_K) ||
                   cmd_n==0 || cmd_n>32'(PARTITIONS*COLS)) command_error<=1;
                else begin
                    busy<=1;m_reg<=cmd_m;k_reg<=cmd_k;n_reg<=cmd_n;
                    workers<=requested_workers;
                    a_wave_stride<=requested_a_stride;c_wave_stride<=requested_c_stride;
                    accumulate<=cmd_accumulate;wave_row<=0;phase<=0;
                    logical_cycles<=0;elapsed_cycles<=0;stall_cycles<=0;
                    for(integer c=0;c<COLS;c=c+1) b_row_base[c]<=0;
                    for(integer p=0;p<PARTITIONS;p=p+1) begin
                        row_index[p]<=requested_row[p];
                        a_row_base[p]<=requested_a_base[p];c_row_base[p]<=requested_c_base[p];
                        column_base[p]<=requested_column[p];
                        // requested_workers <= cmd_m for every legal command.
                        partition_used[p]<=requested_row[p]<requested_workers;
                    end
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
                        for(integer c=0;c<COLS;c=c+1) b_row_base[c]<=0;
                        if(wave_row+workers>=m_reg) begin busy<=0;done<=1;end
                        else begin
                            wave_row<=wave_row+workers;
                            for(integer p=0;p<PARTITIONS;p=p+1) begin
                                // Only a committed wave can deactivate a row;
                                // stalls retain the complete current-wave mask.
                                partition_used[p]<=partition_used[p] && row_index[p]+workers<m_reg;
                                row_index[p]<=row_index[p]+workers;
                                a_row_base[p]<=a_row_base[p]+a_wave_stride;
                                c_row_base[p]<=c_row_base[p]+c_wave_stride;
                            end
                        end
                    end else begin
                        phase<=phase+1;
                        for(integer c=0;c<COLS;c=c+1)
                            if(phase>=32'(c)) b_row_base[c]<=b_row_base[c]+n_reg;
                    end
                end
            end
        end
    end
endmodule
