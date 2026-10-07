"""Artifact publisher orchestrating validation, manifest building, atomic transactions, and recovery."""

import logging
import os
import shutil

from scripts.artifacts.manifest import ArtifactManifest, ArtifactManifestBuilder
from scripts.artifacts.provenance import (
    ProvenanceValidationError,
    validate_provenance_manifest,
)
from scripts.artifacts.transaction import GENERATED_DIR, ArtifactLock, ArtifactTransaction

logger = logging.getLogger(__name__)


class ArtifactPublisher:
    """Orchestrates artifact publication: Validation -> Manifest -> Atomic Transaction -> Published Location."""

    def __init__(
        self,
        target_dir: str | None = None,
        strict_provenance: bool = True,
        canonical_data_as_of: str | None = None,
    ):
        self.target_dir = os.path.abspath(target_dir if target_dir is not None else GENERATED_DIR)
        self.strict_provenance = strict_provenance
        self.canonical_data_as_of = canonical_data_as_of

    def validate_artifact(self, relative_path: str, payload: dict) -> None:
        """Validate artifact payload prior to publication.

        Publisher strictly validates without altering quantitative results or investment signals.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"Artifact '{relative_path}' payload must be a dict")

        if relative_path == "provenance.json":
            validate_provenance_manifest(payload)
            return

        from scripts.pipeline.validation import (
            validate_final_payload_integrity,
            validate_performance_payload,
        )
        from scripts.schema import SchemaResolutionError, load_schema_for_version

        schema_to_use = None

        if relative_path == "performance.json" or ("stages" in payload and "provider" in payload):
            schema_ver = payload.get("schema_version")
            if not schema_ver or not isinstance(schema_ver, str) or not schema_ver.strip():
                raise SchemaResolutionError(
                    f"Artifact '{relative_path}' is missing required non-empty 'schema_version'"
                )
            validate_performance_payload(payload)
            return

        if (
            relative_path in ("recommendations.json",) or relative_path.startswith("history/20")
        ) or ("recommendations" in payload):
            schema_ver = payload.get("schema_version")
            if not schema_ver or not isinstance(schema_ver, str) or not schema_ver.strip():
                raise SchemaResolutionError(
                    f"Artifact '{relative_path}' is missing required non-empty 'schema_version'"
                )
            schema_to_use = load_schema_for_version("recommendations", schema_ver.strip())

        validate_final_payload_integrity(payload, schema=schema_to_use, payload_name=relative_path)

    def publish(
        self,
        artifacts: dict[str, dict] | ArtifactManifest,
        canonical_data_as_of: str | None = None,
    ) -> ArtifactManifest:
        """Publish artifacts through full publishing pipeline under single-writer lock.

        Guarantees publication flow: Domain Results -> Schema Validation -> Manifest -> Atomic Transaction -> Published Artifacts.
        """
        if isinstance(artifacts, ArtifactManifest):
            manifest = artifacts
        elif isinstance(artifacts, dict):
            builder = ArtifactManifestBuilder(target_dir=self.target_dir)
            for rel_path, payload in artifacts.items():
                builder.add_artifact(rel_path, payload)
            manifest = builder.build()
        else:
            raise TypeError("artifacts must be a dict or ArtifactManifest instance")

        # Step 1: Pre-publish schema and payload integrity validation of all manifest artifacts
        for rel_path, payload in manifest.artifacts.items():
            self.validate_artifact(rel_path, payload)

        # Step 1b: Pre-publish batch-level data_as_of consistency check across ALL artifacts
        effective_canonical_date = canonical_data_as_of or self.canonical_data_as_of

        artifact_dates: dict[str, str] = {}
        for rel_path, payload in manifest.artifacts.items():
            if (
                isinstance(payload, dict)
                and "data_as_of" in payload
                and payload["data_as_of"] is not None
            ):
                artifact_dates[rel_path] = str(payload["data_as_of"])

        if effective_canonical_date is None:
            distinct_dates = set(artifact_dates.values())
            if len(distinct_dates) > 1:
                raise ProvenanceValidationError(
                    f"Conflicting 'data_as_of' dates detected across artifacts in published batch: {artifact_dates}"
                )
            if len(distinct_dates) == 1:
                effective_canonical_date = next(iter(distinct_dates))

        if effective_canonical_date is not None:
            for rel_path, art_date in artifact_dates.items():
                if art_date != effective_canonical_date:
                    raise ProvenanceValidationError(
                        f"Artifact '{rel_path}' data_as_of ({art_date!r}) does not match canonical date ({effective_canonical_date!r})"
                    )

        # Step 1c: Pre-publish provenance manifest validation
        batch_paths = set(manifest.artifacts.keys())

        if "provenance.json" in manifest.artifacts:
            validate_provenance_manifest(
                manifest.artifacts["provenance.json"],
                batch_artifacts=batch_paths,
                canonical_data_as_of=effective_canonical_date,
                artifacts_dict=manifest.artifacts,
            )
        elif self.strict_provenance:
            raise ProvenanceValidationError(
                "Missing required provenance manifest artifact 'provenance.json' in publication batch"
            )

        # Step 2: Acquire single-writer lock and execute atomic transaction
        target_dir = os.path.abspath(manifest.target_dir)

        with ArtifactLock(target_dir):
            txn = ArtifactTransaction(target_dir)
            try:
                txn.execute_publish(manifest.artifacts)
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
                            "Failed restoring target directory from backup during rollback: %s",
                            r_err,
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
                    err_msg = (
                        "; ".join(rollback_errors) if rollback_errors else "Target not restored"
                    )
                    logger.critical(
                        "CRITICAL: Directory-level atomic artifact rollback failed: %s", err_msg
                    )
                    raise RuntimeError(
                        f"CRITICAL: Directory-level atomic artifact publish rollback failed: {err_msg}"
                    ) from exc

                raise

        return manifest


def publish_artifacts_atomically(
    artifacts: dict[str, dict] | ArtifactManifest,
    target_dir: str | None = None,
    strict_provenance: bool = True,
    canonical_data_as_of: str | None = None,
) -> ArtifactManifest:
    """Publish multiple JSON artifacts or ArtifactManifest atomically using ArtifactPublisher."""
    publisher = ArtifactPublisher(
        target_dir=target_dir,
        strict_provenance=strict_provenance,
        canonical_data_as_of=canonical_data_as_of,
    )
    return publisher.publish(artifacts, canonical_data_as_of=canonical_data_as_of)


__all__ = [
    "ArtifactPublisher",
    "publish_artifacts_atomically",
]
