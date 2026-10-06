"""Regression unit tests for provenance manifest, provenance builder, secret scanning, fail-closed validation, and artifact publisher integration."""

import os
import shutil
import tempfile
import unittest

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


class TestArtifactProvenanceSuite(unittest.TestCase):
    """Comprehensive regression tests for PR #180 artifact provenance and reproducibility manifest."""

    def setUp(self):
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

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_1_valid_provenance_manifest_dataclass_and_serialization(self):
        """1. Verify ProvenanceManifest dataclass serialization and deserialization completeness."""
        manifest = ProvenanceManifest.from_dict(self.valid_provenance)
        self.assertEqual(manifest.data_as_of, self.canonical_date)
        self.assertEqual(manifest.pipeline_version, "2.0.0")
        self.assertEqual(manifest.signal_model_version, "2.0")
        self.assertEqual(manifest.quantitative_config_version["quant_version"], "1.0.0")

        d_repr = manifest.to_dict()
        self.assertEqual(d_repr["data_as_of"], self.canonical_date)
        self.assertEqual(
            d_repr["artifacts"], ["market.json", "provenance.json", "recommendations.json"]
        )

    def test_2_provenance_builder_from_pipeline_context(self):
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

        self.assertEqual(prov_manifest.data_as_of, "2026-03-31")
        self.assertEqual(prov_manifest.signal_model_version, "2.0")
        self.assertEqual(prov_manifest.quantitative_config_version["config_hash"], "c1d2e3f4")
        self.assertEqual(sorted(prov_manifest.artifacts), sorted(batch_artifacts))

    def test_3_validate_provenance_manifest_data_as_of_mismatch_rejection(self):
        """3. Verify validate_provenance_manifest rejects mismatched data_as_of relative to canonical date."""
        bad_prov = dict(self.valid_provenance)
        bad_prov["data_as_of"] = "2026-01-01"

        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(
                bad_prov,
                batch_artifacts=["market.json", "provenance.json", "recommendations.json"],
                canonical_data_as_of="2026-03-31",
            )

        self.assertIn("does not match canonical pipeline date", str(cm.exception))

    def test_4_validate_provenance_manifest_missing_required_fields(self):
        """4. Verify missing required fields cause fail-closed rejection."""
        incomplete_prov = dict(self.valid_provenance)
        incomplete_prov.pop("signal_model_version")

        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(incomplete_prov)

        self.assertIn("missing required fields", str(cm.exception))

    def test_5_validate_provenance_manifest_malformed_version_metadata(self):
        """5. Verify malformed version metadata strings or dicts trigger validation rejection."""
        malformed = dict(self.valid_provenance)
        malformed["quantitative_config_version"] = {"quant_version": "", "config_hash": "123"}

        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(malformed)

        self.assertIn("must be a non-empty string", str(cm.exception))

    def test_6_validate_provenance_manifest_artifact_list_mismatch(self):
        """6. Verify declared artifacts list must match published batch exactly."""
        mismatched_batch = ["market.json", "provenance.json"]  # Missing recommendations.json

        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(self.valid_provenance, batch_artifacts=mismatched_batch)

        self.assertIn("does not match published batch", str(cm.exception))

    def test_7_secret_detection_scanner_rejects_credentials(self):
        """7. Verify detect_secrets_in_dict identifies forbidden keys and credential patterns."""
        secret_prov_1 = dict(self.valid_provenance)
        secret_prov_1["source_provider"] = {"api_key": "secret123", "data_source": "REAL_DATA"}

        violations_1 = detect_secrets_in_dict(secret_prov_1)
        self.assertTrue(len(violations_1) > 0)
        self.assertIn("api_key", violations_1[0])

        secret_prov_2 = dict(self.valid_provenance)
        secret_prov_2["data_quality"] = {
            "token": "AKIAIOSFODNN7EXAMPLE"  # AWS Access Key ID pattern
        }

        violations_2 = detect_secrets_in_dict(secret_prov_2)
        self.assertTrue(len(violations_2) > 0)

        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(secret_prov_1)
        self.assertIn("forbidden secrets or credentials", str(cm.exception))

    def test_8_publisher_rejects_invalid_provenance_before_transaction_start(self):
        """8. Verify provenance validation occurs BEFORE atomic transaction starts (no disk mutations)."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        bad_batch = {
            "recommendations.json": {"data_as_of": "2026-03-31", "v": 1},
            "market.json": {"data_as_of": "2026-03-31", "regime": "BULL"},
            "provenance.json": {
                "data_as_of": "2026-03-31",
                # Missing required fields...
            },
        }

        with self.assertRaises(ProvenanceValidationError):
            publisher.publish(bad_batch)

        # Confirm no target or staging files created
        self.assertFalse(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        for item in os.listdir(self.temp_dir):
            self.assertNotIn("staging", item)

    def test_9_publisher_rejects_missing_provenance_in_strict_mode(self):
        """9. Verify publisher in strict mode rejects artifact batch lacking provenance.json."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=True)

        batch_no_prov = {
            "recommendations.json": {"v": 1},
            "market.json": {"regime": "BULL"},
        }

        with self.assertRaises(ProvenanceValidationError) as cm:
            publisher.publish(batch_no_prov)

        self.assertIn("Missing required provenance manifest artifact", str(cm.exception))

    def test_10_successful_publish_with_valid_provenance(self):
        """10. Verify successful publication with valid provenance manifest."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        batch = {
            "recommendations.json": {"data_as_of": self.canonical_date, "recommendations": []},
            "market.json": {"data_as_of": self.canonical_date, "market": {}},
            "provenance.json": self.valid_provenance,
        }

        published_manifest = publisher.publish(batch)
        self.assertIn("provenance.json", published_manifest.artifacts)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "provenance.json")))

    def test_11_pipeline_stage_generates_and_validates_provenance(self):
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
        self.assertTrue(os.path.exists(prov_path))

        import json

        with open(prov_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)

        self.assertEqual(p_data["data_as_of"], self.canonical_date)
        self.assertEqual(p_data["signal_model_version"], "2.0")
        self.assertIn("provenance.json", p_data["artifacts"])

    def test_12_historical_report_pipeline_provenance_integration(self):
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
        self.assertTrue(os.path.exists(prov_path))

        import json

        with open(prov_path, "r", encoding="utf-8") as f:
            p_data = json.load(f)

        self.assertEqual(p_data["data_as_of"], target_as_of)
        self.assertEqual(p_data["source_provider"]["data_source"], "explicit_historical_input")

    def test_13_backward_compatibility_publisher_api(self):
        """13. Verify publish_artifacts_atomically supports strict_provenance=False for backward compatibility."""
        simple_batch = {"test_doc.json": {"v": 1}}

        published = publish_artifacts_atomically(
            simple_batch, target_dir=self.target_dir, strict_provenance=False
        )
        self.assertIn("test_doc.json", published.artifacts)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "test_doc.json")))

    def test_14_missing_context_data_as_of_causes_fail_closed_rejection(self):
        """14. Verify missing or None context.data_as_of raises ProvenanceValidationError without fallback."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = None

        with self.assertRaises(ProvenanceValidationError) as cm:
            ProvenanceBuilder.from_context(context)

        self.assertIn("missing valid canonical 'data_as_of'", str(cm.exception))

    def test_15_empty_or_malformed_context_data_as_of_causes_fail_closed_rejection(self):
        """15. Verify empty or malformed context.data_as_of raises ProvenanceValidationError."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        for bad_date in ("", "invalid-date", "2026/03/31", "2026-3-31"):
            context.data_as_of = bad_date
            with self.assertRaises(ProvenanceValidationError):
                ProvenanceBuilder.from_context(context)

    def test_16_conflicting_data_as_of_across_artifacts_causes_fail_closed_rejection(self):
        """16. Verify conflicting data_as_of dates across artifacts (e.g. recs=2026-10-06 vs mkt=2026-10-05) fails closed."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        # Batch where recommendations date is 2026-10-06 and market date is 2026-10-05
        conflicting_batch = {
            "recommendations.json": {"data_as_of": "2026-10-06", "recommendations": []},
            "market.json": {"data_as_of": "2026-10-05", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        with self.assertRaises(ProvenanceValidationError) as cm:
            publisher.publish(conflicting_batch)

        self.assertIn("data_as_of", str(cm.exception))

    def test_17_matching_data_as_of_across_artifacts_succeeds(self):
        """17. Verify when all artifacts contain matching data_as_of, publication succeeds cleanly."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        matching_batch = {
            "recommendations.json": {"data_as_of": "2026-10-06", "recommendations": []},
            "market.json": {"data_as_of": "2026-10-06", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        manifest = publisher.publish(matching_batch)
        self.assertIn("provenance.json", manifest.artifacts)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "provenance.json")))

    def test_18_mismatched_data_as_of_validation_occurs_before_transaction(self):
        """18. Verify mismatched data_as_of validation occurs BEFORE atomic transaction/staging starts."""
        publisher = ArtifactPublisher(target_dir=self.target_dir)

        conflicting_batch = {
            "recommendations.json": {"data_as_of": "2026-10-06", "recommendations": []},
            "market.json": {"data_as_of": "2026-10-05", "market": {}},
            "provenance.json": {
                **self.valid_provenance,
                "data_as_of": "2026-10-06",
            },
        }

        with self.assertRaises(ProvenanceValidationError):
            publisher.publish(conflicting_batch)

        # Confirm no target file or staging directory was created
        self.assertFalse(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        for item in os.listdir(self.temp_dir):
            self.assertNotIn("staging", item)

    def test_19_empty_nested_structures_cause_fail_closed_rejection(self):
        """19. Verify passing empty dicts {} for source_provider, universe, or data_quality fails closed."""
        for field in ("source_provider", "universe", "data_quality"):
            bad_prov = dict(self.valid_provenance)
            bad_prov[field] = {}
            with self.assertRaises(ProvenanceValidationError) as cm:
                validate_provenance_manifest(bad_prov)
            self.assertIn("must be a non-empty dict", str(cm.exception))

    def test_20_missing_required_nested_keys_cause_fail_closed_rejection(self):
        """20. Verify missing required nested keys (data_source, universe_type, status, processed_ratio) fail closed."""
        # Missing data_source
        p1 = dict(self.valid_provenance)
        p1["source_provider"] = {"other_key": "val"}
        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p1)
        self.assertIn("data_source", str(cm.exception))

        # Missing universe_type
        p2 = dict(self.valid_provenance)
        p2["universe"] = {"other_key": "val"}
        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p2)
        self.assertIn("universe_type", str(cm.exception))

        # Missing status in data_quality
        p3 = dict(self.valid_provenance)
        p3["data_quality"] = {"processed_ratio": 1.0}
        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p3)
        self.assertIn("status", str(cm.exception))

        # Missing processed_ratio in data_quality
        p4 = dict(self.valid_provenance)
        p4["data_quality"] = {"status": "SUCCESS"}
        with self.assertRaises(ProvenanceValidationError) as cm:
            validate_provenance_manifest(p4)
        self.assertIn("processed_ratio", str(cm.exception))

    def test_21_malformed_nested_field_values_cause_fail_closed_rejection(self):
        """21. Verify malformed values for status or out-of-bound processed_ratio fail closed."""
        # Empty status string
        p1 = dict(self.valid_provenance)
        p1["data_quality"] = {"status": "  ", "processed_ratio": 1.0}
        with self.assertRaises(ProvenanceValidationError):
            validate_provenance_manifest(p1)

        # processed_ratio > 1.0
        p2 = dict(self.valid_provenance)
        p2["data_quality"] = {"status": "SUCCESS", "processed_ratio": 1.5}
        with self.assertRaises(ProvenanceValidationError):
            validate_provenance_manifest(p2)

        # processed_ratio < 0.0
        p3 = dict(self.valid_provenance)
        p3["data_quality"] = {"status": "SUCCESS", "processed_ratio": -0.1}
        with self.assertRaises(ProvenanceValidationError):
            validate_provenance_manifest(p3)

    def test_22_from_dict_strictly_enforces_validation_contract(self):
        """22. Verify ProvenanceManifest.from_dict() validates the payload and rejects invalid inputs."""
        invalid_payload = dict(self.valid_provenance)
        invalid_payload["data_quality"] = {}  # Empty dict

        with self.assertRaises(ProvenanceValidationError):
            ProvenanceManifest.from_dict(invalid_payload)

    def test_23_pipeline_version_propagates_from_canonical_config_source(self):
        """23. Verify PIPELINE_VERSION matches canonical config source and propagates to provenance."""
        from scripts.lib.config import PIPELINE_VERSION

        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        self.assertEqual(manifest.pipeline_version, PIPELINE_VERSION)
        self.assertEqual(manifest.pipeline_version, "2.0.0")

    def test_24_pipeline_version_and_signal_model_version_are_independent(self):
        """24. Verify pipeline_version and signal_model_version are distinct independent metadata fields."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        self.assertEqual(manifest.pipeline_version, "2.0.0")
        self.assertEqual(manifest.signal_model_version, "2.0")
        self.assertNotEqual(manifest.pipeline_version, manifest.signal_model_version)

    def test_25_changing_model_version_does_not_change_pipeline_version(self):
        """25. Verify modifying signal_model_version in payload does not alter pipeline_version."""
        context = PipelineContext(
            generated_dir=self.target_dir,
            reference_date="2026-03-31T00:00:00Z",
        )
        context.data_as_of = "2026-03-31"
        context.recommendations_payload = {"signal_model_version": "2.1-custom"}

        builder = ProvenanceBuilder.from_context(context)
        manifest = builder.build()

        self.assertEqual(manifest.pipeline_version, "2.0.0")
        self.assertEqual(manifest.signal_model_version, "2.1-custom")


if __name__ == "__main__":
    unittest.main()
