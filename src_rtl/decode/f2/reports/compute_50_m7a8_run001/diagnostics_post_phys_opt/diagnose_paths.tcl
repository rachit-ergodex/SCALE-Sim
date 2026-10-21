set checkpoint [lindex $argv 0]
set out [lindex $argv 1]
file mkdir $out
set_param general.maxThreads 8
open_checkpoint $checkpoint
set registers [all_registers]
set inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set outputs [all_outputs]
report_clocks -file $out/clocks.rpt
report_timing_summary -delay_type min_max -report_unconstrained -check_timing_verbose -file $out/timing_summary.rpt
foreach delay {min max} {
 foreach {kind from to} [list internal $registers $registers input_to_register $inputs $registers register_to_output $registers $outputs feedthrough $inputs $outputs] {
  report_timing -delay_type $delay -from $from -to $to -max_paths 50 -nworst 1 -path_type full_clock_expanded -file $out/${kind}_${delay}.rpt
 }
}
set fp [open $out/summary.tsv w]
puts $fp "kind\tdelay\tpaths_sampled\tworst_slack_ns\tstartpoint\tendpoint"
foreach delay {min max} {
 foreach {kind from to} [list internal $registers $registers input_to_register $inputs $registers register_to_output $registers $outputs feedthrough $inputs $outputs] {
  set paths [get_timing_paths -delay_type $delay -from $from -to $to -max_paths 1 -nworst 1]
  if {[llength $paths]} {
   set p [lindex $paths 0]
   puts $fp "$kind\t$delay\t[llength $paths]\t[get_property SLACK $p]\t[get_property STARTPOINT_PIN $p]\t[get_property ENDPOINT_PIN $p]"
  } else { puts $fp "$kind\t$delay\t0\tNA\tNA\tNA" }
 }
}
close $fp
set fp [open $out/complete.txt w]
puts $fp "Diagnostic post_phys_opt snapshot; not routed timing signoff"
close $fp
close_design
