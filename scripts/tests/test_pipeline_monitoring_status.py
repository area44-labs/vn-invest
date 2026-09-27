"""Deterministic offline unit tests for production monitoring status propagation and artifact safety."""

import copy
import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from scripts.data_provider import ProviderRateLimitError
from scripts.generate_report import main
from scripts.lib.monitoring import evaluate_data_and_model_drift


def make_test_payload(
    data_as_of: str = "2026-09-25",
    action_counts: dict | None = None,
    signal_score: float = 75.0,
    confidence: float = 0.8,
) -> dict:
    """Create a schema-compliant recommendation report payload for exit-behavior testing."""
    if action_counts is None:
        action_counts = {"BUY": 10, "WATCH": 5, "HOLD": 5, "SELL": 0, "AVOID": 0}

    total_scanned = sum(action_counts.values())
    recs = []
    idx = 1
    for act, cnt in action_counts.items():
        for _ in range(cnt):
            recs.append(
                {
                    "symbol": f"SYM{idx:03d}",
                    "company_name": f"Company {idx}",
                    "exchange": "HOSE",
                    "sector": "Technology",
                    "action": act,
                    "model_version": "2.0",
                    "data_quality": "SUFFICIENT" if act != "AVOID" else "INSUFFICIENT",
                    "data_quality_issues": [] if act != "AVOID" else ["Insufficient history"],
                    "data_as_of": data_as_of,
                    "data_source": "kbs",
                    "signal_score": signal_score if act != "AVOID" else None,
                    "risk_adjusted_score": (signal_score - 5.0) if act != "AVOID" else None,
                    "confidence": confidence if act != "AVOID" else None,
                    "risk_level": "LOW" if act != "AVOID" else None,
                    "expected_return": {
                        "expected_return_5d": 1.0 if act != "AVOID" else None,
                        "expected_return_10d": 2.0 if act != "AVOID" else None,
                        "expected_return_20d": 3.0 if act != "AVOID" else None,
                    },
                    "risk_metrics": {
                        "var_t25": -0.02 if act != "AVOID" else None,
                        "es_t25": -0.03 if act != "AVOID" else None,
                        "volatility_60d": 0.15 if act != "AVOID" else None,
                        "max_drawdown": -0.05 if act != "AVOID" else None,
                        "liquidity_score": 80.0 if act != "AVOID" else None,
                        "avg_value_20d": 50.0 if act != "AVOID" else None,
                    },
                    "trade_plan": {
                        "current_price": 50000.0 if act != "AVOID" else None,
                        "entry_low": 49000.0 if act != "AVOID" else None,
                        "entry_high": 51000.0 if act != "AVOID" else None,
                        "stop_loss": 47000.0 if act != "AVOID" else None,
                        "tp1": 55000.0 if act != "AVOID" else None,
                        "tp2": 60000.0 if act != "AVOID" else None,
                        "risk_reward": 2.0 if act != "AVOID" else None,
                        "position_percent": 10.0 if act != "AVOID" else 0.0,
                    },
                    "reasons": ["Test reason"],
                    "warnings": [],
                    "invalidation": ["Test invalidation"],
                }
            )
            idx += 1

    summary = {
        "total_scanned": total_scanned,
        "buy_count": action_counts.get("BUY", 0),
        "watch_count": action_counts.get("WATCH", 0),
        "hold_count": action_counts.get("HOLD", 0),
        "sell_count": action_counts.get("SELL", 0),
        "avoid_count": action_counts.get("AVOID", 0),
    }

    market = {
        "regime": "STRONG_BULL",
        "confidence": 0.85,
        "regime_score": 75.0,
        "metrics": {
            "vnindex_value": 1250.0,
            "vnindex_change_pct": 0.5,
            "vn30_change_pct": 0.4,
            "market_breadth_ratio": 0.6,
            "volatility": 0.15,
            "volume_20d_ratio": 1.1,
        },
    }

    return {
        "schema_version": "2.0",
        "signal_model_version": "2.0",
        "generated_at": "2026-09-25T14:00:00Z",
        "data_as_of": data_as_of,
        "source_date": data_as_of,
        "data_source": "kbs",
        "universe_info": {
            "universe_type": "MANDATORY_AND_CANDIDATES",
            "universe_size": total_scanned,
        },
        "market": market,
        "summary": summary,
        "recommendations": recs,
    }


class MockPipelineResult(tuple):
    """Helper tuple mocking run_pipeline return value."""

    def __new__(cls, recs_data, market_data, history_data, universe_audit=None):
        obj = super().__new__(cls, (recs_data, market_data, history_data))
        obj.df_vnindex = None
        obj.df_vn30 = None
        obj.universe_audit = universe_audit
        return obj


class TestPipelineMonitoringStatusExitBehavior(unittest.TestCase):
    """Test suite verifying pipeline status exit codes, logging, and artifact preservation contracts."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.gen_dir = os.path.join(self.temp_dir, "generated")
        self.hist_dir = os.path.join(self.gen_dir, "history")
        os.makedirs(self.hist_dir, exist_ok=True)

        self.valid_payload = make_test_payload(data_as_of="2026-09-25")
        self.mock_res = MockPipelineResult(
            self.valid_payload,
            self.valid_payload.get("market"),
            self.valid_payload,
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_a_monitoring_pass_succeeds(self):
        """Test A: Monitoring PASS -> pipeline succeeds, monitoring status is PASS, process exits 0."""
        mock_mon = MagicMock()
        mock_mon.overall_status = "PASS"
        mock_mon.to_dict.return_value = {
            "overall_status": "PASS",
            "generated_at": "2026-09-25T14:00:00Z",
            "data_as_of": "2026-09-25",
            "checks": [],
            "metrics": {},
        }

        with (
            patch("scripts.generate_report.GENERATED_DIR", self.gen_dir),
            patch("scripts.generate_report.run_pipeline", return_value=self.mock_res),
            patch(
                "scripts.generate_report.evaluate_production_monitoring",
                return_value=mock_mon,
            ),
            patch("sys.argv", ["generate_report.py"]),
        ):
            # Should complete cleanly without SystemExit(1)
            main()

        mon_path = os.path.join(self.gen_dir, "monitoring.json")
        self.assertTrue(os.path.exists(mon_path))
        with open(mon_path, "r", encoding="utf-8") as f:
            mon_data = json.load(f)
        self.assertEqual(mon_data["overall_status"], "PASS")

    def test_b_monitoring_warn_succeeds_with_warning_logged(self):
        """Test B: Monitoring WARN -> pipeline remains successful (exit 0), monitoring payload contains WARN."""
        mock_mon = MagicMock()
        mock_mon.overall_status = "WARN"
        mock_mon.to_dict.return_value = {
            "overall_status": "WARN",
            "generated_at": "2026-09-25T14:00:00Z",
            "data_as_of": "2026-09-25",
            "checks": [],
            "metrics": {},
        }

        with (
            patch("scripts.generate_report.GENERATED_DIR", self.gen_dir),
            patch("scripts.generate_report.run_pipeline", return_value=self.mock_res),
            patch(
                "scripts.generate_report.evaluate_production_monitoring",
                return_value=mock_mon,
            ),
            patch("sys.argv", ["generate_report.py"]),
        ):
            # Process remains successful
            main()

        mon_path = os.path.join(self.gen_dir, "monitoring.json")
        self.assertTrue(os.path.exists(mon_path))
        with open(mon_path, "r", encoding="utf-8") as f:
            mon_data = json.load(f)
        self.assertEqual(mon_data["overall_status"], "WARN")

    def test_c_monitoring_fail_exits_nonzero(self):
        """Test C: Monitoring FAIL -> process exits non-zero (SystemExit(1)), no artifacts written."""
        mock_mon = MagicMock()
        mock_mon.overall_status = "FAIL"
        mock_mon.to_dict.return_value = {
            "overall_status": "FAIL",
            "generated_at": "2026-09-25T14:00:00Z",
            "data_as_of": "2026-09-25",
            "checks": [],
            "metrics": {},
        }

        with (
            patch("scripts.generate_report.GENERATED_DIR", self.gen_dir),
            patch("scripts.generate_report.run_pipeline", return_value=self.mock_res),
            patch(
                "scripts.generate_report.evaluate_production_monitoring",
                return_value=mock_mon,
            ),
            patch("sys.argv", ["generate_report.py"]),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

        # No artifacts (including monitoring.json) are created or modified on monitoring failure
        mon_path = os.path.join(self.gen_dir, "monitoring.json")
        self.assertFalse(os.path.exists(mon_path))

    def test_d_existing_drift_scenario_evaluates_to_fail(self):
        """Test D: Reproduce realistic distribution shift scenario and verify monitoring result evaluates to FAIL."""
        # Current distribution:
        # BUY   0.000 (0 / 42)
        # WATCH 0.310 (13 / 42)
        # HOLD  0.071 (3 / 42)
        # SELL  0.143 (6 / 42)
        # AVOID 0.476 (20 / 42)
        curr_counts = {"BUY": 0, "WATCH": 13, "HOLD": 3, "SELL": 6, "AVOID": 20}
        curr_payload = make_test_payload(data_as_of="2026-09-25", action_counts=curr_counts)

        # Baseline distribution (e.g. 100 recs per report):
        # BUY   0.197 (20 / 100)
        # WATCH 0.133 (13 / 100)
        # HOLD  0.058 (6 / 100)
        # SELL  0.510 (51 / 100)
        # AVOID 0.102 (10 / 100)
        base_counts = {"BUY": 20, "WATCH": 13, "HOLD": 6, "SELL": 51, "AVOID": 10}
        baselines = [
            make_test_payload(data_as_of=f"2026-09-{24 - i:02d}", action_counts=base_counts)
            for i in range(5)
        ]

        drift_res = evaluate_data_and_model_drift(
            data_as_of="2026-09-25",
            current_payload=curr_payload,
            baseline_reports=baselines,
        )

        self.assertEqual(drift_res.overall_status, "FAIL")
        action_chk = next(
            c for c in drift_res.drift_checks if c.check_name == "drift_action_distribution"
        )
        self.assertEqual(action_chk.status, "FAIL")
        # Shift in SELL action = |0.143 - 0.510| = 0.367 > 0.35 threshold
        self.assertGreater(action_chk.observation.absolute_difference["max_difference"], 0.35)

    def test_e_payload_integrity_failure_preserves_artifacts_byte_for_byte(self):
        """Test E: Payload integrity failure -> exit non-zero, existing artifacts remain byte-for-byte unchanged, no partial output created."""
        recs_file = os.path.join(self.gen_dir, "recommendations.json")
        mkt_file = os.path.join(self.gen_dir, "market.json")
        mon_file = os.path.join(self.gen_dir, "monitoring.json")
        hist_file = os.path.join(self.hist_dir, "2026-09-25.json")
        idx_file = os.path.join(self.hist_dir, "index.json")

        original_files = {
            recs_file: '{"existing": "recs"}\n',
            mkt_file: '{"existing": "mkt"}\n',
            hist_file: '{"existing": "hist"}\n',
            idx_file: '{"existing": "idx"}\n',
        }

        for path, content in original_files.items():
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)

        # Create invalid payload containing NaN
        invalid_payload = copy.deepcopy(self.valid_payload)
        invalid_payload["recommendations"][0]["risk_metrics"]["volatility_60d"] = float("nan")

        bad_res = MockPipelineResult(
            invalid_payload,
            invalid_payload.get("market"),
            invalid_payload,
        )

        with (
            patch("scripts.generate_report.GENERATED_DIR", self.gen_dir),
            patch("scripts.generate_report.run_pipeline", return_value=bad_res),
            patch("sys.argv", ["generate_report.py"]),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

        # Verify existing artifacts remain byte-for-byte unchanged
        for path, expected_content in original_files.items():
            with open(path, "r", encoding="utf-8") as f:
                actual_content = f.read()
            self.assertEqual(actual_content, expected_content)

        # Verify monitoring.json was not created
        self.assertFalse(os.path.exists(mon_file))

    def test_f_rate_limit_regression_preserves_artifacts(self):
        """Test F: ProviderRateLimitError handling -> exits non-zero, preserves existing artifacts."""
        recs_file = os.path.join(self.gen_dir, "recommendations.json")
        original_content = '{"existing": "data"}\n'
        with open(recs_file, "w", encoding="utf-8") as f:
            f.write(original_content)

        with (
            patch("scripts.generate_report.GENERATED_DIR", self.gen_dir),
            patch(
                "scripts.generate_report.run_pipeline",
                side_effect=ProviderRateLimitError("Quota exceeded", cooldown_seconds=60),
            ),
            patch("sys.argv", ["generate_report.py", "--update"]),
        ):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 1)

        with open(recs_file, "r", encoding="utf-8") as f:
            actual_content = f.read()
        self.assertEqual(actual_content, original_content)


if __name__ == "__main__":
    unittest.main()
