# Registered physical timing experiment. No timing exceptions or waived paths.
if {[llength $argv] != 8} {error "Expected source output partitions cols period synth|route threads checkpoint|none"}
lassign $argv source_root run partitions cols period_ns stage threads checkpoint
set source_root [file normalize $source_root]
set run [file normalize $run]
foreach value [list $partitions $cols] {
    if {![string is integer -strict $value] || $value < 1 || $value > 64} {error "Invalid geometry"}
}
if {$period_ns ni {10 20} || $stage ni {synth route}} {error "Expected 50/100 MHz and synth/route"}
if {![string is integer -strict $threads] || $threads < 1 || $threads > 8} {error "Invalid thread limit"}
file mkdir $run
cd $run
set_param general.maxThreads $threads
set_msg_config -severity {CRITICAL WARNING} -new_severity ERROR

proc assert_design {} {
    if {[get_property PART [current_design]] ne "xcvu47p-fsvh2892-2-e" ||
        [get_property TOP [current_design]] ne "decode_compute_timing_harness"} {error "Wrong harness design"}
    set buffers [get_cells -hierarchical -filter {REF_NAME =~ BUFG*}]
    if {[llength $buffers] != 1} {error "Expected one actual global clock buffer"}
    set buffer [lindex $buffers 0]
    set reference [get_property REF_NAME $buffer]
    # UltraScale may normalize the explicit BUFG into BUFGCE. Accept that
    # mapping only for our named instance on the actual input-to-core path.
    if {$reference ni {BUFG BUFGCE} || ![string match "core_clock_buffer*" [get_property NAME $buffer]]} {
        error "Unexpected global clock buffer: $buffer ($reference)"
    }
    set input_net [get_nets -of_objects [get_pins $buffer/I]]
    set output_net [get_nets -of_objects [get_pins $buffer/O]]
    set port_net [get_nets -of_objects [get_ports clk]]
    set core_net [get_nets -of_objects [get_pins core/clk]]
    if {[llength $input_net] != 1 || [llength $output_net] != 1 ||
        $input_net ne $port_net || $output_net ne $core_net || $input_net eq $output_net} {
        error "Global buffer is not connected between clk and the real core clock"
    }
    puts "HARNESS_GLOBAL_BUFFER name=$buffer ref=$reference input=$input_net output=$output_net"
    if {[llength [get_cells -quiet core]] != 1} {error "Real compute core hierarchy is missing"}
    if {![llength [get_cells -hierarchical -filter {NAME =~ core/* && IS_SEQUENTIAL == 1}]]} {
        error "Compute core state was removed"
    }
}
proc assert_constraints {run period} {
    if {[llength [get_clocks]] != 1 || [llength [get_clocks harness_clock]] != 1 ||
        abs([get_property PERIOD [get_clocks harness_clock]] - $period) > 0.001} {error "Wrong harness clock"}
    write_xdc -force $run/resolved.xdc
    set fp [open $run/resolved.xdc r]; set contents [read $fp]; close $fp
    if {[regexp -line {^\s*(set_false_path|set_multicycle_path|set_clock_groups|set_max_delay|set_min_delay|set_case_analysis|set_disable_timing)(\s|$)} $contents]} {
        error "Timing exceptions are forbidden in the harness experiment"
    }
}
proc report_stage {run label} {
    report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $run/${label}_timing.rpt
    check_timing -verbose -file $run/${label}_check_timing.rpt
    report_utilization -file $run/${label}_utilization_flat.rpt
    report_utilization -hierarchical -file $run/${label}_utilization.rpt
    report_drc -file $run/${label}_drc.rpt
}
proc assert_coverage {run label} {
    set fp [open $run/${label}_check_timing.rpt r]; set coverage [read $fp]; close $fp
    foreach check {no_clock constant_clock multiple_clock loops no_input_delay no_output_delay partial_input_delay partial_output_delay unconstrained_internal_endpoints} {
        set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $check]
        if {![regexp -nocase $pattern $coverage ignored count] || $count != 0} {error "Invalid coverage: $check"}
    }
    foreach violation [get_drc_violations -quiet] {
        if {[get_property SEVERITY $violation] in {Error {Critical Warning}}} {error "DRC blocks readiness"}
    }
}
proc write_metrics {run completed} {
    set fp [open $run/metrics.tsv w]
    puts $fp "stage\troute"
    puts $fp "route_command_completed\t$completed"
    puts $fp "part\t[get_property PART [current_design]]"
    puts $fp "clock_count\t[llength [get_clocks]]"
    puts $fp "clock_period_ns\t[get_property PERIOD [get_clocks harness_clock]]"
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
    foreach status {UNROUTED PARTIALLY_ROUTED CONFLICTS} {
        set count [llength [get_nets -hierarchical -quiet -filter "ROUTE_STATUS == $status"]]
        puts $fp "nets_$status\t$count"
    }
    close $fp
}
proc path_report_commands {run} {
    set commands [list]
    foreach {kind delay} {setup max hold min} {
        lappend commands ${kind}_all [list report_timing -delay_type $delay -max_paths 50 -path_type full_clock_expanded -file $run/${kind}_paths.rpt]
        # Clock objects avoid enormous endpoint collections and Vivado 12-4439.
        # This is a clock-domain report; clocked boundary paths may be included.
        lappend commands ${kind}_clock_domain [list report_timing -delay_type $delay \
            -from [get_clocks harness_clock] -to [get_clocks harness_clock] \
            -max_paths 50 -path_type full_clock_expanded -file $run/${kind}_clock_domain_paths.rpt]
        lappend commands ${kind}_input [list report_timing -delay_type $delay \
            -from [get_ports -filter {DIRECTION == IN && NAME != clk}] \
            -max_paths 20 -path_type full_clock_expanded -file $run/${kind}_input_paths.rpt]
        lappend commands ${kind}_output [list report_timing -delay_type $delay \
            -to [get_ports -filter {DIRECTION == OUT}] \
            -max_paths 20 -path_type full_clock_expanded -file $run/${kind}_output_paths.rpt]
    }
    return $commands
}
proc detailed_paths {run} {
    foreach {label command} [path_report_commands $run] {uplevel #0 $command}
}
proc capture_failed_route {run message options} {
    set fp [open $run/route_failure.txt w]
    puts $fp "Diagnostic artifacts only; route failed."
    puts $fp $message
    if {[dict exists $options -errorinfo]} {puts $fp [dict get $options -errorinfo]}
    close $fp
    set fp [open $run/route_failure_capture.tsv w]
    set commands [list \
        checkpoint [list write_checkpoint -force $run/failed_route.dcp] \
        timing [list report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $run/route_timing.rpt] \
        coverage [list check_timing -verbose -file $run/route_check_timing.rpt] \
        drc [list report_drc -file $run/route_drc.rpt] \
        utilization [list report_utilization -hierarchical -file $run/route_utilization.rpt] \
        route_status [list report_route_status -file $run/route_status.rpt] \
        metrics [list write_metrics $run 0]]
    set commands [concat $commands [path_report_commands $run]]
    foreach {label command} $commands {
        if {[catch {uplevel #0 $command} detail]} {
            puts $fp "$label\tfailed\t[string map [list \n {\n} \t {\t}] $detail]"
        } else {puts $fp "$label\tcompleted"}
        flush $fp
    }
    close $fp
}

if {$checkpoint eq "none"} {
    read_verilog -sv $source_root/src_rtl/decode/rtl/decode_os_core.sv
    read_verilog -sv $source_root/src_rtl/decode/f2/harness/decode_compute_timing_harness.sv
    # No simulation BUFG model or mapping fixture is in the synthesis source set.
    synth_design -top decode_compute_timing_harness -part xcvu47p-fsvh2892-2-e \
        -mode out_of_context -flatten_hierarchy none \
        -generic [list PARTITIONS=$partitions COLS=$cols MAX_M=4 MAX_K=8192]
} else {
    if {$stage ne "route"} {error "Checkpoint reuse is route-only"}
    open_checkpoint $checkpoint
}
assert_design
source $source_root/src_rtl/decode/f2/harness/harness_constraints.tcl
assert_constraints $run $period_ns
write_checkpoint -force $run/post_synth.dcp
report_stage $run synth
assert_coverage $run synth
report_exceptions -coverage -file $run/exceptions.rpt
set fp [open $run/synth_ready.txt w]; puts $fp "Source, clock, coverage, DRC and physical BUFG checks passed; unplaced timing is not closure."; close $fp
if {$stage eq "synth"} {exit}

opt_design
place_design -directive Explore
write_checkpoint -force $run/post_place.dcp
report_stage $run place
phys_opt_design -directive AggressiveExplore
# AggressiveExplore skipped -180 ps hold in the earlier run (250 ps threshold).
# Explicit hold repair is a physical change, not a timing exception.
phys_opt_design -aggressive_hold_fix
write_checkpoint -force $run/post_phys_opt.dcp
report_stage $run phys_opt
if {[catch {route_design -directive Explore -tns_cleanup} message options]} {
    if {[catch {capture_failed_route $run $message $options} detail]} {puts stderr "Failure capture: $detail"}
    return -options $options $message
}
write_checkpoint -force $run/post_route.dcp
report_stage $run route
assert_coverage $run route
detailed_paths $run
report_route_status -file $run/route_status.rpt
write_metrics $run 1
