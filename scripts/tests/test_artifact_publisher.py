"""Unit tests for ArtifactPublisher, ArtifactManifest, atomic publishing transactions, and rollback/recovery."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.artifacts import (
    ArtifactLock,
    ArtifactManifest,
    ArtifactManifestBuilder,
    ArtifactPublisher,
    recover_interrupted_publish,
)
from scripts.pipeline import (
    ArtifactPublishingStage,
    PipelineContext,
)


class TestArtifactPublisherSuite(unittest.TestCase):
    """Independent unit tests for ArtifactPublisher, manifest generation, schema validation, atomic transactions, recovery, and pipeline integration."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_dir = os.path.join(self.temp_dir, "generated")
        os.makedirs(self.target_dir, exist_ok=True)
        self.sample_artifacts = {
            "recommendations.json": {"v": 1, "status": "ok"},
            "market.json": {"regime": "BULL"},
            "history/2026-03-31.json": {"data": "historical"},
        }

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_manifest_builder_and_manifest_generation(self):
        """Verify ArtifactManifestBuilder constructs immutable ArtifactManifest with metadata and history index."""
        builder = ArtifactManifestBuilder(target_dir=self.target_dir)
        builder.add_artifact("recommendations.json", {"a": 1})
        builder.add_artifact("market.json", {"b": 2})

        # Test history index building inside manifest
        builder.build_history_index("2026-03-31", generated_at="2026-03-31T00:00:00Z")

        manifest = builder.build()
        self.assertIsInstance(manifest, ArtifactManifest)
        self.assertEqual(len(manifest.artifacts), 3)
        self.assertIn("recommendations.json", manifest.artifacts)
        self.assertIn("market.json", manifest.artifacts)
        self.assertIn("history/index.json", manifest.artifacts)

        m_dict = manifest.to_dict()
        self.assertEqual(m_dict["artifact_count"], 3)
        self.assertIn("recommendations.json", m_dict["paths"])

    def test_manifest_failure_halts_publishing_without_silent_reset(self):
        """Verify corrupt history/index.json causes build_history_index to fail closed without silent date reset."""
        hist_dir = os.path.join(self.target_dir, "history")
        os.makedirs(hist_dir, exist_ok=True)
        index_file = os.path.join(hist_dir, "index.json")

        with open(index_file, "w", encoding="utf-8") as f:
            f.write("CORRUPT_JSON_DATA {{{")

        builder = ArtifactManifestBuilder(target_dir=self.target_dir)
        with self.assertRaises(ValueError) as cm:
            builder.build_history_index("2026-03-31")

        self.assertIn("invalid JSON", str(cm.exception))

    def test_schema_validation_before_publish(self):
        """Verify schema validation occurs before publishing and rejects invalid payloads before disk mutation."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)

        invalid_artifacts = {
            "recommendations.json": {
                # Non-dict or invalid numeric
                "recommendations": [{"symbol": "AAA", "signal_score": 150.0}]
            }
        }

        with self.assertRaises(ValueError) as cm:
            publisher.publish(invalid_artifacts)

        self.assertIn("out of range", str(cm.exception))
        # Ensure no artifacts were created in target_dir
        self.assertFalse(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))

    def test_validation_failure_prevents_transaction_start(self):
        """Verify validation failure prevents transaction start (no staging dir, no backup, no state file)."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)

        invalid_artifacts = {
            "recommendations.json": {
                "recommendations": [
                    {
                        "symbol": "AAA",
                        "company_name": "Co A",
                        "exchange": "HOSE",
                        "sector": "Tech",
                        "action": "BUY",
                        "signal_score": 999.0,  # Invalid score out of bounds
                    }
                ]
            }
        }

        with self.assertRaises(ValueError):
            publisher.publish(invalid_artifacts)

        # Check no staging directory or state file was created
        for item in os.listdir(self.temp_dir):
            self.assertNotIn("staging", item)
            self.assertNotIn("bak", item)
            self.assertNotIn("_txn", item)

    def test_invalid_partial_artifacts_not_published(self):
        """Verify that if any artifact in a batch is invalid, no partial artifacts are published."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)

        valid_market = {"data_as_of": "2026-03-31", "market": {"regime": "BULL"}}
        invalid_rec = {"recommendations": [{"symbol": "AAA", "signal_score": -10.0}]}

        batch = {
            "market.json": valid_market,
            "recommendations.json": invalid_rec,
        }

        with self.assertRaises(ValueError):
            publisher.publish(batch)

        # Neither market.json nor recommendations.json should be published
        self.assertFalse(os.path.exists(os.path.join(self.target_dir, "market.json")))
        self.assertFalse(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))

    def test_publisher_always_creates_and_consumes_artifact_manifest(self):
        """Verify ArtifactPublisher creates and consumes ArtifactManifest when given a dict batch."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)
        batch = {
            "recommendations.json": {"recommendations": []},
            "market.json": {"market": {}},
        }

        published_manifest = publisher.publish(batch)
        self.assertIsInstance(published_manifest, ArtifactManifest)
        self.assertEqual(published_manifest.target_dir, self.target_dir)
        self.assertIn("recommendations.json", published_manifest.artifacts)

    def test_successful_publish_and_replacement(self):
        """Verify successful atomic publish and subsequent replacement of existing artifacts."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)

        # 1. First publish
        batch_v1 = {
            "recommendations.json": {"recommendations": []},
            "market.json": {"market": {"regime": "BULL"}},
        }
        publisher.publish(batch_v1)

        rec_path = os.path.join(self.target_dir, "recommendations.json")
        self.assertTrue(os.path.exists(rec_path))

        # 2. Second publish replacing existing
        batch_v2 = {
            "recommendations.json": {"recommendations": []},
            "market.json": {"market": {"regime": "BEAR"}},
        }
        publisher.publish(batch_v2)

        mkt_path = os.path.join(self.target_dir, "market.json")
        with open(mkt_path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["market"]["regime"], "BEAR")

    def test_successful_publish_leaves_no_leftover_artifacts(self):
        """Verify successful transaction leaves no staging, backup, or journal state files in parent dir."""
        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)
        publisher.publish(self.sample_artifacts)

        # Verify parent directory contains ONLY target_dir and no .generated_txn.json or generated_bak
        items = [i for i in os.listdir(self.temp_dir) if not i.endswith(".lock")]
        self.assertEqual(items, ["generated"])

    def test_staging_failure_triggers_clean_rollback(self):
        """Verify failure during staging phase rolls back cleanly without leaving staging directory."""
        initial_file = os.path.join(self.target_dir, "recommendations.json")
        with open(initial_file, "w", encoding="utf-8") as f:
            f.write('{"v": "initial_data"}\n')

        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)
        bad_batch = {"bad_file.json": {"bad": object()}}  # Non-serializable object fails json.dump

        with self.assertRaises(TypeError):
            publisher.publish(bad_batch)

        # Target preserved, no staging directory left behind
        with open(initial_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "initial_data"}\n')

        items = [i for i in os.listdir(self.temp_dir) if not i.endswith(".lock")]
        self.assertEqual(items, ["generated"])

    def test_atomic_transaction_and_rollback_recovery(self):
        """Verify atomic transaction rollback restores original target when transaction fails during execute_publish."""
        initial_file = os.path.join(self.target_dir, "recommendations.json")
        with open(initial_file, "w", encoding="utf-8") as f:
            f.write('{"v": "original_valid"}\n')

        publisher = ArtifactPublisher(target_dir=self.target_dir, strict_provenance=False)

        real_replace = os.replace

        def failing_replace(src, dst):
            if "staging" in str(src):
                raise OSError("Simulated replace failure during commit")
            return real_replace(src, dst)

        with patch("os.replace", side_effect=failing_replace), self.assertRaises(OSError):
            publisher.publish(self.sample_artifacts)

        # Verify original target content is preserved
        with open(initial_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "original_valid"}\n')

    def test_interrupted_transaction_idempotent_recovery(self):
        """Verify recovery from interrupted transaction is idempotent."""
        bak_dir = f"{self.target_dir}_bak"
        os.makedirs(bak_dir, exist_ok=True)
        bak_file = os.path.join(bak_dir, "recommendations.json")
        with open(bak_file, "w", encoding="utf-8") as f:
            f.write('{"v": "backed_up_good"}\n')

        shutil.rmtree(self.target_dir, ignore_errors=True)

        recover_interrupted_publish(self.target_dir)
        recover_interrupted_publish(self.target_dir)

        rec_file = os.path.join(self.target_dir, "recommendations.json")
        self.assertTrue(os.path.exists(rec_file))
        with open(rec_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "backed_up_good"}\n')

    def test_backward_compatibility_re_export(self):
        """Verify backward compatibility of imports from scripts.pipeline.publishing."""
        from scripts.pipeline.publishing import ArtifactLock as LegacyLock
        from scripts.pipeline.publishing import ArtifactPublisher as LegacyPublisher
        from scripts.pipeline.publishing import publish_artifacts_atomically as legacy_publish

        self.assertIs(LegacyPublisher, ArtifactPublisher)
        self.assertIs(LegacyLock, ArtifactLock)

        # Test legacy function execution
        legacy_publish({"test.json": {"a": 1}}, target_dir=self.target_dir, strict_provenance=False)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "test.json")))

    def test_pipeline_stage_artifact_publisher_integration(self):
        """Verify ArtifactPublishingStage uses ArtifactPublisher cleanly during pipeline execution."""
        context = PipelineContext(publish_artifacts=True, generated_dir=self.target_dir)
        context.data_as_of = "2026-03-31"
        context.generated_at = "2026-03-31T00:00:00Z"
        context.recommendations_payload = {"recommendations": []}
        context.market_payload = {"market": {}}
        context.history_payload = context.recommendations_payload
        context.monitoring_dict = {"status": "PASS"}

        stage = ArtifactPublishingStage()
        stage.execute(context)

        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "market.json")))
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "monitoring.json")))
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "history", "2026-03-31.json")))
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "history", "index.json")))


if __name__ == "__main__":
    unittest.main()
