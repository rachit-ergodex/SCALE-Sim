# Usage (normally called by run_compute_ooc.py): source-root output synth|route threads
if {[llength $argv] != 4} {error "Expected source-root output synth|route threads"}
set root [file normalize [lindex $argv 0]]
set run [file normalize [lindex $argv 1]]
set stage [lindex $argv 2]
set threads [lindex $argv 3]
if {$stage ni {synth route}} {error "Invalid stage: $stage"}
if {![string is integer -strict $threads] || $threads < 1 || $threads > 8} {
    error "Threads must be between 1 and 8 (Vivado limit)"
}
file mkdir $run
cd $run
set_param general.maxThreads $threads
set part xcvu47p-fsvh2892-2-e
create_project -in_memory -part $part
read_verilog -sv $root/src_rtl/decode/rtl/decode_os_core.sv
read_verilog -sv $root/src_rtl/decode/generated/decode_f2_compute.sv
# Missing constraints must stop the run, rather than silently reaching P&R.
set_msg_config -severity {CRITICAL WARNING} -new_severity ERROR
read_xdc -unmanaged -mode out_of_context $root/src_rtl/decode/f2/constraints/compute_200mhz.tcl
synth_design -mode out_of_context -top decode_f2_compute -part $part \
    -flatten_hierarchy rebuilt -keep_equivalent_registers

proc reports {run name} {
    report_timing_summary -delay_type min_max -report_unconstrained \
        -check_timing_verbose -file $run/${name}_timing.rpt
    check_timing -verbose -file $run/${name}_check_timing.rpt
    report_utilization -hierarchical -file $run/${name}_utilization.rpt
    report_drc -file $run/${name}_drc.rpt
}
write_checkpoint -force $run/post_synth.dcp
reports $run synth
# Fail before placement if any boundary budget or clock constraint was lost.
if {[llength [get_ports -filter {DIRECTION == IN && NAME != clk}]] != 164453 ||
    [llength [get_ports -filter {DIRECTION == OUT}]] != 407812} {
    error "Unexpected full 64x64 compute boundary width"
}
set coverage_file [open $run/synth_check_timing.rpt r]
set coverage [read $coverage_file]
close $coverage_file
foreach check {no_clock constant_clock multiple_clock loops no_input_delay no_output_delay partial_input_delay partial_output_delay unconstrained_internal_endpoints} {
    set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $check]
    if {![regexp -nocase $pattern $coverage ignored count] || $count != 0} {
        error "Pre-placement timing coverage failed or missing: $check"
    }
}
if {$stage eq "route"} {
    opt_design
    write_checkpoint -force $run/post_opt.dcp
    place_design -directive Explore
    write_checkpoint -force $run/post_place.dcp
    reports $run place
    report_design_analysis -congestion -file $run/place_congestion.rpt
    phys_opt_design -directive AggressiveExplore
    write_checkpoint -force $run/post_phys_opt.dcp
    # Alex's version-specific leaf-clock workaround is intentionally not applied
    # to this unrelated OOC design. A tool failure must be recorded and diagnosed.
    route_design -directive Explore -tns_cleanup
    write_checkpoint -force $run/post_route.dcp
    reports $run route
    report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded \
        -file $run/setup_paths.rpt
    report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded \
        -file $run/hold_paths.rpt
    report_route_status -file $run/route_status.rpt
    report_clock_interaction -file $run/clock_interaction.rpt
    report_exceptions -coverage -file $run/exceptions.rpt
    report_methodology -file $run/methodology.rpt
    report_design_analysis -congestion -file $run/route_congestion.rpt
}

# Machine-readable checks complement (not replace) the saved native reports.
set fp [open $run/metrics.tsv w]
puts $fp "stage\t$stage"
puts $fp "part\t[get_property PART [current_design]]"
puts $fp "clock_count\t[llength [get_clocks]]"
puts $fp "clock_period_ns\t[get_property PERIOD [get_clocks decode_core]]"
foreach {name delay} {setup max hold min} {
    set paths [get_timing_paths -delay_type $delay -max_paths 1]
    puts $fp "${name}_path_count\t[llength $paths]"
    if {[llength $paths]} {puts $fp "${name}_slack_ns\t[get_property SLACK $paths]"}
}
foreach {key severity} {drc_errors Error drc_critical_warnings {Critical Warning}} {
    set count 0
    foreach violation [get_drc_violations -quiet] {
        if {[get_property SEVERITY $violation] eq $severity} {incr count}
    }
    puts $fp "$key\t$count"
}
if {$stage eq "route"} {
    foreach status {UNROUTED PARTIALLY_ROUTED CONFLICTS} {
        set count [llength [get_nets -hierarchical -quiet -filter "ROUTE_STATUS == $status"]]
        puts $fp "nets_$status\t$count"
    }
}
close $fp
puts "COMPUTE_OOC_${stage}_COMPLETE: run the report audit; this is not F2 shell closure"
close_project
