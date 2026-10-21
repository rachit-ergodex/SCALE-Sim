# Reuse a preserved 200 MHz full-compute synthesis checkpoint at a lower clock.
proc assert_checkpoint_identity {design} {
    set part [get_property PART $design]
    set top [get_property TOP $design]
    set name [get_property NAME $design]
    # NAME is an in-memory alias (e.g. checkpoint_post_synth), not the RTL top.
    puts "SCALESIM_CHECKPOINT_IDENTITY part=$part top=$top design_name=$name"
    if {$part ne "xcvu47p-fsvh2892-2-e"} {
        error "Unexpected checkpoint part: $part"
    }
    if {$top ne "decode_f2_compute"} {
        error "Unexpected checkpoint top: $top (design alias: $name)"
    }
}
# Reports from a failed route are diagnostic evidence, never closure artifacts.
proc write_route_metrics {run route_completed} {
    set fp [open $run/metrics.tsv w]
    puts $fp "stage\troute"
    puts $fp "route_command_completed\t$route_completed"
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
    foreach status {UNROUTED PARTIALLY_ROUTED CONFLICTS} {
        set count [llength [get_nets -hierarchical -quiet -filter "ROUTE_STATUS == $status"]]
        puts $fp "nets_$status\t$count"
    }
    close $fp
}

proc classify_sampled_paths {paths input_names output_names} {
    set categories [dict create input_boundary {} output_boundary {} input_to_output {} internal {}]
    foreach path $paths {
        set from_input [dict exists $input_names [get_property STARTPOINT_PIN $path]]
        set to_output [dict exists $output_names [get_property ENDPOINT_PIN $path]]
        if {$from_input && $to_output} {
            set category input_to_output
        } elseif {$from_input} {
            set category input_boundary
        } elseif {$to_output} {
            set category output_boundary
        } else {
            set category internal
        }
        dict lappend categories $category $path
    }
    return $categories
}

proc report_sampled_category {run kind category paths} {
    set output $run/${kind}_${category}_sample.rpt
    if {![llength $paths]} {
        set fp [open $output w]
        puts $fp "No $category paths occurred in this bounded global worst-path sample."
        puts $fp "This is NOT evidence that the category has no timing violations."
        close $fp
    } else {
        # -of_objects already specifies path type/delay. Adding -path_type here
        # is ignored by Vivado (12-1072); preserve the path objects as returned.
        report_timing -of_objects $paths -max_paths [llength $paths] -file $output
    }
}

proc collect_scoped_path_reports {run} {
    # A bounded global sample avoids Vivado 12-4439 from giant -from/-to lists.
    # Classify actual endpoint names: clock selectors also include timed IO and
    # cannot truthfully be described as register-to-register-only selections.
    # The mandatory global timing/coverage/DRC reports remain the closure gates.
    set sample_limit 200
    set inputs [dict create]
    set outputs [dict create]
    foreach port [get_ports -filter {DIRECTION == IN}] {dict set inputs $port 1}
    foreach port [get_ports -filter {DIRECTION == OUT}] {dict set outputs $port 1}
    set fp [open $run/sampled_path_reports.tsv w]
    puts $fp "category\tdelay\tstatus\tpaths\tdetail"
    set note [open $run/sampled_path_scope.txt w]
    puts $note "Supplemental classification of at most $sample_limit globally worst setup and hold paths each."
    puts $note "Categories use actual startpoint/endpoint port names, not clock selectors."
    puts $note "An absent category means not present in the sample, never passing timing."
    puts $note "These samples do not enumerate all violations or replace mandatory global reports/audit."
    close $note
    set failures 0
    foreach {kind delay} {setup max hold min} {
        if {[catch {
            set paths [get_timing_paths -delay_type $delay -max_paths $sample_limit -nworst 1]
            if {[llength $paths] > $sample_limit} {error "Timing sample exceeded its bound"}
            set categories [classify_sampled_paths $paths $inputs $outputs]
        } detail]} {
            incr failures
            set detail [string map [list "\n" "\\n" "\r" "\\r" "\t" "\\t"] $detail]
            puts $fp "all\t$delay\tfailed\t0\t$detail"
            puts stderr "SAMPLED_TIMING_QUERY_FAILED $delay: $detail"
            flush $fp
            continue
        }
        dict for {category selected} $categories {
            set count [llength $selected]
            if {[catch {report_sampled_category $run $kind $category $selected} detail]} {
                incr failures
                set detail [string map [list "\n" "\\n" "\r" "\\r" "\t" "\\t"] $detail]
                puts $fp "$category\t$delay\tfailed\t$count\t$detail"
                puts stderr "SAMPLED_TIMING_REPORT_FAILED $category/$delay: $detail"
            } else {
                set status [expr {$count ? "sampled" : "not_in_sample"}]
                puts $fp "$category\t$delay\t$status\t$count\t"
            }
            flush $fp
        }
    }
    close $fp
    return $failures
}

proc capture_route_failure {run message options} {
    set fp [open $run/route_failure.txt w]
    puts $fp "route_design failed; all following artifacts are diagnostic only."
    puts $fp $message
    foreach key {-errorcode -errorinfo} {
        if {[dict exists $options $key]} {puts $fp "$key: [dict get $options $key]"}
    }
    close $fp
    set commands [list \
        [list checkpoint [list write_checkpoint -force $run/failed_route.dcp]] \
        [list timing_summary [list report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $run/route_timing.rpt]] \
        [list coverage [list check_timing -verbose -file $run/route_check_timing.rpt]] \
        [list utilization [list report_utilization -hierarchical -file $run/route_utilization.rpt]] \
        [list drc [list report_drc -file $run/route_drc.rpt]] \
        [list setup [list report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file $run/setup_paths.rpt]] \
        [list hold [list report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file $run/hold_paths.rpt]]]
    lappend commands [list sampled_paths [list collect_scoped_path_reports $run]]
    foreach {name command} {
        route_status report_route_status
        clock_interaction report_clock_interaction
        methodology report_methodology
    } {
        lappend commands [list $name [list $command -file $run/${name}.rpt]]
    }
    lappend commands \
        [list exceptions [list report_exceptions -coverage -file $run/exceptions.rpt]] \
        [list congestion [list report_design_analysis -congestion -file $run/route_congestion.rpt]] \
        [list constraints [list write_xdc -force $run/failed_route_resolved.xdc]] \
        [list metrics [list write_route_metrics $run 0]]
    set log [open $run/route_failure_capture.tsv w]
    puts $log "artifact\tstatus\tdetail"
    foreach item $commands {
        lassign $item label command
        puts $log "$label\tstarted\t"
        flush $log
        # Each report is independent: a failing DRC/report must not discard the
        # remaining evidence, nor replace the original routing error.
        if {[catch {uplevel #0 $command} detail]} {
            set detail [string map [list "\n" "\\n" "\r" "\\r" "\t" "\\t"] $detail]
            puts $log "$label\tfailed\t$detail"
            puts stderr "ROUTE_DIAGNOSTIC_FAILED $label: $detail"
        } else {
            puts $log "$label\tcompleted\t"
        }
        flush $log
    }
    close $log
}

proc route_with_failure_capture {run} {
    if {[catch {route_design -directive Explore -tns_cleanup} message options]} {
        if {[catch {capture_route_failure $run $message $options} capture_error]} {
            puts stderr "ROUTE_FAILURE_CAPTURE_ABORTED: $capture_error"
        }
        # Preserve Vivado's original error code, stack and nonzero exit status.
        return -options $options $message
    }
}

# Arguments: checkpoint new-output target-period-ns preflight|route threads
if {[llength $argv] != 5} {error "Expected checkpoint output period preflight|route threads"}
set checkpoint [file normalize [lindex $argv 0]]
set run [file normalize [lindex $argv 1]]
set period [lindex $argv 2]
set stage [lindex $argv 3]
set threads [lindex $argv 4]
if {![string is double -strict $period] || !($period >= 5.0 && $period < Inf)} {
    error "Expected a finite clock period of at least 5 ns"
}
if {$stage ni {preflight route}} {error "Invalid stage"}
if {![string is integer -strict $threads] || $threads < 1 || $threads > 8} {
    error "Threads must be between 1 and 8"
}
file mkdir $run
cd $run
set_param general.maxThreads $threads
set_msg_config -severity {CRITICAL WARNING} -new_severity ERROR
open_checkpoint $checkpoint
assert_checkpoint_identity [current_design]
if {[llength [get_clocks]] != 1 || [llength [get_clocks decode_core]] != 1 ||
    abs([get_property PERIOD [get_clocks decode_core]] - 5.0) > 0.001} {
    error "Baseline must have exactly one 200 MHz decode_core clock"
}
set data_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set data_outputs [get_ports -filter {DIRECTION == OUT}]
if {[llength [get_ports clk]] != 1 || [llength $data_inputs] != 164453 ||
    [llength $data_outputs] != 407812} {
    error "Unexpected full 64x64 compute boundary width"
}

proc reject_timing_exceptions {path} {
    set fp [open $path r]
    set contents [read $fp]
    close $fp
    # Check canonical resolved commands, not the potentially indirect source Tcl.
    if {[regexp -line {^\s*(set_false_path|set_multicycle_path|set_clock_groups|set_max_delay|set_min_delay|set_case_analysis|set_disable_timing)(\s|$)} $contents]} {
        error "Unexpected timing exception or case analysis in $path"
    }
}
write_xdc -force $run/baseline_resolved.xdc
reject_timing_exceptions $run/baseline_resolved.xdc

# Replacing an existing clock may remove constraints referring to it. Therefore
# reapply all boundary delays and both uncertainties explicitly after replacement.
create_clock -name decode_core -period $period [get_ports clk]
set_clock_uncertainty -setup 0.250 [get_clocks decode_core]
set_clock_uncertainty -hold 0.100 [get_clocks decode_core]
foreach {ports command} [list $data_inputs set_input_delay $data_outputs set_output_delay] {
    set constrained 0
    for {set offset 0} {$offset < [llength $ports]} {incr offset 4096} {
        set chunk [lrange $ports $offset [expr {$offset + 4095}]]
        $command -clock decode_core -max 1.000 $chunk
        $command -clock decode_core -min 0.000 $chunk
        incr constrained [llength $chunk]
    }
    if {$constrained != [llength $ports]} {error "Incomplete boundary coverage"}
}
if {[llength [get_clocks]] != 1 ||
    abs([get_property PERIOD [get_clocks decode_core]] - $period) > 0.001} {
    error "Retarget did not produce exactly one clock at the requested period"
}
write_xdc -force $run/retarget_resolved.xdc
reject_timing_exceptions $run/retarget_resolved.xdc
write_checkpoint -force $run/post_retarget.dcp

proc reports {run name} {
    report_timing_summary -delay_type min_max -report_unconstrained \
        -check_timing_verbose -file $run/${name}_timing.rpt
    check_timing -verbose -file $run/${name}_check_timing.rpt
    report_utilization -hierarchical -file $run/${name}_utilization.rpt
    report_drc -file $run/${name}_drc.rpt
}
reports $run retarget
report_exceptions -coverage -file $run/retarget_exceptions.rpt
set fp [open $run/retarget_check_timing.rpt r]
set coverage [read $fp]
close $fp
foreach check {no_clock constant_clock multiple_clock loops no_input_delay no_output_delay partial_input_delay partial_output_delay unconstrained_internal_endpoints} {
    set pattern [format {checking\s+%s\s+\(([0-9]+)\)} $check]
    if {![regexp -nocase $pattern $coverage ignored count] || $count != 0} {
        error "Retarget timing coverage failed or missing: $check"
    }
}
set fp [open $run/preflight_passed.txt w]
puts $fp "PASS full4096MAC checkpoint retarget; period_ns=$period; inputs=164453; outputs=407812; coverage complete; no timing exceptions"
close $fp
if {$stage eq "preflight"} {
    puts "COMPUTE_RETARGET_PREFLIGHT_COMPLETE: no implementation or closure claim"
    close_design
    exit
}
opt_design
write_checkpoint -force $run/post_opt.dcp
place_design -directive Explore
write_checkpoint -force $run/post_place.dcp
reports $run place
report_design_analysis -congestion -file $run/place_congestion.rpt
phys_opt_design -directive AggressiveExplore
write_checkpoint -force $run/post_phys_opt.dcp
route_with_failure_capture $run
write_checkpoint -force $run/post_route.dcp
reports $run route
report_timing -delay_type max -max_paths 50 -path_type full_clock_expanded -file $run/setup_paths.rpt
report_timing -delay_type min -max_paths 50 -path_type full_clock_expanded -file $run/hold_paths.rpt
report_route_status -file $run/route_status.rpt
report_clock_interaction -file $run/clock_interaction.rpt
report_exceptions -coverage -file $run/exceptions.rpt
report_methodology -file $run/methodology.rpt
report_design_analysis -congestion -file $run/route_congestion.rpt
write_route_metrics $run 1
# Even failure to create the supplemental status file cannot invalidate the
# mandatory global evidence already written above. Record that error in the log.
if {[catch {collect_scoped_path_reports $run} detail]} {
    puts stderr "SCOPED_TIMING_REPORT_COLLECTION_FAILED: $detail"
}
puts "COMPUTE_RETARGET_ROUTE_COMPLETE: run the period-specific report audit; not F2 shell closure"
close_design
