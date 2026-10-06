"""Atomic artifact transaction management and single-writer locking."""

import fcntl
import json
import logging
import os
import shutil
import time
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any, Self

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GENERATED_DIR = os.path.join(ROOT_DIR, "generated")

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
        from scripts.artifacts.recovery import recover_transaction_state

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


__all__ = [
    "GENERATED_DIR",
    "ROOT_DIR",
    "ArtifactLock",
    "ArtifactLockError",
    "ArtifactTransaction",
    "ArtifactTransactionError",
    "save_json_files",
]
