# Analysis-only physical harness. All paths remain timed; no false/multicycle paths.
# Source after setting period_ns, for example: set period_ns 20.0
if {![info exists period_ns] || ![string is double -strict $period_ns] ||
    !($period_ns > 0 && $period_ns < Inf)} {
    error "Set a finite positive period_ns before sourcing harness constraints"
}
create_clock -name harness_clock -period $period_ns [get_ports clk]
set_clock_uncertainty -setup 0.250 [get_clocks harness_clock]
set_clock_uncertainty -hold 0.100 [get_clocks harness_clock]
set harness_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set harness_outputs [get_ports -filter {DIRECTION == OUT}]
if {[llength [get_ports clk]] != 1 || [llength $harness_inputs] != 6 ||
    [llength $harness_outputs] != 1} {
    error "Unexpected physical harness boundary"
}
set_input_delay -clock harness_clock -max 1.000 $harness_inputs
set_input_delay -clock harness_clock -min 0.000 $harness_inputs
set_output_delay -clock harness_clock -max 1.000 $harness_outputs
set_output_delay -clock harness_clock -min 0.000 $harness_outputs
