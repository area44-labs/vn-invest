"""Artifact publisher orchestrating validation, manifest building, atomic transactions, and recovery."""

import logging
import os
import shutil

from scripts.artifacts.manifest import ArtifactManifest
from scripts.artifacts.transaction import GENERATED_DIR, ArtifactLock, ArtifactTransaction

logger = logging.getLogger(__name__)


class ArtifactPublisher:
    """Orchestrates artifact publication: Validation -> Manifest -> Atomic Transaction -> Published Location."""

    def __init__(
        self,
        target_dir: str | None = None,
        schema: dict | None = None,
        validate_schema: bool = False,
    ):
        self.target_dir = os.path.abspath(target_dir if target_dir is not None else GENERATED_DIR)
        self.schema = schema
        self.validate_schema = validate_schema

    def validate_artifact(self, relative_path: str, payload: dict) -> None:
        """Validate artifact payload prior to publication.

        Publisher strictly validates without altering quantitative results or investment signals.
        """
        if not isinstance(payload, dict):
            raise TypeError(f"Artifact '{relative_path}' payload must be a dict")

        from scripts.pipeline.validation import load_schema, validate_final_payload_integrity

        schema_to_use = None
        if self.schema is not None:
            schema_to_use = self.schema
        elif self.validate_schema and (
            relative_path in ("recommendations.json",) or relative_path.startswith("history/20")
        ):
            schema_to_use = load_schema()

        validate_final_payload_integrity(payload, schema=schema_to_use, payload_name=relative_path)

    def publish(self, artifacts: dict[str, dict] | ArtifactManifest) -> None:
        """Publish artifacts through full publishing pipeline under single-writer lock."""
        if isinstance(artifacts, ArtifactManifest):
            artifact_map = artifacts.artifacts
            target_dir = artifacts.target_dir
        elif isinstance(artifacts, dict):
            artifact_map = artifacts
            target_dir = self.target_dir
        else:
            raise TypeError("artifacts must be a dict or ArtifactManifest instance")

        # Step 1: Pre-publish validation of all artifacts
        for rel_path, payload in artifact_map.items():
            self.validate_artifact(rel_path, payload)

        # Step 2: Acquire lock and execute atomic transaction
        target_dir = os.path.abspath(target_dir)

        with ArtifactLock(target_dir):
            txn = ArtifactTransaction(target_dir)
            try:
                txn.execute_publish(artifact_map)
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


def publish_artifacts_atomically(artifacts: dict[str, dict], target_dir: str | None = None) -> None:
    """Publish multiple JSON artifacts atomically using ArtifactPublisher."""
    publisher = ArtifactPublisher(target_dir=target_dir)
    publisher.publish(artifacts)


__all__ = [
    "ArtifactPublisher",
    "publish_artifacts_atomically",
]
