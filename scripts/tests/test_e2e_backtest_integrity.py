"""End-to-End Integrity Validation Test Suite for Backtesting Framework (PR #105).

This module provides test-only validation proving that when all existing layers are used together:
    historical PIT data
            ↓
     signal / regime
            ↓
      forward outcome
            ↓
    execution eligibility
            ↓
  transaction cost + slippage
            ↓
    portfolio allocation
            ↓
    portfolio aggregation

all invariants established in previous PRs are strictly preserved.
"""

import unittest
from unittest.mock import patch

import pandas as pd

from scripts.lib.backtest import (
    ExecutionConfig,
    calculate_execution_return,
)
from scripts.lib.portfolio_backtest import (
    PortfolioConfig,
    aggregate_portfolio_results,
    evaluate_portfolio_at_date,
    run_portfolio_backtest,
)


def create_synthetic_ohlcv(
    start_date: str = "2024-01-01",
    num_days: int = 100,
    base_price: float = 50000.0,
    daily_trend: float = 100.0,
    vol_base: float = 100000.0,
) -> pd.DataFrame:
    """Generate clean, valid daily OHLCV synthetic price data."""
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


def create_multi_symbol_universe(
    num_days: int = 100,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, pd.DataFrame]]:
    """Generate benchmark and multi-stock universe datasets for end-to-end testing."""
    df_vni = create_synthetic_ohlcv("2024-01-01", num_days, 1200.0, 1.0, 500_000_000.0)
    df_vn30 = create_synthetic_ohlcv("2024-01-01", num_days, 1250.0, 1.0, 300_000_000.0)

    # 4 distinct stock series
    df_sym1 = create_synthetic_ohlcv("2024-01-01", num_days, 10000.0, 100.0, 200_000.0)
    df_sym2 = create_synthetic_ohlcv("2024-01-01", num_days, 20000.0, 150.0, 300_000.0)
    df_sym3 = create_synthetic_ohlcv("2024-01-01", num_days, 30000.0, -50.0, 150_000.0)
    df_sym4 = create_synthetic_ohlcv("2024-01-01", num_days, 15000.0, 200.0, 250_000.0)

    universe = {
        "SYM1": df_sym1,
        "SYM2": df_sym2,
        "SYM3": df_sym3,
        "SYM4": df_sym4,
    }
    return df_vni, df_vn30, universe


class TestE2ETemporalIntegrity(unittest.TestCase):
    """Test Suite 1 — End-to-End Temporal Integrity & Anti-Lookahead Safety."""

    def setUp(self) -> None:
        self.df_vni, self.df_vn30, self.universe = create_multi_symbol_universe(num_days=100)
        self.eval_date = self.df_vni["date"].iloc[50]  # Date T

    def test_end_to_end_temporal_isolation_and_future_mutation(self) -> None:
        """Verify signals/regimes/actions at T depend strictly on data <= T, and mutating data > T does not alter signal/regime/action at T."""
        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

        # Baseline evaluation at T
        eval_baseline = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10, 20],
        )

        # Record baseline state at T
        baseline_positions = {p.symbol: p for p in eval_baseline.positions}

        # Mutate future data (> T) across all stocks and benchmark
        universe_mutated = {}
        for sym, df in self.universe.items():
            df_mut = df.copy()
            mask = df_mut["date"] > self.eval_date
            df_mut.loc[mask, "close"] *= 3.5
            df_mut.loc[mask, "open"] *= 3.5
            df_mut.loc[mask, "high"] *= 3.5
            df_mut.loc[mask, "low"] *= 3.5
            df_mut.loc[mask, "volume"] *= 10.0
            universe_mutated[sym] = df_mut

        df_vni_mutated = self.df_vni.copy()
        mask_vni = df_vni_mutated["date"] > self.eval_date
        df_vni_mutated.loc[mask_vni, "close"] *= 0.2

        # Re-run evaluation at T with mutated future data
        eval_mutated = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=universe_mutated,
            config=cfg,
            df_vnindex=df_vni_mutated,
            df_vn30=self.df_vn30,
            horizons=[5, 10, 20],
        )

        mutated_positions = {p.symbol: p for p in eval_mutated.positions}

        # 1. Constituent selection and symbols at T must be 100% identical
        self.assertEqual(
            sorted(baseline_positions.keys()),
            sorted(mutated_positions.keys()),
        )

        # 2. Allocation weights at T must be 100% identical
        self.assertEqual(eval_baseline.allocated_weight, eval_mutated.allocated_weight)
        self.assertEqual(eval_baseline.unallocated_weight, eval_mutated.unallocated_weight)

        for sym, pos_base in baseline_positions.items():
            pos_mut = mutated_positions[sym]
            # Action at T
            self.assertEqual(pos_base.action, pos_mut.action)
            # Signal score at T
            self.assertEqual(pos_base.signal_score, pos_mut.signal_score)
            # Risk adjusted score at T
            self.assertEqual(pos_base.risk_adjusted_score, pos_mut.risk_adjusted_score)
            # Confidence at T
            self.assertEqual(pos_base.confidence, pos_mut.confidence)
            # Entry price at T
            self.assertEqual(pos_base.entry_price, pos_mut.entry_price)
            # Position weight at T
            self.assertEqual(pos_base.weight, pos_mut.weight)
            # Execution eligibility at T
            self.assertEqual(pos_base.is_executable, pos_mut.is_executable)

            # 3. Forward outcomes (> T) MUST change due to mutated future prices
            for h in [5, 10, 20]:
                if pos_base.forward_availability[h]:
                    self.assertNotEqual(
                        pos_base.forward_returns[h],
                        pos_mut.forward_returns[h],
                    )

        # 4. Portfolio returns change ONLY because forward outcomes changed
        for h in [5, 10, 20]:
            if eval_baseline.horizon_availability[h]:
                self.assertNotEqual(
                    eval_baseline.portfolio_forward_returns[h],
                    eval_mutated.portfolio_forward_returns[h],
                )


class TestE2EMissingOutcomePropagation(unittest.TestCase):
    """Test Suite 2 — Missing Outcome Propagation across position, portfolio, and aggregate summary layers."""

    def setUp(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        self.cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
        )

    def test_scenario_1_all_outcomes_available(self) -> None:
        """Scenario 1: All outcomes available."""
        df1 = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        df2 = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0)
        universe = {"SYM1": df1, "SYM2": df2}
        eval_d = df1["date"].iloc[50]

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10, 20],
        )

        for pos in eval_res.positions:
            for h in [5, 10, 20]:
                self.assertTrue(pos.forward_availability[h])
                self.assertIsInstance(pos.forward_returns[h], float)

        for h in [5, 10, 20]:
            self.assertTrue(eval_res.horizon_availability[h])
            self.assertIsInstance(eval_res.portfolio_forward_returns[h], float)

        agg = aggregate_portfolio_results([eval_res], horizons=[5, 10, 20])
        for h in [5, 10, 20]:
            self.assertEqual(agg["horizon_metrics"][h]["valid_evaluation_points"], 1)
            self.assertIsNotNone(agg["horizon_metrics"][h]["mean"])

    def test_scenario_2_one_horizon_unavailable(self) -> None:
        """Scenario 2: One horizon unavailable (e.g., 5D available, 20D unavailable due to proximity to end of data)."""
        df1 = create_synthetic_ohlcv("2024-01-01", 60, 10000.0, 100.0)
        df2 = create_synthetic_ohlcv("2024-01-01", 60, 20000.0, 150.0)
        universe = {"SYM1": df1, "SYM2": df2}
        eval_d = df1["date"].iloc[49]  # 50th session

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=self.cfg,
            df_vnindex=self.df_vni.iloc[:60],
            horizons=[5, 20],
        )

        # 5D is available
        self.assertTrue(eval_res.horizon_availability[5])
        self.assertIsNotNone(eval_res.portfolio_forward_returns[5])

        # 20D is unavailable
        self.assertFalse(eval_res.horizon_availability[20])
        self.assertIsNone(eval_res.portfolio_forward_returns[20])

        agg = aggregate_portfolio_results([eval_res], horizons=[5, 20])
        self.assertEqual(agg["horizon_metrics"][5]["valid_evaluation_points"], 1)
        self.assertEqual(agg["horizon_metrics"][20]["valid_evaluation_points"], 0)
        self.assertIsNone(agg["horizon_metrics"][20]["mean"])
        self.assertIsNone(agg["horizon_metrics"][20]["hit_rate"])

    def test_scenario_3_one_symbol_unavailable(self) -> None:
        """Scenario 3: One symbol in portfolio lacks future data for horizon, rendering portfolio outcome None."""
        df1 = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        df2 = create_synthetic_ohlcv("2024-01-01", 55, 20000.0, 150.0)  # df2 ends at day 55
        universe = {"SYM1": df1, "SYM2": df2}
        eval_d = df1["date"].iloc[49]  # day 50 -> 10D horizon requires day 60 (SYM2 lacks day 60)

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            horizons=[10],
        )

        pos1 = next(p for p in eval_res.positions if p.symbol == "SYM1")
        pos2 = next(p for p in eval_res.positions if p.symbol == "SYM2")

        # SYM1 has 10D return
        self.assertTrue(pos1.forward_availability[10])
        self.assertIsNotNone(pos1.forward_returns[10])

        # SYM2 lacks 10D return -> MUST remain None, NOT 0.0 or loss
        self.assertFalse(pos2.forward_availability[10])
        self.assertIsNone(pos2.forward_returns[10])

        # Portfolio level horizon_availability MUST be False, portfolio_forward_returns MUST be None
        self.assertFalse(eval_res.horizon_availability[10])
        self.assertIsNone(eval_res.portfolio_forward_returns[10])

        agg = aggregate_portfolio_results([eval_res], horizons=[10])
        self.assertEqual(agg["horizon_metrics"][10]["valid_evaluation_points"], 0)
        self.assertIsNone(agg["horizon_metrics"][10]["mean"])

    def test_scenario_4_multiple_symbols_unavailable(self) -> None:
        """Scenario 4: Multiple symbols in portfolio lack future data for horizon."""
        df1 = create_synthetic_ohlcv("2024-01-01", 52, 10000.0, 100.0)
        df2 = create_synthetic_ohlcv("2024-01-01", 52, 20000.0, 150.0)
        universe = {"SYM1": df1, "SYM2": df2}
        eval_d = df1["date"].iloc[49]  # day 50 -> 5D requires day 55

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=self.cfg,
            df_vnindex=self.df_vni.iloc[:52],
            horizons=[5],
        )

        for pos in eval_res.positions:
            self.assertFalse(pos.forward_availability[5])
            self.assertIsNone(pos.forward_returns[5])

        self.assertFalse(eval_res.horizon_availability[5])
        self.assertIsNone(eval_res.portfolio_forward_returns[5])

    def test_scenario_5_entire_horizon_unavailable(self) -> None:
        """Scenario 5: Entire horizon unavailable for all symbols in portfolio."""
        df1 = create_synthetic_ohlcv("2024-01-01", 50, 10000.0, 100.0)
        df2 = create_synthetic_ohlcv("2024-01-01", 50, 20000.0, 150.0)
        universe = {"SYM1": df1, "SYM2": df2}
        eval_d = df1["date"].iloc[49]  # evaluation at exact last trading session

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=self.cfg,
            df_vnindex=self.df_vni.iloc[:50],
            horizons=[5, 10, 20],
        )

        for h in [5, 10, 20]:
            self.assertFalse(eval_res.horizon_availability[h])
            self.assertIsNone(eval_res.portfolio_forward_returns[h])

        agg = aggregate_portfolio_results([eval_res], horizons=[5, 10, 20])
        for h in [5, 10, 20]:
            self.assertEqual(agg["horizon_metrics"][h]["valid_evaluation_points"], 0)
            self.assertIsNone(agg["horizon_metrics"][h]["mean"])
            self.assertIsNone(agg["horizon_metrics"][h]["median"])
            self.assertIsNone(agg["horizon_metrics"][h]["hit_rate"])


class TestE2ECostSlippageSingleApplication(unittest.TestCase):
    """Test Suite 3 — Single-Application Invariant for Transaction Costs & Slippage."""

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

        # WATCH stock (100 -> 120 at +5D - price moves, but non-executed WATCH earns 0 return / 0 cost)
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
            "BUY_STK": self.df_buy,
            "SELL_STK": self.df_sell,
            "WATCH_STK": self.df_watch,
        }
        self.eval_date = self.dates[49]

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_single_application_cost_slippage_against_independent_math_oracle(
        self, mock_gen_rec
    ) -> None:
        """Verify gross -> execution -> net -> portfolio return does NOT apply cost/slippage twice using pure independent mathematical oracles."""

        def side_effect(symbol, **kwargs):
            if symbol == "BUY_STK":
                return {
                    "action": "BUY",
                    "signal_score": 85.0,
                    "risk_adjusted_score": 85.0,
                    "confidence": 0.8,
                    "trade_plan": {"current_price": 100.0},
                }
            if symbol == "SELL_STK":
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

        tc = 0.0030  # 0.30% total transaction cost (0.15% entry, 0.15% exit)
        slip = 0.0010  # 0.10% adverse slippage per leg

        # --- INDEPENDENT MATHEMATICAL ORACLE FORMULAS (No helper calls!) ---
        c_entry = tc / 2.0  # 0.0015
        c_exit = tc / 2.0  # 0.0015

        # 1. BUY_STK Oracle (entry=100, exit=110):
        # p_entry_exec = 100 * (1 + 0.001) = 100.1
        # p_exit_exec  = 110 * (1 - 0.001) = 109.89
        # net_return   = (1 - 0.0015) * (109.89 / 100.1) * (1 - 0.0015) - 1.0 = 0.094511
        p_entry_buy_exec = round(100.0 * (1.0 + slip), 6)
        p_exit_buy_exec = round(110.0 * (1.0 - slip), 6)
        oracle_net_buy = round(
            (1.0 - c_entry) * (p_exit_buy_exec / p_entry_buy_exec) * (1.0 - c_exit) - 1.0, 6
        )
        self.assertEqual(oracle_net_buy, 0.094511)

        # 2. SELL_STK Oracle (entry=100, exit=90):
        # p_entry_exec = 100 * (1 - 0.001) = 99.9
        # p_exit_exec  = 90 * (1 + 0.001) = 90.09
        # slip_ret     = 1.0 - (90.09 / 99.9) = 0.098198
        # net_return   = (1 - 0.0015) * (1 + 0.098198) * (1 - 0.0015) - 1.0 = 0.094906
        p_entry_sell_exec = round(100.0 * (1.0 - slip), 6)
        p_exit_sell_exec = round(90.0 * (1.0 + slip), 6)
        slip_ret_sell = round(1.0 - (p_exit_sell_exec / p_entry_sell_exec), 6)
        oracle_net_sell = round((1.0 - c_entry) * (1.0 + slip_ret_sell) * (1.0 - c_exit) - 1.0, 6)
        self.assertEqual(oracle_net_sell, 0.094906)

        # 3. WATCH_STK Oracle: non-executed -> 0.0
        oracle_net_watch = 0.0

        # Equal weighting across 3 positions: w = round(1 / 3, 6) = 0.333333
        w = round(1.0 / 3.0, 6)
        oracle_portfolio_net = round(
            w * oracle_net_buy + w * oracle_net_sell + w * oracle_net_watch, 6
        )

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

        pos_buy = next(p for p in eval_res.positions if p.symbol == "BUY_STK")
        pos_sell = next(p for p in eval_res.positions if p.symbol == "SELL_STK")
        pos_watch = next(p for p in eval_res.positions if p.symbol == "WATCH_STK")

        # Position level net returns must match independent oracles
        self.assertEqual(pos_buy.forward_returns[5], oracle_net_buy)
        self.assertEqual(pos_sell.forward_returns[5], oracle_net_sell)
        self.assertEqual(pos_watch.forward_returns[5], oracle_net_watch)

        # Portfolio level net return must match independent oracle exactly
        self.assertEqual(eval_res.portfolio_forward_returns[5], oracle_portfolio_net)

        # Double-deduction check: if costs were subtracted a second time at portfolio level,
        # portfolio return would be roughly 0.058133 instead of 0.063139
        self.assertNotEqual(eval_res.portfolio_forward_returns[5], 0.058133)


class TestE2EActionSemantics(unittest.TestCase):
    """Test Suite 4 — Action Semantics (BUY, SELL, WATCH, HOLD, AVOID)."""

    def setUp(self) -> None:
        self.tc = 0.0030
        self.slip = 0.0010

    def test_flat_buy_action(self) -> None:
        """Flat BUY trade (entry == exit): gross = 0.0, net < 0 due to slippage & transaction costs."""
        # Math oracle:
        # entry_exec = 100 * (1 + 0.001) = 100.1
        # exit_exec  = 100 * (1 - 0.001) = 99.9
        # net_return = 0.9985 * (99.9 / 100.1) * 0.9985 - 1.0 = -0.00499
        oracle_net = round(0.9985 * (99.9 / 100.1) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 100.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="BUY"
        )
        self.assertEqual(res.gross_return, 0.0)
        self.assertEqual(res.net_return, oracle_net)
        self.assertLess(res.net_return, 0.0)

    def test_flat_sell_action(self) -> None:
        """Flat SELL trade (entry == exit): gross = 0.0, net < 0 due to slippage & transaction costs."""
        # Math oracle:
        # entry_exec = 100 * (1 - 0.001) = 99.9
        # exit_exec  = 100 * (1 + 0.001) = 100.1
        # slip_ret   = 1.0 - (100.1 / 99.9) = -0.002002
        # net_return = 0.9985 * (1 - 0.002002) * 0.9985 - 1.0 = -0.004994
        oracle_net = round(0.9985 * (1.0 + (1.0 - 100.1 / 99.9)) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 100.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="SELL"
        )
        self.assertEqual(res.gross_return, 0.0)
        self.assertEqual(res.net_return, oracle_net)
        self.assertLess(res.net_return, 0.0)

    def test_profitable_buy_action(self) -> None:
        """Profitable BUY trade (exit > entry): gross > 0, net > 0."""
        # 100 -> 120 (+20% gross): net = 0.194012
        oracle_net = round(0.9985 * (119.88 / 100.10) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 120.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="BUY"
        )
        self.assertEqual(res.gross_return, 0.20)
        self.assertEqual(res.net_return, oracle_net)
        self.assertGreater(res.net_return, 0.0)

    def test_losing_buy_action(self) -> None:
        """Losing BUY trade (exit < entry): gross < 0, net < gross."""
        # 100 -> 80 (-20% gross): net = -0.203992
        oracle_net = round(0.9985 * (79.92 / 100.10) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 80.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="BUY"
        )
        self.assertEqual(res.gross_return, -0.20)
        self.assertEqual(res.net_return, oracle_net)
        self.assertLess(res.net_return, -0.20)

    def test_profitable_sell_action(self) -> None:
        """Profitable SELL trade (exit < entry): price drops 100 -> 80 -> gross = +0.20, net > 0."""
        # entry_exec = 99.9, exit_exec = 80.08
        # slip_ret = 1.0 - (80.08 / 99.9) = 0.198398
        # net_return = 0.9985 * (1 + 0.198398) * 0.9985 - 1 = 0.194801
        p_entry_exec = 99.9
        p_exit_exec = 80.08
        slip_ret = 1.0 - (p_exit_exec / p_entry_exec)
        oracle_net = round(0.9985 * (1.0 + slip_ret) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 80.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="SELL"
        )
        self.assertEqual(res.gross_return, 0.20)
        self.assertEqual(res.net_return, oracle_net)
        self.assertGreater(res.net_return, 0.0)

    def test_losing_sell_action(self) -> None:
        """Losing SELL trade (exit > entry): price rises 100 -> 120 -> gross = -0.20, net < 0."""
        # entry_exec = 99.9, exit_exec = 120.12
        # slip_ret = 1.0 - (120.12 / 99.9) = -0.202402
        # net_return = 0.9985 * (1 - 0.202402) * 0.9985 - 1 = -0.204787
        p_entry_exec = 99.9
        p_exit_exec = 120.12
        slip_ret = 1.0 - (p_exit_exec / p_entry_exec)
        oracle_net = round(0.9985 * (1.0 + slip_ret) * 0.9985 - 1.0, 6)
        res = calculate_execution_return(
            100.0, 120.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action="SELL"
        )
        self.assertEqual(res.gross_return, -0.20)
        self.assertEqual(res.net_return, oracle_net)
        self.assertLess(res.net_return, -0.20)

    def test_non_executed_actions_earn_zero(self) -> None:
        """WATCH, HOLD, and AVOID actions earn strictly zero return without incurring transaction fees or slippage."""
        for act in ("WATCH", "HOLD", "AVOID"):
            res = calculate_execution_return(
                100.0, 150.0, transaction_cost_pct=self.tc, slippage_pct=self.slip, action=act
            )
            self.assertEqual(res.gross_return, 0.0)
            self.assertEqual(res.slippage_adjusted_return, 0.0)
            self.assertEqual(res.net_return, 0.0)


class TestE2EPortfolioAllocationInvariants(unittest.TestCase):
    """Test Suite 5 — End-to-End Portfolio Allocation Invariants."""

    def setUp(self) -> None:
        self.df_vni, self.df_vn30, self.universe = create_multi_symbol_universe(num_days=100)
        self.eval_date = self.df_vni["date"].iloc[50]

    def test_single_position_portfolio_allocation_invariant(self) -> None:
        """Single-position portfolio allocation invariant: sum(weights) + unallocated == 1.0."""
        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        self.assertEqual(len(eval_res.positions), 1)
        self.assertEqual(eval_res.positions[0].weight, 1.0)
        self.assertEqual(eval_res.allocated_weight, 1.0)
        self.assertEqual(eval_res.unallocated_weight, 0.0)
        self.assertAlmostEqual(
            sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight, 1.0, places=6
        )

    def test_multi_position_portfolio_allocation_invariant_and_no_duplicates(self) -> None:
        """Multi-position portfolio allocation invariant & symbol uniqueness."""
        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        symbols = [p.symbol for p in eval_res.positions]
        self.assertEqual(len(symbols), len(set(symbols)))  # No duplicate symbols!

        total_w = sum(p.weight for p in eval_res.positions)
        self.assertEqual(eval_res.allocated_weight, round(total_w, 6))
        self.assertAlmostEqual(total_w + eval_res.unallocated_weight, 1.0, places=6)

    def test_partially_allocated_portfolio_due_to_weight_cap(self) -> None:
        """Partially allocated portfolio due to max_weight_per_position hard cap."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            max_weight_per_position=0.35,  # 2 positions * 0.35 = 0.70 allocated, 0.30 unallocated
            min_history=30,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        self.assertEqual(len(eval_res.positions), 2)
        for pos in eval_res.positions:
            self.assertEqual(pos.weight, 0.35)
        self.assertEqual(eval_res.allocated_weight, 0.70)
        self.assertEqual(eval_res.unallocated_weight, 0.30)
        self.assertAlmostEqual(
            sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight, 1.0, places=6
        )

    @patch("scripts.lib.portfolio_backtest.generate_recommendation")
    def test_unallocated_capital_earns_zero_return(self, mock_gen_rec) -> None:
        """Unallocated capital generates strictly zero return contribution."""
        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": 100.0},
        }

        # 50% allocated to SYM1 (which earns 10%), 50% unallocated -> portfolio return = 5%
        dates = pd.date_range("2024-01-01", periods=60, freq="B").strftime("%Y-%m-%d")
        prices = [100.0] * 50 + [110.0] * 10
        df_sym = pd.DataFrame(
            {
                "date": dates,
                "open": prices,
                "high": prices,
                "low": prices,
                "close": prices,
                "volume": [1_000_000.0] * 60,
            }
        )

        cfg = PortfolioConfig(
            max_positions=1,
            min_signal_score=0.0,
            allowed_actions=("BUY",),
            max_weight_per_position=0.50,
            min_history=30,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )
        eval_res = evaluate_portfolio_at_date(
            evaluation_date=dates[49],
            universe_stock_map={"SYM1": df_sym},
            config=cfg,
            horizons=[5],
        )

        self.assertEqual(len(eval_res.positions), 1)
        self.assertEqual(eval_res.positions[0].weight, 0.50)
        self.assertEqual(eval_res.allocated_weight, 0.50)
        self.assertEqual(eval_res.unallocated_weight, 0.50)
        # Position return: 10%
        self.assertEqual(eval_res.positions[0].forward_returns[5], 0.10)
        # Portfolio return: 0.50 * 0.10 = 0.05
        self.assertEqual(eval_res.portfolio_forward_returns[5], 0.05)

    def test_cost_and_slippage_do_not_alter_allocation_weights(self) -> None:
        """Transaction cost and slippage parameters change position net returns, NOT allocation weights."""
        cfg_zero = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        cfg_cost = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.005,
            slippage_pct=0.002,
        )

        eval_zero = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg_zero,
            df_vnindex=self.df_vni,
        )

        eval_cost = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=cfg_cost,
            df_vnindex=self.df_vni,
        )

        weights_zero = [p.weight for p in eval_zero.positions]
        weights_cost = [p.weight for p in eval_cost.positions]

        self.assertEqual(weights_zero, weights_cost)
        self.assertEqual(eval_zero.allocated_weight, eval_cost.allocated_weight)
        self.assertEqual(eval_zero.unallocated_weight, eval_cost.unallocated_weight)


class TestE2EHorizonIsolation(unittest.TestCase):
    """Test Suite 6 — Horizon Isolation & Cross-Horizon Independence."""

    def setUp(self) -> None:
        self.df_vni, self.df_vn30, self.universe = create_multi_symbol_universe(num_days=100)
        self.eval_date = self.df_vni["date"].iloc[50]
        self.cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

    def test_horizon_isolation_across_single_and_multi_horizon_runs(self) -> None:
        """Verify 5D outputs are 100% strictly identical whether running [5], [5, 10], or [5, 10, 20]."""
        eval_5 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )

        eval_5_10 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10],
        )

        eval_5_10_20 = evaluate_portfolio_at_date(
            evaluation_date=self.eval_date,
            universe_stock_map=self.universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10, 20],
        )

        # 1. 5D portfolio returns must be strictly identical across all 3 runs
        ret_5_from_run1 = eval_5.portfolio_forward_returns[5]
        ret_5_from_run2 = eval_5_10.portfolio_forward_returns[5]
        ret_5_from_run3 = eval_5_10_20.portfolio_forward_returns[5]

        self.assertEqual(ret_5_from_run1, ret_5_from_run2)
        self.assertEqual(ret_5_from_run1, ret_5_from_run3)

        # 2. 10D portfolio returns must be strictly identical between [5, 10] and [5, 10, 20]
        ret_10_from_run2 = eval_5_10.portfolio_forward_returns[10]
        ret_10_from_run3 = eval_5_10_20.portfolio_forward_returns[10]

        self.assertEqual(ret_10_from_run2, ret_10_from_run3)

        # 3. Position level 5D returns must be strictly identical
        for pos1 in eval_5.positions:
            pos2 = next(p for p in eval_5_10.positions if p.symbol == pos1.symbol)
            pos3 = next(p for p in eval_5_10_20.positions if p.symbol == pos1.symbol)

            self.assertEqual(pos1.forward_returns[5], pos2.forward_returns[5])
            self.assertEqual(pos1.forward_returns[5], pos3.forward_returns[5])


class TestE2EDeterministicReproducibility(unittest.TestCase):
    """Test Suite 7 — Deterministic End-to-End Reproducibility (Run A == Run B)."""

    def setUp(self) -> None:
        self.df_vni, self.df_vn30, self.universe = create_multi_symbol_universe(num_days=90)
        self.eval_dates = [self.df_vni["date"].iloc[40], self.df_vni["date"].iloc[50]]
        self.cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            allowed_actions=("BUY", "SELL", "WATCH", "HOLD", "AVOID"),
            min_history=30,
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

    def test_run_a_equals_run_b_exact_value_reproducibility(self) -> None:
        """Verify Run A and Run B produce 100% byte/value identical outputs across all quantitative fields."""
        res_a = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        res_b = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=self.cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        dict_a = res_a.to_dict()
        dict_b = res_b.to_dict()

        # Strict dictionary equivalence without stripping any quantitative fields!
        self.assertEqual(dict_a, dict_b)


class TestE2EFailClosedPropagation(unittest.TestCase):
    """Test Suite 8 — Fail-Closed Boundary Validation Propagation."""

    def setUp(self) -> None:
        self.df_vni, self.df_vn30, self.universe = create_multi_symbol_universe(num_days=80)
        self.eval_date = self.df_vni["date"].iloc[40]
        self.cfg = PortfolioConfig(min_history=30)

    def test_invalid_ohlcv_data_raises_error(self) -> None:
        """Invalid OHLCV data (negative volume) raises ValueError loudly."""
        df_corrupted = self.universe["SYM1"].copy()
        df_corrupted.loc[10, "volume"] = -500.0  # Critical error: negative volume
        universe_bad = {"SYM1": df_corrupted, "SYM2": self.universe["SYM2"]}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_bad,
                config=self.cfg,
            )

    def test_invalid_or_timezone_aware_date_raises_error(self) -> None:
        """Timezone-aware dates or invalid date formats raise ValueError loudly."""
        tz_ts = pd.Timestamp("2024-03-01 00:00:00+00:00")
        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=tz_ts,
                universe_stock_map=self.universe,
                config=self.cfg,
            )

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2024-03-01 12:00:00",  # Contains time component
                universe_stock_map=self.universe,
                config=self.cfg,
            )

    def test_duplicate_and_unsorted_dates_raise_error(self) -> None:
        """Duplicate dates or unsorted chronological dates raise ValueError loudly."""
        df_dup = self.universe["SYM1"].copy()
        df_dup.iloc[5] = df_dup.iloc[4]  # duplicate row
        universe_dup = {"SYM1": df_dup}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_dup,
                config=self.cfg,
            )

    def test_missing_required_columns_raises_error(self) -> None:
        """Missing required OHLCV columns raise ValueError loudly."""
        df_missing_col = self.universe["SYM1"].drop(columns=["close"]).copy()
        universe_bad = {"SYM1": df_missing_col}

        with self.assertRaises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_bad,
                config=self.cfg,
            )

    def test_invalid_execution_configuration_raises_error(self) -> None:
        """Invalid execution configuration parameters raise ValueError loudly."""
        with self.assertRaises(ValueError):
            ExecutionConfig(min_avg_volume=-500.0)

        with self.assertRaises(ValueError):
            ExecutionConfig(max_participation_rate=1.5)

        with self.assertRaises(ValueError):
            ExecutionConfig(
                estimated_order_size_shares=1000.0,
                estimated_order_value_vnd=10_000_000.0,  # Cannot supply both!
            )


if __name__ == "__main__":
    unittest.main()
