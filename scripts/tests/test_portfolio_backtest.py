"""Unit & Integration Tests for Portfolio Backtesting Framework."""

import unittest

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

        with self.assertRaises(ValueError):
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

    def test_exclusion_of_non_executable_securities(self) -> None:
        # AAA volume low, configured min volume high -> AAA excluded
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
            max_positions=1, min_signal_score=0.0, allowed_actions=("BUY", "HOLD", "WATCH")
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
        cfg = PortfolioConfig()

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_corrupted,
                config=cfg,
            )

    def test_duplicate_and_unsorted_dates_fail_closed(self) -> None:
        df_dup = self.df_aaa.copy()
        df_dup.iloc[5] = df_dup.iloc[4]  # duplicate date
        universe_dup = {"AAA": df_dup}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_dup,
            )

        df_unsorted = self.df_aaa.iloc[::-1].copy().reset_index(drop=True)
        universe_unsorted = {"AAA": df_unsorted}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_unsorted,
            )

    def test_missing_exact_evaluation_date_raises_error(self) -> None:
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2099-01-01",  # Not in history
                universe_stock_map=self.universe,
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


if __name__ == "__main__":
    unittest.main()
