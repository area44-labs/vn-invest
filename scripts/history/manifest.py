"""Run Manifest subsystem: partitioned pipeline execution history tracking and error sanitization."""

import json
import logging
import os
import re
from typing import Any

from scripts.history.models import (
    HistoryDirectoryConventions,
    RunManifestEntry,
    is_valid_date_string,
)

logger = logging.getLogger(__name__)

SENSITIVE_KEY_PATTERNS = [
    re.compile(r"api[_-]?key", re.IGNORECASE),
    re.compile(r"token", re.IGNORECASE),
    re.compile(r"secret", re.IGNORECASE),
    re.compile(r"password", re.IGNORECASE),
    re.compile(r"auth", re.IGNORECASE),
    re.compile(r"credential", re.IGNORECASE),
]


def sanitize_error_metadata(raw_meta: Any) -> dict[str, Any] | None:
    """Recursively sanitize error metadata, redacting secrets, credentials, and excessive logs."""
    if raw_meta is None:
        return None

    if isinstance(raw_meta, (str, int, float, bool)):
        return {"message": str(raw_meta)[:500]}

    if not isinstance(raw_meta, dict):
        return {"error": type(raw_meta).__name__, "message": str(raw_meta)[:500]}

    sanitized: dict[str, Any] = {}
    for k, v in raw_meta.items():
        k_str = str(k)
        if any(pat.search(k_str) for pat in SENSITIVE_KEY_PATTERNS):
            sanitized[k_str] = "[REDACTED]"
            continue

        if isinstance(v, dict):
            sanitized[k_str] = sanitize_error_metadata(v)
        elif isinstance(v, list):
            sanitized[k_str] = [
                sanitize_error_metadata(x) if isinstance(x, dict) else str(x)[:200] for x in v[:10]
            ]
        elif isinstance(v, (int, float, bool)) or v is None:
            sanitized[k_str] = v
        else:
            v_str = str(v)
            if any(pat.search(k_str) for pat in SENSITIVE_KEY_PATTERNS):
                sanitized[k_str] = "[REDACTED]"
            else:
                sanitized[k_str] = v_str[:500]

    return sanitized


class RunManifestTracker:
    """Manages immutable append-oriented partitioned storage of run manifest entries."""

    def __init__(self, base_generated_dir: str):
        self.conventions = HistoryDirectoryConventions(base_generated_dir)

    def load_partition(self, trading_date: str) -> list[RunManifestEntry]:
        """Load all run manifest entries for a given trading date."""
        filepath = self.conventions.get_manifest_partition_path(trading_date)
        if not os.path.exists(filepath):
            return []

        entries: list[RunManifestEntry] = []
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                clean = line.strip()
                if not clean:
                    continue
                try:
                    data = json.loads(clean)
                    entries.append(RunManifestEntry.from_dict(data))
                except (json.JSONDecodeError, ValueError, TypeError) as err:
                    logger.warning(
                        "Malformed run manifest line %d in '%s': %s",
                        line_no,
                        filepath,
                        err,
                    )
        return entries

    def stage_run_entry(
        self,
        staging_dir: str,
        entry: RunManifestEntry,
    ) -> str:
        """Append or merge a run manifest entry into staging partition."""
        trading_date = entry.trading_date
        if not is_valid_date_string(trading_date):
            raise ValueError(f"Invalid trading_date: {trading_date!r}")

        staged_conventions = HistoryDirectoryConventions(staging_dir)
        target_path = staged_conventions.get_manifest_partition_path(trading_date)
        os.makedirs(os.path.dirname(target_path), exist_ok=True)

        existing_entries = self.load_partition(trading_date)
        entries_by_id: dict[str, RunManifestEntry] = {e.run_id: e for e in existing_entries}

        if os.path.exists(target_path):
            with open(target_path, "r", encoding="utf-8") as f:
                for line in f:
                    clean = line.strip()
                    if clean:
                        try:
                            item = RunManifestEntry.from_dict(json.loads(clean))
                            entries_by_id[item.run_id] = item
                        except (json.JSONDecodeError, ValueError, TypeError) as err:
                            logger.debug("Skipping unparseable staged manifest line: %s", err)

        entries_by_id[entry.run_id] = entry
        sorted_entries = sorted(entries_by_id.values(), key=lambda e: e.generated_at)

        with open(target_path, "w", encoding="utf-8") as f:
            for item in sorted_entries:
                f.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")

        return target_path


__all__ = [
    "RunManifestTracker",
    "sanitize_error_metadata",
]
