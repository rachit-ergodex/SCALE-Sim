# Unmanaged OOC Tcl: read_xdc -unmanaged -mode out_of_context.
# Provisional boundary budgets include synchronous reset; no timing exceptions.
create_clock -name decode_core -period 5.000 [get_ports clk]
set_clock_uncertainty -setup 0.250 [get_clocks decode_core]
set_clock_uncertainty -hold 0.100 [get_clocks decode_core]
set data_inputs [get_ports -filter {DIRECTION == IN && NAME != clk}]
set data_outputs [get_ports -filter {DIRECTION == OUT}]
if {[llength [get_ports clk]] != 1 || [llength $data_inputs] == 0 || [llength $data_outputs] == 0} {
    error "Missing clock or data boundary ports"
}
# Bound each delay collection: the full core has over 400,000 output bits.
# Unmanaged mode is required for these Tcl loops/list operations.
foreach {ports command} [list $data_inputs set_input_delay $data_outputs set_output_delay] {
    set constrained 0
    for {set offset 0} {$offset < [llength $ports]} {incr offset 4096} {
        set chunk [lrange $ports $offset [expr {$offset + 4095}]]
        $command -clock decode_core -max 1.000 $chunk
        $command -clock decode_core -min 0.000 $chunk
        incr constrained [llength $chunk]
    }
    if {$constrained != [llength $ports]} {error "Incomplete boundary constraint coverage"}
}
puts "SCALESIM_BOUNDARY_INPUT_BITS=[llength $data_inputs] OUTPUT_BITS=[llength $data_outputs]"
