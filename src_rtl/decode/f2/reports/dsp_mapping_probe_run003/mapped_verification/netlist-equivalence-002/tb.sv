`timescale 1ns/1ps
module tb;
  logic clk;
  logic rst;
  logic cmd_valid;
  logic [31:0] cmd_m;
  logic [31:0] cmd_k;
  logic [31:0] cmd_n;
  logic cmd_parallel_rows;
  logic cmd_accumulate;
  logic cycle_ready;
  logic [31:0] a_data;
  logic [255:0] b_data;
  logic [1023:0] seed_data;
  wire cmd_ready_got;
  wire busy_got;
  wire done_got;
  wire command_error_got;
  wire [3:0] a_valid_got;
  wire [127:0] a_address_got;
  wire [31:0] b_valid_got;
  wire [1023:0] b_address_got;
  wire [31:0] seed_valid_got;
  wire [31:0] c_valid_got;
  wire [1023:0] c_address_got;
  wire [1023:0] c_data_got;
  wire [63:0] logical_cycles_got;
  wire [63:0] elapsed_cycles_got;
  wire [63:0] stall_cycles_got;
  wire cmd_ready_ref;
  wire busy_ref;
  wire done_ref;
  wire command_error_ref;
  wire [3:0] a_valid_ref;
  wire [127:0] a_address_ref;
  wire [31:0] b_valid_ref;
  wire [1023:0] b_address_ref;
  wire [31:0] seed_valid_ref;
  wire [31:0] c_valid_ref;
  wire [1023:0] c_address_ref;
  wire [1023:0] c_data_ref;
  wire [63:0] logical_cycles_ref;
  wire [63:0] elapsed_cycles_ref;
  wire [63:0] stall_cycles_ref;
  mapped_core_observed dut_got (.clk(clk),
    .rst(rst),
    .cmd_valid(cmd_valid),
    .cmd_m(cmd_m),
    .cmd_k(cmd_k),
    .cmd_n(cmd_n),
    .cmd_parallel_rows(cmd_parallel_rows),
    .cmd_accumulate(cmd_accumulate),
    .cycle_ready(cycle_ready),
    .a_data(a_data),
    .b_data(b_data),
    .seed_data(seed_data),
    .cmd_ready(cmd_ready_got),
    .busy(busy_got),
    .done(done_got),
    .command_error(command_error_got),
    .a_valid(a_valid_got),
    .a_address(a_address_got),
    .b_valid(b_valid_got),
    .b_address(b_address_got),
    .seed_valid(seed_valid_got),
    .c_valid(c_valid_got),
    .c_address(c_address_got),
    .c_data(c_data_got),
    .logical_cycles(logical_cycles_got),
    .elapsed_cycles(elapsed_cycles_got),
    .stall_cycles(stall_cycles_got));
  decode_os_core_reference #(.PARTITIONS(4),.COLS(8),.MAX_M(4),.MAX_K(8192)) dut_ref (.clk(clk),
    .rst(rst),
    .cmd_valid(cmd_valid),
    .cmd_m(cmd_m),
    .cmd_k(cmd_k),
    .cmd_n(cmd_n),
    .cmd_parallel_rows(cmd_parallel_rows),
    .cmd_accumulate(cmd_accumulate),
    .cycle_ready(cycle_ready),
    .a_data(a_data),
    .b_data(b_data),
    .seed_data(seed_data),
    .cmd_ready(cmd_ready_ref),
    .busy(busy_ref),
    .done(done_ref),
    .command_error(command_error_ref),
    .a_valid(a_valid_ref),
    .a_address(a_address_ref),
    .b_valid(b_valid_ref),
    .b_address(b_address_ref),
    .seed_valid(seed_valid_ref),
    .c_valid(c_valid_ref),
    .c_address(c_address_ref),
    .c_data(c_data_ref),
    .logical_cycles(logical_cycles_ref),
    .elapsed_cycles(elapsed_cycles_ref),
    .stall_cycles(stall_cycles_ref));
  wire [3495:0] observable_got = {cmd_ready_got,busy_got,done_got,command_error_got,a_valid_got,a_address_got,b_valid_got,b_address_got,seed_valid_got,c_valid_got,c_address_got,c_data_got,logical_cycles_got,elapsed_cycles_got,stall_cycles_got};
  wire [3495:0] observable_ref = {cmd_ready_ref,busy_ref,done_ref,command_error_ref,a_valid_ref,a_address_ref,b_valid_ref,b_address_ref,seed_valid_ref,c_valid_ref,c_address_ref,c_data_ref,logical_cycles_ref,elapsed_cycles_ref,stall_cycles_ref};

  bit checks_enabled=0;
  logic [31:0] rng=32'hd5f2c0de;
  longint unsigned ticks=0, comparisons=0, valid_cases=0, invalid_cases=0, abort_cases=0;
  longint unsigned stall_checks=0, committed_steps=0;
  int operand_batches=0;
  string context_name="startup";

  function automatic logic [31:0] next_random();
    rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
    return rng;
  endfunction

  task automatic check_outputs(input string edge_name);
    int first_bad;
    if(checks_enabled) begin
      comparisons++;
      if((observable_got !== observable_ref) || $isunknown(observable_got) || $isunknown(observable_ref)) begin
        first_bad=-1;
        for(int bitno=0;bitno<3496;bitno++)
          if(first_bad<0 && observable_got[bitno] !== observable_ref[bitno]) first_bad=bitno;
        $display("TB_MISMATCH context=%s edge=%s tick=%0d first_bit=%0d ready=%b rst=%b",context_name,edge_name,ticks,first_bad,cycle_ready,rst);
        $display("got busy/done/error=%b%b%b ref=%b%b%b",busy_got,done_got,command_error_got,busy_ref,done_ref,command_error_ref);
        $display("got c_valid=%h c_data=%h",c_valid_got,c_data_got);
        $display("ref c_valid=%h c_data=%h",c_valid_ref,c_data_ref);
        $fatal(1,"Mapped UNISIM netlist disagrees with verified reference RTL");
      end
    end
  endtask

  task automatic tick();
    // Inputs are driven between calls; compare settled combinational outputs
    // before and after the rising edge, avoiding active/NBA scheduling races.
    clk=0; #2;check_outputs("before");
    #3;clk=1;#2;check_outputs("after");#3;ticks++;
  endtask

  task automatic operands();
    logic [31:0] word;
    operand_batches++;
    for(int p=0;p<4;p++) begin
      word=next_random();
      if(operand_batches%11==0) word=32'h80;
      if(operand_batches%13==0) word=32'h7f;
      a_data[p*8 +: 8]=word[7:0];
    end
    for(int lane=0;lane<32;lane++) begin
      word=next_random();
      if(operand_batches%11==0) word=32'h80;
      if(operand_batches%13==0) word=32'hff;
      b_data[lane*8 +: 8]=word[7:0];
      word=next_random();
      case((operand_batches+lane)%8)
        0:word=32'h7ffffffb;
        1:word=32'h80000005;
        2:word=32'hffffffff;
        3:word=32'h00000000;
        default:begin end
      endcase
      seed_data[lane*32 +: 32]=word;
    end
  endtask

  task automatic reset_core();
    rst=1;cmd_valid=0;cycle_ready=0;tick();
    rst=0;cmd_valid=0;cycle_ready=1;tick();
    if(busy_ref || !cmd_ready_ref) $fatal(1,"Reference reset protocol failed");
  endtask

  task automatic run_valid(input int m,input int k,input int n,input bit parallel,input bit accumulate);
    int parts,workers,expected,commits,stalls,elapsed;
    bit previous_ready;
    logic [31:0] random_word;
    context_name=$sformatf("valid M%0d K%0d N%0d par%0d acc%0d",m,k,n,parallel,accumulate);
    rst=0;cmd_m=m;cmd_k=k;cmd_n=n;cmd_parallel_rows=parallel;cmd_accumulate=accumulate;
    cmd_valid=1;cycle_ready=1;operands();tick();cmd_valid=0;
    if(!busy_ref || command_error_ref) $fatal(1,"Reference rejected legal command");
    parts=(n+7)/8;workers=parallel?((m<4/parts)?m:4/parts):1;
    expected=((m+workers-1)/workers)*(k+7);
    commits=0;stalls=0;elapsed=0;previous_ready=1;
    while(busy_ref) begin
      // Keep all operands and seeds unchanged across backpressure.
      if(previous_ready) operands();
      random_word=next_random();cycle_ready=(random_word%4)!=0;
      previous_ready=cycle_ready;
      random_word=next_random();cmd_valid=(random_word%17)==0;
      // Commands offered while busy must not change the active command.
      if(cmd_valid) begin cmd_m=0;cmd_k=8193;cmd_n=33;end
      tick();elapsed++;
      if(cycle_ready) commits++;else begin stalls++;stall_checks++;end
      if(elapsed>expected*12+100) $fatal(1,"Command failed to make progress");
    end
    cmd_valid=0;
    if(!done_ref || commits!=expected || logical_cycles_ref!=64'(commits) || elapsed_cycles_ref!=64'(elapsed) || stall_cycles_ref!=64'(stalls))
      $fatal(1,"Reference cycle accounting failed");
    valid_cases++;committed_steps+=64'(commits);
    cycle_ready=1;tick();
    if(valid_cases%64==0) $display("TB_PROGRESS valid_cases=%0d ticks=%0d",valid_cases,ticks);
  endtask

  task automatic run_invalid(input int m,input int k,input int n);
    context_name=$sformatf("invalid M%0d K%0d N%0d",m,k,n);
    cmd_m=m;cmd_k=k;cmd_n=n;cmd_valid=1;cycle_ready=1;tick();cmd_valid=0;
    if(!command_error_ref || busy_ref || !cmd_ready_ref) $fatal(1,"Invalid command accepted");
    invalid_cases++;tick();
  endtask

  task automatic run_abort(input bit parallel,input bit accumulate);
    context_name=$sformatf("abort par%0d acc%0d",parallel,accumulate);
    cmd_m=4;cmd_k=23;cmd_n=32;cmd_parallel_rows=parallel;cmd_accumulate=accumulate;
    cmd_valid=1;cycle_ready=1;operands();tick();cmd_valid=0;
    for(int i=0;i<13;i++) begin
      operands();cycle_ready=1;tick();
      cycle_ready=0;tick();tick();stall_checks+=2;
    end
    // Reset with backpressure and a simultaneously asserted command.
    rst=1;cmd_valid=1;cycle_ready=0;tick();
    rst=0;cmd_valid=0;cycle_ready=1;tick();abort_cases++;
    if(busy_ref || !cmd_ready_ref) $fatal(1,"Abort reset failed");
  endtask

  initial begin
    int k,fd;
    clk=0;rst=1;cmd_valid=0;cmd_m=0;cmd_k=0;cmd_n=0;
    cmd_parallel_rows=0;cmd_accumulate=0;cycle_ready=0;a_data=0;b_data=0;seed_data=0;
    // UNISIM glbl holds GSR for100ns. Exercise reset through its release.
    repeat(24) tick();checks_enabled=1;reset_core();
    for(int m=1;m<=4;m++)
      for(int n=1;n<=32;n++)
        for(int parallel=0;parallel<=1;parallel++)
          for(int accumulate=0;accumulate<=1;accumulate++) begin
            case((m+n+parallel+accumulate)%6)
              0:k=1;1:k=2;2:k=7;3:k=8;4:k=9;default:k=17;
            endcase
            run_valid(m,k,n,parallel!=0,accumulate!=0);
          end
    run_valid(1,8192,32,1,1);
    run_valid(4,8192,7,1,0);
    run_valid(4,8192,9,1,1);
    run_valid(4,8192,32,0,1);
    run_invalid(0,1,1);run_invalid(5,1,1);run_invalid(1,0,1);
    run_invalid(1,8193,1);run_invalid(1,1,0);run_invalid(1,1,33);
    for(int parallel=0;parallel<=1;parallel++)
      for(int accumulate=0;accumulate<=1;accumulate++) begin
        run_abort(parallel!=0,accumulate!=0);
        run_valid(4,19,17,parallel!=0,accumulate!=0);
      end
    if(valid_cases!=520 || invalid_cases!=6 || abort_cases!=4 || stall_checks==0 || comparisons!=2*(ticks-24))
      $fatal(1,"Incomplete equivalence coverage");
    fd=$fopen("results.tsv","w");
    if(fd==0) $fatal(1,"Could not create result marker");
    $fdisplay(fd,"status%cpassed",9);
    $fdisplay(fd,"valid_commands%c%0d",9,valid_cases);
    $fdisplay(fd,"invalid_commands%c%0d",9,invalid_cases);
    $fdisplay(fd,"mid_command_resets%c%0d",9,abort_cases);
    $fdisplay(fd,"clock_ticks%c%0d",9,ticks);
    $fdisplay(fd,"all_output_comparisons%c%0d",9,comparisons);
    $fdisplay(fd,"stall_cycles_checked%c%0d",9,stall_checks);
    $fdisplay(fd,"committed_steps%c%0d",9,committed_steps);
    $fdisplay(fd,"observed_output_bits%c3496",9);
    $fdisplay(fd,"initial_random_seed%cd5f2c0de",9);
    $fclose(fd);
    $display("TB_PASS valid=%0d invalid=%0d resets=%0d ticks=%0d comparisons=%0d stalls=%0d",valid_cases,invalid_cases,abort_cases,ticks,comparisons,stall_checks);
    $finish;
  end
  initial begin #20000000;$fatal(1,"Equivalence watchdog expired");end
endmodule
