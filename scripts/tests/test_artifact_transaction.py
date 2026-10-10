"""Focused unit tests for artifact transaction safety, single-writer locking, and deterministic recovery."""

import json
import os
import shutil
import tempfile

import pytest

from scripts.generate_report import (
    ArtifactLock,
    ArtifactLockError,
    ArtifactTransaction,
    ArtifactTransactionError,
    publish_artifacts_atomically,
    recover_interrupted_publish,
)


@pytest.mark.unit
class TestArtifactTransactionSuite:
    """Test suite for covering single-writer locking, transaction lifecycle, and deterministic recovery."""

    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.target_dir = os.path.join(self.temp_dir, "generated")
        os.makedirs(self.target_dir, exist_ok=True)

        def _make_valid_rec_payload(date_str="2026-03-31"):
            return {
                "schema_version": "2.0",
                "signal_model_version": "2.0",
                "generated_at": f"{date_str}T00:00:00Z",
                "data_as_of": date_str,
                "source_date": date_str,
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

        self.make_valid_rec_payload = _make_valid_rec_payload
        self.sample_artifacts = {
            "recommendations.json": _make_valid_rec_payload("2026-03-31"),
            "market.json": {"schema_version": "2.0", "market": {"regime": "BULL"}},
            "history/2026-03-31.json": _make_valid_rec_payload("2026-03-31"),
        }

    def teardown_method(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_successful_transaction_lifecycle(self):
        """Verifies that a successful artifact transaction completes all stages from STAGING through CLEANUP cleanly."""
        publish_artifacts_atomically(
            self.sample_artifacts, target_dir=self.target_dir, strict_provenance=False
        )

        # Check published files exist
        recs_path = os.path.join(self.target_dir, "recommendations.json")
        mkt_path = os.path.join(self.target_dir, "market.json")
        hist_path = os.path.join(self.target_dir, "history", "2026-03-31.json")

        assert os.path.exists(recs_path)
        assert os.path.exists(mkt_path)
        assert os.path.exists(hist_path)

        with open(recs_path, "r", encoding="utf-8") as f:
            assert json.load(f)["schema_version"] == "2.0"

        # Verify no backup, staging, or state files remain
        bak_dir = f"{self.target_dir}_bak"
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)

    def test_second_writer_blocked_by_active_lock(self):
        """Verifies that a second writer process is blocked with ArtifactLockError while the transaction lock is active."""
        with ArtifactLock(self.target_dir):
            lock2 = ArtifactLock(self.target_dir, timeout=0.0)
            with pytest.raises(ArtifactLockError) as cm:
                lock2.acquire()
            assert "locked by another process" in str(cm.value)

    def test_stale_lock_recovery(self):
        """Verifies that stale lock file metadata belonging to a non-existent process PID is handled safely."""
        lock_path = os.path.join(self.temp_dir, ".generated.lock")
        stale_pid = 99999999  # Guaranteed non-existent PID
        with open(lock_path, "w", encoding="utf-8") as f:
            json.dump({"pid": stale_pid, "target_dir": self.target_dir}, f)

        # Acquiring lock should succeed since flock was not held by active process
        with ArtifactLock(self.target_dir, timeout=0.1) as lock:
            assert lock.is_acquired

    def test_interruption_after_staging(self):
        """Verifies that an interruption during STAGING leaves the valid target intact and cleans up the staging directory."""
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
            assert f.read() == '{"v": "original"}\n'
        assert not os.path.exists(staging_dir)

    def test_interruption_after_backup(self):
        """Verifies that an interruption after BACKUP restores the backup directory to the target when the target is missing."""
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
        assert os.path.exists(restored_file)
        with open(restored_file, "r", encoding="utf-8") as f:
            assert f.read() == '{"v": "backed_up_data"}\n'
        assert not os.path.exists(bak_dir)

    def test_backup_exists_and_production_target_valid(self):
        """Verifies that when the target directory is valid and a leftover backup exists, the backup is discarded and the target is preserved."""
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
            assert f.read() == '{"v": "valid_target"}\n'
        assert not os.path.exists(bak_dir)

    def test_staging_exists_and_production_target_valid(self):
        """Verifies that when the target directory is valid and a staging directory exists, the staging directory is discarded."""
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
            assert f.read() == '{"v": "valid_target"}\n'
        assert not os.path.exists(staging_dir)

    def test_commit_publish_failure_rollback(self, mocker):
        """Verifies that a failure during the COMMIT phase triggers automatic rollback, restoring previous valid artifacts."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "pre_commit_val"}\n')

        real_replace = os.replace

        def failing_replace(src, dst):
            if "staging" in str(src):
                raise OSError("Simulated disk replacement failure during commit")
            return real_replace(src, dst)

        mocker.patch("os.replace", side_effect=failing_replace)
        with pytest.raises(OSError):
            publish_artifacts_atomically(
                self.sample_artifacts, target_dir=self.target_dir, strict_provenance=False
            )

        # Target must be restored byte-for-byte to pre-commit state
        with open(target_file, "r", encoding="utf-8") as f:
            assert f.read() == '{"v": "pre_commit_val"}\n'

    def test_rollback_failure_preserves_journal_and_backup(self, mocker):
        """Verifies that when publish fails and rollback fails to restore the target, the journal and backup are preserved for subsequent recovery."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "pre_commit_val"}\n')

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        bak_dir = f"{self.target_dir}_bak"

        real_replace = os.replace

        def failing_replace_during_commit_and_rollback(src, dst):
            # Fail when attempting to promote staging -> target in COMMIT, or restore bak -> target in rollback
            if dst == self.target_dir:
                raise OSError("Simulated commit swap and rollback failure")
            return real_replace(src, dst)

        mocker.patch("os.replace", side_effect=failing_replace_during_commit_and_rollback)
        with pytest.raises(RuntimeError) as cm:
            publish_artifacts_atomically(
                self.sample_artifacts, target_dir=self.target_dir, strict_provenance=False
            )
        mocker.stopall()

        assert "Directory-level atomic artifact publish rollback failed" in str(cm.value)
        # State file and backup directory must be preserved for future recovery
        assert os.path.exists(state_file)
        assert os.path.exists(bak_dir)

        # Test recovery from a fresh context
        recover_interrupted_publish(self.target_dir)

        # Target restored, journal and backup cleaned up
        assert os.path.exists(target_file)
        assert not os.path.exists(state_file)
        assert not os.path.exists(bak_dir)

    def test_repeated_recovery_is_idempotent(self):
        """Verifies that running transaction recovery multiple times consecutively produces an identical clean state."""
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
        assert os.path.exists(target_file)
        with open(target_file, "r", encoding="utf-8") as f:
            assert f.read() == '{"v": "backed_up_data"}\n'

    def test_failed_transaction_preserves_previous_valid_artifacts(self):
        """Verifies that a failed transaction preserves previous valid artifacts and cleans up temporary staging and state files."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "original_good_data"}\n')

        # Fail transaction during execute_publish write phase with non-serializable object
        bad_artifacts = {"bad_file.json": {"unserializable": object()}}

        with pytest.raises(TypeError):
            publish_artifacts_atomically(
                bad_artifacts, target_dir=self.target_dir, strict_provenance=False
            )

        # Original data preserved
        with open(target_file, "r", encoding="utf-8") as f:
            assert f.read() == '{"v": "original_good_data"}\n'

        # No staging directory or state file left behind
        for item in os.listdir(self.temp_dir):
            assert "staging" not in item
            assert "bak" not in item

    def test_corrupted_or_invalid_journal_recovery(self):
        """Verifies that recovery raises ArtifactTransactionError and preserves the journal and target when the journal is corrupt or invalid."""
        target_file = os.path.join(self.target_dir, "recommendations.json")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write('{"v": "good_data"}\n')

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")

        # Corrupted non-JSON file -> raises ArtifactTransactionError, preserves journal & target
        with open(state_file, "w", encoding="utf-8") as f:
            f.write("CORRUPTED_NOT_JSON {{{")

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        assert os.path.exists(state_file)
        with open(target_file, "r", encoding="utf-8") as f:
            assert f.read() == '{"v": "good_data"}\n'

        # Missing required fields
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump({"txn_id": "123", "stage": "STAGING"}, f)

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        assert os.path.exists(state_file)

        # Unknown stage string
        invalid_journal = {
            "txn_id": "123",
            "stage": "UNKNOWN_STAGE",
            "target_dir": self.target_dir,
            "staging_dir": f"{self.target_dir}_staging_123",
            "backup_dir": f"{self.target_dir}_bak",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(invalid_journal, f)

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        assert os.path.exists(state_file)

        # Path escape check
        path_escape_journal = {
            "txn_id": "123",
            "stage": "STAGING",
            "target_dir": self.target_dir,
            "staging_dir": "/etc/passwd_staging_123",
            "backup_dir": f"{self.target_dir}_bak",
        }
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(path_escape_journal, f)

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        assert os.path.exists(state_file)

    def test_stage_boundary_failure_injection_with_journal(self):
        """Verifies failure recovery at STAGING, BACKUP, COMMIT, and CLEANUP stage boundaries using the persisted journal."""
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        bak_dir = f"{self.target_dir}_bak"
        staging_dir = f"{self.target_dir}_staging_test"

        # Crashed during STAGING
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
        assert not os.path.exists(staging_dir)
        assert os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        assert not os.path.exists(state_file)

        # Crashed during BACKUP (target_dir moved to bak_dir, target_dir missing)
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
        assert os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)

        # Crashed during COMMIT with missing target_dir and backup_dir present
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
        assert os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "r", encoding="utf-8"
        ) as f:
            assert f.read() == '{"v": "restore_me"}\n'
        assert not os.path.exists(state_file)

    def test_cleanup_boundary_scenarios(self, mocker):
        """Verifies transaction recovery behavior across CLEANUP stage boundary conditions."""
        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        bak_dir = f"{self.target_dir}_bak"
        staging_dir = f"{self.target_dir}_staging_test_cleanup"

        # Valid target with leftover backup directory cleans backup and completes recovery
        os.makedirs(bak_dir, exist_ok=True)
        os.makedirs(self.target_dir, exist_ok=True)
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "w", encoding="utf-8"
        ) as f:
            f.write('{"v": "target_valid"}\n')
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "old_backup"}\n')
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test_cleanup",
                    "stage": "CLEANUP",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)

        # Missing target with backup directory restores backup to target
        shutil.rmtree(self.target_dir, ignore_errors=True)
        os.makedirs(bak_dir, exist_ok=True)
        with open(os.path.join(bak_dir, "recommendations.json"), "w", encoding="utf-8") as f:
            f.write('{"v": "restore_backup_cleanup"}\n')
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test_cleanup",
                    "stage": "CLEANUP",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        recover_interrupted_publish(self.target_dir)
        assert os.path.exists(os.path.join(self.target_dir, "recommendations.json"))
        with open(
            os.path.join(self.target_dir, "recommendations.json"), "r", encoding="utf-8"
        ) as f:
            assert f.read() == '{"v": "restore_backup_cleanup"}\n'
        assert not os.path.exists(bak_dir)

        # Missing target with backup restore failure preserves journal and raises ArtifactTransactionError
        shutil.rmtree(self.target_dir, ignore_errors=True)
        os.makedirs(bak_dir, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "txn_id": "test_cleanup",
                    "stage": "CLEANUP",
                    "target_dir": self.target_dir,
                    "staging_dir": staging_dir,
                    "backup_dir": bak_dir,
                },
                f,
            )

        mocker.patch("os.replace", side_effect=PermissionError("Permission denied"))
        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        mocker.stopall()

        assert os.path.exists(state_file)
        assert os.path.exists(bak_dir)

        # Missing target and missing backup raises ArtifactTransactionError and preserves journal
        shutil.rmtree(self.target_dir, ignore_errors=True)
        shutil.rmtree(bak_dir, ignore_errors=True)

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)

        assert os.path.exists(state_file)

    def test_required_vs_optional_cleanup_failures(self, mocker):
        """Verifies that required cleanup failure raises an error while optional cleanup failure logs a warning and preserves overall transaction success."""
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
        mocker.patch("shutil.rmtree", side_effect=PermissionError("Permission denied"))
        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        mocker.stopall()

        # Journal remains for retry when required cleanup fails
        assert os.path.exists(state_file)

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

        mocker.patch("shutil.rmtree", side_effect=failing_rmtree_for_bak)
        # Should NOT raise error because bak_dir removal in CLEANUP is optional
        recover_interrupted_publish(self.target_dir)

        # Journal is removed because recovery completed successfully
        assert not os.path.exists(state_file)

    def test_unrelated_staging_directories_preserved(self):
        """Verifies that unrelated staging directories not belonging to the active transaction journal are preserved."""
        unrelated_staging = f"{self.target_dir}_staging_unrelated_999"
        os.makedirs(unrelated_staging, exist_ok=True)

        recover_interrupted_publish(self.target_dir)

        # Unrelated staging dir must NOT be blindly deleted
        assert os.path.exists(unrelated_staging)

    def test_real_cleanup_interruption_and_recovery(self, mocker):
        """Verifies end-to-end real transaction interruption recovery at CLEANUP boundary across multiple system recovery states.

        - Executes a real transaction advancing through STAGING -> BACKUP -> COMMIT -> CLEANUP.
        - Injects an interruption/failure at CLEANUP boundary before cleanup completes.
        - Verifies recovery context behaviors across target valid, target missing, both missing,
          required restore/cleanup failure, and idempotency.
        """
        # Setup initial valid target
        initial_file = os.path.join(self.target_dir, "recommendations.json")
        with open(initial_file, "w", encoding="utf-8") as f:
            f.write('{"v": "version_0"}\n')

        state_file = os.path.join(self.temp_dir, ".generated_txn.json")
        bak_dir = f"{self.target_dir}_bak"

        # Helper to execute a real publish interrupted at CLEANUP boundary
        def execute_interrupted_publish_at_cleanup():
            os.makedirs(self.target_dir, exist_ok=True)
            with open(
                os.path.join(self.target_dir, "recommendations.json"), "w", encoding="utf-8"
            ) as f:
                f.write('{"v": "pre_publish"}\n')

            txn = ArtifactTransaction(self.target_dir)
            real_update_state = txn.update_state

            def interrupting_update_state(stage):
                real_update_state(stage)
                if stage == "CLEANUP":
                    raise RuntimeError("Simulated process crash/interruption at CLEANUP boundary")

            mocker.patch.object(txn, "update_state", side_effect=interrupting_update_state)
            with pytest.raises(RuntimeError):
                txn.execute_publish(self.sample_artifacts)

        # CLEANUP interrupt + Target valid -> keep target, cleanup backup & journal
        execute_interrupted_publish_at_cleanup()

        assert os.path.exists(state_file)
        assert os.path.exists(bak_dir)
        assert os.path.exists(self.target_dir)

        # Fresh recovery context (as a process restarting)
        recover_interrupted_publish(self.target_dir)

        # Target remains valid with new artifacts
        recs_file = os.path.join(self.target_dir, "recommendations.json")
        assert os.path.exists(recs_file)
        with open(recs_file, "r", encoding="utf-8") as f:
            assert json.load(f)["schema_version"] == "2.0"

        # Backup and journal cleaned up safely
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)

        # CLEANUP interrupt + Target missing, backup exists -> restore backup
        execute_interrupted_publish_at_cleanup()
        shutil.rmtree(self.target_dir, ignore_errors=True)

        recover_interrupted_publish(self.target_dir)

        assert os.path.exists(self.target_dir)
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)

        # CLEANUP interrupt + Target missing AND backup missing -> raise ArtifactTransactionError & keep journal
        execute_interrupted_publish_at_cleanup()
        shutil.rmtree(self.target_dir, ignore_errors=True)
        shutil.rmtree(bak_dir, ignore_errors=True)

        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)

        assert os.path.exists(state_file)

        # CLEANUP interrupt + Required restore/cleanup failure -> raise exception & preserve journal + backup
        shutil.rmtree(state_file, ignore_errors=True)
        execute_interrupted_publish_at_cleanup()
        shutil.rmtree(self.target_dir, ignore_errors=True)

        mocker.patch("os.replace", side_effect=PermissionError("Permission denied"))
        with pytest.raises(ArtifactTransactionError):
            recover_interrupted_publish(self.target_dir)
        mocker.stopall()

        assert os.path.exists(state_file)
        assert os.path.exists(bak_dir)

        # Repeated recovery runs are idempotent
        # Fix permission patch and complete recovery twice
        recover_interrupted_publish(self.target_dir)
        recover_interrupted_publish(self.target_dir)

        assert os.path.exists(self.target_dir)
        assert not os.path.exists(bak_dir)
        assert not os.path.exists(state_file)
