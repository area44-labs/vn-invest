"""Centralized JSON Schema Registry and Resolver for VN Invest artifacts.

Provides explicit, version-aware schema resolution and loading for all artifact types.
Rejecting unsupported, malformed, or missing versions fail-closed without silent fallback.
"""

import json
import os
from typing import Any

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Canonical supported schema version
SCHEMA_VERSION = "2.0"

# Mapping of (artifact_type, schema_version) -> relative path from repo root
SCHEMA_REGISTRY: dict[tuple[str, str], str] = {
    ("recommendations", "2.0"): os.path.join("schemas", "v2", "recommendations.schema.json"),
    ("performance", "2.0"): os.path.join("schemas", "v2", "performance.schema.json"),
}


class SchemaResolutionError(ValueError):
    """Raised when an artifact schema version cannot be resolved or is invalid."""


def get_supported_schema_versions(artifact_type: str | None = None) -> list[str]:
    """Return sorted list of supported schema versions, optionally filtered by artifact type."""
    if artifact_type is not None:
        art_type = str(artifact_type).strip().lower()
        versions = [ver for (atype, ver) in SCHEMA_REGISTRY if atype == art_type]
    else:
        versions = list({ver for (_, ver) in SCHEMA_REGISTRY})
    return sorted(versions)


def get_registered_schema_path(artifact_type: str, schema_version: str) -> str:
    """Resolve absolute schema file path for a given artifact type and schema version.

    Raises SchemaResolutionError if artifact_type or schema_version is invalid or unsupported.
    """
    if not artifact_type or not isinstance(artifact_type, str) or not artifact_type.strip():
        raise SchemaResolutionError(
            f"Artifact type must be a non-empty string, got {artifact_type!r}"
        )

    if not schema_version or not isinstance(schema_version, str) or not schema_version.strip():
        raise SchemaResolutionError(
            f"Schema version must be a non-empty string, got {schema_version!r}"
        )

    art_type = artifact_type.strip().lower()
    ver = schema_version.strip()

    key = (art_type, ver)
    if key not in SCHEMA_REGISTRY:
        supported = get_supported_schema_versions(art_type)
        if not supported:
            raise SchemaResolutionError(
                f"Unknown artifact type {artifact_type!r}. No schemas registered for this artifact type."
            )
        raise SchemaResolutionError(
            f"Unsupported schema version {ver!r} for artifact type {art_type!r}. "
            f"Supported versions for {art_type!r}: {supported}."
        )

    rel_path = SCHEMA_REGISTRY[key]
    abs_path = os.path.join(ROOT_DIR, rel_path)
    return abs_path


def load_schema_for_version(artifact_type: str, schema_version: str) -> dict[str, Any]:
    """Load JSON Schema dictionary for a given artifact type and schema version.

    Raises SchemaResolutionError or FileNotFoundError if schema file cannot be resolved/read.
    """
    abs_path = get_registered_schema_path(artifact_type, schema_version)
    if not os.path.exists(abs_path):
        raise FileNotFoundError(
            f"Registered schema file not found on disk at '{abs_path}' "
            f"for artifact '{artifact_type}' version '{schema_version}'"
        )
    with open(abs_path, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve_schema(artifact_type: str, schema_version: str) -> dict[str, Any]:
    """Explicit version-aware schema resolver alias."""
    return load_schema_for_version(artifact_type, schema_version)


__all__ = [
    "SCHEMA_REGISTRY",
    "SCHEMA_VERSION",
    "SchemaResolutionError",
    "get_registered_schema_path",
    "get_supported_schema_versions",
    "load_schema_for_version",
    "resolve_schema",
]
