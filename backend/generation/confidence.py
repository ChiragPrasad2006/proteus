"""Deterministic Evidence & Confidence Engine for personalization (Layer 4C)."""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

VALID_AUDIENCES = ("1on1_private", "group_cc", "broadcast_bcc")


@dataclass(frozen=True)
class ConfidenceThresholds:
    """Configurable thresholds for confidence-aware personalization."""

    min_usable_similarity: float = 0.35
    high_min_examples: int = 3
    high_min_similarity: float = 0.55
    recent_window_days: float = 90.0


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    for method_name in ("model_dump", "dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            try:
                result = method()
                if isinstance(result, dict):
                    return dict(result)
            except Exception:
                pass
    return {}


def _same_account(record: dict[str, Any], account_id: str | None) -> bool:
    if not account_id:
        return True
    tagged = record.get("account_id")
    return not tagged or str(tagged) == str(account_id)


def _example_audience(example: dict[str, Any]) -> str:
    mode = example.get("audience_mode")
    if mode in VALID_AUDIENCES:
        return str(mode)
    try:
        bcc_count = int(example.get("bcc_count") or 0)
        cc_count = int(example.get("cc_count") or 0)
    except (TypeError, ValueError):
        bcc_count = cc_count = 0
    if bcc_count > 0:
        return "broadcast_bcc"
    if cc_count > 0:
        return "group_cc"
    return "1on1_private"


def _extract_similarity(example: dict[str, Any]) -> float:
    """Extract heuristic semantic similarity in [0.0, 1.0]."""
    for key in ("similarity", "cos_sim", "score"):
        val = example.get(key)
        if val is not None:
            try:
                return max(0.0, min(1.0, float(val)))
            except (TypeError, ValueError):
                pass
    dist = example.get("_distance")
    if dist is not None:
        try:
            # LanceDB returns squared L2 distance (l2_sq = 2 * (1 - cos_sim)) for unit vectors.
            return max(0.0, min(1.0, 1.0 - (float(dist) / 2.0)))
        except (TypeError, ValueError):
            pass
    # Synthetic examples without explicit score fields default to usable.
    return 0.6


def _extract_age_days(example: dict[str, Any], now_epoch: float) -> float | None:
    """Extract example age in days; return None if timestamp is missing/invalid."""
    age_val = example.get("age_days")
    if age_val is not None:
        try:
            return max(0.0, float(age_val))
        except (TypeError, ValueError):
            pass
    epoch_val = example.get("timestamp_epoch")
    if epoch_val is not None:
        try:
            ep = float(epoch_val)
            if ep > 0:
                return max(0.0, (now_epoch - ep) / 86400.0)
        except (TypeError, ValueError):
            pass
    ts_str = str(example.get("timestamp") or "").strip()
    if ts_str:
        try:
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max(0.0, (now_epoch - dt.timestamp()) / 86400.0)
        except Exception:
            pass
    return None


def assess_personalization_confidence(
    retrieved_emails: list[Any] | None,
    audience_type: str,
    account_id: str | None = None,
    thresholds: ConfidenceThresholds | None = None,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Evaluate retrieved evidence strength for the resolved audience."""
    cfg = thresholds or ConfidenceThresholds()
    now_ts = now_epoch if now_epoch is not None else datetime.now(timezone.utc).timestamp()

    matched: list[dict[str, Any]] = []
    mismatched_count = 0

    for raw in retrieved_emails or []:
        ex = _as_dict(raw)
        if not _same_account(ex, account_id):
            continue
        if _example_audience(ex) == audience_type:
            matched.append(ex)
        else:
            mismatched_count += 1

    matched_sims = [_extract_similarity(ex) for ex in matched]
    usable = [ex for ex, sim in zip(matched, matched_sims) if sim >= cfg.min_usable_similarity]
    usable_ages = [
        age for age in (_extract_age_days(ex, now_ts) for ex in usable) if age is not None
    ]

    usable_count = len(usable)
    matched_count = len(matched)
    top_sim = round(max(matched_sims), 4) if matched_sims else None
    avg_sim = round(sum(matched_sims) / len(matched_sims), 4) if matched_sims else None
    newest_age = round(min(usable_ages), 2) if usable_ages else None
    median_age = round(statistics.median(usable_ages), 2) if usable_ages else None

    # Strict non-compensatory confidence rules
    if matched_count == 0 or usable_count == 0:
        level = "low"
        fallback_applied = True
        if matched_count == 0:
            reason = f"No audience-matched examples for {audience_type}."
        else:
            reason = "Retrieved audience-matched examples fell below minimum usable similarity."
    elif (
        usable_count >= cfg.high_min_examples
        and avg_sim is not None
        and avg_sim >= cfg.high_min_similarity
        and newest_age is not None
        and newest_age <= cfg.recent_window_days
    ):
        level = "high"
        fallback_applied = False
        reason = f"{usable_count} recent, relevant {audience_type} examples."
    else:
        level = "medium"
        fallback_applied = False
        if usable_count < cfg.high_min_examples:
            reason = f"Limited evidence: {usable_count} usable {audience_type} example(s)."
        elif newest_age is None or newest_age > cfg.recent_window_days:
            reason = f"Stale or undated evidence for {audience_type}."
        else:
            reason = f"Mixed relevance across {usable_count} {audience_type} examples."

    return {
        "level": level,
        "reason": reason,
        "fallback_applied": fallback_applied,
        "signals": {
            "usable_example_count": usable_count,
            "audience_matched_count": matched_count,
            "audience_mismatched_count": mismatched_count,
            "top_similarity": top_sim,
            "avg_similarity": avg_sim,
            "newest_age_days": newest_age,
            "median_age_days": median_age,
        },
    }


__all__ = ["ConfidenceThresholds", "assess_personalization_confidence"]
