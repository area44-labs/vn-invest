"""Rollback and recovery handling for artifact publishing transactions."""

import json
import logging
import os
import shutil

from scripts.artifacts.transaction import GENERATED_DIR, ArtifactLock, ArtifactTransactionError

logger = logging.getLogger(__name__)


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


def recover_interrupted_publish(target_dir: str | None = None) -> None:
    """Recover target_dir from interrupted atomic publish under single-writer lock."""
    if target_dir is None:
        target_dir = GENERATED_DIR

    target_dir = os.path.abspath(target_dir)

    with ArtifactLock(target_dir):
        recover_transaction_state(target_dir)


__all__ = [
    "recover_interrupted_publish",
    "recover_transaction_state",
    "validate_journal_metadata",
]
