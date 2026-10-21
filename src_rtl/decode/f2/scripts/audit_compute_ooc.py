#!/usr/bin/env python3
"""Fail-closed audit of this flow's Vivado component reports (not F2 signoff)."""
import argparse
import json
import math
from pathlib import Path
import re


def audit(run: Path, expected_period_ns: float = 5.0) -> dict:
    if not math.isfinite(expected_period_ns) or expected_period_ns <= 0:
        raise ValueError("Expected clock period must be finite and positive")
    problems = []
    metrics = dict(line.split("\t", 1) for line in
                   (run / "metrics.tsv").read_text().splitlines())
    stage = metrics["stage"]
    if stage not in {"synth", "route"}:
        raise ValueError(f"Unrecognized stage: {stage}")
    prefix = "route" if stage == "route" else "synth"

    def number(key):
        value = float(metrics[key])
        if not math.isfinite(value):
            raise ValueError(f"Nonfinite metric {key}")
        return value

    # Legacy runs did not record completion explicitly. New failure captures
    # must remain failures even if someone changes the stage label, copies a
    # routed checkpoint, or partial timing reports otherwise look passing.
    if "route_command_completed" in metrics and number("route_command_completed") != 1:
        problems.append("route_design did not complete successfully")
    if (run / "route_failure.txt").exists():
        problems.append("Recorded route_design failure; reports are diagnostic only")

    if metrics["part"] != "xcvu47p-fsvh2892-2-e":
        problems.append("Unexpected FPGA part")
    if number("clock_count") != 1 or abs(number("clock_period_ns") - expected_period_ns) > 0.001:
        problems.append(f"Expected exactly one clock with period {expected_period_ns:g} ns")
    for kind in ("setup", "hold"):
        if number(f"{kind}_path_count") < 1:
            problems.append(f"No {kind} timing paths")
        elif number(f"{kind}_slack_ns") < 0:
            problems.append(f"Negative {kind} slack")
    for key in ("drc_errors", "drc_critical_warnings"):
        if number(key) != 0:
            problems.append(f"{key}={metrics[key]}")

    # Vivado check_timing headings include "checking no_clock (0)". Require
    # known checks; a changed report format cannot silently produce a pass.
    checks = dict((key, int(value)) for key, value in re.findall(
        r"checking\s+(\w+)\s+\((\d+)\)",
        (run / f"{prefix}_check_timing.rpt").read_text(), re.IGNORECASE))
    required = {"no_clock", "constant_clock", "multiple_clock", "loops",
                "no_input_delay", "no_output_delay", "partial_input_delay",
                "partial_output_delay", "unconstrained_internal_endpoints"}
    for key in sorted(required):
        if key not in checks:
            problems.append(f"Missing timing coverage check: {key}")
    for key, value in checks.items():
        if value:
            problems.append(f"Timing coverage {key}={value}")

    # Extract the numeric row immediately below Vivado's Design Timing Summary.
    # Keep all twelve values: setup, hold and pulse-width timing and endpoints.
    timing = (run / f"{prefix}_timing.rpt").read_text()
    summary = re.search(r"WNS\(ns\)[^\n]*TNS\(ns\)[^\n]*\n"
                        r"\s*[-\s]+\n([^\n]+)", timing)
    timing_values = []
    if summary:
        tokens = summary.group(1).split()
        if len(tokens) == 12:
            try:
                timing_values = [float(token) for token in tokens]
            except ValueError:
                pass
    if len(timing_values) != 12 or not all(map(math.isfinite, timing_values)):
        problems.append("Missing or unrecognized twelve-column timing summary")
        timing_values = []
    else:
        for index, label in ((0, "WNS"), (4, "WHS"), (8, "WPWS")):
            if timing_values[index] < 0:
                problems.append(f"{label} is negative")
        for index, label in ((1, "TNS"), (2, "setup failing endpoints"),
                             (5, "THS"), (6, "hold failing endpoints"),
                             (9, "TPWS"), (10, "pulse-width failing endpoints")):
            if timing_values[index] != 0:
                problems.append(f"{label} is nonzero")
    if stage == "route":
        for key in ("nets_UNROUTED", "nets_PARTIALLY_ROUTED", "nets_CONFLICTS"):
            if number(key) != 0:
                problems.append(f"{key}={metrics[key]}")
        if not (run / "post_route.dcp").is_file():
            problems.append("Missing routed checkpoint")
    return {
        "status": "passed" if not problems else "failed",
        "stage": stage,
        "scope": "Compute-only OOC on the full VU47P; no AWS shell or HBM integration",
        "component_routed_timing_pass": stage == "route" and not problems,
        "f2_shell_timing_closed": False,
        "expected_clock_period_ns": expected_period_ns,
        "metrics": metrics,
        "timing_checks": checks,
        "timing_summary_values": timing_values,
        "problems": problems,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    parser.add_argument("--expected-period-ns", type=float, default=5.0,
                        help="Required clock period; defaults to the original 200 MHz target")
    args = parser.parse_args()
    try:
        result = audit(args.run, expected_period_ns=args.expected_period_ns)
    except (OSError, ValueError, KeyError) as exc:
        result = {"status": "failed", "f2_shell_timing_closed": False,
                  "problems": [f"Incomplete or unrecognized reports: {exc}"]}
    (args.run / "audit.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
