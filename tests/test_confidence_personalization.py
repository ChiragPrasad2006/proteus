"""Offline unit tests for Layer 4C: Confidence-Aware Personalization."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.generation.confidence import (
    ConfidenceThresholds,
    assess_personalization_confidence,
)
from backend.generation.context_resolver import resolve_draft_context


def _iso_days_ago(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def _make_example(
    *,
    audience_mode: str = "1on1_private",
    similarity: float = 0.8,
    days_ago: float = 10.0,
    account_id: str = "acct-a",
) -> dict:
    return {
        "message_id": f"msg-{audience_mode}-{days_ago}",
        "recipient_email": "alex@example.com",
        "recipient_domain": "example.com",
        "subject": "Quick sync",
        "clean_body": "Hi Alex, let us sync tomorrow.",
        "audience_mode": audience_mode,
        "similarity": similarity,
        "timestamp": _iso_days_ago(days_ago),
        "account_id": account_id,
    }


def _base_global_profile(account_id: str = "acct-a") -> dict:
    return {
        "account_id": account_id,
        "global_style_card": {
            "formality": "professional",
            "tone": "clear",
            "directness": "direct",
        },
        "deterministic_stylometry": {
            "exact_signoff": "Best regards",
            "avg_sentence_length_words": 15.0,
        },
        "global_learned_rules": ["Keep updates concise and action-oriented"],
    }


def _base_recipient_profiles(account_id: str = "acct-a") -> dict:
    return {
        "alex@example.com": {
            "account_id": account_id,
            "preferred_greeting": "Hey Alex,",
            "preferred_signoff": "Cheers",
            "learned_rules_json": [
                "Use casual banter and emojis",
                "Include ticket numbers when relevant",
            ],
        }
    }


def test_high_confidence_applies_full_recipient_rules() -> None:
    examples = [_make_example(similarity=0.82, days_ago=5.0) for _ in range(3)]
    ctx = resolve_draft_context(
        to=["alex@example.com"],
        cc=[],
        bcc=[],
        account_id="acct-a",
        retrieved_emails=examples,
        recipient_profiles=_base_recipient_profiles(),
        global_profile=_base_global_profile(),
    )
    conf = ctx["resolution_meta"]["confidence"]
    assert conf["level"] == "high"
    assert conf["fallback_applied"] is False
    assert conf["signals"]["usable_example_count"] == 3
    assert ctx["cold_start_fallback"] is False
    assert ctx["greeting"] == "Hey Alex,"
    assert any("Use casual banter and emojis" in r for r in ctx["applied_rules"])


def test_medium_confidence_limited_quantity() -> None:
    examples = [_make_example(similarity=0.85, days_ago=4.0) for _ in range(2)]
    conf = assess_personalization_confidence(examples, "1on1_private", account_id="acct-a")
    assert conf["level"] == "medium"
    assert conf["fallback_applied"] is False
    assert conf["signals"]["usable_example_count"] == 2


def test_medium_confidence_stale_evidence() -> None:
    examples = [_make_example(similarity=0.90, days_ago=200.0) for _ in range(4)]
    conf = assess_personalization_confidence(examples, "1on1_private", account_id="acct-a")
    assert conf["level"] == "medium"
    assert conf["fallback_applied"] is False
    assert conf["signals"]["newest_age_days"] >= 199.0


def test_anti_compensation_gate_blocks_1on1_in_group_cc() -> None:
    examples = [_make_example(audience_mode="1on1_private", similarity=0.95, days_ago=2.0) for _ in range(5)]
    ctx = resolve_draft_context(
        to=["alex@example.com"],
        cc=["manager@example.com"],
        bcc=[],
        account_id="acct-a",
        retrieved_emails=examples,
        recipient_profiles=_base_recipient_profiles(),
        global_profile=_base_global_profile(),
    )
    conf = ctx["resolution_meta"]["confidence"]
    assert conf["level"] == "low"
    assert conf["fallback_applied"] is True
    assert conf["signals"]["audience_matched_count"] == 0
    assert conf["signals"]["audience_mismatched_count"] == 5
    assert ctx["cold_start_fallback"] is True
    assert ctx["examples"] == []
    assert any("Use casual banter and emojis" in r for r in ctx["suppressed_rules"])
    assert any("Evidence for this recipient/audience is low" in d for d in ctx["policy_directives"])


def test_low_semantic_relevance_triggers_fallback() -> None:
    thresholds = ConfidenceThresholds(min_usable_similarity=0.40)
    examples = [_make_example(similarity=0.20, days_ago=3.0) for _ in range(3)]
    conf = assess_personalization_confidence(
        examples, "1on1_private", account_id="acct-a", thresholds=thresholds
    )
    assert conf["level"] == "low"
    assert conf["fallback_applied"] is True
    assert conf["signals"]["usable_example_count"] == 0


def test_dynamic_recalculation_on_cc_toggle() -> None:
    examples = [_make_example(audience_mode="1on1_private", similarity=0.85, days_ago=5.0) for _ in range(3)]
    ctx_1on1 = resolve_draft_context(
        to=["alex@example.com"],
        cc=[],
        bcc=[],
        account_id="acct-a",
        retrieved_emails=examples,
        recipient_profiles=_base_recipient_profiles(),
        global_profile=_base_global_profile(),
    )
    assert ctx_1on1["resolution_meta"]["confidence"]["level"] == "high"

    ctx_cc = resolve_draft_context(
        to=["alex@example.com"],
        cc=["lead@example.com"],
        bcc=[],
        account_id="acct-a",
        retrieved_emails=examples,
        recipient_profiles=_base_recipient_profiles(),
        global_profile=_base_global_profile(),
    )
    assert ctx_cc["resolution_meta"]["confidence"]["level"] == "low"
    assert ctx_cc["cold_start_fallback"] is True

    ctx_restored = resolve_draft_context(
        to=["alex@example.com"],
        cc=[],
        bcc=[],
        account_id="acct-a",
        retrieved_emails=examples,
        recipient_profiles=_base_recipient_profiles(),
        global_profile=_base_global_profile(),
    )
    assert ctx_restored["resolution_meta"]["confidence"]["level"] == "high"


def test_account_isolation() -> None:
    other_account_examples = [
        _make_example(similarity=0.95, days_ago=1.0, account_id="acct-b") for _ in range(4)
    ]
    conf = assess_personalization_confidence(
        other_account_examples, "1on1_private", account_id="acct-a"
    )
    assert conf["level"] == "low"
    assert conf["signals"]["audience_matched_count"] == 0
    assert conf["signals"]["usable_example_count"] == 0


def test_squared_l2_distance_maps_accurately_to_cosine_similarity() -> None:
    # For unit-normalized vectors, LanceDB L2^2 = 0.80 => cos_sim = 1 - 0.80/2 = 0.60 (>= high_min_similarity 0.55)
    examples = [
        {
            "message_id": f"l2-{i}",
            "recipient_email": "alex@example.com",
            "audience_mode": "1on1_private",
            "_distance": 0.80,
            "timestamp": _iso_days_ago(5.0),
            "account_id": "acct-a",
        }
        for i in range(3)
    ]
    conf = assess_personalization_confidence(examples, "1on1_private", account_id="acct-a")
    assert conf["level"] == "high"
    assert conf["signals"]["avg_similarity"] == 0.6
