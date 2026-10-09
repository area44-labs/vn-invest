"""Metric extraction, normalization, and classification utilities for monitoring."""

import math
from datetime import UTC, datetime
from typing import Any

from scripts.monitoring.models import CANONICAL_CONFIDENCE_BUCKETS


def is_canonical_yyyy_mm_dd(value: Any) -> bool:
    """Validate if a value is strictly a canonical YYYY-MM-DD calendar date string.

    Rejects booleans, non-strings, single-digit months/days, time components,
    timezone offsets/suffixes, and invalid calendar dates.
    """
    if not isinstance(value, str) or isinstance(value, bool):
        return False
    if len(value) != 10:
        return False
    parts = value.split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        return False
    if not (parts[0].isdigit() and parts[1].isdigit() and parts[2].isdigit()):
        return False
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
        return dt.strftime("%Y-%m-%d") == value
    except ValueError:
        return False


def normalize_market_payload(market_payload: Any, data_as_of: str | None = None) -> dict[str, Any]:
    """Normalize raw market payload into a canonical dictionary shape.

    Canonical Shape:
    {
        "data_as_of": <date_str>,
        "market": {
            "regime": ...,
            "confidence": ...,
            "metrics": { ... },
            ...
        }
    }
    """
    if not isinstance(market_payload, dict):
        return {"data_as_of": data_as_of, "market": {}}

    payload_date = market_payload.get("data_as_of")
    if (
        not payload_date
        and "market" in market_payload
        and isinstance(market_payload["market"], dict)
    ):
        payload_date = market_payload["market"].get("data_as_of")

    resolved_date = payload_date or data_as_of

    if "market" in market_payload and isinstance(market_payload["market"], dict):
        inner_market = dict(market_payload["market"])
    else:
        inner_market = dict(market_payload)

    inner_market.pop("data_as_of", None)

    return {
        "data_as_of": resolved_date,
        "market": inner_market,
    }


def classify_confidence_bucket(conf: float | None) -> str | None:
    """Classify numeric confidence score [0.0..1.0] into canonical bucket string."""
    if conf is None:
        return None
    if isinstance(conf, bool) or not isinstance(conf, (int, float)):
        raise TypeError(f"Confidence score must be numeric or None, got {type(conf).__name__}")
    if math.isnan(conf) or math.isinf(conf):
        raise ValueError(f"Invalid non-finite confidence score: {conf}")
    if not (0.0 <= conf <= 1.0):
        raise ValueError(f"Confidence score out of bounds [0.0..1.0]: {conf}")

    if conf == 1.0:
        return "0.9-1.0"

    bucket_idx = min(int(conf * 10), 9)
    lower = bucket_idx / 10.0
    upper = (bucket_idx + 1) / 10.0
    return f"{lower:.1f}-{upper:.1f}"


def _extract_market_metrics(
    market_payload: dict | None, fallback_payload: dict | None
) -> tuple[str | None, float | None, float | None]:
    """Extract (regime, vnindex_change_pct, market_breadth_ratio) prioritizing market_payload."""
    m_source = (
        market_payload
        if market_payload is not None
        else (fallback_payload.get("market", {}) if isinstance(fallback_payload, dict) else {})
    )

    if not isinstance(m_source, dict):
        return None, None, None

    if "market" in m_source and isinstance(m_source["market"], dict):
        m_source = m_source["market"]

    regime = m_source.get("regime")
    m_metrics = m_source.get("metrics", {})
    if not isinstance(m_metrics, dict):
        m_metrics = {}

    vnindex_change_pct = m_metrics.get("vnindex_change_pct")
    if vnindex_change_pct is not None:
        if isinstance(vnindex_change_pct, bool) or not isinstance(vnindex_change_pct, (int, float)):
            raise TypeError(
                f"vnindex_change_pct must be numeric, got {type(vnindex_change_pct).__name__}"
            )
        f_vn = float(vnindex_change_pct)
        if math.isnan(f_vn) or math.isinf(f_vn):
            raise ValueError(f"vnindex_change_pct must be finite, got {f_vn}")
        vnindex_change_pct = f_vn

    market_breadth_ratio = m_metrics.get("market_breadth_ratio")
    if market_breadth_ratio is not None:
        if isinstance(market_breadth_ratio, bool) or not isinstance(
            market_breadth_ratio, (int, float)
        ):
            raise TypeError(
                f"market_breadth_ratio must be numeric, got {type(market_breadth_ratio).__name__}"
            )
        f_b = float(market_breadth_ratio)
        if math.isnan(f_b) or math.isinf(f_b):
            raise ValueError(f"market_breadth_ratio must be finite, got {f_b}")
        if not (0.0 <= f_b <= 1.0):
            raise ValueError(f"market_breadth_ratio out of bounds [0.0, 1.0]: {f_b}")
        market_breadth_ratio = f_b

    return regime, vnindex_change_pct, market_breadth_ratio


def extract_recommendation_metrics(
    payload: dict, market_payload: dict | None = None
) -> dict[str, Any]:
    """Extract operational distribution and numeric metrics from a recommendation report payload.

    Market metrics (vnindex_change_pct, market_breadth_ratio) strictly prioritize market_payload
    when provided, falling back to payload.get("market") only when market_payload is None.

    Fails closed by raising ValueError or TypeError if payload, summary, recommendations items,
    or model metrics are malformed or non-finite.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"Payload must be a dict, got {type(payload).__name__}")

    recs = payload.get("recommendations")
    if not isinstance(recs, list):
        raise TypeError(f"Recommendations must be a list, got {type(recs).__name__}")

    # 1. Validate each recommendation item
    valid_actions = {"BUY", "WATCH", "HOLD", "SELL", "AVOID"}
    for idx, r in enumerate(recs):
        if not isinstance(r, dict):
            raise TypeError(
                f"Recommendation item at index {idx} must be a dict, got {type(r).__name__}"
            )
        act = r.get("action")
        if not isinstance(act, str) or isinstance(act, bool) or act not in valid_actions:
            raise ValueError(
                f"Recommendation item at index {idx} has missing or invalid action: {act}"
            )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise TypeError(f"Summary must be a dict, got {type(summary).__name__}")

    # 2. Validate summary consistency
    total_scanned = summary.get("total_scanned")
    if isinstance(total_scanned, bool) or not isinstance(total_scanned, int) or total_scanned < 0:
        raise ValueError(
            f"Invalid summary total_scanned: {total_scanned}. Must be non-boolean non-negative integer"
        )

    if total_scanned != len(recs):
        raise ValueError(
            f"Summary total_scanned ({total_scanned}) does not match recommendations list count ({len(recs)})"
        )

    action_counts = {}
    for act_key, count_field in [
        ("BUY", "buy_count"),
        ("WATCH", "watch_count"),
        ("HOLD", "hold_count"),
        ("SELL", "sell_count"),
        ("AVOID", "avoid_count"),
    ]:
        cnt = summary.get(count_field)
        if isinstance(cnt, bool) or not isinstance(cnt, int) or cnt < 0:
            raise ValueError(
                f"Invalid summary {count_field}: {cnt}. Must be non-boolean non-negative integer"
            )
        action_counts[act_key] = cnt

    sum_action_counts = sum(action_counts.values())
    if sum_action_counts != total_scanned:
        raise ValueError(
            f"Summary action counts sum ({sum_action_counts}) does not equal total_scanned ({total_scanned})"
        )

    actual_action_counts = {act: 0 for act in valid_actions}
    for r in recs:
        actual_action_counts[r["action"]] += 1

    for act, expected_cnt in action_counts.items():
        actual_cnt = actual_action_counts[act]
        if actual_cnt != expected_cnt:
            raise ValueError(
                f"Summary action count mismatch for {act}: summary={expected_cnt} vs actual={actual_cnt}"
            )

    if total_scanned > 0:
        action_proportions = {
            act: round(cnt / total_scanned, 6) for act, cnt in action_counts.items()
        }
    else:
        action_proportions = {act: 0.0 for act in action_counts}

    for act, prop in action_proportions.items():
        if not (0.0 <= prop <= 1.0):
            raise ValueError(
                f"Action proportion for {act} ({prop}) is outside allowed bounds [0.0, 1.0]"
            )

    processed_count = sum(1 for r in recs if r.get("data_quality") in ("SUFFICIENT", "PARTIAL"))
    processed_ratio = round(processed_count / total_scanned, 6) if total_scanned > 0 else 0.0

    # 3. Validate confidence, signal_score, and risk_adjusted_score on each recommendation item
    conf_counts = {b: 0 for b in CANONICAL_CONFIDENCE_BUCKETS}
    valid_conf_vals = []
    sig_scores = []
    risk_scores = []

    for idx, r in enumerate(recs):
        sym = r.get("symbol", f"item_{idx}")

        conf = r.get("confidence")
        if conf is not None:
            if isinstance(conf, bool) or not isinstance(conf, (int, float)):
                raise TypeError(
                    f"Confidence score for '{sym}' must be numeric, got {type(conf).__name__}"
                )
            f_conf = float(conf)
            if math.isnan(f_conf) or math.isinf(f_conf):
                raise ValueError(f"Confidence score for '{sym}' must be finite, got {f_conf}")
            if not (0.0 <= f_conf <= 1.0):
                raise ValueError(f"Confidence score for '{sym}' out of bounds [0.0, 1.0]: {f_conf}")
            bucket = classify_confidence_bucket(f_conf)
            if bucket in conf_counts:
                conf_counts[bucket] += 1
                valid_conf_vals.append(f_conf)

        ss = r.get("signal_score")
        if ss is not None:
            if isinstance(ss, bool) or not isinstance(ss, (int, float)):
                raise TypeError(
                    f"Signal score for '{sym}' must be numeric, got {type(ss).__name__}"
                )
            f_ss = float(ss)
            if math.isnan(f_ss) or math.isinf(f_ss):
                raise ValueError(f"Signal score for '{sym}' must be finite, got {f_ss}")
            sig_scores.append(f_ss)

        rs = r.get("risk_adjusted_score")
        if rs is not None:
            if isinstance(rs, bool) or not isinstance(rs, (int, float)):
                raise TypeError(
                    f"Risk-adjusted score for '{sym}' must be numeric, got {type(rs).__name__}"
                )
            f_rs = float(rs)
            if math.isnan(f_rs) or math.isinf(f_rs):
                raise ValueError(f"Risk-adjusted score for '{sym}' must be finite, got {f_rs}")
            risk_scores.append(f_rs)

    total_valid_conf = len(valid_conf_vals)
    if total_valid_conf > 0:
        conf_bucket_proportions = {
            b: round(conf_counts[b] / total_valid_conf, 6) for b in CANONICAL_CONFIDENCE_BUCKETS
        }
    else:
        conf_bucket_proportions = {b: 0.0 for b in CANONICAL_CONFIDENCE_BUCKETS}

    sig_mean = round(sum(sig_scores) / len(sig_scores), 4) if sig_scores else None
    sig_median = round(sorted(sig_scores)[len(sig_scores) // 2], 4) if sig_scores else None

    risk_mean = round(sum(risk_scores) / len(risk_scores), 4) if risk_scores else None
    risk_median = round(sorted(risk_scores)[len(risk_scores) // 2], 4) if risk_scores else None

    conf_mean = round(sum(valid_conf_vals) / len(valid_conf_vals), 4) if valid_conf_vals else None

    regime, vnindex_change_pct, market_breadth_ratio = _extract_market_metrics(
        market_payload, payload
    )

    return {
        "total_scanned": total_scanned,
        "processed_count": processed_count,
        "processed_ratio": processed_ratio,
        "action_counts": action_counts,
        "action_proportions": action_proportions,
        "confidence_bucket_counts": conf_counts,
        "confidence_bucket_proportions": conf_bucket_proportions,
        "signal_score_mean": sig_mean,
        "signal_score_median": sig_median,
        "risk_adjusted_score_mean": risk_mean,
        "risk_adjusted_score_median": risk_median,
        "confidence_mean": conf_mean,
        "market_regime": regime,
        "vnindex_change_pct": vnindex_change_pct,
        "market_breadth_ratio": market_breadth_ratio,
    }


__all__ = [
    "_extract_market_metrics",
    "classify_confidence_bucket",
    "extract_recommendation_metrics",
    "is_canonical_yyyy_mm_dd",
    "normalize_market_payload",
]
