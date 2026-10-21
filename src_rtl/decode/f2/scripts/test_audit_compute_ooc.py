"""Synthetic report parser tests; these are not timing evidence for the RTL."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("audit_compute_ooc", Path(__file__).with_name("audit_compute_ooc.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.metrics = {
            "stage": "route", "part": "xcvu47p-fsvh2892-2-e", "clock_count": "1",
            "clock_period_ns": "5.000", "setup_path_count": "1", "hold_path_count": "1",
            "setup_slack_ns": "0.125", "hold_slack_ns": "0.020",
            "drc_errors": "0", "drc_critical_warnings": "0", "nets_UNROUTED": "0",
            "nets_PARTIALLY_ROUTED": "0", "nets_CONFLICTS": "0"}
        self.checks = ["no_clock", "constant_clock", "multiple_clock", "loops",
                       "no_input_delay", "no_output_delay", "partial_input_delay",
                       "partial_output_delay", "unconstrained_internal_endpoints"]
        self.write_metrics()
        self.write_checks()
        self.write_timing()
        (self.run / "post_route.dcp").touch()

    def write_metrics(self):
        (self.run / "metrics.tsv").write_text("".join(f"{k}\t{v}\n" for k, v in self.metrics.items()))

    def write_checks(self, failing=None):
        (self.run / "route_check_timing.rpt").write_text("\n".join(
            f"{i}. checking {key} ({3 if key == failing else 0})" for i, key in enumerate(self.checks, 1)))

    def write_timing(self, tns="0.000"):
        (self.run / "route_timing.rpt").write_text(
            "WNS(ns) TNS(ns) TNS Failing Endpoints TNS Total Endpoints WHS(ns) THS(ns) THS Failing Endpoints THS Total Endpoints WPWS(ns) TPWS(ns) TPWS Failing Endpoints TPWS Total Endpoints\n"
            "------- ------- ------- ------- ------- ------- ------- ------- ------- ------- ------- -------\n"
            f"  0.125 {tns} 0 8192 0.020 0.000 0 8192 1.000 0.000 0 1024\n")

    def test_complete_route_pass_is_not_board_closure(self):
        result = MODULE.audit(self.run)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["component_routed_timing_pass"])
        self.assertFalse(result["f2_shell_timing_closed"])

    def test_100mhz_pass_requires_explicit_matching_target(self):
        self.metrics["clock_period_ns"] = "10.000"
        self.write_metrics()
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")
        result = MODULE.audit(self.run, expected_period_ns=10.0)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["expected_clock_period_ns"], 10.0)
        self.assertFalse(result["f2_shell_timing_closed"])
        self.write_timing(tns="-0.100")
        self.assertEqual(MODULE.audit(self.run, expected_period_ns=10.0)["status"], "failed")

    def test_old_clock_does_not_pass_retargeted_audit(self):
        self.assertEqual(MODULE.audit(self.run, expected_period_ns=10.0)["status"], "failed")

    def test_invalid_expected_period_is_rejected(self):
        for period in (0, -1, float("nan"), float("inf")):
            with self.subTest(period=period), self.assertRaises(ValueError):
                MODULE.audit(self.run, expected_period_ns=period)

    def test_missing_timing_coverage_fails(self):
        self.checks.remove("unconstrained_internal_endpoints")
        self.write_checks()
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")

    def test_unconstrained_endpoints_fail(self):
        self.write_checks("unconstrained_internal_endpoints")
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")

    def test_negative_tns_fails_even_with_positive_worst_path_metric(self):
        self.write_timing(tns="-0.100")
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")

    def test_hold_drc_and_route_violations_fail(self):
        for key, value in (("hold_slack_ns", "-0.01"), ("drc_errors", "1"),
                           ("drc_critical_warnings", "1"), ("nets_UNROUTED", "1"),
                           ("nets_PARTIALLY_ROUTED", "1"), ("nets_CONFLICTS", "1")):
            with self.subTest(key=key):
                before = self.metrics[key]
                self.metrics[key] = value
                self.write_metrics()
                self.assertEqual(MODULE.audit(self.run)["status"], "failed")
                self.metrics[key] = before

    def test_synthesis_success_is_not_routed_closure(self):
        self.metrics["stage"] = "synth"
        self.write_metrics()
        for suffix in ("check_timing", "timing"):
            (self.run / f"route_{suffix}.rpt").rename(self.run / f"synth_{suffix}.rpt")
        result = MODULE.audit(self.run)
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["component_routed_timing_pass"])

    def test_explicit_route_completion_is_required_when_recorded(self):
        # The fixture has positive timing, clean coverage and post_route.dcp.
        self.metrics["route_command_completed"] = "1"
        self.write_metrics()
        self.assertEqual(MODULE.audit(self.run)["status"], "passed")
        for value in ("0", "-1", "2"):
            with self.subTest(value=value):
                self.metrics["route_command_completed"] = value
                self.write_metrics()
                result = MODULE.audit(self.run)
                self.assertEqual(result["status"], "failed")
                self.assertFalse(result["component_routed_timing_pass"])
                self.assertIn("route_design did not complete successfully", result["problems"])
        del self.metrics["route_command_completed"]
        self.write_metrics()
        self.assertEqual(MODULE.audit(self.run)["status"], "passed")

    def test_route_failure_marker_overrides_positive_reports_and_completion(self):
        self.metrics["route_command_completed"] = "1"
        self.write_metrics()
        (self.run / "route_failure.txt").write_text("SYNTHETIC route failure")
        result = MODULE.audit(self.run)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["component_routed_timing_pass"])
        self.assertIn("Recorded route_design failure; reports are diagnostic only", result["problems"])

    def test_failure_evidence_cannot_be_bypassed_by_synthesis_stage_label(self):
        self.metrics["stage"] = "synth"
        for suffix in ("check_timing", "timing"):
            (self.run / f"route_{suffix}.rpt").rename(self.run / f"synth_{suffix}.rpt")
        self.metrics["route_command_completed"] = "0"
        self.write_metrics()
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")
        del self.metrics["route_command_completed"]
        self.write_metrics()
        (self.run / "route_failure.txt").touch()
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")

    def test_missing_summary_does_not_pass(self):
        (self.run / "route_timing.rpt").write_text("Unrecognized report\n")
        self.assertEqual(MODULE.audit(self.run)["status"], "failed")


if __name__ == "__main__":
    unittest.main()
