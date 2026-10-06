"""Adapter and re-export wrapper for artifact publishing subsystem.

Maintains 100% backward compatibility for imports from scripts.pipeline.publishing.
Actual implementation resides in scripts.artifacts.
"""

from scripts.artifacts import (
    PIPELINE_VERSION,
    REQUIRED_PROVENANCE_KEYS,
    SCHEMA_VERSION,
    ArtifactLock,
    ArtifactLockError,
    ArtifactManifest,
    ArtifactManifestBuilder,
    ArtifactPublisher,
    ArtifactTransaction,
    ArtifactTransactionError,
    ProvenanceBuilder,
    ProvenanceManifest,
    ProvenanceValidationError,
    detect_secrets_in_dict,
    load_history_index,
    publish_artifacts_atomically,
    recover_interrupted_publish,
    recover_transaction_state,
    save_json_files,
    update_history_index,
    validate_journal_metadata,
    validate_provenance_manifest,
)

__all__ = [
    "PIPELINE_VERSION",
    "REQUIRED_PROVENANCE_KEYS",
    "SCHEMA_VERSION",
    "ArtifactLock",
    "ArtifactLockError",
    "ArtifactManifest",
    "ArtifactManifestBuilder",
    "ArtifactPublisher",
    "ArtifactTransaction",
    "ArtifactTransactionError",
    "ProvenanceBuilder",
    "ProvenanceManifest",
    "ProvenanceValidationError",
    "detect_secrets_in_dict",
    "load_history_index",
    "publish_artifacts_atomically",
    "recover_interrupted_publish",
    "recover_transaction_state",
    "save_json_files",
    "update_history_index",
    "validate_journal_metadata",
    "validate_provenance_manifest",
]
