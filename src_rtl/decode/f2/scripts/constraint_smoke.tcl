# Usage: vivado -mode batch -source constraint_smoke.tcl -tclargs source-root new-output
set root [file normalize [lindex $argv 0]]
set run [file normalize [lindex $argv 1]]
file mkdir $run
cd $run
set_param general.maxThreads 1
set_msg_config -severity {CRITICAL WARNING} -new_severity ERROR
create_project -in_memory -part xcvu47p-fsvh2892-2-e
read_verilog -sv $root/src_rtl/decode/f2/scripts/constraint_smoke.sv
read_xdc -unmanaged -mode out_of_context $root/src_rtl/decode/f2/constraints/compute_200mhz.tcl
synth_design -mode out_of_context -top decode_constraint_smoke -part xcvu47p-fsvh2892-2-e
check_timing -verbose -file check_timing.rpt
set fp [open check_timing.rpt r]
set coverage [read $fp]
close $fp
foreach check {no_clock constant_clock multiple_clock loops no_input_delay no_output_delay partial_input_delay partial_output_delay unconstrained_internal_endpoints} {
    set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $check]
    if {![regexp -nocase $pattern $coverage ignored count] || $count != 0} {
        error "Constraint smoke coverage failed or missing: $check"
    }
}
if {[llength [get_ports -filter {DIRECTION == IN && NAME != clk}]] != 4098 ||
    [llength [get_ports -filter {DIRECTION == OUT}]] != 4097} {
    error "Constraint smoke ports unexpectedly changed"
}
report_timing_summary -delay_type min_max -report_unconstrained -file timing.rpt
write_xdc -force resolved.xdc
set fp [open passed.txt w]
puts $fp "PASS unmanaged Tcl constraints, two chunks per boundary, all coverage checks zero"
close $fp
exit
