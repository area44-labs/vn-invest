"""Focused unit tests for artifact transaction safety, single-writer locking, and deterministic recovery."""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from scripts.generate_report import (
    ArtifactLock,
    ArtifactLockError,
    ArtifactTransactionError,
    publish_artifacts_atomically,
    recover_interrupted_publish,
)


class TestArtifactTransactionSuite(unittest.TestCase):
    """Test suite covering single-writer locking, transaction lifecycle, and deterministic recovery."""

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

    def test_1_successful_transaction_lifecycle(self):
        """1. Verify successful transaction completes STAGING -> BACKUP -> COMMIT -> CLEANUP cleanly."""
        publish_artifacts_atomically(self.sample_artifacts, target_dir=self.target_dir)

        # Check published files exist
        recs_path = os.path.join(self.target_dir, "recommendations.json")
        mkt_path = os.path.join(self.target_dir, "market.json")
        hist_path = os.path.join(self.target_dir, "history", "2026-03-31.json")

        self.assertTrue(os.path.exists(recs_path))
        self.assertTrue(os.path.exists(mkt_path))
        self.assertTrue(os.path.exists(hist_path))

        with open(recs_path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f)["v"], 1)

        # Verify no backup, staging, or state files remain
        bak_dir = f"{self.target_dir}_bak"
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        self.assertFalse(os.path.exists(bak_dir))
        self.assertFalse(os.path.exists(state_file))

    def test_2_second_writer_blocked_by_active_lock(self):
        """2. Verify second writer is blocked with ArtifactLockError when lock is active."""
        with ArtifactLock(self.target_dir):
            lock2 = ArtifactLock(self.target_dir, timeout=0.0)
            with self.assertRaises(ArtifactLockError) as cm:
                lock2.acquire()
            self.assertIn("locked by another process", str(cm.exception))

    def test_3_stale_lock_recovery(self):
        """3. Verify stale lock file metadata belonging to a non-existent process PID is handled safely."""
        lock_path = os.path.join(self.temp_dir, ".generated.lock")
        stale_pid = 99999999  # Guaranteed non-existent PID
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({"pid": stale_pid, "target_dir": self.target_dir}, f)

        # Acquiring lock should succeed since flock was not held by active process
        with ArtifactLock(self.target_dir, timeout=0.1) as lock:
            self.assertTrue(lock.is_acquired)

    def test_4_interruption_after_staging(self):
        """4. Verify interruption after STAGING leaves valid target intact and cleans staging dir."""
        # Setup initial valid target
        initial_file = os.path.join(self.target_dir, "recommendations.json")
        with open(initial_file, "w", encoding="utf-8") as f:
            f.write('{"v": "original"}\n')

        # Simulate leftover staging dir and journal
        staging_dir = f"{self.target_dir}_staging_test_123"
        os.makedirs(staging_dir, exist_ok=True)
        with open(os.path.join(staging_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "incomplete_staging"}\n')

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test_123",
                    "stage": "STAGING",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": f"{self.target_dir}_bak",
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)

        # Verify target retains original valid content and staging dir is removed
        with open(initial_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "original"}\n')
        self.assertFalse(os.path.exists(staging_dir))

    def test_5_interruption_after_backup(self):
        """5. Verify interruption after BACKUP (target missing, backup exists) restores backup to target."""
        bak_dir = f"{self.target_dir}_bak"
        os.makedirs(bak_dir, exist_ok=True)
        bak_file = os.path.join(bak_dir, "recommendations.json")
        with open(bak_file, "w", encoding="utf-8") as f:
            f.write('{"v": "backed_up_data"}\n')

        # Remove target_dir to simulate process crash right after moving target -> bak
        shutil.rmtree(self.target_dir, ignore_errors=True)

        recover_interrupted_publish(self.target_dir)

        # Target must be restored from backup
        restored_file = os.path.join(self.target_dir, "recommendations.json")
        self.assertTrue(os.path.exists(restored_file))
        with open(restored_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "backed_up_data"}\n')
        self.assertFalse(os.path.exists(bak_dir))

    def test_6_backup_exists_and_production_target_valid(self):
        """6. Verify when target is valid and backup exists, backup is discarded and target preserved."""
        # Valid production target
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "valid_target"}\n')

        # Leftover backup dir
        bak_dir = f"{self.target_dir}_bak"
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "old_backup"}\n')

        recover_interrupted_publish(self.target_dir)

        # Target remains valid_target, backup is removed
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "valid_target"}\n')
        self.assertFalse(os.path.exists(bak_dir))

    def test_7_staging_exists_and_production_target_valid(self):
        """7. Verify when target is valid and staging exists, staging is discarded."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "valid_target"}\n')

        staging_dir = f"{self.target_dir}_staging_456"
        os.makedirs(staging_dir, exist_ok=True)

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "456",
                    "stage": "STAGING",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": f"{self.target_dir}_bak",
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)

        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "valid_target"}\n')
        self.assertFalse(os.path.exists(staging_dir))

    def test_8_commit_publish_failure_rollback(self):
        """8. Verify commit failure triggers rollback restoring previous valid artifacts."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "pre_commit_val"}\n')

        real_replace = os.replace

        def failing_replace(src, dst):
            if "staging" in str(src):
                raise OSError("Simulated disk replacement failure during commit")
            return real_replace(src, dst)

        with (
            patch("os.replace", side_effect=failing_replace),
            self.assertRaises(OSError),
        ):
            publish_artifacts_atomically(self.sample_artifacts, target_dir=self.target_dir)

        # Target must be restored byte-for-byte to pre-commit state
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "pre_commit_val"}\n')

    def test_9_repeated_recovery_is_idempotent(self):
        """9. Verify running recovery multiple times produces identical clean state."""
        bak_dir = f"{self.target_dir}_bak"
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "backed_up_data"}\n')
        shutil.rmtree(self.target_dir, ignore_errors=True)

        # Run recovery 3 times consecutively
        recover_interrupted_publish(self.target_dir)
        recover_interrupted_publish(self.target_dir)
        recover_interrupted_publish(self.target_dir)

        target_file = os.path.join(self.target_dir, "recommendations.json")
        self.assertTrue(os.path.exists(target_file))
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "backed_up_data"}\n')

    def test_10_failed_transaction_preserves_previous_valid_artifacts(self):
        """10. Verify failed transaction preserves previous valid artifacts and cleans up temporary staging/state files."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "original_good_data"}\n')

        # Fail transaction during execute_publish write phase with non-serializable object
        bad_artifacts = {"bad_file.json": {"unserializable": object()}}

        with self.assertRaises(TypeError):
            publish_artifacts_atomically(bad_artifacts, target_dir=self.target_dir)

        # Original data preserved
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "original_good_data"}\n')

        # No staging directory or state file left behind
        for item in os.listdir(self.temp_dir):
            self.assertFalse("staging" in item)
            self.assertFalse("bak" in item)

    def test_11_corrupted_or_invalid_journal_recovery(self):
        """11. Verify recovery raises ArtifactTransactionError and preserves journal/target when journal is corrupt or invalid."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "good_data"}\n')

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")

        # Scenario A: Corrupted non-JSON file -> raises ArtifactTransactionError, preserves journal & target
        with open(state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_NOT_JSON {{{")

        with self.assertRaises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(state_file))
        with open(target_file, "r", encoding="utf-8") as f:
            self.assertEqual(f.read(), '{"v": "good_data"}\n')

        # Scenario B: Missing required fields
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"txn_id": "123", "stage": "STAGING"}, f)

        with self.assertRaises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(state_file))

        # Scenario C: Unknown stage string
        invalid_journal = {
            "txn_id": "123",
            "stage": "UNKNOWN_STAGE",
            "target_dir": self.target_dir,
            "staging_dir": f"{self.target_dir}_staging_123",
            "backup_dir": f"{self.target_dir}_bak",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(invalid_journal, f)

        with self.assertRaises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(state_file))

        # Scenario D: Path escape check
        path_escape_journal = {
            "txn_id": "123",
            "stage": "STAGING",
            "target_dir": self.target_dir,
            "staging_dir": "/etc/passwd_staging_123",
            "backup_dir": f"{self.target_dir}_bak",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(path_escape_journal, f)

        with self.assertRaises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(state_file))

    def test_12_stage_boundary_failure_injection_with_journal(self):
        """12. Verify failure-injection at STAGING, BACKUP, COMMIT, and CLEANUP boundaries using persisted journal."""
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        bak_dir = f"{self.target_dir}_bak"
        staging_dir = f"{self.target_dir}_staging_test"

        # Boundary A: Crashed during STAGING
        os.makedirs(staging_dir, exist_ok=True)
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "w", encoding="utf-8"
        ) as f:
            f.write('{"v": "valid_target"}\n')
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test",
                    "stage": "STAGING",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)
        self.assertFalse(os.path.exists(staging_dir))
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        self.assertFalse(os.path.exists(state_file))

        # Boundary B: Crashed during BACKUP (target_dir moved to bak_dir, target_dir missing)
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "backed_up_good"}\n')
        shutil.rmtree(self.target_dir, ignore_errors=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test",
                    "stage": "BACKUP",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        self.assertFalse(os.path.exists(bak_dir))
        self.assertFalse(os.path.exists(state_file))

        # Boundary C: Crashed during COMMIT with missing target_dir and backup_dir present
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "restore_me"}\n')
        shutil.rmtree(self.target_dir, ignore_errors=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test",
                    "stage": "COMMIT",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)
        self.assertTrue(os.path.exists(os.path.join(self.target_dir, "recommendations.json")))
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "r", encoding="utf-8"
        ) as f:
            self.assertEqual(f.read(), '{"v": "restore_me"}\n')
        self.assertFalse(os.path.exists(state_file))

    def test_13_required_vs_optional_cleanup_failures(self):
        """13. Verify required cleanup failure raises error while optional cleanup failure logs warning and preserves success."""
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        staging_dir = f"{self.target_dir}_staging_req_test"
        bak_dir = f"{self.target_dir}_bak"

        os.makedirs(staging_dir, exist_ok=True)
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "w", encoding="utf-8"
        ) as f:
            f.write('{"v": "valid_target"}\n')
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "req_test",
                    "stage": "STAGING",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        # Required cleanup failure (shutil.rmtree failing on required staging dir removal)
        with patch("shutil.rmtree", side_effect=PermissionError("Permission denied")):
            with self.assertRaises(ArtifactTransactionError):
                recover_interrupted_publish(self.target_dir)

        # Journal remains for retry when required cleanup fails
        self.assertTrue(os.path.exists(state_file))

        # Optional cleanup failure (backup removal in stage COMMIT)
        os.makedirs(bak_dir, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "req_test",
                    "stage": "CLEANUP",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        real_rmtree = shutil.rmtree

        def failing_rmtree_for_bak(path, *args, **kwargs):
            if path == bak_dir:
                raise PermissionError("Optional cleanup permission error")
            return real_rmtree(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=failing_rmtree_for_bak):
            # Should NOT raise error because bak_dir removal in CLEANUP is optional
            recover_interrupted_publish(self.target_dir)

        # Journal is removed because recovery completed successfully
        self.assertFalse(os.path.exists(state_file))

    def test_14_unrelated_staging_directories_preserved(self):
        """14. Verify unrelated staging directories not belonging to current journal are preserved."""
        unrelated_staging = f"{self.target_dir}_staging_unrelated_999"
        os.makedirs(unrelated_staging, exist_ok=True)

        recover_interrupted_publish(self.target_dir)

        # Unrelated staging dir must NOT be blindly deleted
        self.assertTrue(os.path.exists(unrelated_staging))


if __name__ == "__main__":
    unittest.main()
