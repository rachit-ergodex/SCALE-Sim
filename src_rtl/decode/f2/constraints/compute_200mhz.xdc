# Component OOC environment, not a board-level timing exception file.
# The 1 ns boundary budgets are provisional contracts with the future banked
# SRAM adapter. Both min and max paths, including synchronous reset, are timed.
create_clock -name decode_core -period 5.000 [get_ports clk]
set_clock_uncertainty -setup 0.250 [get_clocks decode_core]
set_clock_uncertainty -hold 0.100 [get_clocks decode_core]
set data_inputs [remove_from_collection [all_inputs] [get_ports clk]]
set_input_delay -clock decode_core -max 1.000 $data_inputs
set_input_delay -clock decode_core -min 0.000 $data_inputs
set_output_delay -clock decode_core -max 1.000 [all_outputs]
set_output_delay -clock decode_core -min 0.000 [all_outputs]
# No false paths, multicycles, asynchronous clock groups or package pins.
