"""Regression unit tests for provenance manifest, provenance builder, secret scanning, fail-closed validation, and artifact publisher integration."""

import os
import shutil
import tempfile

import pytest

from scripts.artifacts import (
    ArtifactPublisher,
    ProvenanceBuilder,
    ProvenanceManifest,
    ProvenanceValidationError,
    detect_secrets_in_dict,
    publish_artifacts_atomically,
    validate_provenance_manifest,
)
from scripts.pipeline import (
    ArtifactPublishingStage,
    PipelineContext,
    generate_historical_report,
)


@pytest.mark.unit
class TestArtifactProvenanceSuite:
    """Comprehensive regression tests for PR #180 artifact provenance and reproducibility manifest."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_dir = os.path.join(self.temp_dir, "generated")
        os.makedirs(self.target_dir, exist_ok=True)

        self.canonical_date = "2026-03-31"
        self.valid_provenance = {
            "data_as_of": self.canonical_date,
            "generated_at": "2026-03-31T12:00:00+00:00",
            "pipeline_version": "2.0.0",
            "signal_model_version": "2.0",
            "quantitative_config_version": {
                "quant_version": "1.0.0",
                "config_hash": "a1b2c3d4e5f6",
            },
            "schema_version": "2.0",
            "source_provider": {
                "data_source": "REAL_DATA",
                "vn_source": "REAL_DATA",
                "vn30_source": "REAL_DATA",
            },
            "universe": {
                "universe_type": "MARKET",
                "expected_symbols_count": 8,
            },
            "artifacts": [
                "market.json",
                "provenance.json",
                "recommendations.json",
            ],
            "data_quality": {
                "status": "SUCCESS",
                "processed_ratio": 1.0,
                "processed_count": 8,
            },
        }

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_valid_provenance_manifest_dataclass_and_serialization(self):
        """1. Verify ProvenanceManifest dataclass serialization and deserialization completeness."""
        manifest = ProvenanceManifest.from_dict(self.valid_provenance)
        assert manifest.data_as_of == self.canonical_date
        assert manifest.pipeline_version == "2.0.0"
        assert manifest.signal_model_version == "2.0"
        assert manifest.quantitative_config_version["quant_version"] == "1.0.0"

        d_repr = manifest.to_dict()
        assert d_repr["data_as_of"] == self.canonical_date
        assert d_repr["artifacts"] == ["market.json", "provenance.json", "recommendations.json"]

    def test_provenance_builder_from_pipeline_context(self):
        """2. Verify ProvenanceBuilder extracts exact context metadata without duplicate sources of truth."""
        from scripts.domain.universe import Universe, UniverseCandidate

        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"
        cand = UniverseCandidate(symbol="AAA", company_name="Co A", sector="Tech", exchange="HOSE")
        context.universe = Universe(universe_type="MARKET", candidates=(cand,))
        context.record_symbol_processed("AAA")
        context.recommendations_payload = {
            "signal_model_version": "2.0",
            "quant_version": "1.0.0",
            "config_hash": "c1d2e3f4",
            "schema_version": "2.0",
            "universe_info": context.universe.to_info_dict(),
        }
        context.update_universe_audit()

        batch_artifacts = ["recommendations.json", "market.json", "provenance.json"]
        builder = ProvenanceBuilder.from_context(context, batch_artifacts=batch_artifacts)
        prov_manifest = builder.build()

        assert prov_manifest.data_as_of == "2026-03-31"
        assert prov_manifest.signal_model_version == "2.0"
        assert prov_manifest.quantitative_config_version["config_hash"] == "c1d2e3f4"
        assert sorted(prov_manifest.artifacts) == sorted(batch_artifacts)

    def test_validate_provenance_manifest_data_as_of_mismatch_rejection(self):
        """3. Verify validate_provenance_manifest rejects mismatched data_as_of relative to canonical date."""
        bad_prov = dict(self.valid_provenance)
        bad_prov["data_as_of"] = "2026-01-01"

        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(
                bad_prov,
                batch_artifacts=["market.json", "provenance.json", "recommendations.json"],
                canonical_data_as_of="2026-03-31",
            )

        assert "does not match canonical pipeline date" in str(cm.value)

    def test_validate_provenance_manifest_missing_required_fields(self):
        """4. Verify missing required fields cause fail-closed rejection."""
        incomplete_prov = dict(self.valid_provenance)
        incomplete_prov.pop("signal_model_version")

        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(incomplete_prov)

        assert "missing required fields" in str(cm.value)

    def test_validate_provenance_manifest_malformed_version_metadata(self):
        """5. Verify malformed version metadata strings or dicts trigger validation rejection."""
        malformed = dict(self.valid_provenance)
        malformed["quantitative_config_version"] = {"quant_version": "", "config_hash": "123"}

        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(malformed)

        assert "must be a non-empty string" in str(cm.value)

    def test_validate_provenance_manifest_artifact_list_mismatch(self):
        """6. Verify declared artifacts list must match published batch exactly."""
        mismatched_batch = ["market.json", "provenance.json"]  # Missing recommendations.json

        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(self.valid_provenance, batch_artifacts=mismatched_batch)

        assert "does not match published batch" in str(cm.value)

    def test_secret_detection_scanner_rejects_credentials(self):
        """7. Verify detect_secrets_in_dict identifies forbidden keys and credential patterns."""
        secret_prov_1 = dict(self.valid_provenance)
        secret_prov_1["source_provider"] = {"api_key": "secret123", "data_source": "REAL_DATA"}

        violations_1 = detect_secrets_in_dict(secret_prov_1)
        assert len(violations_1) > 0
        assert "api_key" in violations_1[0]

        secret_prov_2 = dict(self.valid_provenance)
        secret_prov_2["data_quality"] = {
            "token": "AKIAIOSFODNN7EXAMPLE"  # AWS Access Key ID pattern
        }

        violations_2 = detect_secrets_in_dict(secret_prov_2)
        assert len(violations_2) > 0

        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(secret_prov_1)
        assert "forbidden secrets or credentials" in str(cm.value)

    def test_publisher_rejects_invalid_provenance_before_transaction_start(self):
        """8. Verify provenance validation occurs BEFORE atomic transaction starts (no disk mutations)."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        valid_rec = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-03-31T00:00:00Z",
            "data_as_of": "2026-03-31",
            "source_date": "2026-03-31",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
            "summary": {
                "total_scanned": 0,
                "buy_count": 0,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [],
        }

        bad_batch = {
            "recommendations.json": valid_rec,
            "market.json": {"schema_version": "2.0", "data_as_of": "2026-03-31", "market": {}},
            "provenance.json": {
                "data_as_of": "2026-03-31",
                # Missing required fields...
            },
        }

        with pytest.raises(ProvenanceValidationError):
            publisher.publish(bad_batch)

        # Confirm no target or staging files created
        assert not os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        for item in os.listdir(self.temp_dir):
            assert "staging" not in item

    def test_publisher_rejects_missing_provenance_in_strict_mode(self):
        """9. Verify publisher in strict mode rejects artifact batch lacking provenance.json."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=True)

        valid_rec = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": "2026-03-31T00:00:00Z",
            "data_as_of": "2026-03-31",
            "source_date": "2026-03-31",
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
            "summary": {
                "total_scanned": 0,
                "buy_count": 0,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [],
        }

        batch_no_prov = {
            "recommendations.json": valid_rec,
            "market.json": {"schema_version": "2.0", "market": {}},
        }

        with pytest.raises(ProvenanceValidationError) as cm:
            publisher.publish(batch_no_prov)

        assert "Missing required provenance manifest artifact" in str(cm.value)

    def test_successful_publish_with_valid_provenance(self):
        """10. Verify successful publication with valid provenance manifest."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        valid_rec = {
            "schema_version": "2.0",
            "signal_model_version": "2.0",
            "generated_at": f"{self.canonical_date}T00:00:00Z",
            "data_as_of": self.canonical_date,
            "source_date": self.canonical_date,
            "market": {
                "regime": "BULL",
                "confidence": 0.9,
                "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
            },
            "summary": {
                "total_scanned": 0,
                "buy_count": 0,
                "watch_count": 0,
                "hold_count": 0,
                "sell_count": 0,
                "avoid_count": 0,
            },
            "recommendations": [],
        }

        batch = {
            "recommendations.json": valid_rec,
            "market.json": {
                "schema_version": "2.0",
                "data_as_of": self.canonical_date,
                "market": {},
            },
            "provenance.json": self.valid_provenance,
        }

        published_manifest = publisher.publish(batch)
        assert "provenance.json" in published_manifest.artifacts
        assert os.path.exists(os.path.join(self.target_dir, "provenance.json"))

    def test_pipeline_stage_generates_and_validates_provenance(self):
        """11. Verify ArtifactPublishingStage generates and validates provenance.json in pipeline."""
        from scripts.domain import Recommendation, RiskAssessment, TradePlan
        from scripts.domain.universe import Universe, UniverseCandidate

        context = PipelineContext(
            publish_artifacts=True,
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = self.canonical_date
        context.source_date = self.canonical_date
        context.final_market_regime = {
            "regime": "BULL",
            "confidence": 0.8,
            "metrics": {
                "vnindex_value": 1200.0,
                "vnindex_change_pct": 0.5,
                "market_breadth_ratio": 0.5,
            },
        }
        cand = UniverseCandidate(symbol="AAA", company_name="Co A", sector="Tech", exchange="HOSE")
        context.universe = Universe(universe_type="MARKET", candidates=(cand,))
        context.record_symbol_processed("AAA")

        rec = Recommendation(
            symbol="AAA",
            company_name="Co A",
            exchange="HOSE",
            sector="Tech",
            action="HOLD",
            signal_score=50.0,
            risk_adjusted_score=50.0,
            confidence=0.8,
            risk_level="MEDIUM",
            expected_return={
                "expected_return_5d": 0.0,
                "expected_return_10d": 0.0,
                "expected_return_20d": 0.0,
            },
            risk_metrics=RiskAssessment(
                var_t25=-0.05,
                es_t25=-0.07,
                volatility_60d=0.2,
                max_drawdown=-0.1,
                liquidity_score=70.0,
            ),
            trade_plan=TradePlan(
                current_price=10.0,
                entry_low=9.5,
                entry_high=10.5,
                stop_loss=9.0,
                tp1=11.0,
                tp2=12.0,
                risk_reward=1.5,
                position_percent=10.0,
            ),
            reasons=["Neutral trend"],
            warnings=[],
            invalidation=[],
            model_version="2.0",
            data_quality="SUFFICIENT",
        )
        context.scanned_recs = [rec]
        context.build_payloads()
        context.monitoring_dict = {"status": "PASS", "checks": []}

        stage = ArtifactPublishingStage()
        stage.execute(context)

        prov_path = os.path.join(self.target_dir, "provenance.json")
        assert os.path.exists(prov_path)

        import json

        with open(prov_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)

        assert p_data["data_as_of"] == self.canonical_date
        assert p_data["signal_model_version"] == "2.0"
        assert "provenance.json" in p_data["artifacts"]

    def test_historical_report_pipeline_provenance_integration(self):
        """12. Verify generate_historical_report creates valid traceable provenance artifact."""
        import pandas as pd

        dates = pd.date_range("2026-01-01", periods=60, freq="D")
        df_vn = pd.DataFrame(
            {
                "date": dates,
                "open": 1200.0,
                "high": 1210.0,
                "low": 1190.0,
                "close": 1205.0,
                "volume": 1000000.0,
            }
        )
        df_st = df_vn.copy()

        universe_map = {"VNINDEX": df_vn, "VN30": df_vn, "AAA": df_st}
        cands = [
            {
                "symbol": "AAA",
                "companyName": "Co A",
                "sector": "Tech",
                "exchange": "HOSE",
            }
        ]

        target_as_of = "2026-02-15"

        generate_historical_report(
            data_as_of=target_as_of,
            universe_stock_map=universe_map,
            df_vnindex=df_vn,
            df_vn30=df_vn,
            candidate_metadata=cands,
            data_source="explicit_historical_input",
            generated_dir=self.target_dir,
            publish_artifacts=True,
        )

        prov_path = os.path.join(self.target_dir, "provenance.json")
        assert os.path.exists(prov_path)

        import json

        with open(prov_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)

        assert p_data["data_as_of"] == target_as_of
        assert p_data["source_provider"]["data_source"] == "explicit_historical_input"

    def test_backward_compatibility_publisher_api(self):
        """13. Verify publish_artifacts_atomically supports strict_provenance=False for backward compatibility."""
        simple_batch = {"test_doc.json": {"v": 1}}

        published = publish_artifacts_atomically(
            simple_batch, target_dir=self.target_dir, strict_provenance=False
        )
        assert "test_doc.json" in published.artifacts
        assert os.path.exists(os.path.join(self.target_dir, "test_doc.json"))

    def test_missing_context_data_as_of_causes_fail_closed_rejection(self):
        """14. Verify missing or None context.data_as_of raises ProvenanceValidationError without fallback."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = None

        with pytest.raises(ProvenanceValidationError) as cm:
            ProvenanceBuilder.from_context(context)

        assert "missing valid canonical 'data_as_of'" in str(cm.value)

    def test_empty_or_malformed_context_data_as_of_causes_fail_closed_rejection(self):
        """15. Verify empty or malformed context.data_as_of raises ProvenanceValidationError."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        for bad_date in ("", "invalid-date", "2026/03/31", "2026-3-31"):
            context.data_as_of = bad_date
            with pytest.raises(ProvenanceValidationError):
                ProvenanceBuilder.from_context(context)

    def test_conflicting_data_as_of_across_artifacts_causes_fail_closed_rejection(self):
        """16. Verify conflicting data_as_of dates across artifacts (e.g. recs=2026-10-06 vs mkt=2026-10-05) fails closed."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        def _make_rec_payload(d_str):
            return {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": f"{d_str}T00:00:00Z",
                "data_as_of": d_str,
                "source_date": d_str,
                "market": {
                    "regime": "BULL",
                    "confidence": 0.9,
                    "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
                },
                "summary": {
                    "total_scanned": 0,
                    "buy_count": 0,
                    "watch_count": 0,
                    "hold_count": 0,
                    "sell_count": 0,
                    "avoid_count": 0,
                },
                "recommendations": [],
            }

        # Batch where recommendations date is 2026-10-06 and market date is 2026-10-05
        conflicting_batch = {
            "recommendations.json": _make_rec_payload("2026-10-06"),
            "market.json": {"schema_version": "2.0", "data_as_of": "2026-10-05", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        with pytest.raises(ProvenanceValidationError) as cm:
            publisher.publish(conflicting_batch)

        assert "data_as_of" in str(cm.value)

    def test_matching_data_as_of_across_artifacts_succeeds(self):
        """17. Verify when all artifacts contain matching data_as_of, publication succeeds cleanly."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        def _make_rec_payload(d_str):
            return {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": f"{d_str}T00:00:00Z",
                "data_as_of": d_str,
                "source_date": d_str,
                "market": {
                    "regime": "BULL",
                    "confidence": 0.9,
                    "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
                },
                "summary": {
                    "total_scanned": 0,
                    "buy_count": 0,
                    "watch_count": 0,
                    "hold_count": 0,
                    "sell_count": 0,
                    "avoid_count": 0,
                },
                "recommendations": [],
            }

        matching_batch = {
            "recommendations.json": _make_rec_payload("2026-10-06"),
            "market.json": {"schema_version": "2.0", "data_as_of": "2026-10-06", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        manifest = publisher.publish(matching_batch)
        assert "provenance.json" in manifest.artifacts
        assert os.path.exists(os.path.join(self.target_dir, "provenance.json"))

    def test_mismatched_data_as_of_validation_occurs_before_transaction(self):
        """18. Verify mismatched data_as_of validation occurs BEFORE atomic transaction/staging starts."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        def _make_rec_payload(d_str):
            return {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": f"{d_str}T00:00:00Z",
                "data_as_of": d_str,
                "source_date": d_str,
                "market": {
                    "regime": "BULL",
                    "confidence": 0.9,
                    "metrics": {"vnindex_value": 1250.0, "vnindex_change_pct": 0.01},
                },
                "summary": {
                    "total_scanned": 0,
                    "buy_count": 0,
                    "watch_count": 0,
                    "hold_count": 0,
                    "sell_count": 0,
                    "avoid_count": 0,
                },
                "recommendations": [],
            }

        conflicting_batch = {
            "recommendations.json": _make_rec_payload("2026-10-06"),
            "market.json": {"schema_version": "2.0", "data_as_of": "2026-10-05", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        with pytest.raises(ProvenanceValidationError):
            publisher.publish(conflicting_batch)

        # Confirm no target file or staging directory was created
        assert not os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        for item in os.listdir(self.temp_dir):
            assert "staging" not in item

    def test_empty_nested_structures_cause_fail_closed_rejection(self):
        """19. Verify passing empty dicts {} for source_provider, universe, or data_quality fails closed."""
        for field in ("source_provider", "universe", "data_quality"):
            bad_prov = dict(self.valid_provenance)
            bad_prov[field] = {}
            with pytest.raises(ProvenanceValidationError) as cm:
                validate_provenance_manifest(bad_prov)
            assert "must be a non-empty dict" in str(cm.value)

    def test_missing_required_nested_keys_cause_fail_closed_rejection(self):
        """20. Verify missing required nested keys (data_source, universe_type, status, processed_ratio) fail closed."""
        # Missing data_source
        p1 = dict(self.valid_provenance)
        p1["source_provider"] = {"other_key": "val"}
        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p1)
        assert "data_source" in str(cm.value)

        # Missing universe_type
        p2 = dict(self.valid_provenance)
        p2["universe"] = {"other_key": "val"}
        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p2)
        assert "universe_type" in str(cm.value)

        # Missing status in data_quality
        p3 = dict(self.valid_provenance)
        p3["data_quality"] = {"processed_ratio": 1.0}
        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p3)
        assert "status" in str(cm.value)

        # Missing processed_ratio in data_quality
        p4 = dict(self.valid_provenance)
        p4["data_quality"] = {"status": "SUCCESS"}
        with pytest.raises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p4)
        assert "processed_ratio" in str(cm.value)

    def test_malformed_nested_field_values_cause_fail_closed_rejection(self):
        """21. Verify malformed values for status or out-of-bound processed_ratio fail closed."""
        # Empty status string
        p1 = dict(self.valid_provenance)
        p1["data_quality"] = {"status": "  ", "processed_ratio": 1.0}
        with pytest.raises(ProvenanceValidationError):
            validate_provenance_manifest(p1)

        # processed_ratio > 1.0
        p2 = dict(self.valid_provenance)
        p2["data_quality"] = {"status": "SUCCESS", "processed_ratio": 1.5}
        with pytest.raises(ProvenanceValidationError):
            validate_provenance_manifest(p2)

        # processed_ratio < 0.0
        p3 = dict(self.valid_provenance)
        p3["data_quality"] = {"status": "SUCCESS", "processed_ratio": -0.1}
        with pytest.raises(ProvenanceValidationError):
            validate_provenance_manifest(p3)

    def test_from_dict_strictly_enforces_validation_contract(self):
        """22. Verify ProvenanceManifest.from_dict() validates the payload and rejects invalid inputs."""
        invalid_payload = dict(self.valid_provenance)
        invalid_payload["data_quality"] = {}  # Empty dict

        with pytest.raises(ProvenanceValidationError):
            ProvenanceManifest.from_dict(invalid_payload)

    def test_pipeline_version_propagates_from_canonical_config_source(self):
        """23. Verify PIPELINE_VERSION matches canonical config source and propagates to provenance."""
        from scripts.pipeline.constants import PIPELINE_VERSION

        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"
        context.recommendations_payload = {"schema_version": "2.0"}

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        assert manifest.pipeline_version == PIPELINE_VERSION
        assert manifest.pipeline_version == "2.0.0"

    def test_pipeline_version_and_signal_model_version_are_independent(self):
        """24. Verify pipeline_version and signal_model_version are distinct independent metadata fields."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"
        context.recommendations_payload = {"schema_version": "2.0"}

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        assert manifest.pipeline_version == "2.0.0"
        assert manifest.signal_model_version == "2.0"
        assert manifest.pipeline_version != manifest.signal_model_version

    def test_changing_model_version_does_not_change_pipeline_version(self):
        """Verify modifying signal_model_version in payload does not alter pipeline_version."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"
        context.recommendations_payload = {
            "schema_version": "2.0",
            "signal_model_version": "2.1-custom",
        }

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        assert manifest.pipeline_version == "2.0.0"
        assert manifest.signal_model_version == "2.1-custom"
