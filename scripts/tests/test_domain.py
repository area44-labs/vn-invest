"""Unit tests for VN Invest Domain Contracts."""

from dataclasses import FrozenInstanceError

import pytest

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


@pytest.mark.unit
class TestOHLCVDataDomainContract:
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
        assert candle.date == "2026-03-31"
        assert candle.open == 50.0
        assert candle.high == 52.5
        assert candle.low == 49.5
        assert candle.close == 51.0
        assert candle.volume == 1000000.0

        data_dict = candle.to_dict()
        assert data_dict["date"] == "2026-03-31"
        assert data_dict["close"] == 51.0

        reconstructed = OHLCVData.from_dict(data_dict)
        assert reconstructed == candle

    def test_immutability(self):
        candle = OHLCVData(
            date="2026-03-31",
            open=50.0,
            high=52.5,
            low=49.5,
            close=51.0,
            volume=1000000.0,
        )
        with pytest.raises((FrozenInstanceError, AttributeError)):
            candle.close = 55.0  # type: ignore

    def test_non_positive_price_rejection(self):
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=0.0, high=52.5, low=49.5, close=51.0, volume=1000.0)
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=-5.0, low=49.5, close=51.0, volume=1000.0)

    def test_negative_volume_rejection(self):
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=49.5, close=51.0, volume=-100.0)

    def test_invalid_ohlc_relationship_rejection(self):
        # High < Low
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=48.0, low=49.5, close=50.0, volume=1000.0)

        # High < Open
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=55.0, high=52.5, low=49.5, close=50.0, volume=1000.0)

        # Low > Close
        with pytest.raises(ValueError):
            OHLCVData("2026-03-31", open=50.0, high=52.5, low=51.0, close=49.5, volume=1000.0)

    def test_empty_date_rejection(self):
        with pytest.raises(ValueError):
            OHLCVData("", open=50.0, high=52.5, low=49.5, close=51.0, volume=1000.0)

    def test_nan_and_inf_rejection(self):
        with pytest.raises(ValueError):
            OHLCVData(
                "2026-03-31", open=float("nan"), high=52.5, low=49.5, close=51.0, volume=1000.0
            )
        with pytest.raises(ValueError):
            OHLCVData(
                "2026-03-31", open=50.0, high=float("inf"), low=49.5, close=51.0, volume=1000.0
            )


@pytest.mark.unit
class TestDataQualityDomainContract:
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
        assert dq.status == "SUFFICIENT"
        assert dq.valid_row_count == 100

        d = dq.to_dict()
        assert d["status"] == "SUFFICIENT"
        assert DataQuality.from_dict(d) == dq

    def test_invalid_status_rejection(self):
        with pytest.raises(ValueError):
            DataQuality(status="UNKNOWN")

    def test_negative_valid_row_count_rejection(self):
        with pytest.raises(ValueError):
            DataQuality(status="SUFFICIENT", valid_row_count=-5)

    def test_immutability(self):
        dq = DataQuality(status="SUFFICIENT")
        with pytest.raises((FrozenInstanceError, AttributeError)):
            dq.status = "PARTIAL"  # type: ignore


@pytest.mark.unit
class TestUniverseDomainContract:
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
        assert u.universe_size == 3
        assert len(u.candidates) == 3

        u_info = u.to_info_dict()
        assert u_info["universe_type"] == "VN30"
        assert u_info["universe_size"] == 3
        assert "candidates" not in u_info

    def test_universe_candidate_valid_exchanges(self):
        for ex in ("HOSE", "HNX", "UPCOM"):
            c = UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange=ex)
            assert c.exchange == ex

            c_dict = UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech", "exchange": ex}
            )
            assert c_dict.exchange == ex

    def test_universe_candidate_strict_rejection(self):
        with pytest.raises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="", sector="Tech", exchange="HOSE")
        with pytest.raises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="  ", exchange="HOSE")
        with pytest.raises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="")
        with pytest.raises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="   ")
        with pytest.raises(ValueError):
            UniverseCandidate(symbol="ABC", company_name="Co ABC", sector="Tech", exchange="NASDAQ")

    def test_universe_candidate_from_dict_missing_exchange_rejection(self):
        with pytest.raises(ValueError):
            UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech"}
            )
        with pytest.raises(ValueError):
            UniverseCandidate.from_dict(
                {"symbol": "ABC", "company_name": "Co ABC", "sector": "Tech", "exchange": ""}
            )
        with pytest.raises(ValueError):
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
        assert "candidates" in u_dict
        assert len(u_dict["candidates"]) == 2

        reconstructed = Universe.from_dict(u_dict)
        assert reconstructed == u
        assert reconstructed.universe_size == 2
        assert reconstructed.candidates[0].symbol == "VNM"
        assert reconstructed.candidates[1].company_name == "FPT Corp"


@pytest.mark.unit
class TestTradePlanDomainContract:
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
        assert tp.current_price == 50000.0
        assert tp.position_percent == 15.0

        tp_dict = tp.to_dict()
        assert tp_dict["stop_loss"] == 47500.0
        assert TradePlan.from_dict(tp_dict) == tp

    def test_invalid_position_percent_rejection(self):
        with pytest.raises(ValueError):
            TradePlan(position_percent=-5.0)
        with pytest.raises(ValueError):
            TradePlan(position_percent=105.0)

    def test_negative_price_rejection(self):
        with pytest.raises(ValueError):
            TradePlan(current_price=-1000.0)


@pytest.mark.unit
class TestRiskAssessmentDomainContract:
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
        assert ra.liquidity_score == 85.0
        assert ra.risk_level == "MEDIUM"

        metrics_dict = ra.to_metrics_dict()
        assert "risk_level" not in metrics_dict
        assert metrics_dict["liquidity_score"] == 85.0
        assert metrics_dict["avg_value_20d"] == 150.5

        full_dict = ra.to_dict()
        assert full_dict["risk_level"] == "MEDIUM"
        assert RiskAssessment.from_dict(full_dict) == ra

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
        assert "avg_value_20d" not in metrics
        expected_keys = {"var_t25", "es_t25", "volatility_60d", "max_drawdown", "liquidity_score"}
        assert set(metrics.keys()) == expected_keys

    def test_invalid_liquidity_score_rejection(self):
        with pytest.raises(ValueError):
            RiskAssessment(liquidity_score=105.0)
        with pytest.raises(ValueError):
            RiskAssessment(liquidity_score=-1.0)

    def test_invalid_risk_level_rejection(self):
        with pytest.raises(ValueError):
            RiskAssessment(risk_level="EXTREME")


@pytest.mark.unit
class TestRecommendationDomainContract:
    """Test suite for Recommendation domain model."""

    def setup_method(self):
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
        assert d["risk_metrics"] == expected_risk_metrics
        assert "avg_value_20d" not in d["risk_metrics"]

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
        assert d["trade_plan"] == expected_trade_plan

        assert d["action"] == "AVOID"
        assert d["data_quality"] == "INSUFFICIENT"

    def test_valid_recommendation_serialization(self):
        rec_dict = self.valid_rec.to_dict()
        assert rec_dict["symbol"] == "VNM"
        assert rec_dict["action"] == "BUY"
        assert rec_dict["confidence"] == 0.82
        assert rec_dict["risk_metrics"]["liquidity_score"] == 90.0
        assert rec_dict["trade_plan"]["current_price"] == 68000.0

        reconstructed = Recommendation.from_dict(rec_dict)
        assert reconstructed.symbol == "VNM"
        assert reconstructed.signal_score == 78.5

    def test_valid_exchanges_supported(self):
        for ex in ("HOSE", "HNX", "UPCOM"):
            rec = Recommendation.from_dict({**self.valid_rec.to_dict(), "exchange": ex})
            assert rec.exchange == ex

    def test_non_string_company_name_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "company_name": None})

    def test_non_string_sector_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "sector": 123})

    def test_invalid_action_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "action": "SUPER_BUY"})

    def test_invalid_exchange_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "exchange": "NYSE"})

    def test_out_of_range_score_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "signal_score": 150.0})

    def test_out_of_range_confidence_rejection(self):
        with pytest.raises(ValueError):
            Recommendation.from_dict({**self.valid_rec.to_dict(), "confidence": 1.5})


@pytest.mark.unit
class TestPipelineResultDomainContract:
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
        assert r == recs_data
        assert m == market_data
        assert h == history_data

        # Attribute access
        assert pr.recommendations_payload == recs_data
        assert pr.universe_audit == universe_audit

        # Serialization
        pr_dict = pr.to_dict()
        assert pr_dict["market"]["market"]["regime"] == "BULL"


@pytest.mark.unit
class TestUniverseAndScanResultDomainContracts:
    """Test suite for Issue #173 Universe and UniverseScanResult contracts."""

    def test_provider_to_universe_conversion(self):
        from scripts.lib.vietnam_market import UniverseProvider

        provider = UniverseProvider()
        u = provider.get_universe()
        assert isinstance(u, Universe)
        assert u.universe_type == "VN30_MIDCAP_LEADERS"
        assert u.benchmarks == ("VNINDEX", "VN30")
        assert u.universe_size > 0
        assert "FPT" in u.candidate_symbols

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
        assert u.universe_type == "VN30_MIDCAP"
        assert u.universe_size == 2
        assert u.candidate_symbols == ("FPT", "VNM")
        assert u.candidate_symbols_set == frozenset({"FPT", "VNM"})
        assert u.benchmarks == ("VNINDEX", "VN30")
        assert u.expected_symbols == frozenset({"VNINDEX", "VN30", "FPT", "VNM"})

    def test_duplicate_symbol_handling(self):
        candidates = [
            {"symbol": "FPT", "companyName": "FPT Corp 1", "sector": "Tech", "exchange": "HOSE"},
            {"symbol": "FPT", "companyName": "FPT Corp 2", "sector": "Tech", "exchange": "HOSE"},
            {"symbol": "VNM", "companyName": "Vinamilk", "sector": "Consumer", "exchange": "HOSE"},
        ]
        u = Universe.from_candidates(candidates, universe_type="DEDUP_TEST")
        # Keeps first occurrence of FPT
        assert u.universe_size == 2
        assert u.candidate_symbols == ("FPT", "VNM")
        assert u.candidates[0].company_name == "FPT Corp 1"

    def test_explicit_vs_default_benchmarks(self):
        # Generic Universe defaults to empty benchmarks
        u_default = Universe.from_candidates([], universe_type="DEFAULT_BM")
        assert u_default.benchmarks == ()
        assert u_default.expected_symbols == frozenset()

        # Production benchmarks from UniverseProvider
        from scripts.lib.vietnam_market import UniverseProvider

        u_prod = UniverseProvider().get_universe()
        assert u_prod.benchmarks == ("VNINDEX", "VN30")
        assert "VNINDEX" in u_prod.expected_symbols
        assert "VN30" in u_prod.expected_symbols

        # Explicit custom benchmarks
        u_custom = Universe.from_candidates(
            [], universe_type="CUSTOM_BM", benchmarks=("SPX", "NDX")
        )
        assert u_custom.benchmarks == ("SPX", "NDX")
        assert u_custom.expected_symbols == frozenset({"SPX", "NDX"})

        # Explicit empty benchmarks
        u_empty_bm = Universe.from_candidates([], universe_type="EMPTY_BM", benchmarks=())
        assert u_empty_bm.benchmarks == ()
        assert u_empty_bm.expected_symbols == frozenset()

    def test_universe_scan_result_fail_fast_validation(self):
        u = Universe.from_candidates(
            [{"symbol": "FPT", "companyName": "FPT", "sector": "Tech", "exchange": "HOSE"}]
        )
        scan_res = UniverseScanResult(universe=u)
        assert isinstance(scan_res.universe, Universe)

        # Invalid universe input must raise TypeError fail-fast
        with pytest.raises(TypeError):
            UniverseScanResult(universe=u.to_dict())  # type: ignore

        with pytest.raises(TypeError):
            UniverseScanResult(universe="INVALID_UNIVERSE_STRING")  # type: ignore

        with pytest.raises(TypeError):
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

        assert updated_scan_res.universe == u2
        assert updated_scan_res.processed_symbols == ("VNM",)

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

        assert scan_res.expected_count == 5
        assert scan_res.processed_count == 3
        assert scan_res.insufficient_count == 1
        assert scan_res.missing_count == 1
        assert scan_res.invalid_count == 0
        assert scan_res.failed_count == 0
        assert scan_res.processed_ratio == pytest.approx(0.6)
        assert not scan_res.is_complete

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
        assert ctx.universe == u
        assert ctx.expected_symbols == {"VNINDEX", "VN30", "FPT", "VNM"}
        assert len(ctx.candidate_stocks) == 2

        audit = ctx.update_universe_audit()
        assert ctx.universe_scan_result is not None
        assert ctx.universe_scan_result.universe == u
        assert set(audit["expected_symbols"]) == {"VNINDEX", "VN30", "FPT", "VNM"}

    def test_pipeline_context_fail_fast_without_universe(self):
        from scripts.pipeline.context import PipelineContext

        ctx = PipelineContext()
        assert ctx.universe is None

        with pytest.raises(ValueError):
            ctx.record_symbol_processed("FPT")

        with pytest.raises(ValueError):
            ctx.discard_symbol_processed("FPT")

        with pytest.raises(ValueError):
            ctx.add_exclusion("FPT", "STAGE", "CAT", "FAILED", "Reason")

        with pytest.raises(ValueError):
            ctx.processed_symbols = {"FPT"}

    def test_legacy_candidate_stocks_isolation(self):
        import scripts.lib.vietnam_market as vnm_module
        from scripts.lib.vietnam_market import CANDIDATE_STOCKS, UniverseProvider

        u = UniverseProvider().get_universe()
        assert len(CANDIDATE_STOCKS) == u.universe_size
        assert [c["symbol"] for c in CANDIDATE_STOCKS] == list(u.candidate_symbols)

        # Modifying legacy CANDIDATE_STOCKS snapshot does not alter UniverseProvider output
        original_len = len(vnm_module.CANDIDATE_STOCKS)
        try:
            vnm_module.CANDIDATE_STOCKS.append(
                {
                    "symbol": "FAKE_MONKEYPATCH",
                    "companyName": "Fake",
                    "sector": "Fake",
                    "exchange": "HOSE",
                }
            )
            u_after = UniverseProvider().get_universe()
            assert "FAKE_MONKEYPATCH" not in u_after.candidate_symbols
            assert u_after.universe_size == u.universe_size
        finally:
            vnm_module.CANDIDATE_STOCKS = vnm_module.CANDIDATE_STOCKS[:original_len]


@pytest.mark.unit
class TestIssue173ArchitectureInvariants:
    """Regression test suite for Issue #173 architectural requirements A through H."""

    def test_a_audit_canonical_state_no_reconstruction(self):
        """A. UniverseScanResult.to_audit_dict() produces audit payload directly without Universe reconstruction."""
        u = Universe.from_candidates(
            [
                {"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"},
                {"symbol": "BBB", "companyName": "Co B", "sector": "Sec B", "exchange": "HOSE"},
            ],
            universe_type="TEST_A",
            benchmarks=("VNINDEX",),
        )
        scan_res = UniverseScanResult(
            universe=u,
            processed_symbols=("VNINDEX", "AAA"),
            failed_symbols=("BBB",),
            exclusions_map={
                "BBB": {
                    "symbol": "BBB",
                    "stage": "STOCK_FETCH",
                    "category": "PROVIDER_FAILURE",
                    "status": "FAILED",
                    "reason": "Fetch timeout",
                }
            },
        )

        audit = scan_res.to_audit_dict()
        assert audit["status"] == "DEGRADED"
        assert audit["failed_stage"] == "STOCK_FETCH"
        assert audit["expected_symbols"] == ["AAA", "BBB", "VNINDEX"]
        assert audit["processed_symbols"] == ["AAA", "VNINDEX"]
        assert audit["failed_symbols"] == ["BBB"]

    def test_b_audit_benchmark_neutrality(self):
        """B. Custom Universe does not infer benchmarks; production Universe preserves VNINDEX and VN30."""
        u_custom = Universe.from_candidates(
            [{"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"}],
            universe_type="CUSTOM",
            benchmarks=(),
        )
        scan_custom = UniverseScanResult(universe=u_custom, processed_symbols=("AAA",))
        audit_custom = scan_custom.to_audit_dict()
        assert audit_custom["expected_symbols"] == ["AAA"]
        assert "VNINDEX" not in audit_custom["expected_symbols"]
        assert "VN30" not in audit_custom["expected_symbols"]

        from scripts.lib.vietnam_market import UniverseProvider

        u_prod = UniverseProvider().get_universe()
        scan_prod = UniverseScanResult(
            universe=u_prod, processed_symbols=tuple(u_prod.expected_symbols)
        )
        audit_prod = scan_prod.to_audit_dict()
        assert "VNINDEX" in audit_prod["expected_symbols"]
        assert "VN30" in audit_prod["expected_symbols"]

    def test_c_historical_canonical_universe_flow(self):
        """C. Historical entry point creates single Universe; stages operate on context.universe."""
        from scripts.pipeline.context import PipelineContext
        from scripts.pipeline.stages import UniverseValidationStage

        cands = [{"symbol": "VNM", "companyName": "Vinamilk", "sector": "Food", "exchange": "HOSE"}]
        u_hist = Universe.from_candidates(
            cands, universe_type="HISTORICAL_SNAPSHOT", benchmarks=("VNINDEX", "VN30")
        )

        ctx = PipelineContext(is_historical=True, historical_data_as_of="2025-01-30")
        ctx.set_universe(u_hist)

        # Mismatch candidate_metadata to verify stage ignores context.candidate_metadata for expected set
        ctx.candidate_metadata = [
            {"symbol": "EXTRA_SYM", "companyName": "Extra", "sector": "Extra", "exchange": "HOSE"}
        ]

        import pandas as pd

        stage = UniverseValidationStage()
        df_dummy = pd.DataFrame({"close": [100.0]})
        ctx.data_as_of = "2025-01-30"
        ctx.df_vnindex_clean = df_dummy
        ctx.vnindex_val = {"latest_date": "2025-01-30"}
        ctx.df_vn30_clean = df_dummy
        ctx.vn30_val = {"status": "SUFFICIENT"}
        ctx.stock_data_map = {"VNM": (df_dummy, "explicit_historical_input", [])}

        stage.execute(ctx)

        assert "VNM" in ctx.processed_symbols
        assert "EXTRA_SYM" not in ctx.expected_symbols
        assert ctx.expected_symbols == frozenset({"VNINDEX", "VN30", "VNM"})

    def test_d_candidate_metadata_mismatch_universe_remains_canonical(self):
        """D. Candidate metadata mismatch does not expand expected symbols set beyond Universe."""
        from scripts.pipeline.context import PipelineContext

        u = Universe.from_candidates(
            [{"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"}],
            universe_type="CANONICAL",
            benchmarks=("VNINDEX",),
        )
        ctx = PipelineContext()
        ctx.set_universe(u)
        ctx.candidate_metadata = [
            {"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"},
            {
                "symbol": "BBB_MISMATCH",
                "companyName": "Co B",
                "sector": "Sec B",
                "exchange": "HOSE",
            },
        ]

        assert ctx.expected_symbols == {"VNINDEX", "AAA"}
        assert "BBB_MISMATCH" not in ctx.expected_symbols

    def test_e_missing_universe_stage_fail_fast(self):
        """E. Downstream stages fail fast with ValueError if executed without canonical Universe."""
        from scripts.pipeline.context import PipelineContext
        from scripts.pipeline.stages import (
            DataAcquisitionStage,
            DataValidationStage,
            MarketAnalysisStage,
            SignalRecommendationGenerationStage,
            UniverseValidationStage,
        )

        ctx = PipelineContext()
        assert ctx.universe is None

        for stage in (
            DataAcquisitionStage(),
            DataValidationStage(),
            UniverseValidationStage(),
            MarketAnalysisStage(),
            SignalRecommendationGenerationStage(),
        ):
            with pytest.raises(ValueError) as cm:
                stage.execute(ctx)
            assert "requires context.universe" in str(cm.value)

    def test_f_synchronization_identity_invariant(self):
        """F. Invariant check: context.universe and context.universe_scan_result.universe remain identical."""
        from scripts.pipeline.context import PipelineContext

        ctx = PipelineContext()
        u1 = Universe.from_candidates(
            [{"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"}],
            universe_type="U1",
        )
        ctx.set_universe(u1)

        assert ctx.universe_scan_result is not None
        assert ctx.universe is ctx.universe_scan_result.universe

        u2 = Universe.from_candidates(
            [{"symbol": "BBB", "companyName": "Co B", "sector": "Sec B", "exchange": "HOSE"}],
            universe_type="U2",
        )
        ctx.universe = u2
        assert ctx.universe is ctx.universe_scan_result.universe

    def test_g_legacy_candidate_stocks_isolation_under_monkeypatching(self):
        """G. Monkeypatching legacy CANDIDATE_STOCKS does not alter UniverseProvider or Pipeline execution."""
        import scripts.lib.vietnam_market as vnm_module
        from scripts.lib.vietnam_market import UniverseProvider

        orig_stocks = list(vnm_module.CANDIDATE_STOCKS)
        try:
            vnm_module.CANDIDATE_STOCKS = [
                {
                    "symbol": "MUTATED",
                    "companyName": "Mutated",
                    "sector": "Mutated",
                    "exchange": "HOSE",
                }
            ]

            u = UniverseProvider().get_universe()
            assert "MUTATED" not in u.candidate_symbols
            assert "FPT" in u.candidate_symbols
        finally:
            vnm_module.CANDIDATE_STOCKS = orig_stocks

    def test_h_audit_adapter_compatibility_delegates_directly(self):
        """H. build_universe_audit(scan_result=...) delegates directly without reconstructing Universe."""
        from scripts.pipeline.audit import build_universe_audit

        u = Universe.from_candidates(
            [{"symbol": "AAA", "companyName": "Co A", "sector": "Sec A", "exchange": "HOSE"}],
            universe_type="ADAPTER_TEST",
            benchmarks=("VNINDEX",),
        )
        scan_res = UniverseScanResult(universe=u, processed_symbols=("VNINDEX", "AAA"))

        audit = build_universe_audit(scan_result=scan_res)
        assert audit["status"] == "SUCCESS"
        assert audit["expected_symbols"] == ["AAA", "VNINDEX"]
        assert audit["processed_symbols"] == ["AAA", "VNINDEX"]
