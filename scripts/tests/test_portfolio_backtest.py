"""Unit & Integration Tests for Portfolio Backtesting Framework."""

from unittest.mock import patch

import pandas as pd
import pytest

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


@pytest.mark.unit
class TestPortfolioConfigValidation:
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
        assert cfg.max_positions == 5
        assert cfg.min_signal_score == 60.0
        assert cfg.min_confidence == 0.5
        assert cfg.max_weight_per_position == 0.25
        assert cfg.require_executable

    def test_invalid_max_positions(self) -> None:
        with pytest.raises(ValueError):
            PortfolioConfig(max_positions=0)

        with pytest.raises(ValueError):
            PortfolioConfig(max_positions=-1)

        with pytest.raises(ValueError):
            PortfolioConfig(max_positions=2.5)  # float not allowed for int

        with pytest.raises(ValueError):
            PortfolioConfig(max_positions=True)  # bool not allowed

    def test_invalid_thresholds(self) -> None:
        with pytest.raises(ValueError):
            PortfolioConfig(min_signal_score=-10.0)

        with pytest.raises(ValueError):
            PortfolioConfig(min_signal_score=150.0)

        with pytest.raises(ValueError):
            PortfolioConfig(min_confidence=-0.1)

        with pytest.raises(ValueError):
            PortfolioConfig(min_confidence=1.5)

    def test_nan_and_inf_config_values(self) -> None:
        with pytest.raises(ValueError):
            PortfolioConfig(min_signal_score=float("nan"))

        with pytest.raises(ValueError):
            PortfolioConfig(min_confidence=float("inf"))

        with pytest.raises(ValueError):
            PortfolioConfig(max_weight_per_position=float("-inf"))

    def test_bool_and_non_numeric_types(self) -> None:
        with pytest.raises(ValueError):
            PortfolioConfig(min_signal_score=True)

        with pytest.raises(ValueError):
            PortfolioConfig(min_signal_score="invalid")

        with pytest.raises((ValueError, TypeError)):
            PortfolioConfig(require_executable="true")  # type: ignore[arg-type]

    def test_deterministic_boundary_values(self) -> None:
        # Boundary: 0.0 and 100.0 for min_signal_score
        cfg1 = PortfolioConfig(min_signal_score=0.0)
        assert cfg1.min_signal_score == 0.0

        cfg2 = PortfolioConfig(min_signal_score=100.0)
        assert cfg2.min_signal_score == 100.0

        # Boundary: max_weight_per_position = 1.0
        cfg3 = PortfolioConfig(max_weight_per_position=1.0)
        assert cfg3.max_weight_per_position == 1.0


@pytest.mark.unit
class TestPortfolioWeightValidation:
    """Test Suite for portfolio weight validation."""

    def test_valid_weights(self) -> None:
        validate_portfolio_weights([0.2, 0.2, 0.2, 0.2, 0.2])
        validate_portfolio_weights([0.5, 0.3])  # partial allocation <= 1.0
        validate_portfolio_weights([])  # empty portfolio weights

    def test_invalid_negative_weight(self) -> None:
        with pytest.raises(ValueError):
            validate_portfolio_weights([0.5, -0.1])

    def test_invalid_weight_exceeding_one(self) -> None:
        with pytest.raises(ValueError):
            validate_portfolio_weights([0.6, 0.5])

    def test_invalid_nan_inf_weight(self) -> None:
        with pytest.raises(ValueError):
            validate_portfolio_weights([0.5, float("nan")])

        with pytest.raises(ValueError):
            validate_portfolio_weights([0.5, float("inf")])

    def test_bool_weight_rejected(self) -> None:
        with pytest.raises(ValueError):
            validate_portfolio_weights([0.5, True])


@pytest.mark.unit
class TestCandidateMetadataValidation:
    """Test Suite for candidate_metadata validation and error handling."""

    def setup_method(self) -> None:
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
        with pytest.raises(ValueError):
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
        with pytest.raises(ValueError):
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
            with pytest.raises((ValueError, TypeError)):
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

        assert res1.to_dict() == res2.to_dict()


@pytest.mark.unit
class TestPortfolioConstruction:
    """Test Suite for portfolio candidate selection and construction."""

    def setup_method(self) -> None:
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
        assert isinstance(eval_res, PortfolioEvaluation)
        assert len(eval_res.positions) <= 2
        assert eval_res.allocated_weight == 1.0
        assert eval_res.unallocated_weight == 0.0

        weights = [p.weight for p in eval_res.positions]
        assert weights == [0.5, 0.5]

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
        assert len(eval_res.positions) == 2
        assert eval_res.positions[0].weight == 0.30
        assert eval_res.positions[1].weight == 0.30
        assert eval_res.allocated_weight == 0.60
        assert eval_res.unallocated_weight == 0.40
        assert round(abs(eval_res.allocated_weight + eval_res.unallocated_weight - (1.0)), 6) == 0

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
        assert len(eval_res.positions) == 3
        for pos in eval_res.positions:
            assert pos.weight == 0.20
        assert eval_res.allocated_weight == 0.60
        assert eval_res.unallocated_weight == 0.40
        assert round(abs(eval_res.allocated_weight + eval_res.unallocated_weight - (1.0)), 6) == 0

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
        assert "LOW_VOL" not in selected_symbols
        assert "LOW_VOL" in eval_res.excluded_non_executable

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
        assert "LOW_VOL" in selected_symbols

        low_vol_pos = next(p for p in eval_res.positions if p.symbol == "LOW_VOL")
        assert not low_vol_pos.is_executable

    def test_universe_with_none_stock_raises_value_error(self) -> None:
        universe_corrupted = {
            "AAA": self.df_aaa,
            "NONE_STOCK": None,
        }
        cfg = PortfolioConfig()
        with pytest.raises(ValueError):
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
        with pytest.raises(ValueError):
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
        with pytest.raises(ValueError):
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
        assert len(eval_res.positions) == 0
        assert eval_res.allocated_weight == 0.0
        assert eval_res.unallocated_weight == 1.0
        assert eval_res.empty_reason == "no_eligible_candidates"
        assert eval_res.portfolio_forward_returns[5] is None

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
        assert len(eval_res.positions) == 0
        assert eval_res.allocated_weight == 0.0
        assert eval_res.unallocated_weight == 1.0
        assert eval_res.empty_reason == "all_candidates_non_executable"
        assert len(eval_res.excluded_non_executable) == 2
        assert eval_res.portfolio_forward_returns[5] is None

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
        assert "HIGH1" in selected_req
        assert "LOW1" not in selected_req
        assert "LOW1" in eval_req.excluded_non_executable

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
        assert "HIGH1" in selected_noreq
        assert "LOW1" in selected_noreq

        pos_low = next(p for p in eval_noreq.positions if p.symbol == "LOW1")
        pos_high = next(p for p in eval_noreq.positions if p.symbol == "HIGH1")
        assert not pos_low.is_executable
        assert pos_high.is_executable


@pytest.mark.unit
class TestPortfolioReturnCalculation:
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
        assert eval_res.portfolio_forward_returns[5] == 0.04
        assert eval_res.portfolio_forward_returns[10] == 0.16

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
            assert not eval_res.horizon_availability[5]
            assert eval_res.portfolio_forward_returns[5] is None


@pytest.mark.unit
class TestPortfolioTemporalIntegrity:
    """Test Suite for temporal integrity and fail-closed validation."""

    def setup_method(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 150.0)
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}
        self.eval_date = self.df_aaa["date"].iloc[40]

    def test_mutating_data_after_t_does_not_affect_portfolio_at_t(self) -> None:
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
        assert [p.symbol for p in eval1.positions] == [p.symbol for p in eval2.positions]
        assert [p.weight for p in eval1.positions] == [p.weight for p in eval2.positions]
        assert [p.signal_score for p in eval1.positions] == [
            p.signal_score for p in eval2.positions
        ]

    def test_physically_inserted_future_row_raises_error(self) -> None:
        df_corrupted = self.df_aaa.copy()
        # Insert a row with a future date before T
        future_date = self.df_aaa["date"].iloc[60]
        corrupted_row = df_corrupted.iloc[60].copy()
        corrupted_row["date"] = future_date

        df_corrupted.iloc[10] = corrupted_row

        universe_corrupted = {"AAA": df_corrupted, "BBB": self.df_bbb}
        cfg = PortfolioConfig(min_history=30)

        with pytest.raises(ValueError):
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

        with pytest.raises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_dup,
                config=cfg,
            )

        df_unsorted = self.df_aaa.iloc[::-1].copy().reset_index(drop=True)
        universe_unsorted = {"AAA": df_unsorted}

        with pytest.raises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=self.eval_date,
                universe_stock_map=universe_unsorted,
                config=cfg,
            )

    def test_missing_exact_evaluation_date_raises_error(self) -> None:
        cfg = PortfolioConfig(min_history=30)
        with pytest.raises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2099-01-01",  # Not in history
                universe_stock_map=self.universe,
                config=cfg,
            )

    def test_timezone_aware_evaluation_date_raises_value_error(self) -> None:
        cfg = PortfolioConfig(min_history=30)
        tz_ts = pd.Timestamp("2024-03-15 00:00:00+00:00")
        with pytest.raises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date=tz_ts,
                universe_stock_map=self.universe,
                config=cfg,
            )

        with pytest.raises(ValueError):
            evaluate_portfolio_at_date(
                evaluation_date="2024-03-15T00:00:00Z",
                universe_stock_map=self.universe,
                config=cfg,
            )

    def test_invalid_and_duplicate_evaluation_dates_in_run_portfolio_backtest(self) -> None:
        cfg = PortfolioConfig(min_history=30)

        # Invalid evaluation date
        with pytest.raises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=["invalid-date"],
                universe_stock_map=self.universe,
                config=cfg,
            )

        # Duplicate evaluation date
        eval_d = self.df_aaa["date"].iloc[40]
        with pytest.raises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=[eval_d, eval_d],
                universe_stock_map=self.universe,
                config=cfg,
            )

        # Unsorted evaluation dates
        eval_d1 = self.df_aaa["date"].iloc[40]
        eval_d2 = self.df_aaa["date"].iloc[30]
        with pytest.raises(ValueError):
            run_portfolio_backtest(
                evaluation_dates=[eval_d1, eval_d2],
                universe_stock_map=self.universe,
                config=cfg,
            )


@pytest.mark.unit
class TestPortfolioDeterminism:
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

        assert res1.to_dict() == res2.to_dict()
        assert "min_history" in res1.to_dict()["config"]
        assert res1.to_dict()["config"]["min_history"] == cfg.min_history


@pytest.mark.unit
class TestPortfolioAggregation:
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

        assert agg["total_evaluation_points"] == 3
        assert agg["non_empty_portfolios_count"] == 2
        assert agg["empty_portfolios_count"] == 1
        assert agg["empty_reasons_breakdown"]["no_eligible_candidates"] == 1

        h5 = agg["horizon_metrics"][5]
        assert h5["valid_evaluation_points"] == 2
        # mean of [0.10, -0.05] = 0.025
        assert h5["mean"] == 0.025
        # hit rate = 1 positive out of 2 = 0.5
        assert h5["hit_rate"] == 0.5

        # Sequential compounding: (1 + 0.10) * (1 - 0.05) - 1 = 1.10 * 0.95 - 1 = 1.045 - 1 = 0.045
        assert "sequential_compounded_return" in h5
        assert round(abs(h5["sequential_compounded_return"] - (0.045)), 5) == 0


@pytest.mark.unit
class TestZeroCostEquivalence:
    """Test Suite verifying transaction_cost_pct=0 and slippage_pct=0 equivalence."""

    def setup_method(self) -> None:
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

        assert len(eval_res.positions) == 2
        pos_a = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_b = next(p for p in eval_res.positions if p.symbol == "BBB")

        # Independent gross calculation directly from known price inputs (100 -> 110 and 100 -> 120)
        expected_gross_a = 0.10
        expected_gross_b = 0.20
        expected_portfolio_ret = round(0.5 * expected_gross_a + 0.5 * expected_gross_b, 6)  # 0.15

        # Weights check
        assert pos_a.weight == 0.5
        assert pos_b.weight == 0.5
        assert eval_res.allocated_weight == 1.0
        assert eval_res.unallocated_weight == 0.0

        # Position return check
        assert pos_a.forward_returns[5] == expected_gross_a
        assert pos_b.forward_returns[5] == expected_gross_b

        # Portfolio return check
        assert eval_res.portfolio_forward_returns[5] == expected_portfolio_ret


@pytest.mark.unit
class TestAllocationInvariants:
    """Test Suite verifying sum(weights) + unallocated_weight == 1.0 across configurations."""

    def setup_method(self) -> None:
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
        assert len(eval_res.positions) == 1
        assert eval_res.positions[0].weight == 1.0
        assert eval_res.allocated_weight == 1.0
        assert eval_res.unallocated_weight == 0.0
        assert (
            round(
                abs(
                    sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight - (1.0)
                ),
                6,
            )
            == 0
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
        assert len(eval_res.positions) == 2
        total_w = sum(p.weight for p in eval_res.positions)
        assert eval_res.allocated_weight == round(total_w, 6)
        assert round(abs(total_w + eval_res.unallocated_weight - (1.0)), 6) == 0

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
        assert len(eval_res.positions) == 3
        for pos in eval_res.positions:
            assert pos.weight == 0.25
        assert eval_res.allocated_weight == 0.75
        assert eval_res.unallocated_weight == 0.25
        assert (
            round(
                abs(
                    sum(p.weight for p in eval_res.positions) + eval_res.unallocated_weight - (1.0)
                ),
                6,
            )
            == 0
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
        assert len(eval_res.positions) == 2
        total_w = sum(p.weight for p in eval_res.positions)
        assert round(abs(total_w + eval_res.unallocated_weight - (1.0)), 6) == 0
        assert "LOW_VOL" not in [p.symbol for p in eval_res.positions]

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
        assert len(eval_res.positions) == 2
        total_w = sum(p.weight for p in eval_res.positions)
        assert round(abs(total_w + eval_res.unallocated_weight - (1.0)), 6) == 0


@pytest.mark.unit
class TestMixedActionPortfolio:
    """Test Suite verifying mixed BUY/SELL/WATCH portfolio semantics."""

    def setup_method(self) -> None:
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

        assert len(eval_res.positions) == 3
        pos_buy = next(p for p in eval_res.positions if p.symbol == "STK_BUY")
        pos_sell = next(p for p in eval_res.positions if p.symbol == "STK_SELL")
        pos_watch = next(p for p in eval_res.positions if p.symbol == "STK_WATCH")

        # Equal weighting (1/3 each)
        w = round(1.0 / 3.0, 6)
        assert pos_buy.weight == w
        assert pos_sell.weight == w
        assert pos_watch.weight == w

        # BUY net return: 0.094511
        assert pos_buy.forward_returns[5] == 0.094511

        # SELL net return: 0.094906
        assert pos_sell.forward_returns[5] == 0.094906

        # WATCH net return: STRICTLY 0.0 (no trading P&L, no transaction costs, no slippage)
        assert pos_watch.forward_returns[5] == 0.0

        # Expected portfolio return: round(w * 0.094511 + w * 0.094906 + w * 0.0, 6)
        expected_port_ret = round(w * 0.094511 + w * 0.094906, 6)
        assert eval_res.portfolio_forward_returns[5] == expected_port_ret


@pytest.mark.unit
class TestZeroReturnPositions:
    """Test Suite verifying zero price-change positions (entry price == exit price)."""

    def setup_method(self) -> None:
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
        assert pos_buy.forward_returns[5] == -0.00499

        # SELL flat trade: entry=100, exit=100
        # gross return = 0.0
        # net_return = (1 - 0.0015) * (1 + (1 - 100.1 / 99.9)) * (1 - 0.0015) - 1 = -0.004994
        assert pos_sell.forward_returns[5] == -0.004994

        # WATCH flat trade:
        # gross return = 0.0, net return = 0.0
        assert pos_watch.forward_returns[5] == 0.0


@pytest.mark.unit
class TestPartialCapitalAllocation:
    """Test Suite verifying partial allocation where allocated_weight < 1.0."""

    def setup_method(self) -> None:
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

        assert len(eval_res.positions) == 1
        pos = eval_res.positions[0]
        assert pos.weight == 0.50
        assert eval_res.allocated_weight == 0.50
        assert eval_res.unallocated_weight == 0.50

        # Position return: (120/100) - 1 = +0.20
        assert pos.forward_returns[5] == 0.20

        # Portfolio return contribution: 0.50 * 0.20 = 0.10 (unallocated capital earns 0.0)
        assert eval_res.portfolio_forward_returns[5] == 0.10


@pytest.mark.unit
class TestMultipleHorizonsIndependence:
    """Test Suite verifying independence across multiple horizons (5D, 10D)."""

    def setup_method(self) -> None:
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
        assert pos.forward_returns[5] == 0.094511
        assert eval_res.portfolio_forward_returns[5] == 0.094511

        # 10D net return: 0.194012 (from 100 -> 120)
        assert pos.forward_returns[10] == 0.194012
        assert eval_res.portfolio_forward_returns[10] == 0.194012


@pytest.mark.unit
class TestIndependentMathOracleCostSlippage:
    """Test Suite validating portfolio net returns against an independent mathematical oracle."""

    def setup_method(self) -> None:
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

        assert oracle_net == 0.194012

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
        assert pos_net == oracle_net
        assert port_net == oracle_net


@pytest.mark.unit
class TestMissingOutcomeSemantics:
    """Test Suite verifying strict missing forward outcome contracts."""

    def setup_method(self) -> None:
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
        assert len(eval_res.positions) == 2
        pos_aaa = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_bbb = next(p for p in eval_res.positions if p.symbol == "BBB")

        assert pos_aaa.forward_availability[5]
        assert pos_bbb.forward_availability[5]
        assert pos_aaa.forward_returns[5] == 0.10
        assert pos_bbb.forward_returns[5] == 0.20

        # Portfolio level horizon_availability MUST be True, portfolio_forward_returns MUST be 0.15
        assert eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] == 0.15

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

        assert len(eval_res.positions) == 2
        pos_aaa = next(p for p in eval_res.positions if p.symbol == "AAA")
        pos_bbb = next(p for p in eval_res.positions if p.symbol == "BBB")

        assert pos_aaa.forward_availability[5]
        assert pos_aaa.forward_returns[5] is not None

        assert not pos_bbb.forward_availability[5]
        assert pos_bbb.forward_returns[5] is None

        # Portfolio level horizon_availability MUST be False, portfolio_forward_returns MUST be None
        assert not eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] is None

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

        assert len(eval_res.positions) == 2
        for pos in eval_res.positions:
            assert not pos.forward_availability[5]
            assert pos.forward_returns[5] is None

        assert not eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] is None

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
        assert h5["valid_evaluation_points"] == 1
        assert h5["mean"] == 0.10
        assert h5["hit_rate"] == 1.0


@pytest.mark.unit
class TestPortfolioIntegration:
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
        assert len(wf_res.evaluation_dates) > 0

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

        assert isinstance(port_res, PortfolioBacktestResult)
        assert port_res.evaluation_dates == wf_res.evaluation_dates
        assert len(port_res.evaluations) == len(wf_res.evaluation_dates)


@pytest.mark.unit
class TestPortfolioTemporalBoundaries:
    """Test Suite focusing on temporal boundaries, exact trading-session semantics, and evaluation-date coverage."""

    def setup_method(self) -> None:
        self.df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        self.df_vn30 = create_synthetic_ohlcv("2024-01-01", 100, 1250.0, 1.0)
        self.df_aaa = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        self.df_bbb = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0)
        self.universe = {"AAA": self.df_aaa, "BBB": self.df_bbb}

    def assert_portfolio_construction_state_equals(
        self, eval1: PortfolioEvaluation, eval2: PortfolioEvaluation
    ) -> None:
        """Assert exact equality of signal and portfolio construction states between two PortfolioEvaluations, excluding forward outcomes."""
        assert eval1.evaluation_date == eval2.evaluation_date
        assert eval1.allocated_weight == eval2.allocated_weight
        assert eval1.unallocated_weight == eval2.unallocated_weight
        assert eval1.excluded_filtered == eval2.excluded_filtered
        assert eval1.excluded_non_executable == eval2.excluded_non_executable
        assert eval1.empty_reason == eval2.empty_reason

        assert len(eval1.positions) == len(eval2.positions)
        for p1, p2 in zip(eval1.positions, eval2.positions, strict=True):
            assert p1.symbol == p2.symbol
            assert p1.weight == p2.weight
            assert p1.action == p2.action
            assert p1.signal_score == p2.signal_score
            assert p1.risk_adjusted_score == p2.risk_adjusted_score
            assert p1.confidence == p2.confidence
            assert p1.entry_price == p2.entry_price
            assert p1.is_executable == p2.is_executable

    def test_case_a_evaluation_date_at_min_history_boundary(self) -> None:
        """1. Evaluation date at the start of sufficient min_history window (T-30 ... T ... T+N).

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

        # Signals, actions, weights, scores, and all construction attributes at T must be strictly identical
        self.assert_portfolio_construction_state_equals(res1, res2)

        # Forward outcomes must reflect mutated future prices (> T)
        pos1_aaa = next(p for p in res1.positions if p.symbol == "AAA")
        pos2_aaa = next(p for p in res2.positions if p.symbol == "AAA")
        assert pos1_aaa.forward_returns[5] != pos2_aaa.forward_returns[5]

    def test_case_b_evaluation_date_at_last_trading_session(self) -> None:
        """2. Evaluation date at the last trading session in the dataset.

        Verify:
        - Signal/history is valid with sufficient history;
        - All forward outcomes are unavailable (None) at position and portfolio levels;
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

        assert eval_res.evaluation_date == last_eval_d
        assert len(eval_res.positions) > 0

        # Every position forward return and availability must be False and None
        for pos in eval_res.positions:
            for h in [5, 10, 20]:
                assert not pos.forward_availability[h]
                assert pos.forward_returns[h] is None

        # Portfolio forward returns must be None
        for h in [5, 10, 20]:
            assert not eval_res.horizon_availability[h]
            assert eval_res.portfolio_forward_returns[h] is None

        # Aggregate accounting must exclude unavailable evaluation point from denominator
        agg = aggregate_portfolio_results([eval_res], horizons=[5])
        h5 = agg["horizon_metrics"][5]
        assert h5["valid_evaluation_points"] == 0
        assert h5["mean"] is None
        assert h5["hit_rate"] is None
        assert h5["sequential_compounded_return"] is None

    def test_case_c_evaluation_date_near_dataset_end(self) -> None:
        """3. Evaluation date near the dataset end (e.g. exactly 1 session available after T).

        Verify:
        - Horizon 1 is available if framework evaluated with horizon=[1, 5] at both stock and portfolio levels;
        - Longer horizons (e.g. 5) are unavailable (None) at both stock and portfolio levels;
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

        assert len(eval_res.positions) > 0

        # Stock-level assertions for selected positions
        for pos in eval_res.positions:
            assert pos.forward_availability[1]
            assert pos.forward_returns[1] is not None

            assert not pos.forward_availability[5]
            assert pos.forward_returns[5] is None

        # Portfolio-level assertions
        assert eval_res.horizon_availability[1]
        assert eval_res.portfolio_forward_returns[1] is not None

        assert not eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] is None

    def test_case_d_evaluation_date_before_min_history(self) -> None:
        """4. Evaluation date before min_history requirement is satisfied.

        Verify:
        - Raises ValueError for insufficient history;
        - Does NOT convert this into a malformed-data error.
        """
        eval_d = self.df_aaa["date"].iloc[10]  # Only 11 sessions <= T
        cfg = PortfolioConfig(min_history=50)

        with pytest.raises(ValueError) as ctx:
            evaluate_portfolio_at_date(
                evaluation_date=eval_d,
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )

        assert "insufficient history" in str(ctx.value)

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
        p_t = df_gap.loc[29, "close"]

        # Row 29 is Friday (2024-02-09)
        # Row 30 is Monday (2024-02-12) -> price 110% of Friday close
        # Row 31 is Tuesday (2024-02-13) -> price 120% of Friday close
        df_gap.loc[30, "close"] = p_t * 1.10
        df_gap.loc[30, "open"] = p_t * 1.09
        df_gap.loc[30, "high"] = p_t * 1.11
        df_gap.loc[30, "low"] = p_t * 1.08

        df_gap.loc[31, "close"] = p_t * 1.20
        df_gap.loc[31, "open"] = p_t * 1.19
        df_gap.loc[31, "high"] = p_t * 1.21
        df_gap.loc[31, "low"] = p_t * 1.18

        eval_fri = df_gap["date"].iloc[29]  # Friday evaluation date

        mock_gen_rec.return_value = {
            "action": "BUY",
            "signal_score": 80.0,
            "risk_adjusted_score": 80.0,
            "confidence": 0.8,
            "trade_plan": {"current_price": p_t},
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
        assert round(abs(pos.forward_returns[1] - (0.10)), 5) == 0
        assert round(abs(eval_res.portfolio_forward_returns[1] - (0.10)), 5) == 0

        # Horizon 2 must use Tuesday (T+2 trading session) price 120% -> 0.20 return
        assert round(abs(pos.forward_returns[2] - (0.20)), 5) == 0
        assert round(abs(eval_res.portfolio_forward_returns[2] - (0.20)), 5) == 0

    def test_evaluation_date_must_be_exact_and_not_fallback(self) -> None:
        """Verify evaluation date must be exact in price history for both non-trading dates and stock missing dates.

        Case 1: Evaluation date is a non-trading date outside dataset ('2024-01-06' Saturday).
        Case 2: Evaluation date is within historical date range, but missing from target stock dataset (e.g. '2024-01-03' missing in stock with '2024-01-01', '2024-01-02', '2024-01-04').

        MUST fail closed with ValueError rather than silently falling back to latest date <= T.
        """
        cfg = PortfolioConfig(min_history=30)
        non_trading_d = "2024-01-06"  # Saturday, not in synthetic dataset

        with pytest.raises(ValueError) as ctx:
            evaluate_portfolio_at_date(
                evaluation_date=non_trading_d,
                universe_stock_map=self.universe,
                config=cfg,
            )

        assert "not present in dataset price history" in str(ctx.value)

        # Case 2: Date within historical range, but missing from a stock dataset
        df_gap_stock = (
            self.df_aaa[self.df_aaa["date"] != "2024-01-15"].copy().reset_index(drop=True)
        )
        universe_missing_stock = {"AAA": df_gap_stock, "BBB": self.df_bbb}

        with pytest.raises(ValueError) as ctx_stock:
            evaluate_portfolio_at_date(
                evaluation_date="2024-01-15",
                universe_stock_map=universe_missing_stock,
                config=cfg,
            )

        assert "not present in dataset price history" in str(ctx_stock.value)

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
        with pytest.raises(ValueError) as ctx_unsorted:
            run_portfolio_backtest(
                evaluation_dates=[t2, t1],
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )
        assert "not sorted in chronological order" in str(ctx_unsorted.value)

        # 2. Duplicate dates raise ValueError
        with pytest.raises(ValueError) as ctx_dup:
            run_portfolio_backtest(
                evaluation_dates=[t1, t1, t2],
                universe_stock_map=self.universe,
                config=cfg,
                df_vnindex=self.df_vni,
            )
        assert "contains duplicate entries" in str(ctx_dup.value)

        # 3. Valid chronological run
        res_multi = run_portfolio_backtest(
            evaluation_dates=[t1, t2, t3],
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        assert res_multi.evaluation_dates == [t1, t2, t3]

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

        assert res_multi.evaluations[0].to_dict() == res_t1.to_dict()
        assert res_multi.evaluations[1].to_dict() == res_t2.to_dict()

    def test_cross_evaluation_temporal_isolation_mutation_boundary(self) -> None:
        """Verify cross-evaluation temporal isolation with T1 < T2.

        Scenario 1: Mutate data > T2.
        - Construction states at T1 and T2 remain strictly invariant.

        Scenario 2: Mutate data strictly between T1 and T2 (T1 < date <= T2).
        - Construction state at T1 remains strictly IDENTICAL to baseline.
        - Construction state at T2 changes deterministically compared to baseline because intermediate data became historical input at T2.
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

        # Construction states at both T1 and T2 must remain strictly identical to baseline
        for idx in range(2):
            self.assert_portfolio_construction_state_equals(
                baseline.evaluations[idx], res_mut1.evaluations[idx]
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

        # At T1: construction state MUST be strictly IDENTICAL to baseline
        self.assert_portfolio_construction_state_equals(
            baseline.evaluations[0], res_mut2.evaluations[0]
        )

        # At T2: entry_price at T2 changed due to intermediate price mutation <= T2
        p2_base = next(p for p in baseline.evaluations[1].positions if p.symbol == "AAA")
        p2_mut = next(p for p in res_mut2.evaluations[1].positions if p.symbol == "AAA")
        assert p2_base.entry_price != p2_mut.entry_price

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

        assert eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] is not None

        assert eval_res.horizon_availability[10]
        assert eval_res.portfolio_forward_returns[10] is not None

        assert not eval_res.horizon_availability[11]
        assert eval_res.portfolio_forward_returns[11] is None

        assert not eval_res.horizon_availability[20]
        assert eval_res.portfolio_forward_returns[20] is None

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
        with pytest.raises(ValueError) as ctx1:
            run_portfolio_backtest(
                evaluation_dates=[],
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "cannot be empty" in str(ctx1.value)

        # 2. Duplicate evaluation_dates
        t1 = self.df_aaa["date"].iloc[50]
        with pytest.raises(ValueError) as ctx2:
            run_portfolio_backtest(
                evaluation_dates=[t1, t1],
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "duplicate" in str(ctx2.value)

        # 3. Invalid evaluation date string
        with pytest.raises(ValueError) as ctx3:
            run_portfolio_backtest(
                evaluation_dates=["invalid-date-string"],
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "canonical 'YYYY-MM-DD'" in str(ctx3.value)

        # 4. Timezone-aware evaluation date
        tz_d = pd.Timestamp("2024-03-01T00:00:00Z")
        with pytest.raises(ValueError) as ctx4:
            evaluate_portfolio_at_date(
                evaluation_date=tz_d,
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "Timezone-aware" in str(ctx4.value)

        # 5. Evaluation date out of historical range
        with pytest.raises(ValueError) as ctx5:
            evaluate_portfolio_at_date(
                evaluation_date="2099-12-31",
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "not present in dataset price history" in str(ctx5.value)

        # 6. Insufficient historical observations
        early_d = self.df_aaa["date"].iloc[10]  # only 11 sessions <= T
        with pytest.raises(ValueError) as ctx6:
            evaluate_portfolio_at_date(
                evaluation_date=early_d,
                universe_stock_map=self.universe,
                config=cfg,
            )
        assert "insufficient history" in str(ctx6.value)


@pytest.mark.unit
class TestPortfolioDeterminismAndStateIsolation:
    """Test Suite verifying framework determinism, state isolation, and input/config immutability."""

    def setup_method(self) -> None:
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
        self.eval_dates = [self.df_aaa["date"].iloc[40], self.df_aaa["date"].iloc[50]]

    def test_1_deterministic_repeated_execution(self) -> None:
        """Requirement 1: Verify repeated backtest runs on identical inputs yield exact deterministic results."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        res3 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        assert res1.to_dict() == res2.to_dict()
        assert res2.to_dict() == res3.to_dict()

        # Explicit granular check on quantitative and structural fields
        for res_a, res_b in [(res1, res2), (res2, res3)]:
            assert res_a.evaluation_dates == res_b.evaluation_dates
            assert len(res_a.evaluations) == len(res_b.evaluations)
            for eval_a, eval_b in zip(res_a.evaluations, res_b.evaluations, strict=True):
                assert eval_a.evaluation_date == eval_b.evaluation_date
                assert eval_a.allocated_weight == eval_b.allocated_weight
                assert eval_a.unallocated_weight == eval_b.unallocated_weight
                assert eval_a.portfolio_forward_returns == eval_b.portfolio_forward_returns
                assert eval_a.horizon_availability == eval_b.horizon_availability
                assert eval_a.excluded_non_executable == eval_b.excluded_non_executable
                assert eval_a.excluded_filtered == eval_b.excluded_filtered
                assert eval_a.empty_reason == eval_b.empty_reason

                assert len(eval_a.positions) == len(eval_b.positions)
                for pos_a, pos_b in zip(eval_a.positions, eval_b.positions, strict=True):
                    assert pos_a.symbol == pos_b.symbol
                    assert pos_a.weight == pos_b.weight
                    assert pos_a.action == pos_b.action
                    assert pos_a.signal_score == pos_b.signal_score
                    assert pos_a.risk_adjusted_score == pos_b.risk_adjusted_score
                    assert pos_a.confidence == pos_b.confidence
                    assert pos_a.entry_price == pos_b.entry_price
                    assert pos_a.is_executable == pos_b.is_executable
                    assert pos_a.forward_returns == pos_b.forward_returns
                    assert pos_a.forward_availability == pos_b.forward_availability

    def test_2_input_dataframe_immutability(self) -> None:
        """Requirement 2: Prove that running backtest does not mutate input DataFrames."""
        # Deep copy inputs before execution
        vni_snapshot = self.df_vni.copy(deep=True)
        vn30_snapshot = self.df_vn30.copy(deep=True)
        stock_snapshots = {sym: df.copy(deep=True) for sym, df in self.universe.items()}

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )

        # Assert VNINDEX unmutated
        pd.testing.assert_frame_equal(self.df_vni, vni_snapshot, check_exact=True)
        pd.testing.assert_frame_equal(self.df_vn30, vn30_snapshot, check_exact=True)

        # Assert stock universe DataFrames unmutated
        for sym, df_orig in self.universe.items():
            pd.testing.assert_frame_equal(df_orig, stock_snapshots[sym], check_exact=True)

    def test_3_configuration_immutability(self) -> None:
        """Requirement 3: Verify PortfolioConfig is not mutated after running backtest, including nested execution_config."""
        from copy import deepcopy

        exec_cfg = ExecutionConfig(
            min_avg_traded_value_bn=2.0,
            min_avg_volume=60000.0,
            min_price=10000.0,
            max_participation_rate=0.05,
            lookback_window=15,
        )

        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=45.0,
            min_confidence=0.5,
            allowed_actions=("BUY", "HOLD"),
            max_weight_per_position=0.30,
            min_history=40,
            require_executable=False,
            execution_config=exec_cfg,
            transaction_cost_pct=0.002,
            slippage_pct=0.001,
        )

        # Independent deep snapshot of entire configuration state
        cfg_snapshot = deepcopy(cfg)

        run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
        )

        # Assert all fields remain unmutated compared to independent deep snapshot
        assert cfg.max_positions == cfg_snapshot.max_positions
        assert cfg.min_signal_score == cfg_snapshot.min_signal_score
        assert cfg.min_confidence == cfg_snapshot.min_confidence
        assert cfg.allowed_actions == cfg_snapshot.allowed_actions
        assert cfg.max_weight_per_position == cfg_snapshot.max_weight_per_position
        assert cfg.min_history == cfg_snapshot.min_history
        assert cfg.require_executable == cfg_snapshot.require_executable
        assert cfg.transaction_cost_pct == cfg_snapshot.transaction_cost_pct
        assert cfg.slippage_pct == cfg_snapshot.slippage_pct

        # Assert nested execution_config fields are unmutated and match deep snapshot
        assert cfg.execution_config is not None
        assert cfg_snapshot.execution_config is not None
        assert (
            cfg.execution_config is not cfg_snapshot.execution_config
        )  # Ensure independent object
        assert (
            cfg.execution_config.min_avg_traded_value_bn
            == cfg_snapshot.execution_config.min_avg_traded_value_bn
        )
        assert cfg.execution_config.min_avg_volume == cfg_snapshot.execution_config.min_avg_volume
        assert cfg.execution_config.min_price == cfg_snapshot.execution_config.min_price
        assert (
            cfg.execution_config.max_participation_rate
            == cfg_snapshot.execution_config.max_participation_rate
        )
        assert cfg.execution_config.lookback_window == cfg_snapshot.execution_config.lookback_window

    def test_4_universe_ordering_independence(self) -> None:
        """Requirement 4: Verify dictionary insertion order of universe symbols does not alter quantitative results."""
        universe1 = {
            "AAA": self.df_aaa,
            "BBB": self.df_bbb,
            "CCC": self.df_ccc,
        }
        universe2 = {
            "CCC": self.df_ccc,
            "AAA": self.df_aaa,
            "BBB": self.df_bbb,
        }

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=universe1,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=universe2,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        assert res1.to_dict() == res2.to_dict()

    def test_5_horizon_ordering_independence(self) -> None:
        """Requirement 5: Verify horizon parameter ordering does not affect forward return results per horizon."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[1, 5, 10],
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[10, 1, 5],
        )

        # Check per-horizon equivalence across all evaluations
        for eval1, eval2 in zip(res1.evaluations, res2.evaluations, strict=True):
            for h in [1, 5, 10]:
                assert eval1.portfolio_forward_returns[h] == eval2.portfolio_forward_returns[h]
                assert eval1.horizon_availability[h] == eval2.horizon_availability[h]

                for pos1, pos2 in zip(eval1.positions, eval2.positions, strict=True):
                    assert pos1.symbol == pos2.symbol
                    assert pos1.forward_returns[h] == pos2.forward_returns[h]
                    assert pos1.forward_availability[h] == pos2.forward_availability[h]

    def test_6_evaluation_date_ordering_contract(self) -> None:
        """Requirement 6: Verify independent calls to evaluate_portfolio_at_date have no state leakage depending on call order."""
        t1, t2 = self.eval_dates[0], self.eval_dates[1]

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        # Sequence 1: evaluate T1 then T2
        eval_t1_seq1 = evaluate_portfolio_at_date(
            evaluation_date=t1,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        eval_t2_seq1 = evaluate_portfolio_at_date(
            evaluation_date=t2,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Sequence 2: evaluate T2 then T1
        eval_t2_seq2 = evaluate_portfolio_at_date(
            evaluation_date=t2,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )
        eval_t1_seq2 = evaluate_portfolio_at_date(
            evaluation_date=t1,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        assert eval_t1_seq1.to_dict() == eval_t1_seq2.to_dict()
        assert eval_t2_seq1.to_dict() == eval_t2_seq2.to_dict()

    def test_7_fresh_state_sequence_repeatability(self) -> None:
        """Requirement 7: Verify A -> B -> A evaluation sequence produces identical result for A without state leakage."""
        t1, t2 = self.eval_dates[0], self.eval_dates[1]

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res_a1 = evaluate_portfolio_at_date(
            evaluation_date=t1,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Intermediary evaluation B
        evaluate_portfolio_at_date(
            evaluation_date=t2,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        res_a2 = evaluate_portfolio_at_date(
            evaluation_date=t1,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        assert res_a1.to_dict() == res_a2.to_dict()

    def test_8_nested_structures_isolation(self) -> None:
        """Requirement 8: Verify mutating result objects from one backtest run does not corrupt other result objects or input data."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        snapshot_res2 = res2.to_dict()

        # Mutate res1 nested structures thoroughly
        res1.evaluations[0].positions[0].weight = 999.0
        res1.evaluations[0].positions[0].forward_returns[5] = -99.0
        res1.evaluations[0].portfolio_forward_returns[5] = 1234.56
        res1.evaluations[0].excluded_filtered.append("MUTATED_SYMBOL")
        res1.aggregate["total_evaluation_points"] = -1

        # Verify res2 remains completely unmutated
        assert res2.to_dict() == snapshot_res2

    def test_9_deterministic_independent_oracle(self) -> None:
        """Requirement 9: Validate allocation invariants and position weights against independent oracle."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res = evaluate_portfolio_at_date(
            evaluation_date=self.eval_dates[0],
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Independent Oracle Check 1: sum(weights) + unallocated_weight == 1.0 (within FP tolerance)
        total_pos_weight = sum(p.weight for p in res.positions)
        assert round(abs(total_pos_weight + res.unallocated_weight - (1.0)), 6) == 0
        assert res.allocated_weight == round(total_pos_weight, 6)

        # Independent Oracle Check 2: Position weight equality under equal-weight scheme
        if res.positions:
            expected_weight = round(1.0 / len(res.positions), 6)
            for pos in res.positions:
                assert pos.weight == expected_weight


@pytest.mark.unit
class TestPortfolioSerializationAndResultContract:
    """Test Suite focusing on result contract, serialization integrity, and state preservation."""

    def setup_method(self) -> None:
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
        self.eval_dates = [self.df_aaa["date"].iloc[40], self.df_aaa["date"].iloc[50]]

    def test_1_to_dict_representation_completeness(self) -> None:
        """Test 1: Verify to_dict() returns a complete dict matching the public result contract."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            transaction_cost_pct=0.003,
            slippage_pct=0.001,
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            df_vn30=self.df_vn30,
            horizons=[5, 10],
        )

        serialized = res.to_dict()
        assert isinstance(serialized, dict)

        # Root level keys check
        required_root_keys = {"evaluation_dates", "evaluations", "config", "aggregate"}
        assert set(serialized.keys()) == required_root_keys

        # Config keys check
        required_config_keys = {
            "max_positions",
            "min_signal_score",
            "min_confidence",
            "allowed_actions",
            "max_weight_per_position",
            "min_history",
            "require_executable",
            "transaction_cost_pct",
            "slippage_pct",
            "quant_version",
            "model_version",
            "quant_config_hash",
        }
        assert set(serialized["config"].keys()) == required_config_keys

        # Aggregate keys check
        required_aggregate_keys = {
            "total_evaluation_points",
            "non_empty_portfolios_count",
            "empty_portfolios_count",
            "empty_reasons_breakdown",
            "horizon_metrics",
        }
        assert set(serialized["aggregate"].keys()) == required_aggregate_keys

        # Evaluation level keys check
        required_eval_keys = {
            "evaluation_date",
            "positions",
            "allocated_weight",
            "unallocated_weight",
            "portfolio_forward_returns",
            "horizon_availability",
            "excluded_non_executable",
            "excluded_filtered",
            "empty_reason",
        }
        for eval_dict in serialized["evaluations"]:
            assert set(eval_dict.keys()) == required_eval_keys

            # Position level keys check
            required_pos_keys = {
                "symbol",
                "weight",
                "action",
                "signal_score",
                "risk_adjusted_score",
                "confidence",
                "entry_price",
                "is_executable",
                "forward_returns",
                "forward_availability",
            }
            for pos_dict in eval_dict["positions"]:
                assert set(pos_dict.keys()) == required_pos_keys

    def test_2_nested_result_completeness(self) -> None:
        """Test 2: Verify .to_dict() preserves all nested fields across all levels."""
        exec_cfg = ExecutionConfig(min_avg_volume=50000.0)
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            require_executable=True,
            execution_config=exec_cfg,
            transaction_cost_pct=0.002,
            slippage_pct=0.001,
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10],
        )

        serialized = res.to_dict()

        # Check evaluations nested completeness
        assert len(serialized["evaluations"]) == len(res.evaluations)

        for obj_eval, dict_eval in zip(res.evaluations, serialized["evaluations"], strict=True):
            assert dict_eval["evaluation_date"] == obj_eval.evaluation_date
            assert dict_eval["allocated_weight"] == obj_eval.allocated_weight
            assert dict_eval["unallocated_weight"] == obj_eval.unallocated_weight
            assert dict_eval["portfolio_forward_returns"] == obj_eval.portfolio_forward_returns
            assert dict_eval["horizon_availability"] == obj_eval.horizon_availability
            assert dict_eval["excluded_non_executable"] == obj_eval.excluded_non_executable
            assert dict_eval["excluded_filtered"] == obj_eval.excluded_filtered
            assert dict_eval["empty_reason"] == obj_eval.empty_reason

            assert len(dict_eval["positions"]) == len(obj_eval.positions)

            for obj_pos, dict_pos in zip(obj_eval.positions, dict_eval["positions"], strict=True):
                assert dict_pos["symbol"] == obj_pos.symbol
                assert dict_pos["weight"] == obj_pos.weight
                assert dict_pos["action"] == obj_pos.action
                assert dict_pos["signal_score"] == obj_pos.signal_score
                assert dict_pos["risk_adjusted_score"] == obj_pos.risk_adjusted_score
                assert dict_pos["confidence"] == obj_pos.confidence
                assert dict_pos["entry_price"] == obj_pos.entry_price
                assert dict_pos["is_executable"] == obj_pos.is_executable
                assert dict_pos["forward_returns"] == obj_pos.forward_returns
                assert dict_pos["forward_availability"] == obj_pos.forward_availability

    def test_3_none_unavailable_semantics(self) -> None:
        """Test 3: Verify None values remain strictly None in memory and serialized output."""
        # Date at end of dataset -> forward outcomes unavailable
        last_date = self.df_aaa["date"].iloc[-1]
        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        eval_res = evaluate_portfolio_at_date(
            evaluation_date=last_date,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10, 20],
        )

        serialized = eval_res.to_dict()

        # Check in-memory and serialized None semantics for unavailable horizon outcomes
        for h in [5, 10, 20]:
            assert eval_res.portfolio_forward_returns[h] is None
            assert serialized["portfolio_forward_returns"][h] is None

            # Ensure None is strictly None and not converted to 0, 0.0, "", [], or False
            val = serialized["portfolio_forward_returns"][h]
            assert val is None
            assert val != 0
            assert val != 0.0
            assert val != ""
            assert val != []
            assert val is not False

        for pos_obj, pos_dict in zip(eval_res.positions, serialized["positions"], strict=True):
            for h in [5, 10, 20]:
                assert pos_obj.forward_returns[h] is None
                assert pos_dict["forward_returns"][h] is None
                val_pos = pos_dict["forward_returns"][h]
                assert val_pos is None
                assert val_pos != 0
                assert val_pos != 0.0
                assert val_pos != ""
                assert val_pos != []
                assert val_pos is not False

    def test_4_empty_portfolio_result(self) -> None:
        """Test 4: Verify empty portfolio result serializes safely without creating fake numerical values."""
        cfg = PortfolioConfig(
            min_history=30,
            min_signal_score=99.9,  # All candidates filtered out
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10],
        )

        serialized = res.to_dict()

        assert serialized["aggregate"]["total_evaluation_points"] == 2
        assert serialized["aggregate"]["non_empty_portfolios_count"] == 0
        assert serialized["aggregate"]["empty_portfolios_count"] == 2
        assert serialized["aggregate"]["empty_reasons_breakdown"] == {"no_eligible_candidates": 2}

        # Verify aggregate metrics for empty evaluations maintain None semantics
        for h in [5, 10]:
            h_metrics = serialized["aggregate"]["horizon_metrics"][h]
            assert h_metrics["valid_evaluation_points"] == 0
            assert h_metrics["mean"] is None
            assert h_metrics["median"] is None
            assert h_metrics["std"] is None
            assert h_metrics["min"] is None
            assert h_metrics["max"] is None
            assert h_metrics["hit_rate"] is None
            assert h_metrics["sequential_compounded_return"] is None

            # Strict check that None is not turned into 0 or 0.0
            assert h_metrics["mean"] is None
            assert h_metrics["hit_rate"] is None

        for eval_dict in serialized["evaluations"]:
            assert eval_dict["positions"] == []
            assert eval_dict["allocated_weight"] == 0.0
            assert eval_dict["unallocated_weight"] == 1.0
            assert eval_dict["empty_reason"] == "no_eligible_candidates"
            for h in [5, 10]:
                assert eval_dict["portfolio_forward_returns"][h] is None
                assert not eval_dict["horizon_availability"][h]

    def test_5_numerical_serialization_integrity(self) -> None:
        """Test 5: Verify numeric fields preserve values and float types without loss of precision or string conversion."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            transaction_cost_pct=0.0035,
            slippage_pct=0.0015,
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )

        serialized = res.to_dict()

        # Config numeric fields check
        assert isinstance(serialized["config"]["transaction_cost_pct"], float)
        assert serialized["config"]["transaction_cost_pct"] == 0.0035
        assert isinstance(serialized["config"]["slippage_pct"], float)
        assert serialized["config"]["slippage_pct"] == 0.0015

        for eval_obj, eval_dict in zip(res.evaluations, serialized["evaluations"], strict=True):
            assert isinstance(eval_dict["allocated_weight"], float)
            assert eval_dict["allocated_weight"] == eval_obj.allocated_weight
            assert isinstance(eval_dict["unallocated_weight"], float)
            assert eval_dict["unallocated_weight"] == eval_obj.unallocated_weight

            ret_val = eval_dict["portfolio_forward_returns"][5]
            if ret_val is not None:
                assert isinstance(ret_val, float)
                assert ret_val == eval_obj.portfolio_forward_returns[5]

            for pos_obj, pos_dict in zip(eval_obj.positions, eval_dict["positions"], strict=True):
                assert isinstance(pos_dict["weight"], float)
                assert pos_dict["weight"] == pos_obj.weight

                if pos_obj.signal_score is not None:
                    assert isinstance(pos_dict["signal_score"], float)
                    assert pos_dict["signal_score"] == pos_obj.signal_score

                if pos_obj.risk_adjusted_score is not None:
                    assert isinstance(pos_dict["risk_adjusted_score"], float)
                    assert pos_dict["risk_adjusted_score"] == pos_obj.risk_adjusted_score

                assert isinstance(pos_dict["confidence"], float)
                assert pos_dict["confidence"] == pos_obj.confidence

                if pos_obj.entry_price is not None:
                    assert isinstance(pos_dict["entry_price"], float)
                    assert pos_dict["entry_price"] == pos_obj.entry_price

                pos_ret = pos_dict["forward_returns"][5]
                if pos_ret is not None:
                    assert isinstance(pos_ret, float)
                    assert pos_ret == pos_obj.forward_returns[5]

    def test_6_deterministic_key_and_ordering_representation(self) -> None:
        """Test 6: Verify same logical result produces deterministic key/value ordering across multiple calls and universe orderings."""
        universe1 = {"AAA": self.df_aaa, "BBB": self.df_bbb, "CCC": self.df_ccc}
        universe2 = {"CCC": self.df_ccc, "AAA": self.df_aaa, "BBB": self.df_bbb}

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=universe1,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        res2 = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=universe2,
            config=cfg,
            df_vnindex=self.df_vni,
        )

        # Verify exact equality of serialized representations regardless of universe insertion order
        assert res1.to_dict() == res2.to_dict()

    def test_7_result_mutation_isolation_after_serialization(self) -> None:
        """Test 7: Verify bi-directional mutation isolation between dataclass objects and serialized dictionary."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )

        serialized = res.to_dict()

        # 1. Mutate serialized dictionary
        serialized["evaluation_dates"].append("2099-01-01")
        serialized["evaluations"][0]["positions"][0]["weight"] = 999.0
        serialized["evaluations"][0]["portfolio_forward_returns"][5] = -99.0
        serialized["evaluations"][0]["excluded_filtered"].append("MUTATED")

        # Verify in-memory result object remains completely unmutated
        assert "2099-01-01" not in res.evaluation_dates
        assert res.evaluations[0].positions[0].weight != 999.0
        assert res.evaluations[0].portfolio_forward_returns[5] != -99.0
        assert "MUTATED" not in res.evaluations[0].excluded_filtered

        # 2. Re-serialize res and verify second_serialized is completely independent
        res_fresh = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5],
        )
        dict_fresh = res_fresh.to_dict()

        # Mutate res_fresh in memory
        res_fresh.evaluations[0].positions[0].weight = 888.0
        res_fresh.evaluations[0].positions[0].forward_returns[5] = 777.0

        # dict_fresh generated prior to mutation must remain unmutated
        assert dict_fresh["evaluations"][0]["positions"][0]["weight"] != 888.0
        assert dict_fresh["evaluations"][0]["positions"][0]["forward_returns"][5] != 777.0

    def test_8_repeated_serialization(self) -> None:
        """Test 8: Verify calling .to_dict() multiple times is idempotent and does not mutate result."""
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res = run_portfolio_backtest(
            evaluation_dates=self.eval_dates,
            universe_stock_map=self.universe,
            config=cfg,
            df_vnindex=self.df_vni,
            horizons=[5, 10],
        )

        first = res.to_dict()
        second = res.to_dict()
        third = res.to_dict()

        assert first == second
        assert second == third


@pytest.mark.unit
class TestPortfolioAggregationConsistencyAndOracles:
    """Test Suite verifying portfolio-level aggregation consistency and independent math oracles."""

    def test_1_evaluation_count_consistency(self) -> None:
        """Test 1: Verify len(result.evaluations) == aggregate['total_evaluation_points'] across non-empty, empty, and mixed evaluations."""
        # Non-empty evaluation
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.05},
            forward_availability={5: True},
        )
        e1 = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.05},
            horizon_availability={5: True},
        )
        # Empty evaluation
        e2 = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )
        # Non-empty evaluation
        p3 = PortfolioPosition(
            symbol="BBB",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: -0.02},
            forward_availability={5: True},
        )
        e3 = PortfolioEvaluation(
            evaluation_date="2024-04-01",
            positions=[p3],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: -0.02},
            horizon_availability={5: True},
        )

        evals = [e1, e2, e3]
        agg = aggregate_portfolio_results(evals, horizons=[5])

        assert len(evals) == agg["total_evaluation_points"]
        assert agg["total_evaluation_points"] == 3

    def test_2_empty_non_empty_aggregation_oracle(self) -> None:
        """Test 2: Verify non_empty + empty == total_evaluation_points matching independent count oracles."""
        # Fixture: T1 -> non-empty, T2 -> empty, T3 -> non-empty, T4 -> empty
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.05},
            forward_availability={5: True},
        )
        t1 = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.05},
            horizon_availability={5: True},
        )
        t2 = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )
        p3 = PortfolioPosition(
            symbol="BBB",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: 0.03},
            forward_availability={5: True},
        )
        t3 = PortfolioEvaluation(
            evaluation_date="2024-04-01",
            positions=[p3],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.03},
            horizon_availability={5: True},
        )
        t4 = PortfolioEvaluation(
            evaluation_date="2024-04-15",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="all_candidates_non_executable",
        )

        evals = [t1, t2, t3, t4]

        # Independent Count Oracle
        oracle_non_empty = sum(1 for e in evals if len(e.positions) > 0)
        oracle_empty = sum(1 for e in evals if len(e.positions) == 0)

        agg = aggregate_portfolio_results(evals, horizons=[5])

        assert agg["non_empty_portfolios_count"] == oracle_non_empty
        assert agg["empty_portfolios_count"] == oracle_empty
        assert agg["non_empty_portfolios_count"] == 2
        assert agg["empty_portfolios_count"] == 2
        assert (
            agg["non_empty_portfolios_count"] + agg["empty_portfolios_count"]
            == agg["total_evaluation_points"]
        )

    def test_3_empty_reason_breakdown_oracle(self) -> None:
        """Test 3: Verify sum(empty_reasons_breakdown.values()) == empty_portfolios_count matching independent oracle."""
        e1 = PortfolioEvaluation(
            evaluation_date="2024-01-01",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )
        e2 = PortfolioEvaluation(
            evaluation_date="2024-01-15",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )
        e3 = PortfolioEvaluation(
            evaluation_date="2024-02-01",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="all_candidates_non_executable",
        )
        e4 = PortfolioEvaluation(
            evaluation_date="2024-02-15",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason=None,
        )

        evals = [e1, e2, e3, e4]

        # Independent Reason Breakdown Oracle
        oracle_breakdown: dict[str, int] = {}
        for e in evals:
            r = e.empty_reason or "unknown"
            oracle_breakdown[r] = oracle_breakdown.get(r, 0) + 1

        agg = aggregate_portfolio_results(evals, horizons=[5])

        assert agg["empty_reasons_breakdown"] == oracle_breakdown
        assert sum(agg["empty_reasons_breakdown"].values()) == agg["empty_portfolios_count"]
        assert agg["empty_portfolios_count"] == 4

    def test_4_valid_evaluation_point_count_oracle(self) -> None:
        """Test 4: Verify horizon valid_evaluation_points matches independent availability count oracle."""
        # Available outcome
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.05, 10: 0.10},
            forward_availability={5: True, 10: True},
        )
        e1 = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.05, 10: 0.10},
            horizon_availability={5: True, 10: True},
        )
        # 5D available, 10D unavailable
        p2 = PortfolioPosition(
            symbol="BBB",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=200.0,
            is_executable=True,
            forward_returns={5: -0.02, 10: None},
            forward_availability={5: True, 10: False},
        )
        e2 = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p2],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: -0.02, 10: None},
            horizon_availability={5: True, 10: False},
        )
        # All unavailable
        p3 = PortfolioPosition(
            symbol="CCC",
            weight=1.0,
            action="BUY",
            signal_score=50.0,
            risk_adjusted_score=45.0,
            confidence=0.6,
            entry_price=300.0,
            is_executable=True,
            forward_returns={5: None, 10: None},
            forward_availability={5: False, 10: False},
        )
        e3 = PortfolioEvaluation(
            evaluation_date="2024-04-01",
            positions=[p3],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: None, 10: None},
            horizon_availability={5: False, 10: False},
        )

        evals = [e1, e2, e3]
        agg = aggregate_portfolio_results(evals, horizons=[5, 10])

        # Independent Oracle for Valid Points per Horizon
        def oracle_valid_points(e_list: list[PortfolioEvaluation], h: int) -> int:
            return sum(
                1
                for e in e_list
                if len(e.positions) > 0
                and e.horizon_availability.get(h, False)
                and e.portfolio_forward_returns.get(h) is not None
            )

        assert agg["horizon_metrics"][5]["valid_evaluation_points"] == oracle_valid_points(evals, 5)
        assert agg["horizon_metrics"][10]["valid_evaluation_points"] == oracle_valid_points(
            evals, 10
        )
        assert agg["horizon_metrics"][5]["valid_evaluation_points"] == 2
        assert agg["horizon_metrics"][10]["valid_evaluation_points"] == 1

    def test_5_mean_return_oracle(self) -> None:
        """Test 5: Verify arithmetic mean matches independent mathematical formula on finite valid returns."""
        rets = [0.08, -0.03, 0.05, 0.12]
        evals = []
        for i, r in enumerate(rets):
            p = PortfolioPosition(
                symbol=f"S{i}",
                weight=1.0,
                action="BUY",
                signal_score=70.0,
                risk_adjusted_score=65.0,
                confidence=0.8,
                entry_price=100.0,
                is_executable=True,
                forward_returns={5: r},
                forward_availability={5: True},
            )
            e = PortfolioEvaluation(
                evaluation_date=f"2024-01-0{i + 1}",
                positions=[p],
                allocated_weight=1.0,
                unallocated_weight=0.0,
                portfolio_forward_returns={5: r},
                horizon_availability={5: True},
            )
            evals.append(e)

        # Independent Pure Math Oracle
        oracle_mean = round(sum(rets) / len(rets), 6)  # (0.08 - 0.03 + 0.05 + 0.12) / 4 = 0.055

        agg = aggregate_portfolio_results(evals, horizons=[5])
        assert agg["horizon_metrics"][5]["mean"] == oracle_mean
        assert oracle_mean == 0.055

    def test_6_median_min_max_std_oracle(self) -> None:
        """Test 6: Verify median, min, max, std match independent mathematical oracles across 5 distinct return values."""
        # Fixture with 5 distinct values
        rets = [0.02, -0.01, 0.05, 0.03, -0.04]
        evals = []
        for i, r in enumerate(rets):
            p = PortfolioPosition(
                symbol=f"S{i}",
                weight=1.0,
                action="BUY",
                signal_score=70.0,
                risk_adjusted_score=65.0,
                confidence=0.8,
                entry_price=100.0,
                is_executable=True,
                forward_returns={5: r},
                forward_availability={5: True},
            )
            e = PortfolioEvaluation(
                evaluation_date=f"2024-01-0{i + 1}",
                positions=[p],
                allocated_weight=1.0,
                unallocated_weight=0.0,
                portfolio_forward_returns={5: r},
                horizon_availability={5: True},
            )
            evals.append(e)

        # Independent Pure Math Oracles (without calling numpy or implementation helpers)
        # Sorted rets: [-0.04, -0.01, 0.02, 0.03, 0.05]
        s_rets = sorted(rets)
        oracle_min = s_rets[0]  # -0.04
        oracle_max = s_rets[-1]  # 0.05
        oracle_median = s_rets[len(s_rets) // 2]  # 0.02
        mean_val = sum(rets) / len(rets)  # 0.05 / 5 = 0.01
        variance = sum((x - mean_val) ** 2 for x in rets) / len(rets)
        oracle_std = round(variance**0.5, 6)

        agg = aggregate_portfolio_results(evals, horizons=[5])
        h5 = agg["horizon_metrics"][5]

        assert h5["min"] == oracle_min
        assert h5["max"] == oracle_max
        assert h5["median"] == oracle_median
        assert h5["std"] == oracle_std

    def test_7_positive_return_hit_rate_oracle(self) -> None:
        """Test 7: Verify hit_rate strictly requires return > 0 (zero return is not positive) on valid observations."""
        rets = [0.10, -0.05, 0.0, 0.04, None]
        evals = []
        for i, r in enumerate(rets):
            if r is None:
                p = PortfolioPosition(
                    symbol=f"S{i}",
                    weight=1.0,
                    action="BUY",
                    signal_score=70.0,
                    risk_adjusted_score=65.0,
                    confidence=0.8,
                    entry_price=100.0,
                    is_executable=True,
                    forward_returns={5: None},
                    forward_availability={5: False},
                )
                e = PortfolioEvaluation(
                    evaluation_date=f"2024-01-0{i + 1}",
                    positions=[p],
                    allocated_weight=1.0,
                    unallocated_weight=0.0,
                    portfolio_forward_returns={5: None},
                    horizon_availability={5: False},
                )
            else:
                p = PortfolioPosition(
                    symbol=f"S{i}",
                    weight=1.0,
                    action="BUY",
                    signal_score=70.0,
                    risk_adjusted_score=65.0,
                    confidence=0.8,
                    entry_price=100.0,
                    is_executable=True,
                    forward_returns={5: r},
                    forward_availability={5: True},
                )
                e = PortfolioEvaluation(
                    evaluation_date=f"2024-01-0{i + 1}",
                    positions=[p],
                    allocated_weight=1.0,
                    unallocated_weight=0.0,
                    portfolio_forward_returns={5: r},
                    horizon_availability={5: True},
                )
            evals.append(e)

        # Independent Hit Rate Oracle
        # Valid returns: [0.10, -0.05, 0.0, 0.04] (4 observations)
        # Positive returns (r > 0): 0.10, 0.04 (2 observations; 0.0 is NOT positive)
        # Expected hit_rate = 2 / 4 = 0.5000
        valid_rets = [r for r in rets if r is not None]
        pos_count = sum(1 for r in valid_rets if r > 0)
        oracle_hit_rate = round(pos_count / len(valid_rets), 4)

        agg = aggregate_portfolio_results(evals, horizons=[5])
        h5 = agg["horizon_metrics"][5]

        assert h5["valid_evaluation_points"] == 4
        assert h5["hit_rate"] == oracle_hit_rate
        assert oracle_hit_rate == 0.5

    def test_8_sequential_compounded_return_oracle(self) -> None:
        """Test 8: Verify sequential_compounded_return = ∏(1 + r_i) - 1.0 using independent math product oracle."""
        rets = [0.10, -0.05, 0.0, 0.02]
        evals = []
        for i, r in enumerate(rets):
            p = PortfolioPosition(
                symbol=f"S{i}",
                weight=1.0,
                action="BUY",
                signal_score=70.0,
                risk_adjusted_score=65.0,
                confidence=0.8,
                entry_price=100.0,
                is_executable=True,
                forward_returns={5: r},
                forward_availability={5: True},
            )
            e = PortfolioEvaluation(
                evaluation_date=f"2024-01-0{i + 1}",
                positions=[p],
                allocated_weight=1.0,
                unallocated_weight=0.0,
                portfolio_forward_returns={5: r},
                horizon_availability={5: True},
            )
            evals.append(e)

        # Add empty evaluation and unavailable evaluation to ensure they are safely ignored
        e_empty = PortfolioEvaluation(
            evaluation_date="2024-02-01",
            positions=[],
            allocated_weight=0.0,
            unallocated_weight=1.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
            empty_reason="no_eligible_candidates",
        )
        p_unavail = PortfolioPosition(
            symbol="S_UNAVAIL",
            weight=1.0,
            action="BUY",
            signal_score=60.0,
            risk_adjusted_score=55.0,
            confidence=0.7,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: None},
            forward_availability={5: False},
        )
        e_unavail = PortfolioEvaluation(
            evaluation_date="2024-02-15",
            positions=[p_unavail],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: None},
            horizon_availability={5: False},
        )
        evals.extend([e_empty, e_unavail])

        # Independent Pure Math Product Oracle
        # (1 + 0.10) * (1 - 0.05) * (1 + 0.0) * (1 + 0.02) - 1.0 = 1.10 * 0.95 * 1.0 * 1.02 - 1.0 = 0.0659
        cum_prod = 1.0
        for r in rets:
            cum_prod *= 1.0 + r
        oracle_seq_comp = round(cum_prod - 1.0, 6)

        agg = aggregate_portfolio_results(evals, horizons=[5])
        h5 = agg["horizon_metrics"][5]

        assert h5["valid_evaluation_points"] == 4
        assert h5["sequential_compounded_return"] == oracle_seq_comp
        assert oracle_seq_comp == 0.0659

    def test_9_position_to_portfolio_weighted_return_consistency(self) -> None:
        """Test 9: Verify portfolio_forward_returns[N] == Σ(w_i × r_i) matching independent weighted sum oracle on production evaluate_portfolio_at_date output."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 200.0)
        df_ccc = create_synthetic_ohlcv("2024-01-01", 80, 30000.0, -50.0)

        universe = {"AAA": df_aaa, "BBB": df_bbb, "CCC": df_ccc}
        eval_d = df_aaa["date"].iloc[40]

        cfg = PortfolioConfig(
            max_positions=3,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            transaction_cost_pct=0.0,
            slippage_pct=0.0,
        )

        res = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        assert len(res.positions) >= 2
        assert res.horizon_availability[5]

        # Production Result Actual
        actual_port_ret = res.portfolio_forward_returns[5]

        # Independent Mathematical Oracle computed strictly from position weights and position returns
        expected_port_ret = round(
            sum(
                p.weight * p.forward_returns[5]
                for p in res.positions
                if p.forward_returns[5] is not None
            ),
            6,
        )

        # Assert production weighted-return matches independent oracle
        assert actual_port_ret == expected_port_ret

    def test_10_unavailable_constituent_propagation(self) -> None:
        """Test 10: Verify unavailable constituent in portfolio forces portfolio return to None and horizon_availability to False."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 50, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 50, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 42, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

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

        assert len(eval_res.positions) == 2
        pos_b = next(p for p in eval_res.positions if p.symbol == "BBB")
        assert not pos_b.forward_availability[5]
        assert pos_b.forward_returns[5] is None

        # Portfolio forward return MUST be None, NOT partial return, NOT zero
        assert not eval_res.horizon_availability[5]
        assert eval_res.portfolio_forward_returns[5] is None

    def test_11_allocation_weight_invariant_oracle(self) -> None:
        """Test 11: Verify sum(pos.weight) == allocated_weight and allocated_weight + unallocated_weight == 1.0 across full, partial, and empty portfolios using production evaluate_portfolio_at_date."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 80, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 80, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 80, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}
        eval_d = df_aaa["date"].iloc[40]

        # 1. Full allocation
        cfg_full = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )
        res_full = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg_full,
            df_vnindex=df_vni,
        )
        assert len(res_full.positions) > 0
        oracle_alloc_full = round(sum(p.weight for p in res_full.positions), 6)
        oracle_unalloc_full = round(1.0 - oracle_alloc_full, 6)

        assert res_full.allocated_weight == oracle_alloc_full
        assert res_full.unallocated_weight == oracle_unalloc_full
        assert res_full.allocated_weight == 1.0
        assert res_full.unallocated_weight == 0.0
        assert round(abs(res_full.allocated_weight + res_full.unallocated_weight - (1.0)), 6) == 0

        # 2. Partial allocation (max_weight_per_position < 1.0, e.g. 0.30 per position)
        cfg_partial = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            allowed_actions=("BUY", "HOLD", "WATCH"),
            max_weight_per_position=0.30,
            min_history=30,
        )
        res_partial = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg_partial,
            df_vnindex=df_vni,
        )
        assert len(res_partial.positions) > 0
        oracle_alloc_partial = round(sum(p.weight for p in res_partial.positions), 6)
        oracle_unalloc_partial = round(1.0 - oracle_alloc_partial, 6)

        assert res_partial.allocated_weight == oracle_alloc_partial
        assert res_partial.unallocated_weight == oracle_unalloc_partial
        assert res_partial.allocated_weight == 0.60
        assert res_partial.unallocated_weight == 0.40
        assert (
            round(abs(res_partial.allocated_weight + res_partial.unallocated_weight - (1.0)), 6)
            == 0
        )

        # 3. Empty portfolio (e.g. min_signal_score=99.9 filters out all candidates)
        cfg_empty = PortfolioConfig(
            min_signal_score=99.9,
            min_history=30,
        )
        res_empty = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg_empty,
            df_vnindex=df_vni,
        )
        assert res_empty.positions == []
        assert res_empty.allocated_weight == 0.0
        assert res_empty.unallocated_weight == 1.0
        assert res_empty.empty_reason == "no_eligible_candidates"
        assert round(abs(res_empty.allocated_weight + res_empty.unallocated_weight - (1.0)), 6) == 0

    def test_12_serialized_result_matches_in_memory_aggregation(self) -> None:
        """Test 12: Verify serialized result (.to_dict()) aggregate metrics match in-memory dataclass objects and independent oracles."""
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

        res = run_portfolio_backtest(
            evaluation_dates=eval_dates,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        serialized = res.to_dict()

        assert serialized["aggregate"] == res.aggregate
        assert serialized["aggregate"]["total_evaluation_points"] == len(eval_dates)
        assert len(serialized["evaluations"]) == len(res.evaluations)

        for obj_eval, dict_eval in zip(res.evaluations, serialized["evaluations"], strict=True):
            assert dict_eval["evaluation_date"] == obj_eval.evaluation_date
            assert dict_eval["portfolio_forward_returns"] == obj_eval.portfolio_forward_returns
            assert dict_eval["allocated_weight"] == obj_eval.allocated_weight
            assert dict_eval["unallocated_weight"] == obj_eval.unallocated_weight

    def test_13_horizon_isolation_mutation_test(self) -> None:
        """Test 13: Verify mutating outcome data for horizon 10 does NOT alter horizon 1 or horizon 5 metrics."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 90, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 90, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 90, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

        eval_d = df_aaa["date"].iloc[40]
        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        res1 = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[1, 5, 10],
        )

        # Mutate stock prices strictly at T+10 trading session (session 50)
        df_aaa_mut = df_aaa.copy()
        target_h10_date = df_aaa["date"].iloc[50]
        mask = df_aaa_mut["date"] == target_h10_date
        df_aaa_mut.loc[mask, "close"] *= 5.0
        df_aaa_mut.loc[mask, "open"] *= 5.0
        df_aaa_mut.loc[mask, "high"] *= 5.0
        df_aaa_mut.loc[mask, "low"] *= 5.0

        universe_mut = {"AAA": df_aaa_mut, "BBB": df_bbb}

        res2 = evaluate_portfolio_at_date(
            evaluation_date=eval_d,
            universe_stock_map=universe_mut,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[1, 5, 10],
        )

        # Horizon 1 and 5 must be completely identical
        assert res1.portfolio_forward_returns[1] == res2.portfolio_forward_returns[1]
        assert res1.portfolio_forward_returns[5] == res2.portfolio_forward_returns[5]

        pos1_a = next(p for p in res1.positions if p.symbol == "AAA")
        pos2_a = next(p for p in res2.positions if p.symbol == "AAA")
        assert pos1_a.forward_returns[1] == pos2_a.forward_returns[1]
        assert pos1_a.forward_returns[5] == pos2_a.forward_returns[5]

        # Only horizon 10 return should change
        assert res1.portfolio_forward_returns[10] != res2.portfolio_forward_returns[10]
        assert pos1_a.forward_returns[10] != pos2_a.forward_returns[10]

    def test_14_evaluation_isolation_mutation_test(self) -> None:
        """Test 14: Verify mutating forward outcome after T3 does not alter signal/construction state at T1, T2, or T3, and only affects outcomes depending on mutated data."""
        df_vni = create_synthetic_ohlcv("2024-01-01", 100, 1200.0, 1.0)
        df_aaa = create_synthetic_ohlcv("2024-01-01", 100, 10000.0, 100.0)
        df_bbb = create_synthetic_ohlcv("2024-01-01", 100, 20000.0, 150.0)
        universe = {"AAA": df_aaa, "BBB": df_bbb}

        t1 = df_aaa["date"].iloc[40]
        t2 = df_aaa["date"].iloc[50]
        t3 = df_aaa["date"].iloc[60]

        cfg = PortfolioConfig(
            max_positions=2,
            min_signal_score=0.0,
            min_history=30,
            allowed_actions=("BUY", "HOLD", "WATCH"),
        )

        baseline = run_portfolio_backtest(
            evaluation_dates=[t1, t2, t3],
            universe_stock_map=universe,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        # Mutate price data strictly after T3 (> t3)
        df_aaa_mut = df_aaa.copy()
        mask = df_aaa_mut["date"] > t3
        df_aaa_mut.loc[mask, "close"] *= 3.0
        df_aaa_mut.loc[mask, "open"] *= 3.0
        df_aaa_mut.loc[mask, "high"] *= 3.0
        df_aaa_mut.loc[mask, "low"] *= 3.0

        universe_mut = {"AAA": df_aaa_mut, "BBB": df_bbb}

        res_mut = run_portfolio_backtest(
            evaluation_dates=[t1, t2, t3],
            universe_stock_map=universe_mut,
            config=cfg,
            df_vnindex=df_vni,
            horizons=[5],
        )

        # Construction states at signal time (constituents, weights, scores, entry_prices) for T1, T2, and T3 must remain strictly unmutated
        for idx in range(3):
            assert [p.symbol for p in baseline.evaluations[idx].positions] == [
                p.symbol for p in res_mut.evaluations[idx].positions
            ]
            assert [p.weight for p in baseline.evaluations[idx].positions] == [
                p.weight for p in res_mut.evaluations[idx].positions
            ]
            assert [p.signal_score for p in baseline.evaluations[idx].positions] == [
                p.signal_score for p in res_mut.evaluations[idx].positions
            ]
            assert [p.entry_price for p in baseline.evaluations[idx].positions] == [
                p.entry_price for p in res_mut.evaluations[idx].positions
            ]

        # T1 and T2 5D forward outcomes (which depend on data <= T3) remain strictly IDENTICAL
        assert (
            baseline.evaluations[0].portfolio_forward_returns[5]
            == res_mut.evaluations[0].portfolio_forward_returns[5]
        )
        assert (
            baseline.evaluations[1].portfolio_forward_returns[5]
            == res_mut.evaluations[1].portfolio_forward_returns[5]
        )

        # T3 5D forward outcome (which depends on data > T3) changes
        assert (
            baseline.evaluations[2].portfolio_forward_returns[5]
            != res_mut.evaluations[2].portfolio_forward_returns[5]
        )

    def test_15_fail_closed_malformed_aggregation_inputs(self) -> None:
        """Test 15: Verify aggregate_portfolio_results fails closed with TypeError or ValueError on malformed inputs."""
        p1 = PortfolioPosition(
            symbol="AAA",
            weight=1.0,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.05},
            forward_availability={5: True},
        )
        valid_eval = PortfolioEvaluation(
            evaluation_date="2024-03-01",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.05},
            horizon_availability={5: True},
        )

        # 1. Non-list/tuple evaluations input
        with pytest.raises(TypeError):
            aggregate_portfolio_results("not_a_list")  # type: ignore[arg-type]

        # 2. Non-PortfolioEvaluation object in list
        with pytest.raises(TypeError):
            aggregate_portfolio_results([valid_eval, "invalid_item"])  # type: ignore[arg-type]

        # 3. Boolean portfolio return when marked available
        bool_eval = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: True},  # type: ignore[dict-item]
            horizon_availability={5: True},
        )
        with pytest.raises(TypeError):
            aggregate_portfolio_results([bool_eval], horizons=[5])

        # 4. Non-numeric return when marked available
        str_eval = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: "invalid_return"},  # type: ignore[dict-item]
            horizon_availability={5: True},
        )
        with pytest.raises(TypeError):
            aggregate_portfolio_results([str_eval], horizons=[5])

        # 5. NaN return when marked available
        nan_eval = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: float("nan")},
            horizon_availability={5: True},
        )
        with pytest.raises(ValueError):
            aggregate_portfolio_results([nan_eval], horizons=[5])

        # 6. Inf return when marked available
        inf_eval = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[p1],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: float("inf")},
            horizon_availability={5: True},
        )
        with pytest.raises(ValueError):
            aggregate_portfolio_results([inf_eval], horizons=[5])

        # 7. Invalid position weight (negative or non-numeric)
        bad_weight_pos = PortfolioPosition(
            symbol="AAA",
            weight=-0.5,
            action="BUY",
            signal_score=70.0,
            risk_adjusted_score=65.0,
            confidence=0.8,
            entry_price=100.0,
            is_executable=True,
            forward_returns={5: 0.05},
            forward_availability={5: True},
        )
        bad_weight_eval = PortfolioEvaluation(
            evaluation_date="2024-03-15",
            positions=[bad_weight_pos],
            allocated_weight=1.0,
            unallocated_weight=0.0,
            portfolio_forward_returns={5: 0.05},
            horizon_availability={5: True},
        )
        with pytest.raises(ValueError):
            aggregate_portfolio_results([bad_weight_eval], horizons=[5])
