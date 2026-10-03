"""Atomic artifact publishing and history index management for VN Invest pipeline orchestration."""

import fcntl
import json
import logging
import os
import shutil
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Self

from scripts.pipeline.constants import GENERATED_DIR

logger = logging.getLogger(__name__)


class ArtifactLockError(RuntimeError):
    """Raised when artifact directory lock cannot be acquired."""


class ArtifactTransactionError(RuntimeError):
    """Raised when artifact publishing transaction fails."""


class ArtifactLock:
    """Single-writer lock for artifact directory modifications.

    Uses OS-level fcntl.flock on POSIX platforms combined with process metadata
    for crash-resilient mutual exclusion and stale lock handling.
    """

    def __init__(self, target_dir: str, timeout: float = 0.0):
        self.target_dir = os.path.abspath(target_dir)
        parent_dir = os.path.dirname(self.target_dir)
        dir_name = os.path.basename(self.target_dir)
        self.lock_path = os.path.join(parent_dir, f".{dir_name}.lock")
        self.fd: Any = None
        self.is_acquired = False
        self.timeout = timeout

    def acquire(self) -> Self:
        if self.is_acquired:
            return self

        os.makedirs(os.path.dirname(self.lock_path), exist_ok=True)
        start_time = time.time()

        while True:
            try:
                fd = open(self.lock_path, "a+", encoding="utf-8")  # noqa: SIM115
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.fd = fd
                self.is_acquired = True
                self._write_metadata()
                return self
            except (BlockingIOError, OSError) as err:
                if "fd" in locals() and fd:
                    with suppress(OSError):
                        fd.close()

                holder_info = self._read_lock_metadata()
                if self._is_stale(holder_info):
                    logger.debug("Lock file metadata refers to a non-existent process PID")

                if time.time() - start_time >= self.timeout:
                    pid = holder_info.get("pid") if holder_info else None
                    pid_str = f" (PID {pid})" if pid and isinstance(pid, int) else ""
                    raise ArtifactLockError(
                        f"Artifact directory '{self.target_dir}' is locked by another process{pid_str}"
                    ) from err

                time.sleep(0.05)

    def release(self) -> None:
        if self.is_acquired and self.fd is not None:
            with suppress(OSError):
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            with suppress(OSError):
                self.fd.close()
            self.fd = None
            self.is_acquired = False

    def __enter__(self) -> Self:
        return self.acquire()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def _write_metadata(self) -> None:
        if self.fd is not None:
            try:
                self.fd.seek(0)
                self.fd.truncate()
                meta = {
                    "pid": os.getpid(),
                    "created_at": datetime.now(UTC).isoformat(),
                    "target_dir": self.target_dir,
                }
                json.dump(meta, self.fd)
                self.fd.flush()
            except (OSError, TypeError, ValueError) as err:
                logger.debug("Non-fatal error writing lock metadata: %s", err)

    def _read_lock_metadata(self) -> dict | None:
        try:
            if os.path.exists(self.lock_path):
                with open(self.lock_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as err:
            logger.debug("Non-fatal error reading lock metadata: %s", err)
        return None

    def _is_stale(self, holder_info: dict | None) -> bool:
        if not holder_info or "pid" not in holder_info:
            return True
        pid = holder_info.get("pid")
        if not isinstance(pid, int):
            return True
        try:
            os.kill(pid, 0)
            return False  # Process is alive
        except ProcessLookupError, OSError:
            return True  # Process is dead


def validate_journal_metadata(state_file: str, target_dir: str) -> dict | None:
    """Validate transaction journal metadata strictly against expected target environment."""
    if not os.path.exists(state_file):
        return None

    target_dir = os.path.abspath(target_dir)
    parent_dir = os.path.dirname(target_dir)
    dir_name = os.path.basename(target_dir)

    try:
        with open(state_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as err:
        logger.error(
            "Transaction journal file '%s' is corrupt or malformed JSON: %s", state_file, err
        )
        raise ArtifactTransactionError(
            f"Transaction journal file '{state_file}' is corrupt or malformed JSON: {err}"
        ) from err

    if not isinstance(data, dict):
        logger.error("Transaction journal root in '%s' is not a JSON object", state_file)
        raise ArtifactTransactionError(
            f"Transaction journal root in '{state_file}' is not a JSON object"
        )

    required_fields = ("txn_id", "stage", "target_dir", "staging_dir", "backup_dir")
    missing = [f for f in required_fields if f not in data or not isinstance(data[f], str)]
    if missing:
        logger.error(
            "Transaction journal '%s' is missing required string fields: %s", state_file, missing
        )
        raise ArtifactTransactionError(
            f"Transaction journal '{state_file}' is missing required string fields: {missing}"
        )

    valid_stages = ("STAGING", "BACKUP", "COMMIT", "CLEANUP")
    if data["stage"] not in valid_stages:
        logger.error("Transaction journal '%s' has unknown stage: '%s'", state_file, data["stage"])
        raise ArtifactTransactionError(
            f"Transaction journal '{state_file}' has unknown stage: '{data['stage']}'"
        )

    j_target = os.path.abspath(data["target_dir"])
    if j_target != target_dir:
        logger.error(
            "Transaction journal '%s' target_dir mismatch: journal specifies '%s', expected '%s'",
            state_file,
            j_target,
            target_dir,
        )
        raise ArtifactTransactionError(
            f"Transaction journal '{state_file}' target_dir mismatch: expected '{target_dir}', got '{j_target}'"
        )

    j_staging = os.path.abspath(data["staging_dir"])
    j_backup = os.path.abspath(data["backup_dir"])
    txn_id = data["txn_id"]

    expected_staging_name = f"{dir_name}_staging_{txn_id}"
    expected_backup = os.path.join(parent_dir, f"{dir_name}_bak")

    if (
        os.path.dirname(j_staging) != parent_dir
        or os.path.basename(j_staging) != expected_staging_name
    ):
        logger.error(
            "Transaction journal '%s' staging_dir '%s' is invalid or escapes parent directory",
            state_file,
            j_staging,
        )
        raise ArtifactTransactionError(
            f"Transaction journal '{state_file}' staging_dir '{j_staging}' is invalid or escapes parent directory"
        )

    if os.path.dirname(j_backup) != parent_dir or j_backup != expected_backup:
        logger.error(
            "Transaction journal '%s' backup_dir '%s' is invalid or escapes parent directory",
            state_file,
            j_backup,
        )
        raise ArtifactTransactionError(
            f"Transaction journal '{state_file}' backup_dir '{j_backup}' is invalid or escapes parent directory"
        )

    return data


def recover_transaction_state(target_dir: str) -> None:
    """Recover target_dir from interrupted atomic transaction deterministically and idempotently."""
    target_dir = os.path.abspath(target_dir)
    parent_dir = os.path.dirname(target_dir)
    dir_name = os.path.basename(target_dir)

    state_file = os.path.join(parent_dir, f".{dir_name}_txn.json")
    journal = validate_journal_metadata(state_file, target_dir)

    target_exists = os.path.exists(target_dir)

    if journal is None:
        bak_dir = os.path.join(parent_dir, f"{dir_name}_bak")
        bak_exists = os.path.exists(bak_dir)

        if not target_exists and bak_exists:
            logger.info(
                "Restoring target directory '%s' from fallback backup '%s'...", target_dir, bak_dir
            )
            try:
                os.replace(bak_dir, target_dir)
            except Exception as err:
                logger.critical("Required cleanup failed restoring target from backup: %s", err)
                raise ArtifactTransactionError(
                    f"Required cleanup failed restoring target from backup: {err}"
                ) from err
        elif target_exists and bak_exists:
            try:
                shutil.rmtree(bak_dir)
            except (OSError, shutil.Error) as err:
                logger.warning("Optional cleanup of fallback backup '%s' failed: %s", bak_dir, err)
        return

    stage = journal["stage"]
    staging_dir = os.path.abspath(journal["staging_dir"])
    backup_dir = os.path.abspath(journal["backup_dir"])

    staging_exists = os.path.exists(staging_dir)
    backup_exists = os.path.exists(backup_dir)

    if stage == "STAGING":
        if staging_exists:
            try:
                shutil.rmtree(staging_dir)
            except Exception as err:
                logger.error(
                    "Required cleanup failed removing staging dir '%s': %s", staging_dir, err
                )
                raise ArtifactTransactionError(
                    f"Required cleanup failed removing staging dir '{staging_dir}': {err}"
                ) from err

    elif stage == "BACKUP":
        if not target_exists and backup_exists:
            logger.info(
                "Restoring target '%s' from backup '%s' (stage=BACKUP)...", target_dir, backup_dir
            )
            try:
                os.replace(backup_dir, target_dir)
                target_exists = True
                backup_exists = False
            except Exception as err:
                logger.critical("Required cleanup failed restoring backup in stage BACKUP: %s", err)
                raise ArtifactTransactionError(
                    f"Required cleanup failed restoring backup in stage BACKUP: {err}"
                ) from err

        if staging_exists:
            try:
                shutil.rmtree(staging_dir)
            except Exception as err:
                logger.error(
                    "Required cleanup failed removing staging dir '%s': %s", staging_dir, err
                )
                raise ArtifactTransactionError(
                    f"Required cleanup failed removing staging dir '{staging_dir}': {err}"
                ) from err

        if target_exists and backup_exists:
            try:
                shutil.rmtree(backup_dir)
                backup_exists = False
            except (OSError, shutil.Error) as err:
                logger.warning(
                    "Optional cleanup failed removing backup dir '%s': %s", backup_dir, err
                )

    elif stage == "COMMIT":
        if not target_exists and backup_exists:
            logger.info("Restoring backup '%s' to '%s' (stage=COMMIT)...", backup_dir, target_dir)
            try:
                os.replace(backup_dir, target_dir)
                target_exists = True
                backup_exists = False
            except Exception as err:
                logger.critical("Required cleanup failed restoring backup in stage COMMIT: %s", err)
                raise ArtifactTransactionError(
                    f"Required cleanup failed restoring backup in stage COMMIT: {err}"
                ) from err

        if staging_exists:
            try:
                shutil.rmtree(staging_dir)
            except Exception as err:
                logger.error(
                    "Required cleanup failed removing staging dir '%s': %s", staging_dir, err
                )
                raise ArtifactTransactionError(
                    f"Required cleanup failed removing staging dir '{staging_dir}': {err}"
                ) from err

        if target_exists and backup_exists:
            try:
                shutil.rmtree(backup_dir)
                backup_exists = False
            except (OSError, shutil.Error) as err:
                logger.warning(
                    "Optional cleanup failed removing backup dir '%s': %s", backup_dir, err
                )

    elif stage == "CLEANUP":
        if not target_exists:
            if backup_exists:
                logger.info(
                    "Restoring target '%s' from backup '%s' during CLEANUP recovery...",
                    target_dir,
                    backup_dir,
                )
                try:
                    os.replace(backup_dir, target_dir)
                    target_exists = True
                    backup_exists = False
                except Exception as err:
                    logger.critical(
                        "Required cleanup failed restoring backup in stage CLEANUP: %s", err
                    )
                    raise ArtifactTransactionError(
                        f"Required cleanup failed restoring backup in stage CLEANUP: {err}"
                    ) from err
            else:
                logger.critical(
                    "CRITICAL: Neither target_dir '%s' nor backup_dir '%s' exists during CLEANUP recovery!",
                    target_dir,
                    backup_dir,
                )
                raise ArtifactTransactionError(
                    f"CRITICAL: Neither target_dir '{target_dir}' nor backup_dir '{backup_dir}' exists during CLEANUP recovery!"
                )

        if staging_exists:
            try:
                shutil.rmtree(staging_dir)
            except Exception as err:
                logger.error(
                    "Required cleanup failed removing staging dir '%s': %s", staging_dir, err
                )
                raise ArtifactTransactionError(
                    f"Required cleanup failed removing staging dir '{staging_dir}': {err}"
                ) from err

        if backup_exists:
            try:
                shutil.rmtree(backup_dir)
                backup_exists = False
            except (OSError, shutil.Error) as err:
                logger.warning(
                    "Optional cleanup failed removing backup dir '%s': %s", backup_dir, err
                )

    try:
        os.remove(state_file)
    except OSError as err:
        logger.warning("Failed removing transaction state file '%s': %s", state_file, err)


class ArtifactTransaction:
    """Manages explicit artifact publishing lifecycle: STAGING -> BACKUP -> COMMIT -> CLEANUP."""

    def __init__(self, target_dir: str | None = None, txn_id: str | None = None):
        self.target_dir = os.path.abspath(target_dir if target_dir is not None else GENERATED_DIR)
        self.parent_dir = os.path.dirname(self.target_dir)
        self.dir_name = os.path.basename(self.target_dir)

        self.txn_id = txn_id or f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}_{os.getpid()}"
        self.staging_dir = os.path.join(self.parent_dir, f"{self.dir_name}_staging_{self.txn_id}")
        self.backup_dir = os.path.join(self.parent_dir, f"{self.dir_name}_bak")
        self.state_path = os.path.join(self.parent_dir, f".{self.dir_name}_txn.json")
        self.stage = "INIT"

    def update_state(self, stage: str) -> None:
        self.stage = stage
        state_data = {
            "txn_id": self.txn_id,
            "stage": stage,
            "target_dir": self.target_dir,
            "staging_dir": self.staging_dir,
            "backup_dir": self.backup_dir,
            "pid": os.getpid(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        tmp_state = f"{self.state_path}.tmp"
        try:
            with open(tmp_state, "w", encoding="utf-8") as f:
                json.dump(state_data, f, indent=2)
            os.replace(tmp_state, self.state_path)
        except Exception as err:
            logger.error("Failed writing transaction state metadata: %s", err)
            raise ArtifactTransactionError(
                f"Failed writing transaction state metadata: {err}"
            ) from err

    def clear_state(self) -> None:
        if os.path.exists(self.state_path):
            with suppress(OSError):
                os.remove(self.state_path)

    def recover(self) -> None:
        """Deterministic, idempotent transaction recovery."""
        recover_transaction_state(self.target_dir)

    def execute_publish(self, artifacts: dict[str, dict]) -> None:
        """Execute full atomic publish transaction with explicit lifecycle stages."""
        self.recover()

        # Step 1: STAGING
        self.update_state("STAGING")
        os.makedirs(self.staging_dir, exist_ok=True)

        if os.path.exists(self.target_dir):
            for item in os.listdir(self.target_dir):
                s_item = os.path.join(self.target_dir, item)
                d_item = os.path.join(self.staging_dir, item)
                if os.path.isdir(s_item):
                    shutil.copytree(s_item, d_item)
                else:
                    shutil.copy2(s_item, d_item)

        for rel_path, data in artifacts.items():
            out_path = os.path.join(self.staging_dir, rel_path)
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")

        # Step 2: BACKUP
        self.update_state("BACKUP")
        if os.path.exists(self.backup_dir):
            shutil.rmtree(self.backup_dir, ignore_errors=True)

        if os.path.exists(self.target_dir):
            os.replace(self.target_dir, self.backup_dir)

        # Step 3: COMMIT
        self.update_state("COMMIT")
        os.replace(self.staging_dir, self.target_dir)

        # Step 4: CLEANUP
        self.update_state("CLEANUP")
        if os.path.exists(self.backup_dir):
            shutil.rmtree(self.backup_dir, ignore_errors=True)
        if os.path.exists(self.staging_dir):
            shutil.rmtree(self.staging_dir, ignore_errors=True)

        self.clear_state()


def save_json_files(relative_path: str, data: dict):
    """Save JSON data atomically to generated/ under lock."""
    with ArtifactLock(GENERATED_DIR):
        p = os.path.join(GENERATED_DIR, relative_path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        tmp_p = f"{p}.tmp"
        with open(tmp_p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp_p, p)


def recover_interrupted_publish(target_dir: str | None = None) -> None:
    """Recover target_dir from interrupted atomic publish under single-writer lock."""
    if target_dir is None:
        target_dir = GENERATED_DIR

    target_dir = os.path.abspath(target_dir)

    with ArtifactLock(target_dir):
        recover_transaction_state(target_dir)


def publish_artifacts_atomically(artifacts: dict[str, dict], target_dir: str | None = None) -> None:
    """Publish multiple JSON artifacts atomically using single-writer lock and explicit lifecycle transaction."""
    if target_dir is None:
        target_dir = GENERATED_DIR

    target_dir = os.path.abspath(target_dir)

    with ArtifactLock(target_dir):
        txn = ArtifactTransaction(target_dir)
        try:
            txn.execute_publish(artifacts)
        except Exception as exc:
            logger.error(
                "Atomic artifact publishing failed during directory staging/swap: stage=%s artifact=ALL operation=publish category=OUTPUT_VALIDATION_FAILURE reason=%s",
                txn.stage,
                exc,
            )
            rollback_errors: list[str] = []

            target_restored = os.path.exists(target_dir)
            if not target_restored and os.path.exists(txn.backup_dir):
                try:
                    os.replace(txn.backup_dir, target_dir)
                    target_restored = True
                except (OSError, shutil.Error) as r_err:
                    logger.critical(
                        "Failed restoring target directory from backup during rollback: %s", r_err
                    )
                    rollback_errors.append(
                        f"Failed restoring target directory from backup: {r_err}"
                    )

            if os.path.exists(txn.staging_dir):
                try:
                    shutil.rmtree(txn.staging_dir, ignore_errors=True)
                except (OSError, shutil.Error) as r_err:
                    logger.warning(
                        "Failed cleaning up staging directory during rollback: %s", r_err
                    )

            if target_restored:
                txn.clear_state()
            else:
                logger.warning(
                    "Preserving transaction state file '%s' and backup '%s' for future recovery because rollback failed to restore target",
                    txn.state_path,
                    txn.backup_dir,
                )

            if rollback_errors or not target_restored:
                err_msg = "; ".join(rollback_errors) if rollback_errors else "Target not restored"
                logger.critical(
                    "CRITICAL: Directory-level atomic artifact rollback failed: %s", err_msg
                )
                raise RuntimeError(
                    f"CRITICAL: Directory-level atomic artifact publish rollback failed: {err_msg}"
                ) from exc

            raise


def load_history_index(index_path: str | None = None) -> dict:
    """Load and validate history index file (history/index.json)."""
    if index_path is None:
        index_path = os.path.join(GENERATED_DIR, "history", "index.json")

    try:
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"dates": []}
    except json.JSONDecodeError as err:
        raise ValueError(f"Failed to load history index '{index_path}': invalid JSON") from err
    except (PermissionError, OSError) as err:
        raise OSError(f"Failed to read history index '{index_path}': {err}") from err

    if not isinstance(data, dict):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': expected object root, got {type(data).__name__}"
        )

    if "dates" not in data:
        raise ValueError(
            f"Invalid history index structure in '{index_path}': missing required 'dates' field"
        )

    dates = data["dates"]
    if not isinstance(dates, list):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': 'dates' field must be a list"
        )

    if not all(isinstance(d, str) for d in dates):
        raise TypeError(
            f"Invalid history index structure in '{index_path}': all items in 'dates' must be strings"
        )

    return data


def update_history_index(data_date: str | None, index_path: str | None = None):
    """Maintain history/index.json with list of available historical dates."""
    if not data_date:
        return

    if index_path is None:
        index_path = os.path.join(GENERATED_DIR, "history", "index.json")

    index_data = load_history_index(index_path)
    history_dates = index_data.get("dates", [])

    if data_date not in history_dates:
        history_dates = list(history_dates)
        history_dates.append(data_date)
        history_dates.sort(reverse=True)

    index_payload = {
        "last_updated": datetime.now(UTC).isoformat(),
        "total_reports": len(history_dates),
        "dates": history_dates,
    }

    relative_path = (
        os.path.relpath(index_path, GENERATED_DIR)
        if index_path.startswith(GENERATED_DIR)
        else os.path.join("history", "index.json")
    )
    save_json_files(relative_path, index_payload)


__all__ = [
    "ArtifactLock",
    "ArtifactLockError",
    "ArtifactTransaction",
    "ArtifactTransactionError",
    "load_history_index",
    "publish_artifacts_atomically",
    "recover_interrupted_publish",
    "recover_transaction_state",
    "save_json_files",
    "update_history_index",
    "validate_journal_metadata",
]
