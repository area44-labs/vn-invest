"""Unit tests for VN Invest Domain Contracts."""

import unittest
from dataclasses import FrozenInstanceError

from scripts.domain import (
    DataQuality,
    OHLCVData,
    PipelineResult,
    Recommendation,
    RiskAssessment,
    TradePlan,
    Universe,
    UniverseCandidate,
    UniverseScanResult,
)


class TestOHLCVDataDomainContract(unittest.TestCase):
    """Test suite for OHLCVData immutable domain model."""

    def test_valid_ohlcv_construction_and_serialization(self):
        candle = OHLCVData(
            date="2026-03-31",
            open=50.0,
            high=52.5,
            low=49.5,
            close=51.0,
            volume=1000000.0,
        )
        self.assertEqual(candle.date, "2026-03-31")
        self.assertEqual(candle.open, 50.0)
        self.assertEqual(candle.high, 52.5)
        self.assertEqual(candle.low, 49.5)
        self.assertEqual(candle.close, 51.0)
        self.assertEqual(candle.volume, 1000000.0)

        data_dict = candle.to_dict()
        self.assertEqual(data_dict["date"], "2026-03-31")
        self.assertEqual(data_dict["close"], 51.0)

        reconstructed = OHLCVData.from_dict(data_dict)
        self.assertEqual(reconstructed, candle)

    def test_immutability(self):
        candle = OHLCVData(
            date="2026-03-31",
            open=50.0,
            high=52.5,
            low=49.5,
            close=51.0,
            volume=1000000.0,
        )
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            candle.close = 55.0  # type: ignore

    def test_non_positive_price_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=0.0, high=52.5, low=49.5, close=51.0, volume=1000.0)
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=-5.0, low=49.5, close=51.0, volume=1000.0)

    def test_negative_volume_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=49.5, close=51.0, volume=-100.0)

    def test_invalid_ohlc_relationship_rejection(self):
        # High < Low
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=48.0, low=49.5, close=50.0, volume=1000.0)

        # High < Open
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=55.0, high=52.5, low=49.5, close=50.0, volume=1000.0)

        # Low > Close
        with self.assertRaises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=51.0, close=49.5, volume=1000.0)

    def test_empty_date_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData("", open=50.0, high=52.5, low=49.5, close=51.0, volume=1000.0)

    def test_nan_and_inf_rejection(self):
        with self.assertRaises(ValueError):
            OHLCVData(
                "2026-03-31", open=float("nan"), high=52.5, low=49.5, close=51.0, volume=1000.0
            )
        with self.assertRaises(ValueError):
            OHLCVData(
                "2026-03-31", open=50.0, high=float("inf"), low=49.5, close=51.0, volume=1000.0
            )


class TestDataQualityDomainContract(unittest.TestCase):
    """Test suite for DataQuality domain model."""

    def test_valid_data_quality(self):
        dq = DataQuality(
            status="SUFFICIENT",
            issues=(),
            valid_row_count=100,
            latest_date="2026-03-31",
            data_as_of="2026-03-31",
            data_source="TEST",
        )
        self.assertEqual(dq.status, "SUFFICIENT")
        self.assertEqual(dq.valid_row_count, 100)

        d = dq.to_dict()
        self.assertEqual(d["status"], "SUFFICIENT")
        self.assertEqual(DataQuality.from_dict(d), dq)

    def test_invalid_status_rejection(self):
        with self.assertRaises(ValueError):
            DataQuality(status="UNKNOWN")

    def test_negative_valid_row_count_rejection(self):
        with self.assertRaises(ValueError):
            DataQuality(status="SUFFICIENT", valid_row_count=-5)

    def test_immutability(self):
        dq = DataQuality(status="SUFFICIENT")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            dq.status = "PARTIAL"  # type: ignore


class TestUniverseDomainContract(unittest.TestCase):
    """Test suite for UniverseCandidate and Universe domain models."""

    def test_candidate_and_universe_construction(self):
        c1 = UniverseCandidate(
            symbol="VNM", company_name="Vinamilk", sector="Consumer", exchange="HOSE"
        )
        c2 = UniverseCandidate(
            symbol="FPT", company_name="FPT Corp", sector="Technology", exchange="HNX"
        )
        c3 = UniverseCandidate(
            symbol="BSR", company_name="Binh Son", sector="Energy", exchange="UPCOM"
        )

        u = Universe(universe_type="VN30", candidates=(c1, c2, c3))
        self.assertEqual(u.universe_size, 3)
        self.assertEqual(len(u.candidates), 3)

        u_info = u.to_info_dict()
        self.assertEqual(u_info["universe_type"], "VN30")
        self.assertEqual(u_info["universe_size"], 3)
        self.assertNotIn("candidates", u_info)

    def test_universe_candidate_valid_exchanges(self):
        for ex in ("HOSE", "HNX", "UPCOM"):
            c = UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange=ex)
            self.assertEqual(c.exchange, ex)

            c_dict = UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech", "exchange": ex}
            )
            self.assertEqual(c_dict.exchange, ex)

    def test_universe_candidate_strict_rejection(self):
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="", sector="Tech", exchange="HOSE")
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="  ", exchange="HOSE")
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="")
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="   ")
        with self.assertRaises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="NASDAQ")

    def test_universe_candidate_from_dict_missing_exchange_rejection(self):
        with self.assertRaises(ValueError):
            UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech"}
            )
        with self.assertRaises(ValueError):
            UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech", "exchange": ""}
            )
        with self.assertRaises(ValueError):
            UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech", "exchange": "  \t "}
            )

    def test_universe_lossless_serialization_roundtrip(self):
        c1 = UniverseCandidate(
            symbol="VNM", company_name="Vinamilk", sector="Consumer", exchange="HOSE"
        )
        c2 = UniverseCandidate(
            symbol="FPT", company_name="FPT Corp", sector="Technology", exchange="HOSE"
        )
        u = Universe(
            universe_type="VN30_EXTENDED",
            candidates=(c1, c2),
            scanned_at="2026-03-31T00:00:00Z",
        )

        u_dict = u.to_dict()
        self.assertIn("candidates", u_dict)
        self.assertEqual(len(u_dict["candidates"]), 2)

        reconstructed = Universe.from_dict(u_dict)
        self.assertEqual(reconstructed, u)
        self.assertEqual(reconstructed.universe_size, 2)
        self.assertEqual(reconstructed.candidates[0].symbol, "VNM")
        self.assertEqual(reconstructed.candidates[1].company_name, "FPT Corp")


class TestTradePlanDomainContract(unittest.TestCase):
    """Test suite for TradePlan domain model."""

    def test_valid_trade_plan(self):
        tp = TradePlan(
            current_price=50000.0,
            entry_low=49500.0,
            entry_high=50500.0,
            stop_loss=47500.0,
            tp1=55000.0,
            tp2=58000.0,
            risk_reward=2.0,
            position_percent=15.0,
        )
        self.assertEqual(tp.current_price, 50000.0)
        self.assertEqual(tp.position_percent, 15.0)

        tp_dict = tp.to_dict()
        self.assertEqual(tp_dict["stop_loss"], 47500.0)
        self.assertEqual(TradePlan.from_dict(tp_dict), tp)

    def test_invalid_position_percent_rejection(self):
        with self.assertRaises(ValueError):
            TradePlan(position_percent=-5.0)
        with self.assertRaises(ValueError):
            TradePlan(position_percent=105.0)

    def test_negative_price_rejection(self):
        with self.assertRaises(ValueError):
            TradePlan(current_price=-1000.0)


class TestRiskAssessmentDomainContract(unittest.TestCase):
    """Test suite for RiskAssessment domain model."""

    def test_valid_risk_assessment(self):
        ra = RiskAssessment(
            var_t25=-0.045,
            es_t25=-0.062,
            volatility_60d=0.25,
            max_drawdown=-0.12,
            liquidity_score=85.0,
            avg_value_20d=150.5,
            risk_level="MEDIUM",
        )
        self.assertEqual(ra.liquidity_score, 85.0)
        self.assertEqual(ra.risk_level, "MEDIUM")

        metrics_dict = ra.to_metrics_dict()
        self.assertNotIn("risk_level", metrics_dict)
        self.assertEqual(metrics_dict["liquidity_score"], 85.0)
        self.assertEqual(metrics_dict["avg_value_20d"], 150.5)

        full_dict = ra.to_dict()
        self.assertEqual(full_dict["risk_level"], "MEDIUM")
        self.assertEqual(RiskAssessment.from_dict(full_dict), ra)

    def test_insufficient_risk_assessment_omits_avg_value_20d(self):
        ra = RiskAssessment(
            var_t25=None,
            es_t25=None,
            volatility_60d=None,
            max_drawdown=None,
            liquidity_score=None,
            avg_value_20d=None,
            risk_level=None,
        )
        metrics = ra.to_metrics_dict()
        self.assertNotIn("avg_value_20d", metrics)
        expected_keys = {"var_t25", "es_t25", "volatility_60d", "max_drawdown", "liquidity_score"}
        self.assertEqual(set(metrics.keys()), expected_keys)

    def test_invalid_liquidity_score_rejection(self):
        with self.assertRaises(ValueError):
            RiskAssessment(liquidity_score=105.0)
        with self.assertRaises(ValueError):
            RiskAssessment(liquidity_score=-1.0)

    def test_invalid_risk_level_rejection(self):
        with self.assertRaises(ValueError):
            RiskAssessment(risk_level="EXTREME")


class TestRecommendationDomainContract(unittest.TestCase):
    """Test suite for Recommendation domain model."""

    def setUp(self):
        self.valid_rec = Recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            exchange="HOSE",
            sector="Consumer Goods",
            action="BUY",
            model_version="2.0",
            data_quality="SUFFICIENT",
            data_as_of="2026-03-31",
            data_source="REAL_DATA",
            signal_score=78.5,
            risk_adjusted_score=75.0,
            score_components={
                "trend": 80.0,
                "momentum": 75.0,
                "volume": 70.0,
                "relative_strength": 85.0,
                "divergence": 80.0,
            },
            confidence=0.82,
            risk_level="MEDIUM",
            expected_return={
                "expected_return_5d": None,
                "expected_return_10d": None,
                "expected_return_20d": None,
            },
            risk_metrics=RiskAssessment(
                var_t25=-0.04,
                es_t25=-0.05,
                volatility_60d=0.22,
                max_drawdown=-0.10,
                liquidity_score=90.0,
                avg_value_20d=200.0,
                risk_level="MEDIUM",
            ),
            trade_plan=TradePlan(
                current_price=68000.0,
                entry_low=67500.0,
                entry_high=68500.0,
                stop_loss=64000.0,
                tp1=74000.0,
                tp2=78000.0,
                risk_reward=2.5,
                position_percent=15.0,
            ),
            reasons=("Gia tren MA20",),
            warnings=(),
            invalidation=("Gia vi pham cat lo 64.000 VNĐ",),
            divergence={"1H": "NONE", "1D": "BULLISH", "1W": "NONE", "1M": "NONE"},
        )

    def test_insufficient_recommendation_exact_legacy_json_parity(self):
        insufficient_rec = Recommendation(
            symbol="VNM",
            company_name="Vinamilk",
            exchange="HOSE",
            sector="Consumer Goods",
            action="AVOID",
            model_version="2.0",
            data_quality="INSUFFICIENT",
            data_quality_issues=("Insufficient historical data",),
            data_as_of="2026-03-31",
            data_source="PROVIDER_FAILURE",
            confidence=0.10,
            risk_level=None,
            risk_metrics=RiskAssessment(),
            trade_plan=TradePlan(),
        )

        d = insufficient_rec.to_dict()

        # Exact legacy keys check for risk_metrics (must NOT contain avg_value_20d)
        expected_risk_metrics = {
            "var_t25": None,
            "es_t25": None,
            "volatility_60d": None,
            "max_drawdown": None,
            "liquidity_score": None,
        }
        self.assertEqual(d["risk_metrics"], expected_risk_metrics)
        self.assertNotIn("avg_value_20d", d["risk_metrics"])

        # Exact legacy trade plan check
        expected_trade_plan = {
            "current_price": None,
            "entry_low": None,
            "entry_high": None,
            "stop_loss": None,
            "tp1": None,
            "tp2": None,
            "risk_reward": None,
            "position_percent": 0.0,
        }
        self.assertEqual(d["trade_plan"], expected_trade_plan)

        self.assertEqual(d["action"], "AVOID")
        self.assertEqual(d["data_quality"], "INSUFFICIENT")

    def test_valid_recommendation_serialization(self):
        rec_dict = self.valid_rec.to_dict()
        self.assertEqual(rec_dict["symbol"], "VNM")
        self.assertEqual(rec_dict["action"], "BUY")
        self.assertEqual(rec_dict["confidence"], 0.82)
        self.assertEqual(rec_dict["risk_metrics"]["liquidity_score"], 90.0)
        self.assertEqual(rec_dict["trade_plan"]["current_price"], 68000.0)

        reconstructed = Recommendation.from_dict(rec_dict)
        self.assertEqual(reconstructed.symbol, "VNM")
        self.assertEqual(reconstructed.signal_score, 78.5)

    def test_valid_exchanges_supported(self):
        for ex in ("HOSE", "HNX", "UPCOM"):
            rec = Recommendation.from_dict({**self.valid_rec.to_dict(), "exchange": ex})
            self.assertEqual(rec.exchange, ex)

    def test_non_string_company_name_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "company_name": None})

    def test_non_string_sector_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "sector": 123})

    def test_invalid_action_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "action": "SUPER_BUY"})

    def test_invalid_exchange_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "exchange": "NYSE"})

    def test_out_of_range_score_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "signal_score": 150.0})

    def test_out_of_range_confidence_rejection(self):
        with self.assertRaises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "confidence": 1.5})


class TestPipelineResultDomainContract(unittest.TestCase):
    """Test suite for PipelineResult domain model."""

    def test_pipeline_result_unpacking_and_attributes(self):
        recs_data = {"schema_version": "2.0", "recommendations": []}
        market_data = {"market": {"regime": "BULL"}}
        history_data = recs_data
        universe_audit = {"status": "SUCCESS"}

        pr = PipelineResult(
            recs_data=recs_data,
            market_data=market_data,
            history_data=history_data,
            universe_audit=universe_audit,
        )

        # 3-element tuple unpacking compatibility
        r, m, h = pr
        self.assertEqual(r, recs_data)
        self.assertEqual(m, market_data)
        self.assertEqual(h, history_data)

        # Attribute access
        self.assertEqual(pr.recommendations_payload, recs_data)
        self.assertEqual(pr.universe_audit, universe_audit)

        # Serialization
        pr_dict = pr.to_dict()
        self.assertEqual(pr_dict["market"]["market"]["regime"], "BULL")


class TestUniverseAndScanResultDomainContracts(unittest.TestCase):
    """Test suite for Issue #173 Universe and UniverseScanResult contracts."""

    def test_provider_to_universe_conversion(self):
        from scripts.lib.vietnam_market import UniverseProvider

        provider = UniverseProvider()
        u = provider.get_universe()
        self.assertIsInstance(u, Universe)
        self.assertEqual(u.universe_type, "VN30_MIDCAP_LEADERS")
        self.assertEqual(u.benchmarks, ("VNINDEX", "VN30"))
        self.assertGreater(u.universe_size, 0)
        self.assertIn("FPT", u.candidate_symbols)

    def test_universe_construction_and_symbol_normalization(self):
        candidates = [
            {
                "symbol": " fpt ",
                "companyName": " FPT Corp ",
                "sector": " Tech ",
                "exchange": " hose ",
            },
            {"symbol": "vnm", "companyName": "Vinamilk", "sector": "Consumer", "exchange": "HOSE"},
        ]
        u = Universe.from_candidates(
            candidates, universe_type="VN30_MIDCAP", benchmarks=("VNINDEX", "VN30")
        )
        self.assertEqual(u.universe_type, "VN30_MIDCAP")
        self.assertEqual(u.universe_size, 2)
        self.assertEqual(u.candidate_symbols, ("FPT", "VNM"))
        self.assertEqual(u.candidate_symbols_set, frozenset({"FPT", "VNM"}))
        self.assertEqual(u.benchmarks, ("VNINDEX", "VN30"))
        self.assertEqual(u.expected_symbols, frozenset({"VNINDEX", "VN30", "FPT", "VNM"}))

    def test_duplicate_symbol_handling(self):
        candidates = [
            {"symbol": "FPT", "companyName": "FPT Corp 1", "sector": "Tech", "exchange": "HOSE"},
            {"symbol": "FPT", "companyName": "FPT Corp 2", "sector": "Tech", "exchange": "HOSE"},
            {"symbol": "VNM", "companyName": "Vinamilk", "sector": "Consumer", "exchange": "HOSE"},
        ]
        u = Universe.from_candidates(candidates, universe_type="DEDUP_TEST")
        # Keeps first occurrence of FPT
        self.assertEqual(u.universe_size, 2)
        self.assertEqual(u.candidate_symbols, ("FPT", "VNM"))
        self.assertEqual(u.candidates[0].company_name, "FPT Corp 1")

    def test_explicit_vs_default_benchmarks(self):
        # Generic Universe defaults to empty benchmarks
        u_default = Universe.from_candidates([], universe_type="DEFAULT_BM")
        self.assertEqual(u_default.benchmarks, ())
        self.assertEqual(u_default.expected_symbols, frozenset())

        # Production benchmarks from UniverseProvider
        from scripts.lib.vietnam_market import UniverseProvider

        u_prod = UniverseProvider().get_universe()
        self.assertEqual(u_prod.benchmarks, ("VNINDEX", "VN30"))
        self.assertIn("VNINDEX", u_prod.expected_symbols)
        self.assertIn("VN30", u_prod.expected_symbols)

        # Explicit custom benchmarks
        u_custom = Universe.from_candidates(
            [], universe_type="CUSTOM_BM", benchmarks=("SPX", "NDX")
        )
        self.assertEqual(u_custom.benchmarks, ("SPX", "NDX"))
        self.assertEqual(u_custom.expected_symbols, frozenset({"SPX", "NDX"}))

        # Explicit empty benchmarks
        u_empty_bm = Universe.from_candidates([], universe_type="EMPTY_BM", benchmarks=())
        self.assertEqual(u_empty_bm.benchmarks, ())
        self.assertEqual(u_empty_bm.expected_symbols, frozenset())

    def test_universe_scan_result_fail_fast_validation(self):
        u = Universe.from_candidates(
            [{"symbol": "FPT", "companyName": "FPT", "sector": "Tech", "exchange": "HOSE"}]
        )
        scan_res = UniverseScanResult(universe=u)
        self.assertIsInstance(scan_res.universe, Universe)

        # Invalid universe input must raise TypeError fail-fast
        with self.assertRaises(TypeError):
            UniverseScanResult(universe=u.to_dict())  # type: ignore

        with self.assertRaises(TypeError):
            UniverseScanResult(universe="INVALID_UNIVERSE_STRING")  # type: ignore

        with self.assertRaises(TypeError):
            UniverseScanResult(universe=123)  # type: ignore

    def test_universe_scan_result_with_updates_supports_universe_parameter(self):
        u1 = Universe.from_candidates(
            [{"symbol": "FPT", "companyName": "FPT", "sector": "Tech", "exchange": "HOSE"}]
        )
        u2 = Universe.from_candidates(
            [{"symbol": "VNM", "companyName": "VNM", "sector": "Food", "exchange": "HOSE"}]
        )

        scan_res = UniverseScanResult(universe=u1, processed_symbols=("FPT",))
        updated_scan_res = scan_res.with_updates(universe=u2, processed_symbols=("VNM",))

        self.assertEqual(updated_scan_res.universe, u2)
        self.assertEqual(updated_scan_res.processed_symbols, ("VNM",))

    def test_universe_scan_result_completeness_and_classification(self):
        u = Universe.from_candidates(
            [
                {"symbol": "FPT", "companyName": "FPT", "sector": "Tech", "exchange": "HOSE"},
                {
                    "symbol": "VNM",
                    "companyName": "Vinamilk",
                    "sector": "Consumer",
                    "exchange": "HOSE",
                },
                {
                    "symbol": "VIC",
                    "companyName": "Vingroup",
                    "sector": "Real Estate",
                    "exchange": "HOSE",
                },
            ],
            benchmarks=("VNINDEX", "VN30"),
        )
        # expected_symbols = {"VNINDEX", "VN30", "FPT", "VNM", "VIC"} (5 total)

        scan_res = UniverseScanResult(
            universe=u,
            processed_symbols=("VNINDEX", "VN30", "FPT"),
            invalid_symbols=(),
            insufficient_symbols=("VNM",),
            failed_symbols=(),
            missing_symbols=("VIC",),
            exclusions_map={
                "VNM": {
                    "symbol": "VNM",
                    "stage": "STOCK_FETCH",
                    "status": "INSUFFICIENT",
                    "reason": "Low history",
                },
                "VIC": {
                    "symbol": "VIC",
                    "stage": "UNIVERSE_DISCOVERY",
                    "status": "MISSING",
                    "reason": "Missing",
                },
            },
        )

        self.assertEqual(scan_res.expected_count, 5)
        self.assertEqual(scan_res.processed_count, 3)
        self.assertEqual(scan_res.insufficient_count, 1)
        self.assertEqual(scan_res.missing_count, 1)
        self.assertEqual(scan_res.invalid_count, 0)
        self.assertEqual(scan_res.failed_count, 0)
        self.assertAlmostEqual(scan_res.processed_ratio, 0.6)
        self.assertFalse(scan_res.is_complete)

    def test_pipeline_context_single_source_of_truth(self):
        from scripts.pipeline.context import PipelineContext

        ctx = PipelineContext(is_historical=False)
        u = Universe.from_candidates(
            [
                {"symbol": "FPT", "companyName": "FPT", "sector": "Tech", "exchange": "HOSE"},
                {
                    "symbol": "VNM",
                    "companyName": "Vinamilk",
                    "sector": "Consumer",
                    "exchange": "HOSE",
                },
            ],
            benchmarks=("VNINDEX", "VN30"),
        )

        ctx.set_universe(u)
        self.assertEqual(ctx.universe, u)
        self.assertEqual(ctx.expected_symbols, {"VNINDEX", "VN30", "FPT", "VNM"})
        self.assertEqual(len(ctx.candidate_stocks), 2)

        audit = ctx.update_universe_audit()
        self.assertIsNotNone(ctx.universe_scan_result)
        self.assertEqual(ctx.universe_scan_result.universe, u)
        self.assertEqual(set(audit["expected_symbols"]), {"VNINDEX", "VN30", "FPT", "VNM"})

    def test_pipeline_context_fail_fast_without_universe(self):
        from scripts.pipeline.context import PipelineContext

        ctx = PipelineContext()
        self.assertIsNone(ctx.universe)

        with self.assertRaises(ValueError):
            ctx.record_symbol_processed("FPT")

        with self.assertRaises(ValueError):
            ctx.discard_symbol_processed("FPT")

        with self.assertRaises(ValueError):
            ctx.add_exclusion("FPT", "STAGE", "CAT", "FAILED", "Reason")

        with self.assertRaises(ValueError):
            ctx.processed_symbols = {"FPT"}

    def test_legacy_candidate_stocks_isolation(self):
        from scripts.lib.vietnam_market import CANDIDATE_STOCKS, UniverseProvider

        u = UniverseProvider().get_universe()
        self.assertEqual(len(CANDIDATE_STOCKS), u.universe_size)
        self.assertEqual([c["symbol"] for c in CANDIDATE_STOCKS], list(u.candidate_symbols))


if __name__ == "__main__":
    unittest.main()
