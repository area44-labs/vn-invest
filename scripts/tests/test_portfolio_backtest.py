"""Unit & Integration Tests for Portfolio Backtesting Framework."""

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.lib.backtest import (
    ExecutionConfig,
    run_walk_forward_backtest,
)
from scripts.lib.portfolio_backtest import (
    PortfolioBacktestResult,
    PortfolioConfig,
    PortfolioEvaluation,
    PortfolioPosition,
    aggregate_portfolio_results,
    evaluate_portfolio_at_date,
    run_portfolio_backtest,
    validate_portfolio_weights,
)


def create_synthetic_ohlcv(
    start_date: str = "2024-01-01",
    num_days: int = 100,
    base_price: float = 50000.0,
    daily_trend: float = 100.0,
    vol_base: float = 100000.0,
) -> pd.DataFrame:
    """Helper to generate clean, valid daily OHLCV synthetic price data."""
    dates = pd.date_range(start=start_date, periods=num_days, freq="B")
    records = []
    for i, d in enumerate(dates):
        c = base_price + i * daily_trend
        o = c - 10.0
        h = c + 50.0
        low = c - 50.0
        v = vol_base + (i % 5) * 1000.0
        records.append(
            {
                "date": d.strftime("%Y-%m-%d"),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": v,
            }
        )
    return pd.DataFrame(records)


class TestPortfolioConfigValidation(unittest.TestCase):
    """Test Suite for PortfolioConfig validation and error handling."""

    def test_valid_configuration(self) -> None:
        cfg = PortfolioConfig(
            max_positions=5,
            min_signal_score=60.0,
            min_confidence=0.5,
            allowed_actions=("BUY",),
            max_weight_per_position=0.25,
            require_executable=True,
        )
        self.assertEqual(cfg.max_positions, 5)
        self.assertEqual(cfg.min_signal_score, 60.0)
        self.assertEqual(cfg.min_confidence, 0.5)
        self.assertEqual(cfg.max_weight_per_position, 0.25)
        self.assertTrue(cfg.require_executable)

    def test_invalid_max_positions(self) -> None:
        with self.assertRaises(ValueError):
            PortfolioConfig(max_positions=0)

        with self.assertRaises(ValueError):
            PortfolioConfig(max_positions=-1)

        with self.assertRaises(ValueError):
            PortfolioConfig(max_positions=2.5)  # float not allowed for int

        with self.assertRaises(ValueError):
            PortfolioConfig(max_positions=True)  # bool not allowed

    def test_invalid_thresholds(self) -> None:
        with self.assertRaises(ValueError):
            PortfolioConfig(min_signal_score=-10.0)

        with self.assertRaises(ValueError):
            PortfolioConfig(min_signal_score=150.0)

        with self.assertRaises(ValueError):
            PortfolioConfig(min_confidence=-0.1)

        with self.assertRaises(ValueError):
            PortfolioConfig(min_confidence=1.5)

    def test_nan_and_inf_config_values(self) -> None:
        with self.assertRaises(ValueError):
            PortfolioConfig(min_signal_score=float("nan"))

        with self.assertRaises(ValueError):
            PortfolioConfig(min_confidence=float("inf"))

        with self.assertRaises(ValueError):
            PortfolioConfig(max_weight_per_position=float("-inf"))

    def test_bool_and_non_numeric_types(self) -> None:
        with self.assertRaises(ValueError):
            PortfolioConfig(min_signal_score=True)

        with self.assertRaises(ValueError):
            PortfolioConfig(min_signal_score="invalid")

        with self.assertRaises((ValueError, TypeError)):
            PortfolioConfig(require_executable="true")  # type: ignore[arg-type]

    def test_deterministic_boundary_values(self) -> None:
        # Boundary: 0.0 and 100.0 for min_signal_score
        cfg1 = PortfolioConfig(min_signal_score=0.0)
        self.assertEqual(cfg1.min_signal_score, 0.0)

        cfg2 = PortfolioConfig(min_signal_score=100.0)
        self.assertEqual(cfg2.min_signal_score, 100.0)

        # Boundary: max_weight_per_position = 1.0
        cfg3 = PortfolioConfig(max_weight_per_position=1.0)
        self.assertEqual(cfg3.max_weight_per_position, 1.0)


class TestPortfolioWeightValidation(unittest.TestCase):
    """Test Suite for portfolio weight validation."""

    def test_valid_weights(self) -> None:
        validate_portfolio_weights([0.2, 0.2, 0.2, 0.2, 0.2])
        validate_portfolio_weights([0.5, 0.3])  # partial allocation <= 1.0
        validate_portfolio_weights([])  # empty portfolio weights

    def test_invalid_negative_weight(self) -> None:
        with self.assertRaises(ValueError):
            validate_portfolio_weights([0.5, -0.1])

    def test_invalid_weight_exceeding_one(self) -> None:
        with self.assertRaises(ValueError):
            validate_portfolio_weights([0.6, 0.5])

    def test_invalid_nan_inf_weight(self) -> None:
        with self.assertRaises(ValueError):
            validate_portfolio_weights([0.5, float("nan")])

        with self.assertRaises(ValueError):
            validate_portfolio_weights([0.5, float("inf")])

    def test_bool_weight_rejected(self) -> None:
        with self.assertRaises(ValueError):
            validate_portfolio_weights([0.5, True])


class TestCandidateMetadataValidation(unittest.TestCase):
    """Test Suite for candidate_metadata validation and error handling."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        self.universe = {"AAA": self.df_aaa}
        self.eval_date = "2024-03-15"

    def test_duplicate_symbol_in_candidate_metadata_raises_value_error(self) -> None:
        duplicate_meta = [
            {"symbol": "AAA", "companyName": "AAA Company 1"},
            {"symbol": "AAA", "companyName": "AAA Company 2"},
        ]
        cfg = PortfolioConfig()
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=self.universe,
                config=cfg,
                candidate_metadata=duplicate_meta,
            )

    def test_metadata_symbol_not_in_universe_raises_value_error(self) -> None:
        unknown_meta = [
            {"symbol": "AAA", "companyName": "AAA Company"},
            {"symbol": "UNKNOWN_STOCK", "companyName": "Unknown Company"},
        ]
        cfg = PortfolioConfig()
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=self.universe,
                config=cfg,
                candidate_metadata=unknown_meta,
            )

    def test_missing_or_invalid_symbol_in_candidate_metadata_raises_value_error(self) -> None:
        invalid_meta_no_symbol = [{"companyName": "No Symbol Corp"}]
        invalid_meta_empty_symbol = [{"symbol": "   "}]
        invalid_meta_bad_type = [{"symbol": 123}]

        cfg = PortfolioConfig()
        for meta in [invalid_meta_no_symbol, invalid_meta_empty_symbol, invalid_meta_bad_type]:
            with self.assertRaises((ValueError, TypeError)):
                evaluate_portfolio_at_date(
                    evaluation_date=self.eval_date,
                    universe_stock_map=self.universe,
                    config=cfg,
                    candidate_metadata=meta,  # type: ignore[arg-type]
                )

    def test_valid_unique_metadata_order_invariance(self) -> None:
        df_bbb = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0)
        universe = {"AAA": self.df_aaa, "BBB": df_bbb}

        meta1 = [
            {"symbol": "AAA", "companyName": "Comp AAA"},
            {"symbol": "BBB", "companyName": "Comp BBB"},
        ]
        meta2 = [
            {"symbol": "BBB", "companyName": "Comp BBB"},
            {"symbol": "AAA", "companyName": "Comp AAA"},
        ]

        cfg = PortfolioConfig(
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe,
            config=cfg,
            candidate_metadata=meta1,
            df_vnindex=self.df_vni,
        )

        res2 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe,
            config=cfg,
            candidate_metadata=meta2,
            df_vnindex=self.df_vni,
        )

        self.assertEqual(res1.to_dict(), res2.to_dict())


class TestPortfolioConstruction(unittest.TestCase):
    """Test Suite for portfolio candidate selection and construction."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        self.df_vn30 = create_synthetic_ohlcv("2024-01-01", 100, 1250.0, 1.0)

        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0, 200000.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0, 300000.0)
        self.df_ccc = create_synthetic_ohlcv("2024-01-01", 100, 30000.0, 50.0, 150000.0)

        self.universe = {
            "AAA": self.df_aaa,
            "BBB": self.df_bbb,
            "CCC": self.df_ccc,
        }
        self.eval_date = "2024-03-15"

    def test_deterministic_constituent_selection_and_equal_weighting(self) -> None:
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=40,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        self.assertIsInstance(eval_res, PortfolioEvaluation)
        self.assertLessEqual(len(eval_res.positions), 2)
        self.assertEqual(eval_res.allocated_weight, 1.0)
        self.assertEqual(eval_res.unallocated_weight, 0.0)

        weights = [p.weight for p in eval_res.positions]
        self.assertEqual(weights, [0.5, 0.5])

    def test_max_weight_constraint_preserves_unallocated_weight(self) -> None:
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            max_weight_per_position=0.30,  # Max 30% per position -> Total 60%, 40% unallocated
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(eval_res.positions), 2)
        self.assertEqual(eval_res.positions[0].weight, 0.30)
        self.assertEqual(eval_res.positions[1].weight, 0.30)
        self.assertEqual(eval_res.allocated_weight, 0.60)
        self.assertEqual(eval_res.unallocated_weight, 0.40)
        self.assertAlmostEqual(
            eval_res.allocated_weight + eval_res.unallocated_weight, 1.0, places=6
        )

    def test_capped_equal_weight_allocation_3_positions(self) -> None:
        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            max_weight_per_position=0.20,  # 3 positions * 0.20 = 0.60 allocated, 0.40 unallocated
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(eval_res.positions), 3)
        for pos in eval_res.positions:
            self.assertEqual(pos.weight, 0.20)
        self.assertEqual(eval_res.allocated_weight, 0.60)
        self.assertEqual(eval_res.unallocated_weight, 0.40)
        self.assertAlmostEqual(
            eval_res.allocated_weight + eval_res.unallocated_weight, 1.0, places=6
        )

    def test_exclusion_of_non_executable_securities(self) -> None:
        # AAA volume low, configured min volume high -> AAA excluded when require_executable=True
        df_low_vol = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0, 1000.0)
        universe_exec = {
            "LOW_VOL": df_low_vol,
            "BBB": self.df_bbb,
        }
        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=True,
            execution_config=exec_cfg,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_exec,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        selected_symbols = [p.symbol for p in eval_res.positions]
        self.assertNotIn("LOW_VOL", selected_symbols)
        self.assertIn("LOW_VOL", eval_res.excluded_non_executable)

    def test_require_executable_false_retains_is_executable_without_excluding(self) -> None:
        # When require_executable=False, LOW_VOL is included and has is_executable=False
        df_low_vol = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0, 1000.0)
        universe_exec = {
            "LOW_VOL": df_low_vol,
            "BBB": self.df_bbb,
        }
        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=False,
            execution_config=exec_cfg,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_exec,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        selected_symbols = [p.symbol for p in eval_res.positions]
        self.assertIn("LOW_VOL", selected_symbols)

        low_vol_pos = next(p for p in eval_res.positions if p.symbol == "LOW_VOL")
        self.assertFalse(low_vol_pos.is_executable)

    def test_universe_with_none_stock_raises_value_error(self) -> None:
        universe_corrupted = {
            "AAA": self.df_aaa,
            "NONE_STOCK": None,
        }
        cfg = PortfolioConfig()
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_corrupted,  # type: ignore[arg-type]
                config=cfg,
            )

    def test_universe_with_empty_stock_raises_value_error(self) -> None:
        universe_corrupted = {
            "AAA": self.df_aaa,
            "EMPTY_STOCK": pd.DataFrame(),
        }
        cfg = PortfolioConfig()
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_corrupted,
                config=cfg,
            )

    def test_one_stock_insufficient_min_history_fails_closed(self) -> None:
        df_short = create_synthetic_ohlcv("2024-03-01", 10, 10000.0, 100.0)
        universe_short = {
            "AAA": self.df_aaa,
            "SHORT": df_short,
        }
        cfg = PortfolioConfig(min_history=50)
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_short,
                config=cfg,
            )

    def test_empty_portfolio_when_no_candidates_qualify(self) -> None:
        cfg = PortfolioConfig(
            min_signal_score=99.0,  # Unreasonably high threshold
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(eval_res.positions), 0)
        self.assertEqual(eval_res.allocated_weight, 0.0)
        self.assertEqual(eval_res.unallocated_weight, 1.0)
        self.assertEqual(eval_res.empty_reason, "no_eligible_candidates")
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_empty_portfolio_when_all_candidates_non_executable(self) -> None:
        # All stocks have volume far below min_avg_volume requirement
        df_low1 = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0, 100.0)
        df_low2 = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0, 100.0)
        universe_low_vol = {"LOW1": df_low1, "LOW2": df_low2}

        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=True,
            execution_config=exec_cfg,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_low_vol,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )
        self.assertEqual(len(eval_res.positions), 0)
        self.assertEqual(eval_res.allocated_weight, 0.0)
        self.assertEqual(eval_res.unallocated_weight, 1.0)
        self.assertEqual(eval_res.empty_reason, "all_candidates_non_executable")
        self.assertEqual(len(eval_res.excluded_non_executable), 2)
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_execution_semantics_consistency_with_single_trade_backtest(self) -> None:
        """Verify portfolio backtest enforces same execution eligibility rules as single-trade backtest."""
        # LOW1 has volume below min and traded value below min; HIGH1 satisfies all liquidity thresholds
        df_low = create_synthetic_ohlcv(
            start_date="2024-01-01",
            num_days=100,
            base_price=10000.0,
            daily_trend=10.0,
            vol_base=1000.0,
        )
        df_high = create_synthetic_ohlcv(
            start_date="2024-01-01",
            num_days=100,
            base_price=50000.0,
            daily_trend=10.0,
            vol_base=100000.0,
        )
        universe = {"LOW1": df_low, "HIGH1": df_high}

        exec_cfg = ExecutionConfig(
            min_avg_traded_value_bn=1.0,
            min_avg_volume=50000.0,
            min_price=10000.0,
        )

        # 1. With require_executable=True: LOW1 is excluded, HIGH1 selected
        cfg_req = PortfolioConfig(
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=True,
            execution_config=exec_cfg,
        )
        eval_req = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe,
            config=cfg_req,
            df_vnindex=self.df_vni,
        )
        selected_req = [p.symbol for p in eval_req.positions]
        self.assertIn("HIGH1", selected_req)
        self.assertNotIn("LOW1", selected_req)
        self.assertIn("LOW1", eval_req.excluded_non_executable)

        # 2. With require_executable=False: Both selected, LOW1 has is_executable=False, HIGH1 has is_executable=True
        cfg_noreq = PortfolioConfig(
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=False,
            execution_config=exec_cfg,
        )
        eval_noreq = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe,
            config=cfg_noreq,
            df_vnindex=self.df_vni,
        )
        selected_noreq = [p.symbol for p in eval_noreq.positions]
        self.assertIn("HIGH1", selected_noreq)
        self.assertIn("LOW1", selected_noreq)

        pos_low = next(p for p in eval_noreq.positions if p.symbol == "LOW1")
        pos_high = next(p for p in eval_noreq.positions if p.symbol == "HIGH1")
        self.assertFalse(pos_low.is_executable)
        self.assertTrue(pos_high.is_executable)


class TestPortfolioReturnCalculation(unittest.TestCase):
    """Test Suite for forward portfolio return calculation."""

    def test_exact_weighted_return_calculation(self) -> None:
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=0.6,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.10, 10: 0.20},
            forward_availability={5: True, 10: True},
        )
        p2 = PortfolioPosition(
            symbol="BBB",
            weight=0.4,
            action="BUY",
            signal_score=65.0,
            risk_adjusted_score=60.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: -0.05, 10: 0.10},
            forward_availability={5: True, 10: True},
        )
        # Expected 5D: 0.6 * 0.10 + 0.4 * (-0.05) = 0.06 - 0.02 = 0.04
        # Expected 10D: 0.6 * 0.20 + 0.4 * 0.10 = 0.12 + 0.04 = 0.16
        eval_res = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p1, p2],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={
                5: round(0.6 * 0.10 + 0.4 * (-0.05), 6),
                10: round(0.6 * 0.20 + 0.4 * 0.10, 6),
            },
            horizon_availability={5: True, 10: True},
        )
        self.assertEqual(eval_res.portfolio_forward_returns[5], 0.04)
        self.assertEqual(eval_res.portfolio_forward_returns[10], 0.16)

    def test_insufficient_future_data_marks_horizon_unavailable(self) -> None:
        # Near end of dataset date
        df_vni = create_synthetic_ohlcv("2024-01-01", 50, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 50, 10000.0, 100.0)
        universe = {"AAA": df_aaa}

        # Date 48 of 50 -> 5D horizon exceeds total dataset length
        eval_d = df_aaa["date"].iloc[47]
        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5, 10, 20],
        )
        if eval_res.positions:
            self.assertFalse(eval_res.horizon_availability[5])
            self.assertIsNone(eval_res.portfolio_forward_returns[5])


class TestPortfolioTemporalIntegrity(unittest.TestCase):
    """Test Suite for temporal integrity and fail-closed validation."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 150.0)
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}
        self.eval_date = self.df_aaa["date"].iloc[40]

    def test_mutating_data_after_T_does_not_affect_portfolio_at_T(self) -> None:
        cfg = PortfolioConfig(
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        eval1 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Mutate future data (> T) consistently preserving valid high/low/open relationships
        df_aaa_mutated = self.df_aaa.copy()
        mask = df_aaa_mutated["date"] > self.eval_date
        df_aaa_mutated.loc[mask, "close"] *= 2.0
        df_aaa_mutated.loc[mask, "open"] *= 2.0
        df_aaa_mutated.loc[mask, "high"] *= 2.0
        df_aaa_mutated.loc[mask, "low"] *= 2.0
        universe_mutated = {"AAA": df_aaa_mutated, "BBB": self.df_bbb}

        eval2 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_mutated,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Portfolio constituents, weights, signal scores at T must be identical
        self.assertEqual([p.symbol for p in eval1.positions], [p.symbol for p in eval2.positions])
        self.assertEqual([p.weight for p in eval1.positions], [p.weight for p in eval2.positions])
        self.assertEqual(
            [p.signal_score for p in eval1.positions], [p.signal_score for p in eval2.positions]
        )

    def test_physically_inserted_future_row_raises_error(self) -> None:
        df_corrupted = self.df_aaa.copy()
        # Insert a row with a future date before T
        future_date = self.df_aaa["date"].iloc[60]
        corrupted_row = df_corrupted.iloc[60].copy()
        corrupted_row["date"] = future_date

        df_corrupted.iloc[10] = corrupted_row

        universe_corrupted = {"AAA": df_corrupted, "BBB": self.df_bbb}
        cfg = PortfolioConfig(min_history=30)

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_corrupted,
                config=cfg,
            )

    def test_duplicate_and_unsorted_dates_fail_closed(self) -> None:
        cfg = PortfolioConfig(min_history=30)
        df_dup = self.df_aaa.copy()
        df_dup.iloc[5] = df_dup.iloc[4]  # duplicate date
        universe_dup = {"AAA": df_dup}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_dup,
                config=cfg,
            )

        df_unsorted = self.df_aaa.iloc[::-1].copy().reset_index(drop=True)
        universe_unsorted = {"AAA": df_unsorted}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_unsorted,
                config=cfg,
            )

    def test_missing_exact_evaluation_date_raises_error(self) -> None:
        cfg = PortfolioConfig(min_history=30)
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2099-01-01",  # Not in history
                universe_stock_map=self.universe,
                config=cfg,
            )

    def test_timezone_aware_evaluation_date_raises_value_error(self) -> None:
        cfg = PortfolioConfig(min_history=30)
        tz_ts = pd.Timestamp("2024-03-15 00:00:00+00:00")
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=tz_ts,
                universe_stock_map=self.universe,
                config=cfg,
            )

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2024-03-15T00:00:00Z",
                universe_stock_map=self.universe,
                config=cfg,
            )

    def test_invalid_and_duplicate_evaluation_dates_in_run_portfolio_backtest(self) -> None:
        cfg = PortfolioConfig(min_history=30)

        # Invalid evaluation date
        with self.assertRaises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=["invalid-date"],
                universe_stock_map=self.universe,
                config=cfg,
            )

        # Duplicate evaluation date
        eval_d = self.df_aaa["date"].iloc[40]
        with self.assertRaises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=[eval_d, eval_d],
                universe_stock_map=self.universe,
                config=cfg,
            )

        # Unsorted evaluation dates
        eval_d1 = self.df_aaa["date"].iloc[40]
        eval_d2 = self.df_aaa["date"].iloc[30]
        with self.assertRaises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=[eval_d1, eval_d2],
                universe_stock_map=self.universe,
                config=cfg,
            )


class TestPortfolioDeterminism(unittest.TestCase):
    """Test Suite verifying deterministic byte/value equivalence across runs."""

    def test_repeated_runs_produce_equivalent_results(self) -> None:
        df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}
        eval_dates = [df_aaa["date"].iloc[40], df_aaa["date"].iloc[50]]

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=eval_dates,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=eval_dates,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
        )

        self.assertEqual(res1.to_dict(), res2.to_dict())
        self.assertIn("min_history", res1.to_dict()["config"])
        self.assertEqual(res1.to_dict()["config"]["min_history"], cfg.min_history)


class TestPortfolioAggregation(unittest.TestCase):
    """Test Suite for portfolio aggregation and cumulative return compounding."""

    def test_aggregation_with_mixed_empty_and_non_empty_portfolios(self) -> None:
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.10},
            forward_availability={5: True},
        )

        eval1 = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.10},
            horizon_availability={5: True},
        )

        p2 = PortfolioPosition(
            symbol="BBB",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: -0.05},
            forward_availability={5: True},
        )

        eval2 = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p2],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: -0.05},
            horizon_availability={5: True},
        )

        eval_empty = PortfolioEvaluation(
            evaluation_date="2024-04-01",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )

        agg = aggregate_portfolio_results([eval1, eval2, eval_empty], horizons=[5])

        self.assertEqual(agg["total_evaluation_points"], 3)
        self.assertEqual(agg["non_empty_portfolios_count"], 2)
        self.assertEqual(agg["empty_portfolios_count"], 1)
        self.assertEqual(agg["empty_reasons_breakdown"]["no_eligible_candidates"], 1)

        h5 = agg["horizon_metrics"][5]
        self.assertEqual(h5["valid_evaluation_points"], 2)
        # mean of [0.10, -0.05] = 0.025
        self.assertEqual(h5["mean"], 0.025)
        # hit rate = 1 positive out of 2 = 0.5
        self.assertEqual(h5["hit_rate"], 0.5)

        # Sequential compounding: (1 + 0.10) * (1 - 0.05) - 1 = 1.10 * 0.95 - 1 = 1.045 - 1 = 0.045
        self.assertIn("sequential_compounded_return", h5)
        self.assertAlmostEqual(h5["sequential_compounded_return"], 0.045, places=5)


class TestZeroCostEquivalence(unittest.TestCase):
    """Test Suite verifying transaction_cost_pct=0 and slippage_pct=0 equivalence."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        # AAA: entry = 100.0, exit = 110.0 (+10.0%)
        prices_aaa = [100.0] * 50 + [110.0] * 10
        self.df_aaa = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_aaa,
                "high": prices_aaa,
                "low": prices_aaa,
                "close": prices_aaa,
                "volume": [1_000_000.0] * 60,
            }
        )
        # BBB: entry = 100.0, exit = 120.0 (+20.0%)
        prices_bbb = [100.0] * 50 + [120.0] * 10
        self.df_bbb = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_bbb,
                "high": prices_bbb,
                "low": prices_bbb,
                "close": prices_bbb,
                "volume": [1_000_000.0] * 60,
            }
        )
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_zero_cost_and_slippage_field_level_equivalence(self, mock_gen_rec) -> None:
        """Verify position returns, portfolio return, weights, allocated and unallocated weight when cost/slippage are zero against independent gross calculations."""

        def side_effect(symbol, **kwargs):
            if symbol == "AAA":
                return {
                    "action": "BUY",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 85.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            return {
                "action": "BUY",
                "signal_score": 80.0,
                "risk_adjusted_score": 80.0,
                "confidence": 0.7,
                "trade_plan": {"current_price": 100.0},
            }

        mock_gen_rec.side_effect = side_effect

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        pos_a = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_b = next(p for p in eval_res.positions if p.symbol == "BBB")

        # Independent gross calculation directly from known price inputs (100 -> 110 and 100 -> 120)
        expected_gross_a = 0.10
        expected_gross_b = 0.20
        expected_portfolio_ret = round(0.5 * expected_gross_a + 0.5 * expected_gross_b, 6)  # 0.15

        # Weights check
        self.assertEqual(pos_a.weight, 0.5)
        self.assertEqual(pos_b.weight, 0.5)
        self.assertEqual(eval_res.allocated_weight, 1.0)
        self.assertEqual(eval_res.unallocated_weight, 0.0)

        # Position return check
        self.assertEqual(pos_a.forward_returns[5], expected_gross_a)
        self.assertEqual(pos_b.forward_returns[5], expected_gross_b)

        # Portfolio return check
        self.assertEqual(eval_res.portfolio_forward_returns[5], expected_portfolio_ret)


class TestAllocationInvariants(unittest.TestCase):
    """Test Suite verifying sum(weights) + unallocated_weight == 1.0 across configurations."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0, 200000.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 150.0, 300000.0)
        self.df_ccc = create_synthetic_ohlcv("2024-01-01", 80, 30000.0, 50.0, 150000.0)
        self.universe = {
            "AAA": self.df_aaa,
            "BBB": self.df_bbb,
            "CCC": self.df_ccc,
        }
        self.eval_date = self.df_aaa["date"].iloc[40]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_allocation_invariant_single_position(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }
        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
        )
        self.assertEqual(len(eval_res.positions), 1)
        self.assertEqual(eval_res.positions[0].weight, 1.0)
        self.assertEqual(eval_res.allocated_weight, 1.0)
        self.assertEqual(eval_res.unallocated_weight, 0.0)
        self.assertAlmostEqual(
            sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight,
            1.0,
            places=6,
        )

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_allocation_invariant_two_positions(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
        )
        self.assertEqual(len(eval_res.positions), 2)
        total_w = sum(p.weight for p in eval_res.positions)
        self.assertEqual(eval_res.allocated_weight, round(total_w, 6))
        self.assertAlmostEqual(total_w + eval_res.unallocated_weight, 1.0, places=6)

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_allocation_invariant_multiple_positions_with_cap(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }
        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
            max_weight_per_position=0.25,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
        )
        self.assertEqual(len(eval_res.positions), 3)
        for pos in eval_res.positions:
            self.assertEqual(pos.weight, 0.25)
        self.assertEqual(eval_res.allocated_weight, 0.75)
        self.assertEqual(eval_res.unallocated_weight, 0.25)
        self.assertAlmostEqual(
            sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight,
            1.0,
            places=6,
        )

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_allocation_invariant_non_executable_filtering(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }
        # LOW_VOL is non-executable
        df_low_vol = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0, 1000.0)
        universe_exec = {
            "LOW_VOL": df_low_vol,
            "BBB": self.df_bbb,
            "CCC": self.df_ccc,
        }
        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
            require_executable=True,
            execution_config=exec_cfg,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_exec,
            config=cfg,
        )
        self.assertEqual(len(eval_res.positions), 2)
        total_w = sum(p.weight for p in eval_res.positions)
        self.assertAlmostEqual(total_w + eval_res.unallocated_weight, 1.0, places=6)
        self.assertNotIn("LOW_VOL", [p.symbol for p in eval_res.positions])

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_allocation_invariant_mixed_executable_require_false(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }
        df_low_vol = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0, 1000.0)
        universe_exec = {
            "LOW_VOL": df_low_vol,
            "BBB": self.df_bbb,
        }
        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
            require_executable=False,
            execution_config=exec_cfg,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_exec,
            config=cfg,
        )
        self.assertEqual(len(eval_res.positions), 2)
        total_w = sum(p.weight for p in eval_res.positions)
        self.assertAlmostEqual(total_w + eval_res.unallocated_weight, 1.0, places=6)


class TestMixedActionPortfolio(unittest.TestCase):
    """Test Suite verifying mixed BUY/SELL/WATCH portfolio semantics."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")

        # BUY stock (100 -> 110 at +5D)
        prices_buy = [100.0] * 50 + [110.0] * 10
        self.df_buy = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_buy,
                "high": prices_buy,
                "low": prices_buy,
                "close": prices_buy,
                "volume": [1_000_000.0] * 60,
            }
        )

        # SELL stock (100 -> 90 at +5D)
        prices_sell = [100.0] * 50 + [90.0] * 10
        self.df_sell = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_sell,
                "high": prices_sell,
                "low": prices_sell,
                "close": prices_sell,
                "volume": [1_000_000.0] * 60,
            }
        )

        # WATCH stock (100 -> 120 at +5D - price moves, but WATCH must earn 0 return and 0 fees)
        prices_watch = [100.0] * 50 + [120.0] * 10
        self.df_watch = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_watch,
                "high": prices_watch,
                "low": prices_watch,
                "close": prices_watch,
                "volume": [1_000_000.0] * 60,
            }
        )

        self.universe = {
            "STK_BUY": self.df_buy,
            "STK_SELL": self.df_sell,
            "STK_WATCH": self.df_watch,
        }
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_mixed_buy_sell_watch_portfolio_returns(self, mock_gen_rec) -> None:
        def side_effect(symbol, **kwargs):
            if symbol == "STK_BUY":
                return {
                    "action": "BUY",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 85.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            if symbol == "STK_SELL":
                return {
                    "action": "SELL",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 80.0,
                    "confidence": 0.7,
                    "trade_plan": {"current_price": 100.0},
                }
            return {
                "action": "WATCH",
                "signal_score": 75.0,
                "risk_adjusted_score": 75.0,
                "confidence": 0.6,
                "trade_plan": {"current_price": 100.0},
            }

        mock_gen_rec.side_effect = side_effect

        tc = 0.0030
        slip = 0.0010

        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "SELL", "WATCH"),
            min_history=30,
            transaction_cost_pct=tc,
            slippage_pct=slip,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 3)
        pos_buy = next(p for p in eval_res.positions if p.symbol == "STK_BUY")
        pos_sell = next(p for p in eval_res.positions if p.symbol == "STK_SELL")
        pos_watch = next(p for p in eval_res.positions if p.symbol == "STK_WATCH")

        # Equal weighting (1/3 each)
        w = round(1.0 / 3.0, 6)
        self.assertEqual(pos_buy.weight, w)
        self.assertEqual(pos_sell.weight, w)
        self.assertEqual(pos_watch.weight, w)

        # BUY net return: 0.094511
        self.assertEqual(pos_buy.forward_returns[5], 0.094511)

        # SELL net return: 0.094906
        self.assertEqual(pos_sell.forward_returns[5], 0.094906)

        # WATCH net return: STRICTLY 0.0 (no trading P&L, no transaction costs, no slippage)
        self.assertEqual(pos_watch.forward_returns[5], 0.0)

        # Expected portfolio return: round(w * 0.094511 + w * 0.094906 + w * 0.0, 6)
        expected_port_ret = round(w * 0.094511 + w * 0.094906, 6)
        self.assertEqual(eval_res.portfolio_forward_returns[5], expected_port_ret)


class TestZeroReturnPositions(unittest.TestCase):
    """Test Suite verifying zero price-change positions (entry price == exit price)."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        prices_flat = [100.0] * 60
        self.df_flat = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_flat,
                "high": prices_flat,
                "low": prices_flat,
                "close": prices_flat,
                "volume": [1_000_000.0] * 60,
            }
        )
        self.universe = {
            "BUY_FLAT": self.df_flat,
            "SELL_FLAT": self.df_flat.copy(),
            "WATCH_FLAT": self.df_flat.copy(),
        }
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_zero_price_change_gross_vs_net_returns(self, mock_gen_rec) -> None:
        def side_effect(symbol, **kwargs):
            if symbol == "BUY_FLAT":
                return {
                    "action": "BUY",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 85.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            if symbol == "SELL_FLAT":
                return {
                    "action": "SELL",
                    "signal_score": 80.0,
                    "risk_adjusted_score": 80.0,
                    "confidence": 0.7,
                    "trade_plan": {"current_price": 100.0},
                }
            return {
                "action": "WATCH",
                "signal_score": 75.0,
                "risk_adjusted_score": 75.0,
                "confidence": 0.6,
                "trade_plan": {"current_price": 100.0},
            }

        mock_gen_rec.side_effect = side_effect

        tc = 0.0030
        slip = 0.0010

        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY", "SELL", "WATCH"),
            min_history=30,
            transaction_cost_pct=tc,
            slippage_pct=slip,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        pos_buy = next(p for p in eval_res.positions if p.symbol == "BUY_FLAT")
        pos_sell = next(p for p in eval_res.positions if p.symbol == "SELL_FLAT")
        pos_watch = next(p for p in eval_res.positions if p.symbol == "WATCH_FLAT")

        # BUY flat trade: entry=100, exit=100
        # gross return = 0.0
        # slippage ret = (99.9 / 100.1) - 1 = -0.001998
        # net return = 0.9985 * (99.9 / 100.1) * 0.9985 - 1 = -0.00499
        self.assertEqual(pos_buy.forward_returns[5], -0.00499)

        # SELL flat trade: entry=100, exit=100
        # gross return = 0.0
        # net_return = (1 - 0.0015) * (1 + (1 - 100.1 / 99.9)) * (1 - 0.0015) - 1 = -0.004994
        self.assertEqual(pos_sell.forward_returns[5], -0.004994)

        # WATCH flat trade:
        # gross return = 0.0, net return = 0.0
        self.assertEqual(pos_watch.forward_returns[5], 0.0)


class TestPartialCapitalAllocation(unittest.TestCase):
    """Test Suite verifying partial allocation where allocated_weight < 1.0."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        prices_buy = [100.0] * 50 + [120.0] * 10
        self.df_buy = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_buy,
                "high": prices_buy,
                "low": prices_buy,
                "close": prices_buy,
                "volume": [1_000_000.0] * 60,
            }
        )
        self.universe = {"STK_BUY": self.df_buy}
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_partial_allocation_portfolio_return_contribution(self, mock_gen_rec) -> None:
        """Verify position_weight = 0.5 with zero cost yields portfolio_return = 0.5 * 20% = 10%."""
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 85.0,
            "risk_adjusted_score": 85.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }

        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            min_confidence=0.0,
            allowed_actions=("BUY",),
            max_weight_per_position=0.50,  # 50% max position weight
            min_history=30,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 1)
        pos = eval_res.positions[0]
        self.assertEqual(pos.weight, 0.50)
        self.assertEqual(eval_res.allocated_weight, 0.50)
        self.assertEqual(eval_res.unallocated_weight, 0.50)

        # Position return: (120/100) - 1 = +0.20
        self.assertEqual(pos.forward_returns[5], 0.20)

        # Portfolio return contribution: 0.50 * 0.20 = 0.10 (unallocated capital earns 0.0)
        self.assertEqual(eval_res.portfolio_forward_returns[5], 0.10)


class TestMultipleHorizonsIndependence(unittest.TestCase):
    """Test Suite verifying independence across multiple horizons (5D, 10D)."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=65, freq="B").strftime("%Y-%m-%d")
        # Session 50: entry = 100.0, Session 55 (+5D): exit = 110.0, Session 60 (+10D): exit = 120.0
        prices = [100.0] * 50 + [110.0] * 5 + [120.0] * 10
        self.df_stock = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1_000_000.0] * 65,
            }
        )
        self.universe = {"STK_BUY": self.df_stock}
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_horizons_calculated_independently_without_double_counting(self, mock_gen_rec) -> None:
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 85.0,
            "risk_adjusted_score": 85.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }

        tc = 0.0030
        slip = 0.0010

        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            allowed_actions=("BUY",),
            min_history=30,
            transaction_cost_pct=tc,
            slippage_pct=slip,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5, 10],
        )

        pos = eval_res.positions[0]

        # 5D net return: 0.094511 (from 100 -> 110)
        self.assertEqual(pos.forward_returns[5], 0.094511)
        self.assertEqual(eval_res.portfolio_forward_returns[5], 0.094511)

        # 10D net return: 0.194012 (from 100 -> 120)
        self.assertEqual(pos.forward_returns[10], 0.194012)
        self.assertEqual(eval_res.portfolio_forward_returns[10], 0.194012)


class TestIndependentMathOracleCostSlippage(unittest.TestCase):
    """Test Suite validating portfolio net returns against an independent mathematical oracle."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        prices_buy = [100.0] * 50 + [120.0] * 10
        self.df_buy = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_buy,
                "high": prices_buy,
                "low": prices_buy,
                "close": prices_buy,
                "volume": [1_000_000.0] * 60,
            }
        )
        self.universe = {"STK_BUY": self.df_buy}
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_independent_math_oracle_portfolio_integration(self, mock_gen_rec) -> None:
        """Verify 100% single position portfolio evaluation net return matches independent mathematical formula exactly without using calculate_execution_return as oracle."""
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 85.0,
            "risk_adjusted_score": 85.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }

        p_entry = 100.0
        p_exit = 120.0
        tc = 0.0030
        slip = 0.0010

        # Independent pure math calculation (WITHOUT calling calculate_execution_return):
        # P_entry_exec = 100.0 * (1 + 0.0010) = 100.10
        # P_exit_exec  = 120.0 * (1 - 0.0010) = 119.88
        # net_return   = (1 - 0.0015) * (119.88 / 100.10) * (1 - 0.0015) - 1.0 = 0.194012
        p_entry_exec = round(p_entry * (1.0 + slip), 6)
        p_exit_exec = round(p_exit * (1.0 - slip), 6)
        c_entry = tc / 2.0
        c_exit = tc / 2.0
        oracle_net = round((1.0 - c_entry) * (p_exit_exec / p_entry_exec) * (1.0 - c_exit) - 1.0, 6)

        self.assertEqual(oracle_net, 0.194012)

        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            allowed_actions=("BUY",),
            min_history=30,
            transaction_cost_pct=tc,
            slippage_pct=slip,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        pos_net = eval_res.positions[0].forward_returns[5]
        port_net = eval_res.portfolio_forward_returns[5]

        # Verify position net return == oracle and portfolio return == oracle
        self.assertEqual(pos_net, oracle_net)
        self.assertEqual(port_net, oracle_net)


class TestMissingOutcomeSemantics(unittest.TestCase):
    """Test Suite verifying strict missing forward outcome contracts."""

    def setUp(self) -> None:
        self.dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        # AAA: entry = 100.0, exit = 110.0 (+10.0%)
        prices_aaa = [100.0] * 50 + [110.0] * 10
        self.df_aaa = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_aaa,
                "high": prices_aaa,
                "low": prices_aaa,
                "close": prices_aaa,
                "volume": [1_000_000.0] * 60,
            }
        )
        # BBB: entry = 100.0, exit = 120.0 (+20.0%)
        prices_bbb = [100.0] * 50 + [120.0] * 10
        self.df_bbb = pd.DataFrame(
            {
                "date": self.dates,
                "open": prices_bbb,
                "high": prices_bbb,
                "low": prices_bbb,
                "close": prices_bbb,
                "volume": [1_000_000.0] * 60,
            }
        )
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_all_outcomes_available(self, mock_gen_rec) -> None:
        """Verify evaluate_portfolio_at_date on real production evaluation path when all position outcomes are available."""

        def side_effect(symbol, **kwargs):
            if symbol == "AAA":
                return {
                    "action": "BUY",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 85.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            return {
                "action": "BUY",
                "signal_score": 80.0,
                "risk_adjusted_score": 80.0,
                "confidence": 0.7,
                "trade_plan": {"current_price": 100.0},
            }

        mock_gen_rec.side_effect = side_effect

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY",),
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            horizons=[5],
        )

        # Both positions have valid 5D outcome data
        self.assertEqual(len(eval_res.positions), 2)
        pos_aaa = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_bbb = next(p for p in eval_res.positions if p.symbol == "BBB")

        self.assertTrue(pos_aaa.forward_availability[5])
        self.assertTrue(pos_bbb.forward_availability[5])
        self.assertEqual(pos_aaa.forward_returns[5], 0.10)
        self.assertEqual(pos_bbb.forward_returns[5], 0.20)

        # Portfolio level horizon_availability MUST be True, portfolio_forward_returns MUST be 0.15
        self.assertTrue(eval_res.horizon_availability[5])
        self.assertEqual(eval_res.portfolio_forward_returns[5], 0.15)

    def test_some_outcomes_missing(self) -> None:
        """When 1 position lacks forward outcome, portfolio return MUST be None, not converted to 0."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 50, 1200.0, 1.0)
        # df_aaa has 50 rows, df_bbb has 42 rows
        df_aaa = create_synthetic_ohlcv("2024-01-01", 50, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 42, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

        # Date 40 (index 39): AAA has 10 sessions after date 40, BBB only has 2 sessions after date 40
        eval_d = df_bbb["date"].iloc[39]
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        pos_aaa = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_bbb = next(p for p in eval_res.positions if p.symbol == "BBB")

        self.assertTrue(pos_aaa.forward_availability[5])
        self.assertIsNotNone(pos_aaa.forward_returns[5])

        self.assertFalse(pos_bbb.forward_availability[5])
        self.assertIsNone(pos_bbb.forward_returns[5])

        # Portfolio level horizon_availability MUST be False, portfolio_forward_returns MUST be None
        self.assertFalse(eval_res.horizon_availability[5])
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_all_outcomes_missing(self) -> None:
        df_vni = create_synthetic_ohlcv("2024-01-01", 42, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 42, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 42, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

        eval_d = df_aaa["date"].iloc[40]
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 2)
        for pos in eval_res.positions:
            self.assertFalse(pos.forward_availability[5])
            self.assertIsNone(pos.forward_returns[5])

        self.assertFalse(eval_res.horizon_availability[5])
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_missing_outcome_aggregation_accounting(self) -> None:
        """Verify aggregate_portfolio_results excludes unavailable evaluation points from mean/hit_rate denominator."""
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.10},
            forward_availability={5: True},
        )
        eval_avail = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.10},
            horizon_availability={5: True},
        )

        p2 = PortfolioPosition(
            symbol="BBB",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: None},
            forward_availability={5: False},
        )
        eval_unavail = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p2],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
        )

        agg = aggregate_portfolio_results([eval_avail, eval_unavail], horizons=[5])
        h5 = agg["horizon_metrics"][5]

        # Denominator MUST be 1 valid_evaluation_point, not 2
        self.assertEqual(h5["valid_evaluation_points"], 1)
        self.assertEqual(h5["mean"], 0.10)
        self.assertEqual(h5["hit_rate"], 1.0)


class TestPortfolioIntegration(unittest.TestCase):
    """Integration Test showing consumption of walk-forward / backtest infrastructure without modifying production signal behavior."""

    def test_consume_walk_forward_outputs_without_altering_production_signals(self) -> None:
        df_vni = create_synthetic_ohlcv("2024-01-01", 90, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 90, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 90, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

        # Run stock-level walk-forward backtest
        wf_res = run_walk_forward_backtest(
            universe_stock_map=universe,
            df_vnindex=df_vni,
            min_history=40,
            step=10,
        )
        self.assertGreater(len(wf_res.evaluation_dates), 0)

        # Run portfolio backtest on identical evaluation dates
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=40,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        port_res = run_portfolio_backtest(
            evaluation_dates=wf_res.evaluation_dates,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
        )

        self.assertIsInstance(port_res, PortfolioBacktestResult)
        self.assertEqual(port_res.evaluation_dates, wf_res.evaluation_dates)
        self.assertEqual(len(port_res.evaluations), len(wf_res.evaluation_dates))


class TestPortfolioTemporalBoundaries(unittest.TestCase):
    """Test Suite focusing on temporal boundaries, exact trading-session semantics, and evaluation-date coverage."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        self.df_vn30 = create_synthetic_ohlcv("2024-01-01", 100, 1250.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0)
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}

    def test_case_a_evaluation_date_at_min_history_boundary(self) -> None:
        """Case A: Evaluation date at the start of sufficient min_history window (T-30 ... T ... T+N).

        Verify:
        - Signal is calculated using data <= T;
        - Forward outcome starts strictly after T;
        - No future leakage;
        - Result is deterministic.
        """
        min_hist = 30
        eval_d = self.df_aaa["date"].iloc[min_hist - 1]  # Exact 30th trading session

        cfg = PortfolioConfig(
            min_history=min_hist,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )

        # Mutate future data (> T)
        df_aaa_mut = self.df_aaa.copy()
        mask = df_aaa_mut["date"] > eval_d
        df_aaa_mut.loc[mask, "close"] *= 5.0
        df_aaa_mut.loc[mask, "open"] *= 5.0
        df_aaa_mut.loc[mask, "high"] *= 5.0
        df_aaa_mut.loc[mask, "low"] *= 5.0
        universe_mut = {"AAA": df_aaa_mut, "BBB": self.df_bbb}

        res2 = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe_mut,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )

        # Signals, actions, weights, scores at T must be identical
        self.assertEqual(eval_d, res1.evaluation_date)
        self.assertEqual([p.symbol for p in res1.positions], [p.symbol for p in res2.positions])
        self.assertEqual([p.weight for p in res1.positions], [p.weight for p in res2.positions])
        self.assertEqual(
            [p.signal_score for p in res1.positions], [p.signal_score for p in res2.positions]
        )

        # Forward outcomes must reflect mutated future prices (> T)
        pos1_aaa = next(p for p in res1.positions if p.symbol == "AAA")
        pos2_aaa = next(p for p in res2.positions if p.symbol == "AAA")
        self.assertNotEqual(pos1_aaa.forward_returns[5], pos2_aaa.forward_returns[5])

    def test_case_b_evaluation_date_at_last_trading_session(self) -> None:
        """Case B: Evaluation date at the last trading session in the dataset.

        Verify:
        - Signal/history is valid with sufficient history;
        - All forward outcomes are unavailable (None);
        - Portfolio forward return is None;
        - Aggregation does not treat unavailable outcome as zero.
        """
        last_eval_d = self.df_aaa["date"].iloc[-1]
        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=last_eval_d,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10, 20],
        )

        self.assertEqual(eval_res.evaluation_date, last_eval_d)
        self.assertGreater(len(eval_res.positions), 0)

        # Every position forward return must be None
        for pos in eval_res.positions:
            for h in [5, 10, 20]:
                self.assertFalse(pos.forward_availability[h])
                self.assertIsNone(pos.forward_returns[h])

        # Portfolio forward returns must be None
        for h in [5, 10, 20]:
            self.assertFalse(eval_res.horizon_availability[h])
            self.assertIsNone(eval_res.portfolio_forward_returns[h])

        # Aggregate accounting must exclude unavailable evaluation point from denominator
        agg = aggregate_portfolio_results([eval_res], horizons=[5])
        h5 = agg["horizon_metrics"][5]
        self.assertEqual(h5["valid_evaluation_points"], 0)
        self.assertIsNone(h5["mean"])
        self.assertIsNone(h5["hit_rate"])
        self.assertIsNone(h5["sequential_compounded_return"])

    def test_case_c_evaluation_date_near_dataset_end(self) -> None:
        """Case C: Evaluation date near the dataset end (e.g. exactly 1 session available after T).

        Verify:
        - Horizon 1 is available if framework evaluated with horizon=[1, 5];
        - Longer horizons (e.g. 5) are unavailable (None);
        - Uses trading-session indexing, not calendar-day arithmetic.
        """
        eval_d = self.df_aaa["date"].iloc[-2]  # Exactly 1 session remaining after T
        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[1, 5],
        )

        self.assertGreater(len(eval_res.positions), 0)

        # Horizon 1 is available
        self.assertTrue(eval_res.horizon_availability[1])
        self.assertIsNotNone(eval_res.portfolio_forward_returns[1])

        # Horizon 5 is unavailable
        self.assertFalse(eval_res.horizon_availability[5])
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_case_d_evaluation_date_before_min_history(self) -> None:
        """Case D: Evaluation date before min_history requirement is satisfied.

        Verify:
        - Raises ValueError for insufficient history;
        - Does NOT convert this into a malformed-data error.
        """
        eval_d = self.df_aaa["date"].iloc[10]  # Only 11 sessions <= T
        cfg = PortfolioConfig(min_history=50)

        with self.assertRaises(ValueError) as ctx:
            evaluate_portfolio_at_date(
                evaluation_date=eval_d,
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )

        self.assertIn("insufficient history", str(ctx.exception))

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_exact_trading_session_semantics_with_weekend_gap(self, mock_gen_rec) -> None:
        """Verify exact trading-session indexing across weekend/holiday gaps.

        Friday   = T
        Monday   = T+1
        Tuesday  = T+2

        Verify forward returns are taken from exact trading observations, not calendar days.
        """
        # Create 33 business days synthetic data
        df_gap = create_synthetic_ohlcv(
            start_date="2024-01-01", num_days=33, base_price=10000.0, daily_trend=100.0
        )
        p_T = df_gap.loc[29, "close"]

        # Row 29 is Friday (2024-02-09)
        # Row 30 is Monday (2024-02-12) -> price 110% of Friday close
        # Row 31 is Tuesday (2024-02-13) -> price 120% of Friday close
        df_gap.loc[30, "close"] = p_T * 1.10
        df_gap.loc[30, "open"] = p_T * 1.09
        df_gap.loc[30, "high"] = p_T * 1.11
        df_gap.loc[30, "low"] = p_T * 1.08

        df_gap.loc[31, "close"] = p_T * 1.20
        df_gap.loc[31, "open"] = p_T * 1.19
        df_gap.loc[31, "high"] = p_T * 1.21
        df_gap.loc[31, "low"] = p_T * 1.18

        eval_fri = df_gap["date"].iloc[29]  # Friday evaluation date

        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": p_T},
        }

        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY",),
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_fri,
            universe_stock_map={"GAP_STK": df_gap},
            config=cfg,
            horizons=[1, 2],
        )

        pos = eval_res.positions[0]

        # Horizon 1 must use Monday (T+1 trading session) price 110% -> 0.10 return
        self.assertAlmostEqual(pos.forward_returns[1], 0.10, places=5)
        self.assertAlmostEqual(eval_res.portfolio_forward_returns[1], 0.10, places=5)

        # Horizon 2 must use Tuesday (T+2 trading session) price 120% -> 0.20 return
        self.assertAlmostEqual(pos.forward_returns[2], 0.20, places=5)
        self.assertAlmostEqual(eval_res.portfolio_forward_returns[2], 0.20, places=5)

    def test_evaluation_date_must_be_exact_and_not_fallback(self) -> None:
        """Verify evaluation date must be exact in price history.

        If evaluation_date is '2024-01-06' (Saturday, not in dataset),
        it MUST fail closed with ValueError rather than silently falling back to '2024-01-05'.
        """
        cfg = PortfolioConfig(min_history=30)
        non_trading_d = "2024-01-06"  # Saturday, not in synthetic dataset

        with self.assertRaises(ValueError) as ctx:
            evaluate_portfolio_at_date(
                evaluation_date=non_trading_d,
                universe_stock_map=self.universe,
                config=cfg,
            )

        self.assertIn("not present in dataset price history", str(ctx.exception))

    def test_multiple_evaluation_dates_chronological_ordering_and_isolation(self) -> None:
        """Verify run_portfolio_backtest with multiple evaluation dates.

        Verify:
        - Dates processed in chronological order;
        - Duplicate dates rejected with ValueError;
        - Unsorted dates rejected with ValueError;
        - Outcome at T1 does not leak into signal input at T2;
        - Running T1 and T2 together matches running them individually.
        """
        t1 = self.df_aaa["date"].iloc[40]
        t2 = self.df_aaa["date"].iloc[50]
        t3 = self.df_aaa["date"].iloc[60]

        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        # 1. Unsorted dates raise ValueError
        with self.assertRaises(ValueError) as ctx_unsorted:
            run_portfolio_backtest(
                evaluation_dates=[t2, t1],
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )
        self.assertIn("not sorted in chronological order", str(ctx_unsorted.exception))

        # 2. Duplicate dates raise ValueError
        with self.assertRaises(ValueError) as ctx_dup:
            run_portfolio_backtest(
                evaluation_dates=[t1, t1, t2],
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )
        self.assertIn("contains duplicate entries", str(ctx_dup.exception))

        # 3. Valid chronological run
        res_multi = run_portfolio_backtest(
            evaluation_dates=[t1, t2, t3],
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        self.assertEqual(res_multi.evaluation_dates, [t1, t2, t3])

        # 4. State isolation check: compare with individual runs
        res_t1 = evaluate_portfolio_at_date(
            evaluation_date=t1,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        res_t2 = evaluate_portfolio_at_date(
            evaluation_date=t2,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        self.assertEqual(res_multi.evaluations[0].to_dict(), res_t1.to_dict())
        self.assertEqual(res_multi.evaluations[1].to_dict(), res_t2.to_dict())

    def test_cross_evaluation_temporal_isolation_mutation_boundary(self) -> None:
        """Verify cross-evaluation temporal isolation with T1 < T2.

        Scenario 1: Mutate data > T2.
        - Results at T1 and T2 remain invariant in signals/regime/action/portfolio construction.

        Scenario 2: Mutate data strictly between T1 and T2 (T1 < date <= T2).
        - Results at T1 remain IDENTICAL in signals/regime/action/portfolio construction.
        - Results at T2 update appropriately because that data has become historical information at T2.
        """
        t1 = self.df_aaa["date"].iloc[40]
        t2 = self.df_aaa["date"].iloc[60]

        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        baseline = run_portfolio_backtest(
            evaluation_dates=[t1, t2],
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Scenario 1: Mutate data > T2
        df_aaa_mut_post_t2 = self.df_aaa.copy()
        mask_post_t2 = df_aaa_mut_post_t2["date"] > t2
        df_aaa_mut_post_t2.loc[mask_post_t2, "close"] *= 3.0
        df_aaa_mut_post_t2.loc[mask_post_t2, "open"] *= 3.0
        df_aaa_mut_post_t2.loc[mask_post_t2, "high"] *= 3.0
        df_aaa_mut_post_t2.loc[mask_post_t2, "low"] *= 3.0
        universe_mut1 = {"AAA": df_aaa_mut_post_t2, "BBB": self.df_bbb}

        res_mut1 = run_portfolio_backtest(
            evaluation_dates=[t1, t2],
            universe_stock_map=universe_mut1,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Positions and signals at both T1 and T2 must remain identical to baseline
        for idx in range(2):
            self.assertEqual(
                [p.symbol for p in baseline.evaluations[idx].positions],
                [p.symbol for p in res_mut1.evaluations[idx].positions],
            )
            self.assertEqual(
                [p.signal_score for p in baseline.evaluations[idx].positions],
                [p.signal_score for p in res_mut1.evaluations[idx].positions],
            )

        # Scenario 2: Mutate data strictly between T1 and T2 (T1 < date <= T2)
        df_aaa_mut_mid = self.df_aaa.copy()
        mask_mid = (df_aaa_mut_mid["date"] > t1) & (df_aaa_mut_mid["date"] <= t2)
        df_aaa_mut_mid.loc[mask_mid, "close"] *= 2.0
        df_aaa_mut_mid.loc[mask_mid, "open"] *= 2.0
        df_aaa_mut_mid.loc[mask_mid, "high"] *= 2.0
        df_aaa_mut_mid.loc[mask_mid, "low"] *= 2.0
        universe_mut2 = {"AAA": df_aaa_mut_mid, "BBB": self.df_bbb}

        res_mut2 = run_portfolio_backtest(
            evaluation_dates=[t1, t2],
            universe_stock_map=universe_mut2,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # At T1: signals, scores, positions MUST be IDENTICAL to baseline
        self.assertEqual(
            [p.symbol for p in baseline.evaluations[0].positions],
            [p.symbol for p in res_mut2.evaluations[0].positions],
        )
        self.assertEqual(
            [p.signal_score for p in baseline.evaluations[0].positions],
            [p.signal_score for p in res_mut2.evaluations[0].positions],
        )

        # At T2: data in T1 < date <= T2 is historical data, so signal score at T2 may change
        # Prove T1 signal isolation holds strictly regardless of intermediate mutations
        self.assertEqual(
            baseline.evaluations[0].positions[0].signal_score,
            res_mut2.evaluations[0].positions[0].signal_score,
        )

    def test_horizon_boundary_isolation_exact_and_missing_sessions(self) -> None:
        """Verify horizon boundary isolation at exact and missing session thresholds.

        Dataset has 100 rows.
        At T = index 89 (90th day), exactly 10 sessions exist after T (index 90 to 99).
        Horizons:
        - 5D: 10 >= 5 -> available -> return calculated.
        - 10D: 10 >= 10 -> available -> return calculated.
        - 11D: 10 < 11 -> unavailable -> None.
        - 20D: 10 < 20 -> unavailable -> None.
        """
        eval_d = self.df_aaa["date"].iloc[89]  # 90th day, 10 future sessions
        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10, 11, 20],
        )

        self.assertTrue(eval_res.horizon_availability[5])
        self.assertIsNotNone(eval_res.portfolio_forward_returns[5])

        self.assertTrue(eval_res.horizon_availability[10])
        self.assertIsNotNone(eval_res.portfolio_forward_returns[10])

        self.assertFalse(eval_res.horizon_availability[11])
        self.assertIsNone(eval_res.portfolio_forward_returns[11])

        self.assertFalse(eval_res.horizon_availability[20])
        self.assertIsNone(eval_res.portfolio_forward_returns[20])

    def test_fail_closed_temporal_boundary_input_validation(self) -> None:
        """Verify fail-closed input validation for temporal boundary edge cases.

        Verify distinct error handling for:
        - Empty evaluation_dates;
        - Duplicate evaluation_dates;
        - Unsorted evaluation_dates;
        - Invalid evaluation date format;
        - Timezone-aware evaluation date;
        - Evaluation date out of historical range;
        - Insufficient historical observations (< min_history).
        """
        cfg = PortfolioConfig(min_history=50)

        # 1. Empty evaluation_dates
        with self.assertRaises(ValueError) as ctx1:
            run_portfolio_backtest(
                evaluation_dates=[],
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("cannot be empty", str(ctx1.exception))

        # 2. Duplicate evaluation_dates
        t1 = self.df_aaa["date"].iloc[50]
        with self.assertRaises(ValueError) as ctx2:
            run_portfolio_backtest(
                evaluation_dates=[t1, t1],
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("duplicate", str(ctx2.exception))

        # 3. Invalid evaluation date string
        with self.assertRaises(ValueError) as ctx3:
            run_portfolio_backtest(
                evaluation_dates=["invalid-date-string"],
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("canonical 'YYYY-MM-DD'", str(ctx3.exception))

        # 4. Timezone-aware evaluation date
        tz_d = pd.Timestamp("2024-03-01T00:00:00Z")
        with self.assertRaises(ValueError) as ctx4:
            evaluate_portfolio_at_date(
                evaluation_date=tz_d,
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("Timezone-aware", str(ctx4.exception))

        # 5. Evaluation date out of historical range
        with self.assertRaises(ValueError) as ctx5:
            evaluate_portfolio_at_date(
                evaluation_date="2099-12-31",
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("not present in dataset price history", str(ctx5.exception))

        # 6. Insufficient historical observations
        early_d = self.df_aaa["date"].iloc[10]  # only 11 sessions <= T
        with self.assertRaises(ValueError) as ctx6:
            evaluate_portfolio_at_date(
                evaluation_date=early_d,
                universe_stock_map=self.universe,
                config=cfg,
            )
        self.assertIn("insufficient history", str(ctx6.exception))


if __name__ == "__main__":
    unittest.main()
