"""Schema registry module."""

from scripts.schema.registry import (
    SCHEMA_REGISTRY,
    SCHEMA_VERSION,
    SchemaResolutionError,
    get_registered_schema_path,
    get_supported_schema_versions,
    load_schema_for_version,
    resolve_schema,
)

__all__ = [
    "SCHEMA_REGISTRY",
    "SCHEMA_VERSION",
    "SchemaResolutionError",
    "get_registered_schema_path",
    "get_supported_schema_versions",
    "load_schema_for_version",
    "resolve_schema",
]
