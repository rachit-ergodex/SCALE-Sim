if {[llength $argv] != 2} {error "Expected probe-root baseline|dsp"}
lassign $argv root variant
if {$variant ni {baseline dsp}} {error "Unknown variant"}
set root [file normalize $root]
set_param general.maxThreads 8
set_msg_config -severity {CRITICAL WARNING} -new_severity ERROR
set arguments [list -sv]
lappend arguments $root/decode_os_core.sv
read_verilog {*}$arguments
read_verilog -sv $root/decode_compute_timing_harness.sv
synth_design -top decode_compute_timing_harness -part xcvu47p-fsvh2892-2-e -mode out_of_context -flatten_hierarchy none -verilog_define SCALESIM_F2_USE_DSP=1 -generic [list PARTITIONS=4 COLS=8 MAX_M=4 MAX_K=8192]
set period_ns 10
source $root/harness_constraints.tcl
report_utilization -file synth_utilization_flat.rpt
report_utilization -hierarchical -file synth_utilization_hier.rpt
report_timing_summary -delay_type min_max -report_unconstrained -file synth_timing.rpt
write_checkpoint -force post_synth.dcp
write_verilog -force -mode funcsim post_synth.v
set cells [get_cells -hierarchical -filter {REF_NAME == DSP48E2}]
set fp [open dsp_mapping.tsv w]
puts $fp "variant\t$variant"
puts $fp "dsp_count\t[llength $cells]"
puts $fp "cell\tUSE_MULT\tAREG\tBREG\tCREG\tMREG\tPREG"
foreach cell $cells {
 puts $fp "$cell\t[get_property USE_MULT $cell]\t[get_property AREG $cell]\t[get_property BREG $cell]\t[get_property CREG $cell]\t[get_property MREG $cell]\t[get_property PREG $cell]"
}
close $fp
set fp [open complete.txt w]; puts $fp "Synthesis mapping probe completed; no functional or timing closure claim."; close $fp
