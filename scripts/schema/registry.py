"""Canonical Schema Version Registry and Version Contract for VN Invest artifacts.

Provides single canonical source for SCHEMA_VERSION, schema path resolution, and schema loading.
Has zero dependencies on scripts.pipeline, scripts.artifacts, or scripts.lib to prevent circular imports.
"""

import json
import os

# Canonical Schema Version Contract
SCHEMA_VERSION = "2.0"

# Root directory of the repository
_ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Single Canonical Mapping: (schema_type, schema_version) -> absolute schema file path
_SCHEMA_FILES: dict[tuple[str, str], str] = {
    ("recommendations", "2.0"): os.path.join(
        _ROOT_DIR, "schemas", "v2", "recommendations.schema.json"
    ),
    ("performance", "2.0"): os.path.join(
        _ROOT_DIR, "schemas", "v2", "performance.schema.json"
    ),
}

# Derived SCHEMA_REGISTRY mapping schema_version -> {schema_type: schema_path}
SCHEMA_REGISTRY: dict[str, dict[str, str]] = {}
for (_stype, _ver), _path in _SCHEMA_FILES.items():
    if _ver not in SCHEMA_REGISTRY:
        SCHEMA_REGISTRY[_ver] = {}
    SCHEMA_REGISTRY[_ver][_stype] = _path


def get_supported_schema_versions(schema_type: str = "recommendations") -> set[str]:
    """Return set of registered supported schema versions for a given schema type."""
    return {ver for (stype, ver) in _SCHEMA_FILES if stype == schema_type}


def get_registered_schema_path(
    schema_type: str = "recommendations", version: str | None = None
) -> str:
    """Return schema file path for a registered (schema_type, version) pair or raise ValueError."""
    target_version = version or SCHEMA_VERSION
    if not isinstance(schema_type, str) or not schema_type.strip():
        raise ValueError("schema_type must be a non-empty string")
    if not isinstance(target_version, str) or not target_version.strip():
        raise ValueError("schema_version must be a non-empty string")

    key = (schema_type, target_version)
    if key not in _SCHEMA_FILES:
        supported = sorted(get_supported_schema_versions(schema_type))
        raise ValueError(
            f"Unsupported schema_version '{target_version}' for schema type '{schema_type}'. "
            f"Supported versions: {supported}"
        )

    path = _SCHEMA_FILES[key]
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Registered schema file for '{schema_type}' version '{target_version}' not found at '{path}'"
        )
    return path


def load_schema_for_version(
    schema_type: str = "recommendations", version: str | None = None
) -> dict:
    """Load and parse JSON Schema Draft 2020-12 for a specific schema type and version."""
    if version is None and (schema_type[0].isdigit() if schema_type else False):
        target_type = "recommendations"
        target_version = schema_type
    else:
        target_type = schema_type or "recommendations"
        target_version = version or SCHEMA_VERSION

    path = get_registered_schema_path(target_type, target_version)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


__all__ = [
    "SCHEMA_REGISTRY",
    "SCHEMA_VERSION",
    "get_registered_schema_path",
    "get_supported_schema_versions",
    "load_schema_for_version",
]
