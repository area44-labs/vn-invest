"""Artifact Provenance Manifest and Validation for VN Invest publishing boundary.

Provides machine-readable provenance tracking and fail-closed validation for published artifacts.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from scripts.quant.config import DEFAULT_QUANT_CONFIG

QUANT_VERSION = DEFAULT_QUANT_CONFIG.quant_version
SIGNAL_MODEL_VERSION = DEFAULT_QUANT_CONFIG.model_version

logger = logging.getLogger(__name__)

# Canonical Pipeline Software Implementation Version
PIPELINE_VERSION = "2.0.0"

# Required top-level keys in a machine-readable Provenance Manifest
REQUIRED_PROVENANCE_KEYS = (
    "data_as_of",
    "generated_at",
    "pipeline_version",
    "signal_model_version",
    "quantitative_config_version",
    "schema_version",
    "source_provider",
    "universe",
    "artifacts",
    "data_quality",
)

# Key patterns indicating potential secrets or credentials
SECRET_KEY_PATTERNS = re.compile(
    r"(api[_-]?key|secret|password|passphrase|private[_-]?key|auth[_-]?token|bearer|credential|conn[_-]?string|access[_-]?token)",
    re.IGNORECASE,
)

# Value patterns indicating potential secret tokens or private keys
SECRET_VALUE_PATTERNS = [
    re.compile(r"-----BEGIN (RSA |EC |PGP |OPENSSH )?PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"ghp_[0-9a-zA-Z]{36}"),
    re.compile(r"eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.?[A-Za-z0-9-_.+/=]*"),  # JWT token
]


class ProvenanceValidationError(ValueError):
    """Exception raised when provenance manifest fails validation."""


def detect_secrets_in_dict(target_dict: Any, path: str = "") -> list[str]:
    """Recursively inspect target_dict for potential secret key names or credential value strings.

    Returns a list of violation messages describing suspicious keys or secret patterns found.
    """
    violations: list[str] = []

    if isinstance(target_dict, dict):
        for k, v in target_dict.items():
            key_str = str(k)
            curr_path = f"{path}.{key_str}" if path else key_str

            if SECRET_KEY_PATTERNS.search(key_str):
                violations.append(
                    f"Suspicious secret key pattern '{key_str}' detected at path '{curr_path}'"
                )

            violations.extend(detect_secrets_in_dict(v, curr_path))

    elif isinstance(target_dict, (list, tuple)):
        for idx, item in enumerate(target_dict):
            curr_path = f"{path}[{idx}]"
            violations.extend(detect_secrets_in_dict(item, curr_path))

    elif isinstance(target_dict, str):
        for pat in SECRET_VALUE_PATTERNS:
            if pat.search(target_dict):
                violations.append(
                    f"Potential secret token/key value pattern detected at path '{path}'"
                )
                break

    return violations


@dataclass(frozen=True)
class ProvenanceManifest:
    """Immutable representation of machine-readable artifact provenance manifest."""

    data_as_of: str
    generated_at: str
    pipeline_version: str
    signal_model_version: str
    quantitative_config_version: dict[str, str]
    schema_version: str
    source_provider: dict[str, Any]
    universe: dict[str, Any]
    artifacts: tuple[str, ...]
    data_quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return dict representation of provenance manifest."""
        return {
            "data_as_of": self.data_as_of,
            "generated_at": self.generated_at,
            "pipeline_version": self.pipeline_version,
            "signal_model_version": self.signal_model_version,
            "quantitative_config_version": dict(self.quantitative_config_version),
            "schema_version": self.schema_version,
            "source_provider": dict(self.source_provider),
            "universe": dict(self.universe),
            "artifacts": list(self.artifacts),
            "data_quality": dict(self.data_quality),
        }

    @classmethod
    def from_dict(cls, manifest_dict: dict[str, Any]) -> ProvenanceManifest:
        """Construct ProvenanceManifest from a dictionary payload after strict validation."""
        validate_provenance_manifest(manifest_dict)

        artifacts = manifest_dict.get("artifacts")
        if isinstance(artifacts, list):
            artifacts = tuple(artifacts)
        elif not isinstance(artifacts, tuple):
            artifacts = ()

        q_cfg = manifest_dict.get("quantitative_config_version")
        q_cfg_dict = dict(q_cfg) if isinstance(q_cfg, dict) else {}

        return cls(
            data_as_of=str(manifest_dict.get("data_as_of") or ""),
            generated_at=str(manifest_dict.get("generated_at") or ""),
            pipeline_version=str(manifest_dict.get("pipeline_version") or ""),
            signal_model_version=str(manifest_dict.get("signal_model_version") or ""),
            quantitative_config_version=q_cfg_dict,
            schema_version=str(manifest_dict.get("schema_version") or ""),
            source_provider=dict(manifest_dict.get("source_provider") or {}),
            universe=dict(manifest_dict.get("universe") or {}),
            artifacts=artifacts,
            data_quality=dict(manifest_dict.get("data_quality") or {}),
        )


def validate_provenance_manifest(
    payload: dict[str, Any],
    batch_artifacts: set[str] | list[str] | tuple[str, ...] | None = None,
    canonical_data_as_of: str | None = None,
    artifacts_dict: dict[str, Any] | None = None,
) -> None:
    """Fail-closed validation of a provenance manifest payload.

    Raises ProvenanceValidationError if any requirement, format, version, data_as_of,
    batch match, artifact consistency, or secret check fails.
    """
    if not isinstance(payload, dict):
        raise ProvenanceValidationError("Provenance manifest payload must be a dictionary")

    # 1. Missing required top-level keys check
    missing_keys = [k for k in REQUIRED_PROVENANCE_KEYS if k not in payload or payload[k] is None]
    if missing_keys:
        raise ProvenanceValidationError(
            f"Provenance manifest missing required fields: {sorted(missing_keys)}"
        )

    # 2. Canonical data_as_of validation
    data_as_of = payload["data_as_of"]
    if not isinstance(data_as_of, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", data_as_of):
        raise ProvenanceValidationError(
            f"Invalid 'data_as_of' format in provenance: expected 'YYYY-MM-DD', got {data_as_of!r}"
        )

    if canonical_data_as_of is not None and data_as_of != canonical_data_as_of:
        raise ProvenanceValidationError(
            f"Provenance 'data_as_of' ({data_as_of!r}) does not match canonical pipeline date ({canonical_data_as_of!r})"
        )

    # 2b. Consistency check across ALL artifacts in artifacts_dict if provided
    if artifacts_dict is not None:
        expected_date = canonical_data_as_of or data_as_of
        for rel_path, art_payload in artifacts_dict.items():
            if (
                isinstance(art_payload, dict)
                and "data_as_of" in art_payload
                and art_payload["data_as_of"] is not None
            ):
                art_date = art_payload["data_as_of"]
                if art_date != expected_date:
                    raise ProvenanceValidationError(
                        f"Artifact '{rel_path}' data_as_of ({art_date!r}) does not match canonical date ({expected_date!r})"
                    )

    # 3. generated_at validation
    gen_at = payload["generated_at"]
    if not isinstance(gen_at, str) or not gen_at.strip():
        raise ProvenanceValidationError("Provenance 'generated_at' must be a non-empty string")
    try:
        # Check ISO timestamp format parseability
        datetime.fromisoformat(gen_at)
    except (ValueError, TypeError) as err:
        raise ProvenanceValidationError(
            f"Invalid 'generated_at' ISO timestamp format in provenance: {gen_at!r}"
        ) from err

    # 4. Version metadata fields validation
    pipe_ver = payload["pipeline_version"]
    if not isinstance(pipe_ver, str) or not pipe_ver.strip():
        raise ProvenanceValidationError("Provenance 'pipeline_version' must be a non-empty string")

    model_ver = payload["signal_model_version"]
    if not isinstance(model_ver, str) or not model_ver.strip():
        raise ProvenanceValidationError(
            "Provenance 'signal_model_version' must be a non-empty string"
        )

    schema_ver = payload["schema_version"]
    if not isinstance(schema_ver, str) or not schema_ver.strip():
        raise ProvenanceValidationError("Provenance 'schema_version' must be a non-empty string")

    try:
        from scripts.schema import load_schema_for_version

        load_schema_for_version("recommendations", schema_ver.strip())
    except Exception as err:
        raise ProvenanceValidationError(
            f"Provenance 'schema_version' {schema_ver!r} resolution failed: {err}"
        ) from err

    q_config = payload["quantitative_config_version"]
    if not isinstance(q_config, dict):
        raise ProvenanceValidationError(
            f"Provenance 'quantitative_config_version' must be a dict, got {type(q_config).__name__}"
        )

    q_ver = q_config.get("quant_version")
    cfg_hash = q_config.get("config_hash")
    if not isinstance(q_ver, str) or not q_ver.strip():
        raise ProvenanceValidationError(
            "Provenance 'quantitative_config_version.quant_version' must be a non-empty string"
        )
    if not isinstance(cfg_hash, str) or not cfg_hash.strip():
        raise ProvenanceValidationError(
            "Provenance 'quantitative_config_version.config_hash' must be a non-empty string"
        )

    # 5. Structure validation for provider, universe, and data_quality
    source_prov = payload["source_provider"]
    if not isinstance(source_prov, dict) or not source_prov:
        raise ProvenanceValidationError("Provenance 'source_provider' must be a non-empty dict")
    data_src = source_prov.get("data_source")
    if not isinstance(data_src, str) or not data_src.strip():
        raise ProvenanceValidationError(
            "Provenance 'source_provider' missing required non-empty 'data_source' string"
        )

    universe_info = payload["universe"]
    if not isinstance(universe_info, dict) or not universe_info:
        raise ProvenanceValidationError("Provenance 'universe' must be a non-empty dict")
    u_type = universe_info.get("universe_type")
    if not isinstance(u_type, str) or not u_type.strip():
        raise ProvenanceValidationError(
            "Provenance 'universe' missing required non-empty 'universe_type' string"
        )

    dq_info = payload["data_quality"]
    if not isinstance(dq_info, dict) or not dq_info:
        raise ProvenanceValidationError("Provenance 'data_quality' must be a non-empty dict")
    dq_status = dq_info.get("status")
    if not isinstance(dq_status, str) or not dq_status.strip():
        raise ProvenanceValidationError(
            "Provenance 'data_quality' missing required non-empty 'status' string"
        )
    proc_ratio = dq_info.get("processed_ratio")
    if (
        not isinstance(proc_ratio, (int, float))
        or isinstance(proc_ratio, bool)
        or not (0.0 <= float(proc_ratio) <= 1.0)
    ):
        raise ProvenanceValidationError(
            "Provenance 'data_quality' missing valid 'processed_ratio' float in [0.0, 1.0]"
        )

    # 6. Artifact list validation & batch match check
    artifacts = payload["artifacts"]
    if not isinstance(artifacts, (list, tuple)):
        raise ProvenanceValidationError(
            f"Provenance 'artifacts' must be a list or tuple of paths, got {type(artifacts).__name__}"
        )

    if not all(isinstance(p, str) and p.strip() for p in artifacts):
        raise ProvenanceValidationError(
            "All items in provenance 'artifacts' must be non-empty strings"
        )

    if batch_artifacts is not None:
        expected_batch = sorted(batch_artifacts)
        declared_batch = sorted(artifacts)
        if declared_batch != expected_batch:
            diff_missing = sorted(set(expected_batch) - set(declared_batch))
            diff_extra = sorted(set(declared_batch) - set(expected_batch))
            msg = f"Provenance 'artifacts' list {declared_batch} does not match published batch {expected_batch}."
            if diff_missing:
                msg += f" Missing in provenance: {diff_missing}."
            if diff_extra:
                msg += f" Extra in provenance: {diff_extra}."
            raise ProvenanceValidationError(msg)

    # 7. Secret and credential scanner check
    secret_violations = detect_secrets_in_dict(payload)
    if secret_violations:
        msg = f"Provenance manifest contains forbidden secrets or credentials: {'; '.join(secret_violations)}"
        logger.error(msg)
        raise ProvenanceValidationError(msg)


class ProvenanceBuilder:
    """Constructs machine-readable ProvenanceManifest instances at the publication boundary."""

    def __init__(
        self,
        data_as_of: str,
        generated_at: str,
        pipeline_version: str = PIPELINE_VERSION,
        signal_model_version: str = SIGNAL_MODEL_VERSION,
        quant_version: str = QUANT_VERSION,
        config_hash: str | None = None,
        schema_version: str = "2.0",
        source_provider: dict[str, Any] | None = None,
        universe: dict[str, Any] | None = None,
        artifacts: list[str] | tuple[str, ...] | None = None,
        data_quality: dict[str, Any] | None = None,
    ):
        self.data_as_of = data_as_of
        self.generated_at = generated_at
        self.pipeline_version = pipeline_version
        self.signal_model_version = signal_model_version
        self.quant_version = quant_version
        self.config_hash = config_hash or DEFAULT_QUANT_CONFIG.get_config_hash()
        self.schema_version = schema_version
        self.source_provider = source_provider or {}
        self.universe = universe or {}
        self.artifacts = tuple(sorted(artifacts)) if artifacts else ()
        self.data_quality = data_quality or {}

    @classmethod
    def from_context(
        cls,
        context: Any,
        batch_artifacts: list[str] | set[str] | tuple[str, ...] | None = None,
    ) -> ProvenanceBuilder:
        """Build ProvenanceBuilder from a PipelineContext instance."""
        data_as_of = getattr(context, "data_as_of", None)
        if (
            not data_as_of
            or not isinstance(data_as_of, str)
            or not re.match(r"^\d{4}-\d{2}-\d{2}$", data_as_of)
        ):
            raise ProvenanceValidationError(
                f"PipelineContext missing valid canonical 'data_as_of' date (got {data_as_of!r})"
            )

        generated_at = getattr(context, "generated_at", None) or datetime.now(UTC).isoformat()

        pipe_ver = getattr(context, "pipeline_version", None) or PIPELINE_VERSION
        rec_payload = getattr(context, "recommendations_payload", {}) or {}

        sig_model_ver = rec_payload.get("signal_model_version") or SIGNAL_MODEL_VERSION
        q_ver = rec_payload.get("quant_version") or QUANT_VERSION
        cfg_hash = rec_payload.get("config_hash") or DEFAULT_QUANT_CONFIG.get_config_hash()
        schema_ver = rec_payload.get("schema_version")

        source_provider = {
            "data_source": getattr(context, "data_source", None) or "REAL_DATA",
            "vn_source": getattr(context, "vn_source", None),
            "vn30_source": getattr(context, "vn30_source", None),
        }

        if getattr(context, "universe", None) is not None:
            u_info = context.universe.to_info_dict()
        else:
            u_info = rec_payload.get("universe_info", {}) or {}

        if (
            not isinstance(u_info, dict)
            or "universe_type" not in u_info
            or not u_info.get("universe_type")
        ):
            u_info = {
                "universe_type": "MARKET",
                "universe_size": len(getattr(context, "expected_symbols", set())),
            }

        u_audit = getattr(context, "universe_audit", {}) or {}

        data_quality = {
            "status": u_audit.get("status") or "SUCCESS",
            "processed_ratio": float(
                u_audit.get(
                    "processed_ratio",
                    1.0 if getattr(context, "processed_symbols", None) else 0.0,
                )
            ),
            "processed_count": len(getattr(context, "processed_symbols", set())),
            "expected_count": len(getattr(context, "expected_symbols", set())),
            "invalid_count": len(getattr(context, "invalid_symbols", set())),
            "insufficient_count": len(getattr(context, "insufficient_history_symbols", set())),
            "failed_count": len(getattr(context, "failed_symbols", set())),
            "missing_count": len(getattr(context, "missing_symbols", set())),
        }

        artifacts_list = list(batch_artifacts) if batch_artifacts else []

        return cls(
            data_as_of=data_as_of,
            generated_at=generated_at,
            pipeline_version=pipe_ver,
            signal_model_version=sig_model_ver,
            quant_version=q_ver,
            config_hash=cfg_hash,
            schema_version=schema_ver,
            source_provider=source_provider,
            universe=u_info,
            artifacts=artifacts_list,
            data_quality=data_quality,
        )

    def set_artifacts(
        self, batch_artifacts: list[str] | set[str] | tuple[str, ...]
    ) -> ProvenanceBuilder:
        """Update batch artifacts in builder."""
        self.artifacts = tuple(sorted(batch_artifacts))
        return self

    def build(self) -> ProvenanceManifest:
        """Build frozen ProvenanceManifest instance and validate it."""
        manifest = ProvenanceManifest(
            data_as_of=self.data_as_of,
            generated_at=self.generated_at,
            pipeline_version=self.pipeline_version,
            signal_model_version=self.signal_model_version,
            quantitative_config_version={
                "quant_version": self.quant_version,
                "config_hash": self.config_hash,
            },
            schema_version=self.schema_version,
            source_provider=self.source_provider,
            universe=self.universe,
            artifacts=self.artifacts,
            data_quality=self.data_quality,
        )

        validate_provenance_manifest(
            manifest.to_dict(),
            batch_artifacts=set(self.artifacts) if self.artifacts else None,
            canonical_data_as_of=self.data_as_of,
        )

        return manifest


__all__ = [
    "PIPELINE_VERSION",
    "REQUIRED_PROVENANCE_KEYS",
    "ProvenanceBuilder",
    "ProvenanceManifest",
    "ProvenanceValidationError",
    "detect_secrets_in_dict",
    "validate_provenance_manifest",
]
