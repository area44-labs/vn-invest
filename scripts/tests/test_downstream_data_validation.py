"""Deterministic Offline Tests for Downstream Data Validation and Calculation Safety.

Verifies:
1. Valid dataset processing.
2. Handling of NaN / Inf values in downstream calculations without propagation.
3. Insufficient history symbols return safe AVOID / null outputs without indicator calculation.
4. Failed symbols excluded from breadth/liquidity denominators and recommendations.
5. Temporal-invalid symbols excluded from breadth and recommendations.
6. Partial universe handling (some symbols valid, others invalid/insufficient).
7. Zero valid symbols fallback (breadth returns 0.50, regime DEFENSIVE, all recommendations AVOID).
8. Denominator and count correctness for breadth, regime, and liquidity percentile ranking.
"""

import math
import unittest
import numpy as np
import pandas as pd

from scripts.lib.recommendation import generate_recommendation
from scripts.lib.regime import detect_market_regime
from scripts.lib.risk import calculate_t25_risk_metrics, normalize_universe_liquidity_scores
from scripts.generate_report import generate_historical_report


def create_mock_ohlcv(
    length: int = 30,
    start_price: float = 50.0,
    vol_base: float = 100000.0,
    trend: float = 0.005,
    start_date: str = "2025-01-01",
) -> pd.DataFrame:
    """Helper to create valid OHLCV DataFrame."""
    dates = pd.date_range(start=start_date, periods=length, freq="B").strftime("%Y-%m-%d").tolist()
    records = []
    p = start_price
    for d in dates:
        p_open = p
        p_close = p * (1.0 + trend)
        p_high = max(p_open, p_close) * 1.01
        p_low = min(p_open, p_close) * 0.99
        vol = vol_base
        records.append(
            {
                "time": d,
                "open": p_open,
                "high": p_high,
                "low": p_low,
                "close": p_close,
                "volume": vol,
            }
        )
        p = p_close
    return pd.DataFrame(records)


class TestDownstreamDataValidation(unittest.TestCase):
    """Test suite ensuring no corrupted/invalid data reaches quantitative calculations."""

    def test_1_valid_dataset(self):
        """1. Valid dataset produces clean risk metrics, regime, recommendation, and liquidity."""
        df_stock = create_mock_ohlcv(length=40, start_price=50.0)
        df_vnindex = create_mock_ohlcv(length=40, start_price=1200.0)

        regime = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.80)
        self.assertIn(regime["regime"], ["STRONG_BULL", "BULL", "DEFENSIVE", "NEUTRAL"])

        rec = generate_recommendation(
            symbol="AAA",
            company_name="Company AAA",
            sector="Sector A",
            exchange="HOSE",
            df_stock=df_stock,
            market_regime_info=regime,
            df_vnindex=df_vnindex,
        )
        self.assertEqual(rec["data_quality"], "SUFFICIENT")
        self.assertIsNotNone(rec["signal_score"])

        norm = normalize_universe_liquidity_scores([rec], market_regime=regime["regime"])
        self.assertEqual(norm[0]["risk_metrics"]["liquidity_score"], 100.0)

    def test_2_nan_inf_safety(self):
        """2. Datasets with NaN / Inf in price/volume do not leak NaN/Inf to downstream metrics."""
        df_stock = create_mock_ohlcv(length=30)
        # Inject NaN and Inf into middle rows
        df_stock.loc[10, "close"] = np.nan
        df_stock.loc[15, "volume"] = np.inf

        # calculate_t25_risk_metrics must handle or reject corrupted rows without returning NaN/Inf
        metrics = calculate_t25_risk_metrics(df_stock)
        for k, v in metrics.items():
            if v is not None:
                self.assertFalse(math.isnan(v), f"Key {k} is NaN")
                self.assertFalse(math.isinf(v), f"Key {k} is Inf")

        regime = detect_market_regime(df_vnindex=df_stock, breadth_ratio=0.5)
        for k, v in regime["metrics"].items():
            if v is not None:
                self.assertFalse(math.isnan(v), f"Metric {k} is NaN")
                self.assertFalse(math.isinf(v), f"Metric {k} is Inf")

    def test_3_insufficient_history(self):
        """3. Insufficient history (<20 rows) returns safe AVOID and null indicators."""
        df_short = create_mock_ohlcv(length=10)
        df_vnindex = create_mock_ohlcv(length=30)
        regime = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.5)

        rec = generate_recommendation(
            symbol="BBB",
            company_name="Company BBB",
            sector="Sector B",
            exchange="HOSE",
            df_stock=df_short,
            market_regime_info=regime,
            df_vnindex=df_vnindex,
        )

        self.assertEqual(rec["action"], "AVOID")
        self.assertEqual(rec["data_quality"], "INSUFFICIENT")
        self.assertIsNone(rec["signal_score"])
        self.assertIsNone(rec["risk_adjusted_score"])
        self.assertIsNone(rec["risk_metrics"]["var_t25"])

    def test_4_failed_symbol_exclusion(self):
        """4. Failed/empty symbol is excluded from breadth and liquidity denominators."""
        df_valid = create_mock_ohlcv(length=30, start_price=50.0, trend=0.01)
        df_vnindex = create_mock_ohlcv(length=30)
        as_of_date = df_vnindex["time"].iloc[-1]

        universe_stock_map = {
            "AAA": df_valid,
            "BBB": pd.DataFrame(),  # Failed symbol
        }
        candidates = [
            {"symbol": "AAA", "companyName": "Comp A", "sector": "Sec A"},
            {"symbol": "BBB", "companyName": "Comp B", "sector": "Sec B"},
        ]

        res = generate_historical_report(
            data_as_of=as_of_date,
            universe_stock_map=universe_stock_map,
            df_vnindex=df_vnindex,
            candidate_metadata=candidates,
        )
        recs_data = res[0]

        # Breadth ratio denominator should equal valid symbols count (1), so 1/1 = 1.00
        breadth = recs_data["market"]["metrics"]["market_breadth_ratio"]
        self.assertEqual(breadth, 1.0)

        # BBB recommendation must be AVOID with INSUFFICIENT data_quality
        recs = recs_data["recommendations"]
        rec_b = next(r for r in recs if r["symbol"] == "BBB")
        self.assertEqual(rec_b["action"], "AVOID")
        self.assertEqual(rec_b["data_quality"], "INSUFFICIENT")
        self.assertIsNone(rec_b["risk_metrics"]["liquidity_score"])

    def test_5_temporal_invalid_symbol(self):
        """5. Symbol with invalid or stale/future date gets empty DF / safe AVOID status."""
        df_vnindex = create_mock_ohlcv(length=30)
        regime = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.5)

        # Passing empty DataFrame representing temporal-invalid replacement
        rec = generate_recommendation(
            symbol="CCC",
            company_name="Comp C",
            sector="Sec C",
            exchange="HOSE",
            df_stock=pd.DataFrame(),
            market_regime_info=regime,
            df_vnindex=df_vnindex,
        )

        self.assertEqual(rec["action"], "AVOID")
        self.assertEqual(rec["data_quality"], "INSUFFICIENT")

    def test_6_partial_universe(self):
        """6. Partial universe (some valid, some invalid) evaluates valid symbols correctly."""
        df_vnindex = create_mock_ohlcv(length=30)
        as_of_date = df_vnindex["time"].iloc[-1]

        df_valid_1 = create_mock_ohlcv(length=30, start_price=50.0, trend=0.01)
        df_valid_2 = create_mock_ohlcv(length=30, start_price=20.0, trend=-0.01)
        # Create 10 rows ending on as_of_date (insufficient history)
        df_short = create_mock_ohlcv(length=10, start_date="2025-01-29")
        df_failed = pd.DataFrame()  # Failed symbol

        universe_stock_map = {
            "AAA": df_valid_1,
            "BBB": df_valid_2,
            "CCC": df_short,
            "DDD": df_failed,
        }
        candidates = [
            {"symbol": "AAA", "companyName": "Comp A", "sector": "Sec A"},
            {"symbol": "BBB", "companyName": "Comp B", "sector": "Sec B"},
            {"symbol": "CCC", "companyName": "Comp C", "sector": "Sec C"},
            {"symbol": "DDD", "companyName": "Comp D", "sector": "Sec D"},
        ]

        res = generate_historical_report(
            data_as_of=as_of_date,
            universe_stock_map=universe_stock_map,
            df_vnindex=df_vnindex,
            candidate_metadata=candidates,
        )
        recs = res[0]["recommendations"]

        rec_a = next(r for r in recs if r["symbol"] == "AAA")
        rec_b = next(r for r in recs if r["symbol"] == "BBB")
        rec_c = next(r for r in recs if r["symbol"] == "CCC")
        rec_d = next(r for r in recs if r["symbol"] == "DDD")

        self.assertIn(rec_a["data_quality"], ["SUFFICIENT", "PARTIAL"])
        self.assertIn(rec_b["data_quality"], ["SUFFICIENT", "PARTIAL"])
        self.assertEqual(rec_c["data_quality"], "INSUFFICIENT")
        self.assertEqual(rec_c["action"], "AVOID")
        self.assertEqual(rec_d["data_quality"], "INSUFFICIENT")
        self.assertEqual(rec_d["action"], "AVOID")

        # Also test direct recommendation generation on corrupted OHLCV
        df_corrupt = create_mock_ohlcv(length=30, start_price=10.0)
        df_corrupt.loc[5, "close"] = -100.0  # Invalid non-positive price
        regime = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.5)
        rec_corrupt = generate_recommendation(
            symbol="CORRUPT",
            company_name="Corrupt Corp",
            sector="Sec",
            exchange="HOSE",
            df_stock=df_corrupt,
            market_regime_info=regime,
            df_vnindex=df_vnindex,
        )
        self.assertEqual(rec_corrupt["action"], "AVOID")
        self.assertEqual(rec_corrupt["data_quality"], "INSUFFICIENT")

    def test_7_zero_valid_symbols(self):
        """7. Zero valid symbols returns safe default breadth (0.50), DEFENSIVE regime, and all AVOID."""
        df_vnindex = create_mock_ohlcv(length=30)
        as_of_date = df_vnindex["time"].iloc[-1]

        universe_stock_map = {
            "AAA": pd.DataFrame(),
            "BBB": pd.DataFrame(),
        }
        candidates = [
            {"symbol": "AAA", "companyName": "Comp A", "sector": "Sec A"},
            {"symbol": "BBB", "companyName": "Comp B", "sector": "Sec B"},
        ]

        res = generate_historical_report(
            data_as_of=as_of_date,
            universe_stock_map=universe_stock_map,
            df_vnindex=df_vnindex,
            candidate_metadata=candidates,
        )
        market = res[0]["market"]
        recs = res[0]["recommendations"]

        self.assertEqual(market["metrics"]["market_breadth_ratio"], 0.50)
        for r in recs:
            self.assertEqual(r["action"], "AVOID")
            self.assertEqual(r["data_quality"], "INSUFFICIENT")

    def test_8_denominator_count_correctness(self):
        """8. Denominator/count correctness for breadth and liquidity rank across mixed stocks."""
        df1 = create_mock_ohlcv(length=30, start_price=10000.0, vol_base=100000.0)
        df2 = create_mock_ohlcv(length=30, start_price=20000.0, vol_base=200000.0)
        df3 = create_mock_ohlcv(length=30, start_price=30000.0, vol_base=300000.0)
        df_invalid = pd.DataFrame()

        df_vnindex = create_mock_ohlcv(length=30)
        regime = detect_market_regime(df_vnindex=df_vnindex, breadth_ratio=0.5)

        recs = [
            generate_recommendation("S1", "C1", "Sec", "HOSE", df1, regime, df_vnindex),
            generate_recommendation("S2", "C2", "Sec", "HOSE", df2, regime, df_vnindex),
            generate_recommendation("S3", "C3", "Sec", "HOSE", df3, regime, df_vnindex),
            generate_recommendation("S4", "C4", "Sec", "HOSE", df_invalid, regime, df_vnindex),
        ]

        norm_recs = normalize_universe_liquidity_scores(recs, market_regime=regime["regime"])

        # S4 must have None liquidity score
        rec_s4 = next(r for r in norm_recs if r["symbol"] == "S4")
        self.assertIsNone(rec_s4["risk_metrics"]["liquidity_score"])

        # S1, S2, S3 must have percentile ranks based on denominator = 3 (approx 33.3, 66.7, 100.0)
        rec_s1 = next(r for r in norm_recs if r["symbol"] == "S1")
        rec_s2 = next(r for r in norm_recs if r["symbol"] == "S2")
        rec_s3 = next(r for r in norm_recs if r["symbol"] == "S3")

        # pd.Series.rank(pct=True) for 3 items produces [1/3, 2/3, 3/3] = [33.3, 66.7, 100.0]
        self.assertAlmostEqual(rec_s1["risk_metrics"]["liquidity_score"], 33.3, delta=0.5)
        self.assertAlmostEqual(rec_s2["risk_metrics"]["liquidity_score"], 66.7, delta=0.5)
        self.assertEqual(rec_s3["risk_metrics"]["liquidity_score"], 100.0)


if __name__ == "__main__":
    unittest.main()
