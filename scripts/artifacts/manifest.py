"""Artifact manifest builder and history index manager for publishing lifecycle."""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scripts.artifacts.transaction import GENERATED_DIR, save_json_files

logger = logging.getLogger(__name__)


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


@dataclass(frozen=True)
class ArtifactManifest:
    """Immutable manifest representation containing the set of relative artifact paths and data payloads."""

    created_at: str
    target_dir: str
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return dict representation of manifest metadata."""
        return {
            "created_at": self.created_at,
            "target_dir": self.target_dir,
            "artifact_count": len(self.artifacts),
            "paths": sorted(self.artifacts.keys()),
        }


class ArtifactManifestBuilder:
    """Constructs the publication manifest from pipeline context outputs or domain results."""

    def __init__(self, target_dir: str | None = None):
        self.target_dir = os.path.abspath(target_dir if target_dir is not None else GENERATED_DIR)
        self._artifacts: dict[str, dict[str, Any]] = {}

    def add_artifact(self, relative_path: str, data: dict[str, Any]) -> "ArtifactManifestBuilder":
        """Add an artifact payload under a relative destination path."""
        if not relative_path or not isinstance(relative_path, str):
            raise ValueError("relative_path must be a non-empty string")
        if not isinstance(data, dict):
            raise TypeError(f"Artifact payload for '{relative_path}' must be a dict")
        self._artifacts[relative_path] = data
        return self

    def build_history_index(
        self, data_as_of: str | None, generated_at: str | None = None
    ) -> "ArtifactManifestBuilder":
        """Build and register historical date report and updated index.json artifact payloads."""
        if not data_as_of:
            return self

        now_iso = generated_at or datetime.now(UTC).isoformat()
        index_path = os.path.join(self.target_dir, "history", "index.json")
        try:
            idx_data = load_history_index(index_path)
            history_dates = idx_data.get("dates", [])
        except ValueError, TypeError, OSError:
            history_dates = []

        if data_as_of not in history_dates:
            history_dates = list(history_dates)
            history_dates.append(data_as_of)
            history_dates.sort(reverse=True)

        index_payload = {
            "last_updated": now_iso,
            "total_reports": len(history_dates),
            "dates": history_dates,
        }

        self.add_artifact(os.path.join("history", "index.json"), index_payload)
        return self

    def build(self) -> ArtifactManifest:
        """Build frozen ArtifactManifest instance."""
        return ArtifactManifest(
            created_at=datetime.now(UTC).isoformat(),
            target_dir=self.target_dir,
            artifacts=dict(self._artifacts),
        )


__all__ = [
    "ArtifactManifest",
    "ArtifactManifestBuilder",
    "load_history_index",
    "update_history_index",
]
