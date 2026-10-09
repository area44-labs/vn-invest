"""Unit and integration tests for quantitative parity between production report generation and historical report generation.

Validates that run_pipeline() and generate_historical_report() produce equivalent
quantitative outputs when given identical point-in-time inputs.
"""

import copy
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.domain.universe import Universe
from scripts.generate_report import generate_historical_report, run_pipeline


def create_synthetic_ohlcv(
    start_date: str = "2025-01-01",
    periods: int = 60,
    base_price: float = 50000.0,
    volume: float = 100000.0,
    trend: str = "uptrend",
) -> pd.DataFrame:
    """Helper to create valid daily OHLCV DataFrames with deterministic patterns."""
    dates = pd.date_range(start=start_date, periods=periods, freq="D")
    data = []
    for i, d in enumerate(dates):
        if trend == "uptrend":
            price = base_price * (1.0 + 0.005 * i)
        elif trend == "downtrend":
            price = base_price * (1.0 - 0.005 * i)
        elif trend == "volatile":
            price = base_price + (1.0 + 0.02 * (1 if i % 2 == 0 else -1))
        else:  # sideways
            price = base_price + (i % 3 - 1) * 100.0

        data.append(
            {
                "time": d.strftime("%Y-%m-%d"),
                "open": round(price - 100.0, 2),
                "high": round(price + 300.0, 2),
                "low": round(price - 300.0, 2),
                "close": round(price, 2),
                "volume": volume + (i * 1000.0),
            }
        )
    return pd.DataFrame(data)


def extract_quantitative_recommendation(rec: dict) -> dict:
    """Extract strictly quantitative and model fields from a stock recommendation object."""
    return {
        "symbol": rec.get("symbol"),
        "company_name": rec.get("company_name"),
        "exchange": rec.get("exchange"),
        "sector": rec.get("sector"),
        "action": rec.get("action"),
        "model_version": rec.get("model_version"),
        "data_quality": rec.get("data_quality"),
        "data_quality_issues": rec.get("data_quality_issues"),
        "data_as_of": rec.get("data_as_of"),
        "signal_score": rec.get("signal_score"),
        "risk_adjusted_score": rec.get("risk_adjusted_score"),
        "score_components": copy.deepcopy(rec.get("score_components")),
        "confidence": rec.get("confidence"),
        "risk_level": rec.get("risk_level"),
        "expected_return": copy.deepcopy(rec.get("expected_return")),
        "risk_metrics": copy.deepcopy(rec.get("risk_metrics")),
        "trade_plan": copy.deepcopy(rec.get("trade_plan")),
        "reasons": copy.deepcopy(rec.get("reasons")),
        "warnings": copy.deepcopy(rec.get("warnings")),
        "invalidation": copy.deepcopy(rec.get("invalidation")),
        "divergence": copy.deepcopy(rec.get("divergence")),
    }


@pytest.mark.integration
class TestProductionHistoricalParity:
    """Test suite for verifying quantitative parity between run_pipeline and generate_historical_report."""

    def setup_method(self):
        self.periods = 60
        self.start_date = "2025-01-01"

        # Raw deterministic PIT benchmark inputs ending at date T
        self.raw_vnindex = create_synthetic_ohlcv(
            start_date=self.start_date, periods=self.periods, base_price=1200.0, trend="uptrend"
        )
        self.raw_vn30 = create_synthetic_ohlcv(
            start_date=self.start_date, periods=self.periods, base_price=1250.0, trend="uptrend"
        )

        # Target date T is the latest date in benchmark
        self.target_date = self.raw_vnindex["time"].iloc[-1]

        # Raw deterministic PIT stock universe inputs with diverse behaviors (BUY, WATCH, HOLD/SELL/AVOID)
        self.raw_fpt = create_synthetic_ohlcv(
            start_date=self.start_date, periods=self.periods, base_price=90000.0, trend="uptrend"
        )
        self.raw_vnm = create_synthetic_ohlcv(
            start_date=self.start_date, periods=self.periods, base_price=70000.0, trend="sideways"
        )
        self.raw_hpg = create_synthetic_ohlcv(
            start_date=self.start_date,
            periods=self.periods,
            base_price=28000.0,
            trend="downtrend",
        )

        # Shared single source of truth raw PIT input map supplied to both production mock and historical report
        self.raw_universe_map = {
            "FPT": self.raw_fpt,
            "VNM": self.raw_vnm,
            "HPG": self.raw_hpg,
        }

        self.candidate_metadata = [
            {
                "symbol": "FPT",
                "companyName": "Công ty Cổ phần FPT",
                "sector": "Công nghệ",
                "exchange": "HOSE",
            },
            {
                "symbol": "VNM",
                "companyName": "Công ty Cổ phần Sữa Việt Nam",
                "sector": "Thực phẩm",
                "exchange": "HOSE",
            },
            {
                "symbol": "HPG",
                "companyName": "Công ty Cổ phần Tập đoàn Hòa Phát",
                "sector": "Thép",
                "exchange": "HOSE",
            },
        ]

    def _mock_fetch_ohlcv(self, symbol, **kwargs):
        sym = symbol.upper()
        if sym == "VNINDEX":
            return self.raw_vnindex.copy()
        if sym == "VN30":
            return self.raw_vn30.copy()
        if sym in self.raw_universe_map:
            return self.raw_universe_map[sym].copy()
        return pd.DataFrame()

    def _run_both_pipelines(self, reference_date: str = "2025-03-01T10:00:00Z"):
        """Run production and historical report generation with identical raw PIT data."""
        with (
            patch(
                "scripts.data.providers.vnstock.VnstockMarketProvider.fetch_ohlcv",
                side_effect=self._mock_fetch_ohlcv,
            ),
            patch("scripts.pipeline.runner.UniverseProvider") as mock_provider_cls,
        ):
            mock_provider = mock_provider_cls.return_value
            mock_provider.get_universe.return_value = Universe.from_candidates(
                self.candidate_metadata,
                universe_type="TEST_UNIVERSE",
                benchmarks=("VNINDEX", "VN30"),
            )

            prod_res = run_pipeline(update_data=False)

        hist_res = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=self.raw_universe_map,
            df_vnindex=self.raw_vnindex,
            df_vn30=self.raw_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date=reference_date,
        )

        return prod_res, hist_res

    def test_same_pit_inputs_produce_same_market_regime(self):
        """Verifies that identical VNINDEX, VN30, and market breadth inputs at date T produce identical production and historical market regime outputs."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs_payload, prod_market_payload, _ = prod_res
        hist_recs_payload, hist_market_payload, _ = hist_res

        assert prod_recs_payload["data_as_of"] == self.target_date
        assert hist_recs_payload["data_as_of"] == self.target_date

        # Market regime structure & quantitative metrics
        assert prod_recs_payload["market"] == hist_recs_payload["market"]
        assert prod_market_payload["market"] == hist_market_payload["market"]

        # Summary counts
        assert prod_recs_payload["summary"] == hist_recs_payload["summary"]

    def test_same_pit_inputs_produce_same_recommendation(self):
        """Verifies that production and historical recommendations match across all quantitative and model fields for identical inputs."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs = {r["symbol"]: r for r in prod_res[0]["recommendations"]}
        hist_recs = {r["symbol"]: r for r in hist_res[0]["recommendations"]}

        assert set(prod_recs.keys()) == set(hist_recs.keys())

        for sym, p_rec in prod_recs.items():
            prod_quant = extract_quantitative_recommendation(p_rec)
            hist_quant = extract_quantitative_recommendation(hist_recs[sym])

            assert prod_quant == hist_quant, (
                f"Quantitative recommendation mismatch for symbol '{sym}'"
            )

    def test_signal_parity(self):
        """Verifies exact parity of signal scores, risk-adjusted scores, recommendation actions, confidence scores, and score components across production and historical paths."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs = {r["symbol"]: r for r in prod_res[0]["recommendations"]}
        hist_recs = {r["symbol"]: r for r in hist_res[0]["recommendations"]}

        for sym, p_rec in prod_recs.items():
            h_rec = hist_recs[sym]

            assert p_rec["action"] == h_rec["action"]
            assert p_rec["signal_score"] == h_rec["signal_score"]
            assert p_rec["risk_adjusted_score"] == h_rec["risk_adjusted_score"]
            assert p_rec["confidence"] == h_rec["confidence"]
            assert p_rec["score_components"] == h_rec["score_components"]
            assert p_rec["divergence"] == h_rec["divergence"]

    def test_risk_parity(self):
        """Verifies exact parity of VaR, Expected Shortfall, volatility, max drawdown, liquidity, and average traded value across production and historical paths."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs = {r["symbol"]: r for r in prod_res[0]["recommendations"]}
        hist_recs = {r["symbol"]: r for r in hist_res[0]["recommendations"]}

        for sym, p_rec in prod_recs.items():
            h_rec = hist_recs[sym]

            assert p_rec["risk_level"] == h_rec["risk_level"]
            assert p_rec["risk_metrics"] == h_rec["risk_metrics"]

            p_rm = p_rec["risk_metrics"]
            h_rm = h_rec["risk_metrics"]

            assert p_rm["var_t25"] == h_rm["var_t25"]
            assert p_rm["es_t25"] == h_rm["es_t25"]
            assert p_rm["volatility_60d"] == h_rm["volatility_60d"]
            assert p_rm["max_drawdown"] == h_rm["max_drawdown"]
            assert p_rm["liquidity_score"] == h_rm["liquidity_score"]
            assert p_rm["avg_value_20d"] == h_rm["avg_value_20d"]

    def test_trade_plan_parity(self):
        """Verifies exact parity of trade plan entry levels, targets, stop-loss levels, and invalidation rules across production and historical paths."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs = {r["symbol"]: r for r in prod_res[0]["recommendations"]}
        hist_recs = {r["symbol"]: r for r in hist_res[0]["recommendations"]}

        for sym, p_rec in prod_recs.items():
            h_rec = hist_recs[sym]

            assert p_rec["trade_plan"] == h_rec["trade_plan"]
            assert p_rec["invalidation"] == h_rec["invalidation"]
            assert p_rec["reasons"] == h_rec["reasons"]
            assert p_rec["warnings"] == h_rec["warnings"]

    def test_multi_stock_parity(self):
        """Verifies multi-stock parity across a diverse universe of stocks producing distinct recommendation actions."""
        prod_res, hist_res = self._run_both_pipelines()

        prod_recs = prod_res[0]["recommendations"]
        hist_recs = hist_res[0]["recommendations"]

        assert len(prod_recs) >= 3
        assert len(prod_recs) == len(hist_recs)

        actions = {r["action"] for r in prod_recs}
        assert len(actions) > 1, "Multi-stock universe should cover diverse actions"

        for p_rec, h_rec in zip(prod_recs, hist_recs, strict=True):
            p_quant = extract_quantitative_recommendation(p_rec)
            h_quant = extract_quantitative_recommendation(h_rec)
            assert p_quant == h_quant

    def test_reproducibility(self):
        """Verifies reproducible parity results across repeated execution runs with identical reference dates."""
        prod_res_a, hist_res_a = self._run_both_pipelines(reference_date="2025-03-01T10:00:00Z")
        prod_res_b, hist_res_b = self._run_both_pipelines(reference_date="2025-03-01T10:00:00Z")

        # Production path run A vs run B
        assert [
            extract_quantitative_recommendation(r) for r in prod_res_a[0]["recommendations"]
        ] == [extract_quantitative_recommendation(r) for r in prod_res_b[0]["recommendations"]]
        assert prod_res_a[0]["market"] == prod_res_b[0]["market"]
        assert prod_res_a[0]["summary"] == prod_res_b[0]["summary"]

        # Historical path run A vs run B
        assert [
            extract_quantitative_recommendation(r) for r in hist_res_a[0]["recommendations"]
        ] == [extract_quantitative_recommendation(r) for r in hist_res_b[0]["recommendations"]]
        assert hist_res_a[0]["market"] == hist_res_b[0]["market"]
        assert hist_res_a[0]["summary"] == hist_res_b[0]["summary"]

    def test_temporal_safety_future_data_invariance(self):
        """Verifies temporal safety where appending future data strictly greater than date T does not alter the historical report at T or introduce parity divergence."""
        # Baseline run at target date T using raw PIT datasets
        prod_res_base, hist_res_base = self._run_both_pipelines()

        # Create extended raw datasets with future observations > T
        future_vnindex = pd.DataFrame(
            [
                {
                    "time": "2025-03-02",
                    "open": 1100.0,
                    "high": 1100.0,
                    "low": 1000.0,
                    "close": 1000.0,
                    "volume": 200000.0,
                },
                {
                    "time": "2025-03-03",
                    "open": 1000.0,
                    "high": 1000.0,
                    "low": 900.0,
                    "close": 900.0,
                    "volume": 250000.0,
                },
            ]
        )
        future_vn30 = pd.DataFrame(
            [
                {
                    "time": "2025-03-02",
                    "open": 1150.0,
                    "high": 1150.0,
                    "low": 1050.0,
                    "close": 1050.0,
                    "volume": 200000.0,
                },
                {
                    "time": "2025-03-03",
                    "open": 1050.0,
                    "high": 1050.0,
                    "low": 950.0,
                    "close": 950.0,
                    "volume": 250000.0,
                },
            ]
        )
        future_stock = pd.DataFrame(
            [
                {
                    "time": "2025-03-02",
                    "open": 20000.0,
                    "high": 20000.0,
                    "low": 15000.0,
                    "close": 15000.0,
                    "volume": 500000.0,
                },
                {
                    "time": "2025-03-03",
                    "open": 15000.0,
                    "high": 15000.0,
                    "low": 10000.0,
                    "close": 10000.0,
                    "volume": 600000.0,
                },
            ]
        )

        extended_vnindex = pd.concat([self.raw_vnindex, future_vnindex], ignore_index=True)
        extended_vn30 = pd.concat([self.raw_vn30, future_vn30], ignore_index=True)

        extended_map = {}
        for sym, df in self.raw_universe_map.items():
            extended_map[sym] = pd.concat([df, future_stock], ignore_index=True)

        # Generate historical report at T using extended datasets (containing future rows > T)
        hist_res_extended = generate_historical_report(
            data_as_of=self.target_date,
            universe_stock_map=extended_map,
            df_vnindex=extended_vnindex,
            df_vn30=extended_vn30,
            candidate_metadata=self.candidate_metadata,
            reference_date="2025-03-01T10:00:00Z",
        )

        # Quantitative outputs must remain identical to baseline at date T
        base_quants = [
            extract_quantitative_recommendation(r) for r in hist_res_base[0]["recommendations"]
        ]
        ext_quants = [
            extract_quantitative_recommendation(r) for r in hist_res_extended[0]["recommendations"]
        ]

        assert base_quants == ext_quants
        assert hist_res_base[0]["market"] == hist_res_extended[0]["market"]
        assert hist_res_base[0]["summary"] == hist_res_extended[0]["summary"]

        # Also verify parity between production path (given data sliced at T) and historical path (given extended data as_of T)
        prod_quants = [
            extract_quantitative_recommendation(r) for r in prod_res_base[0]["recommendations"]
        ]
        assert prod_quants == ext_quants
