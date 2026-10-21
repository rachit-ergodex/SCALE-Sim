`timescale 1ns/1ps
// Four-state checks: invalid operand lanes and unused seeds carry X throughout.
module os_four_state_tb;
    localparam integer P=4, C=8;
    reg clk=0, rst=1, cmd_valid=0, cycle_ready=0;
    wire cmd_ready, busy, done, command_error;
    reg [31:0] cmd_m=0, cmd_k=0, cmd_n=0;
    reg cmd_parallel_rows=0, cmd_accumulate=0;
    wire [P-1:0] a_valid;
    wire [P*32-1:0] a_address;
    reg [P*8-1:0] a_data='x;
    wire [P*C-1:0] b_valid, seed_valid, c_valid;
    wire [P*C*32-1:0] b_address, c_address, c_data;
    reg [P*C*8-1:0] b_data='x;
    reg [P*C*32-1:0] seed_data='x;
    wire [63:0] logical_cycles, elapsed_cycles, stall_cycles;
    decode_os_core #(.PARTITIONS(P), .COLS(C)) dut (.*);

    task tick;
        begin clk=0; #5; clk=1; #5; end
    endtask

    function automatic integer av(input integer addr);
        av=(addr%7)-3;
    endfunction
    function automatic integer bv(input integer addr);
        bv=(addr%11)-5;
    endfunction
    function automatic [31:0] seed(input integer addr);
        seed=(addr%2) ? 32'h7ffffff0 : 32'h80000010;
    endfunction

    task automatic execute(input integer m, k, n, parallel_rows, accumulate);
        integer cycles, commits, writes, stalls, idx, addr, row, col, kk;
        integer expected_cycles, parts, workers;
        reg signed [31:0] expected;
        reg [P*C*32-1:0] saved_data, saved_b_address;
        reg [P*32-1:0] saved_a_address;
        reg [P*C-1:0] saved_c_valid;
        reg [127:0] seen;
        begin
            cmd_m=m;cmd_k=k;cmd_n=n;cmd_parallel_rows=(parallel_rows!=0);
            cmd_accumulate=(accumulate!=0);cmd_valid=1;cycle_ready=0;
            tick();cmd_valid=0;
            if (busy !== 1'b1 || command_error !== 1'b0) $fatal(1,"command acceptance");
            cycles=0;commits=0;writes=0;stalls=0;seen=0;
            parts=(n+C-1)/C;workers=parallel_rows ? ((m<P/parts)?m:P/parts) : 1;
            expected_cycles=((m+workers-1)/workers)*(k+C-1);
            while (busy) begin
                a_data='x;b_data='x;seed_data='x;
                for(idx=0;idx<P;idx=idx+1)
                    if(a_valid[idx]) a_data[idx*8 +: 8]=8'(av(a_address[idx*32 +: 32]));
                for(idx=0;idx<P*C;idx=idx+1) begin
                    if(b_valid[idx]) b_data[idx*8 +: 8]=8'(bv(b_address[idx*32 +: 32]));
                    if(seed_valid[idx]) seed_data[idx*32 +: 32]=seed(c_address[idx*32 +: 32]);
                end
                cycle_ready=(cycles%4 != 1);
                #1;
                if ((^c_valid) === 1'bx || (^c_data) === 1'bx)
                    $fatal(1,"unused X propagated into output");
                saved_data=c_data;saved_a_address=a_address;saved_b_address=b_address;saved_c_valid=c_valid;
                if (cycle_ready) begin
                    commits=commits+1;
                    for(idx=0;idx<P*C;idx=idx+1) if(c_valid[idx]) begin
                        addr=c_address[idx*32 +: 32];row=addr/n;col=addr%n;
                        if(addr>=m*n || seen[addr]) $fatal(1,"duplicate/out-of-range output");
                        expected=accumulate ? seed(addr) : 32'd0;
                        for(kk=0;kk<k;kk=kk+1) expected=expected+av(row*k+kk)*bv(kk*n+col);
                        if(c_data[idx*32 +: 32] !== expected)
                            $fatal(1,"wrong output %0d: %h expected %h",addr,c_data[idx*32 +: 32],expected);
                        seen[addr]=1;writes=writes+1;
                    end
                end else stalls=stalls+1;
                tick();cycles=cycles+1;
                if(!cycle_ready && (c_data !== saved_data || a_address !== saved_a_address ||
                    b_address !== saved_b_address || c_valid !== saved_c_valid))
                    $fatal(1,"stalled state changed");
                if(cycles>200) $fatal(1,"timeout");
            end
            if(writes!=m*n || commits!=expected_cycles || logical_cycles!=commits ||
                elapsed_cycles!=commits+stalls || stall_cycles!=stalls || done !== 1'b1)
                $fatal(1,"completion/counter mismatch");
        end
    endtask

    initial begin
        tick();rst=0;#1;
        if(busy !== 1'b0 || cmd_ready !== 1'b1 || done !== 1'b0 || c_valid !== '0)
            $fatal(1,"reset state unknown or wrong");
        execute(4,5,9,1,1);
        execute(3,7,4,0,0);
        execute(1,1,1,1,1);
        $display("PASS four-state invalid-lane/seed poisoning, wrap, stalls and reset");
        $finish;
    end
endmodule
