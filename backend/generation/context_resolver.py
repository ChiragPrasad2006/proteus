"""Deterministic personalization context resolver (Priority 0 policy layer).

This module is a pure policy engine: no database, no network, no model and no
I/O of any kind. Audience classification, strict memory precedence and
retrieval filtering all happen *before* qwen3:8b is prompted, so the same
decision is produced for initial generation, live recipient edits and
``/api/draft/tweak``. Everything it returns is deterministic and unit-testable
without a running Ollama server.
"""

from __future__ import annotations

import re
from typing import Any

from backend.generation.confidence import assess_personalization_confidence

AUDIENCE_1ON1 = "1on1_private"
AUDIENCE_GROUP = "group_cc"
AUDIENCE_BROADCAST = "broadcast_bcc"
VALID_AUDIENCES = (AUDIENCE_1ON1, AUDIENCE_GROUP, AUDIENCE_BROADCAST)

# Words that mark a learned rule as belonging to a casual, 1:1-only register.
_CASUAL_RULE_RE = re.compile(
    r"\b(casual|informal|slang|emoji|emojis|bro|hey|yo|lol|banter|joke|jokes|"
    r"laid[- ]back|first[- ]name only|use their name|short greeting)\b",
    re.IGNORECASE,
)
_FORMAL_COMMAND_RE = re.compile(
    r"/formal\b|\bformal\s+(?:tone|register|style)\b|"
    r"\b(?:be|keep|make|use|write|sound)\s+(?:it\s+)?(?:very\s+)?formal\b",
    re.IGNORECASE,
)
_CASUAL_COMMAND_RE = re.compile(
    r"/casual\b|\bcasual\s+(?:tone|register|style)\b|"
    r"\b(?:be|keep|make|use|write|sound)\s+(?:it\s+)?(?:more\s+)?casual\b",
    re.IGNORECASE,
)
_SLASH_COMMAND_RE = re.compile(r"/(?:formal|casual|professional|concise)\b", re.IGNORECASE)
_GREETING_NAME_RE = re.compile(r"(?:hi|hello|dear|hey)\s+([A-Za-z]+)", re.IGNORECASE)


def classify_audience(to: list[str] | None, cc: list[str] | None, bcc: list[str] | None) -> str:
    """Classify the audience deterministically from the recipient topology.

    ``len(bcc) > 0`` wins over everything (hidden recipients => broadcast),
    then any Cc or more than one To => group, otherwise a private 1:1 email.
    """
    bcc_list = [str(item) for item in (bcc or []) if str(item).strip()]
    cc_list = [str(item) for item in (cc or []) if str(item).strip()]
    to_list = [str(item) for item in (to or []) if str(item).strip()]
    if len(bcc_list) > 0:
        return AUDIENCE_BROADCAST
    if len(cc_list) > 0 or len(to_list) > 1:
        return AUDIENCE_GROUP
    return AUDIENCE_1ON1


def _as_dict(value: Any) -> dict[str, Any]:
    """Coerce a mapping or a Pydantic model into a plain deterministic dict."""
    if isinstance(value, dict):
        return dict(value)
    for method_name in ("model_dump", "dict"):
        method: Any = getattr(value, method_name, None)
        if callable(method):
            try:
                result: Any = method()
                if not isinstance(result, dict):
                    result = method(mode="json")
                if isinstance(result, dict):
                    return dict(result)
            except Exception:
                pass
            return {}
    return {}


def _same_account(record: dict[str, Any], account_id: str) -> bool:
    """Defensive guard: a record explicitly tagged with another account is ignored."""
    tagged = record.get("account_id")
    return not tagged or str(tagged) == str(account_id)


def _norm_email(email: str) -> str:
    return str(email or "").strip().lower()


def _first_name_from_email(email: str) -> str:
    local = email.split("@", 1)[0] if "@" in email else email
    for separator in (".", "_", "-", "+"):
        local = local.split(separator)[0]
    return local.capitalize() if local.isalpha() and 2 <= len(local) <= 20 else ""


def _recipient_first_name(profile: dict[str, Any], email: str) -> str:
    greeting = str(profile.get("preferred_greeting") or "")
    match = _GREETING_NAME_RE.search(greeting)
    if match:
        return match.group(1)
    return _first_name_from_email(email)


def _is_casual_rule(rule: str) -> bool:
    return bool(_CASUAL_RULE_RE.search(rule or ""))


def _example_audience(example: dict[str, Any]) -> str:
    """Resolve an example's audience from its explicit mode or its cc/bcc counts."""
    mode = example.get("audience_mode")
    if mode in VALID_AUDIENCES:
        return str(mode)
    try:
        bcc_count = int(example.get("bcc_count") or 0)
        cc_count = int(example.get("cc_count") or 0)
    except (TypeError, ValueError):
        bcc_count = cc_count = 0
    if bcc_count > 0:
        return AUDIENCE_BROADCAST
    if cc_count > 0:
        return AUDIENCE_GROUP
    return AUDIENCE_1ON1


def _parse_tier1(instructions: str) -> tuple[str | None, list[str]]:
    """Extract a forced register and authoritative directives from the current instruction."""
    text = (instructions or "").strip()
    if not text:
        return None, []
    register: str | None = None
    if _FORMAL_COMMAND_RE.search(text):
        register = "formal"
    elif _CASUAL_COMMAND_RE.search(text):
        register = "casual"
    directives: list[str] = []
    if register:
        directives.append(
            f"Tier 1 user override: use a {register} register. "
            "This is the highest-priority instruction and overrides lower-priority style memory."
        )
    remainder = _SLASH_COMMAND_RE.sub("", text).strip(" \t\n\r,;:-")
    if remainder:
        directives.append(f"Tier 1 user instruction (highest priority): {remainder[:400]}")
    return register, directives


def _style_card_rules(card: dict[str, Any]) -> str:
    parts = []
    for key in ("formality", "tone", "directness", "vocabulary_level", "sentence_structure"):
        value = card.get(key)
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def resolve_draft_context(
    to: list[str],
    cc: list[str],
    bcc: list[str],
    account_id: str,
    retrieved_emails: list[dict],
    recipient_profiles: dict[str, dict],
    global_profile: dict | None,
    current_instructions: str = "",
) -> dict[str, Any]:
    """Resolve all deterministic personalization policy for one draft turn.

    Precedence (strictly descending): Tier 1 current instruction, Tier 2 audience
    policy, Tier 3 recipient rules/stylometry, Tier 4 global rules/style card,
    Tier 5 audience-filtered examples, Tier 6 cold-start baseline. Lower tiers
    never leak when a higher tier overrides them; suppressed rules are recorded
    instead of being passed to the LLM.
    """
    normalized_to = [str(item) for item in (to or []) if str(item).strip()]
    normalized_cc = [str(item) for item in (cc or []) if str(item).strip()]
    normalized_bcc = [str(item) for item in (bcc or []) if str(item).strip()]
    audience = classify_audience(normalized_to, normalized_cc, normalized_bcc)

    tier1_register, tier1_directives = _parse_tier1(current_instructions)

    account_settings = _as_dict(global_profile)
    if not _same_account(account_settings, account_id):
        account_settings = {}
    style_card = _as_dict(account_settings.get("global_style_card"))
    stylometry = _as_dict(account_settings.get("deterministic_stylometry"))
    global_rules = [
        str(rule).strip()
        for rule in (account_settings.get("global_learned_rules") or [])
        if str(rule).strip()
    ]

    primary = normalized_to[0] if normalized_to else ""
    raw_recipient = _as_dict((recipient_profiles or {}).get(_norm_email(primary), {}))
    if not _same_account(raw_recipient, account_id):
        raw_recipient = {}
    recipient_rules = [
        str(rule).strip()
        for rule in (raw_recipient.get("learned_rules_json") or raw_recipient.get("learned_rules") or [])
        if str(rule).strip()
    ]

    applied_rules: list[str] = []
    suppressed_rules: list[str] = []
    suppressed_rules_detail: list[dict[str, str]] = []
    recipient_rules_used: list[str] = []
    global_rules_used: list[str] = []
    policy_directives: list[str] = []

    # --- Tier 1: explicit current instruction ------------------------------
    applied_rules.extend(tier1_directives)
    policy_directives.extend(tier1_directives)

    first_name = _recipient_first_name(raw_recipient, primary)
    global_signoff = str(stylometry.get("exact_signoff") or "").strip()
    try:
        base_length = float(stylometry.get("avg_sentence_length_words") or 16.0)
    except (TypeError, ValueError):
        base_length = 16.0

    # --- Tier 2: audience & communication policy ---------------------------
    if audience == AUDIENCE_1ON1:
        greeting = str(raw_recipient.get("preferred_greeting") or "").strip()
        if not greeting:
            greetings = stylometry.get("top_greetings") or []
            pattern = str(_as_dict(greetings[0]).get("pattern") or "") if greetings else ""
            greeting = (
                pattern.replace("{first_name}", first_name)
                if pattern
                else (f"Hi {first_name}," if first_name else "Hi,")
            )
        greeting = re.sub(r"\s+", " ", greeting).strip()
        signoff = (
            str(raw_recipient.get("preferred_signoff") or raw_recipient.get("signoff") or "").strip()
            or global_signoff
            or "Best"
        )
        try:
            target_length = float(
                raw_recipient.get("target_sentence_length")
                or raw_recipient.get("avg_sentence_length_words")
                or base_length
            )
        except (TypeError, ValueError):
            target_length = base_length
        audience_directives = [
            "AUDIENCE POLICY (1on1_private): Write a private one-to-one email. "
            "Match this recipient's established greeting, sign-off and sentence length.",
        ]
    elif audience == AUDIENCE_GROUP:
        greeting = f"Hi {first_name}," if first_name else "Hi everyone,"
        signoff = global_signoff or "Best regards"
        target_length = max(14.0, min(20.0, base_length))
        audience_directives = [
            "AUDIENCE POLICY (group_cc): Write for a shared, multi-stakeholder audience, "
            "not a private 1:1 exchange.",
            "Use an inclusive professional greeting such as 'Hi <FirstName>,' or 'Hi everyone,'. "
            "Never use 'Hey' or 'Yo'.",
            "Keep context self-contained for every Cc'd participant: state background explicitly "
            "and avoid private shorthand or inside jokes.",
            "Do not apply recipient-specific casual 1:1 greetings or rules.",
        ]
    else:  # AUDIENCE_BROADCAST
        greeting = "Hello everyone,"
        signoff = global_signoff or "Best regards"
        target_length = max(15.0, min(20.0, base_length))
        audience_directives = [
            "AUDIENCE POLICY (broadcast_bcc): Write a formal announcement/broadcast "
            "using 'Hello everyone,' or 'Hi team,'.",
            "Never address, name or mention BCC recipients in the body; their addresses are hidden.",
            "Suppress all 1:1 personal greetings and recipient-specific rules; "
            "keep the register neutral and impersonal.",
        ]

    if tier1_register == "formal":
        if audience == AUDIENCE_1ON1:
            greeting = f"Hello {first_name}," if first_name else "Hello,"
        audience_directives.append(
            "Tier 1 formal override: discard casual greetings and casual-style rules from lower tiers."
        )
    elif tier1_register == "casual" and audience != AUDIENCE_1ON1:
        audience_directives.append(
            "Tier 1 casual request is constrained by the audience policy: "
            "group/broadcast register stays professional."
        )

    policy_directives.extend(audience_directives)
    applied_rules.extend(audience_directives)

    # --- Confidence assessment (Layer 4C) ----------------------------------
    confidence = assess_personalization_confidence(
        retrieved_emails=retrieved_emails,
        audience_type=audience,
        account_id=account_id,
    )
    conf_level = confidence["level"]

    if conf_level == "low" and audience == AUDIENCE_1ON1:
        # Fall back to clean professional baseline greeting/sign-off
        greeting = f"Hi {first_name}," if first_name else "Hello,"
        signoff = global_signoff or "Best regards"

    # --- Tier 3: recipient rules, filtered against Tier 1/2 & confidence ---
    for rule in recipient_rules:
        if audience == AUDIENCE_BROADCAST:
            suppressed_rules.append(rule)
            suppressed_rules_detail.append({
                "rule": rule,
                "reason": "Suppressed because Broadcast BCC hides recipients and uses a formal, impersonal tone.",
            })
            policy_directives.append(f"Suppressed recipient rule (broadcast policy): {rule}")
        elif audience == AUDIENCE_GROUP and _is_casual_rule(rule):
            suppressed_rules.append(rule)
            reason = (
                "Casual 1:1 rule suppressed because Cc recipients are present."
                if normalized_cc
                else "Casual 1:1 rule suppressed because multiple recipients are on this Group CC email."
            )
            suppressed_rules_detail.append({"rule": rule, "reason": reason})
            policy_directives.append(f"Suppressed casual 1:1 recipient rule (group policy): {rule}")
        elif tier1_register == "formal" and _is_casual_rule(rule):
            suppressed_rules.append(rule)
            suppressed_rules_detail.append({
                "rule": rule,
                "reason": "Casual rule suppressed because your current instruction requested a formal tone.",
            })
            policy_directives.append(f"Suppressed casual recipient rule (Tier 1 formal override): {rule}")
        elif conf_level == "low" and _is_casual_rule(rule):
            suppressed_rules.append(f"{rule} (low_confidence_fallback)")
            suppressed_rules_detail.append({
                "rule": rule,
                "reason": "Casual rule suppressed due to low historical evidence for this recipient/audience.",
            })
            policy_directives.append(f"Suppressed casual recipient rule (low_confidence_fallback): {rule}")
        else:
            recipient_rules_used.append(rule)
            applied_rules.append(f"Recipient rule for {primary or 'primary recipient'}: {rule}")

    # --- Tier 4: global rules and style card -------------------------------
    for rule in global_rules:
        if _is_casual_rule(rule) and (tier1_register == "formal" or audience != AUDIENCE_1ON1):
            suppressed_rules.append(rule)
            if tier1_register == "formal":
                reason = "Casual global rule suppressed because your current instruction requested a formal tone."
            elif audience == AUDIENCE_BROADCAST:
                reason = "Casual global rule suppressed because Broadcast BCC uses a formal, impersonal tone."
            else:
                reason = "Casual global rule suppressed because Group CC emails stay professional."
            suppressed_rules_detail.append({"rule": rule, "reason": reason})
            policy_directives.append(f"Suppressed conflicting global rule: {rule}")
        else:
            global_rules_used.append(rule)
            applied_rules.append(f"Global rule: {rule}")
    card_rules = _style_card_rules(style_card)
    if card_rules:
        applied_rules.append(f"Global style card: {card_rules}")

    # --- Tier 5: audience-filtered historical examples ---------------------
    matched_examples: list[dict[str, Any]] = []
    for raw_example in (retrieved_emails or []):
        example = _as_dict(raw_example)
        if not _same_account(example, account_id):
            continue
        if _example_audience(example) == audience:
            matched_examples.append(example)

    # --- Tier 6: confidence-aware & cold-start professional baseline -------
    cold_start_fallback = (conf_level == "low") or (
        audience in (AUDIENCE_GROUP, AUDIENCE_BROADCAST) and not matched_examples
    )
    if conf_level == "low":
        policy_directives.append(
            "Evidence for this recipient/audience is low — write in a clear, polite professional baseline matching the user's global style rather than assuming casual rapport."
        )
        applied_rules.append(
            "Cold-start professional baseline: concise, inclusive, factual prose "
            "with no casual 1:1 shorthand."
        )
        examples: list[dict[str, Any]] = []
    elif conf_level == "medium":
        policy_directives.append(
            "Evidence for this recipient/audience is moderate — apply compatible rules conservatively and do not over-index on a single or stale example."
        )
        examples = matched_examples
    else:
        examples = matched_examples

    # --- Explainability payload (Layer 4D) ---------------------------------
    audience_labels = {
        AUDIENCE_1ON1: "1:1 Private",
        AUDIENCE_GROUP: "Group CC",
        AUDIENCE_BROADCAST: "Broadcast BCC",
    }
    if audience == AUDIENCE_BROADCAST:
        bcc_n = len(normalized_bcc)
        audience_reason = (
            f"{bcc_n} Bcc recipient{'s' if bcc_n != 1 else ''} detected"
            if bcc_n > 0
            else "Bcc recipients detected"
        )
    elif audience == AUDIENCE_GROUP:
        if normalized_cc and len(normalized_to) > 1:
            audience_reason = f"{len(normalized_to)} recipients in To and {len(normalized_cc)} in Cc"
        elif normalized_cc:
            cc_n = len(normalized_cc)
            audience_reason = f"{cc_n} Cc recipient{'s' if cc_n != 1 else ''} detected"
        else:
            audience_reason = f"{len(normalized_to)} recipients in To, no Bcc"
    else:
        audience_reason = (
            "1 recipient in To, no Cc/Bcc"
            if len(normalized_to) == 1
            else "No Cc/Bcc recipients detected"
        )

    signals = confidence.get("signals") or {}
    usable_count = int(signals.get("usable_example_count") or 0)
    matched_raw_count = int(signals.get("audience_matched_count") or 0)
    if usable_count > 0:
        if audience == AUDIENCE_GROUP:
            retrieved_examples_summary = (
                f"{usable_count} relevant group conversation{'s' if usable_count != 1 else ''} retrieved"
            )
        elif audience == AUDIENCE_BROADCAST:
            retrieved_examples_summary = (
                f"{usable_count} relevant broadcast email{'s' if usable_count != 1 else ''} retrieved"
            )
        else:
            retrieved_examples_summary = (
                f"{usable_count} relevant 1:1 conversation{'s' if usable_count != 1 else ''} retrieved"
            )
    elif matched_raw_count > 0:
        if audience == AUDIENCE_GROUP:
            retrieved_examples_summary = "Prior group conversations had low relevance"
        elif audience == AUDIENCE_BROADCAST:
            retrieved_examples_summary = "Prior broadcast emails had low relevance"
        else:
            retrieved_examples_summary = "Prior 1:1 conversations had low relevance"
    else:
        if audience == AUDIENCE_GROUP:
            retrieved_examples_summary = "No prior group conversations found"
        elif audience == AUDIENCE_BROADCAST:
            retrieved_examples_summary = "No prior broadcast emails found"
        else:
            retrieved_examples_summary = "No prior 1:1 conversations found"

    default_style_reason: str | None = None
    if cold_start_fallback:
        has_suppressed = len(suppressed_rules_detail) > 0
        if audience == AUDIENCE_GROUP and usable_count == 0:
            default_style_reason = (
                "No prior Group CC emails found; casual 1:1 rules suppressed and global professional style applied."
                if has_suppressed
                else "No prior Group CC emails found; global professional style applied."
            )
        elif audience == AUDIENCE_BROADCAST and usable_count == 0:
            default_style_reason = (
                "No prior Broadcast BCC emails found; 1:1 recipient rules suppressed and global professional style applied."
                if has_suppressed
                else "No prior Broadcast BCC emails found; global professional style applied."
            )
        elif matched_raw_count == 0:
            default_style_reason = (
                "No prior matching emails found for this recipient/audience; casual rules suppressed and global professional style applied."
                if has_suppressed
                else "No prior matching emails found for this recipient/audience; global professional style applied."
            )
        else:
            default_style_reason = (
                "Retrieved examples had low relevance; casual rules suppressed and global professional style applied."
                if has_suppressed
                else "Retrieved examples had low relevance; global professional style applied."
            )

    explainability: dict[str, Any] = {
        "audience_type": audience,
        "audience_label": audience_labels[audience],
        "audience_reason": audience_reason,
        "confidence_level": conf_level,
        "retrieved_examples_count": usable_count,
        "retrieved_examples_summary": retrieved_examples_summary,
        "recipient_rules_used": list(recipient_rules_used),
        "global_rules_used": list(global_rules_used),
        "suppressed_rules": list(suppressed_rules_detail),
        "default_style_used": cold_start_fallback,
        "default_style_reason": default_style_reason,
    }

    return {
        "audience_type": audience,
        "greeting": greeting,
        "signoff": signoff,
        "target_sentence_length": round(float(target_length), 2),
        "applied_rules": applied_rules,
        "suppressed_rules": suppressed_rules,
        "examples": examples,
        "cold_start_fallback": cold_start_fallback,
        "confidence": confidence,
        "policy_directives": policy_directives,
        "resolution_meta": {
            "account_id": str(account_id),
            "primary_recipient": primary,
            "audience_type": audience,
            "tier1_register": tier1_register or "",
            "recipient_rules_applied": sum(
                1 for rule in applied_rules if rule.startswith("Recipient rule for ")
            ),
            "recipient_rules_suppressed": len(suppressed_rules),
            "global_rules_applied": sum(1 for rule in applied_rules if rule.startswith("Global rule: ")),
            "examples_received": len(retrieved_emails or []),
            "examples_matched": len(examples),
            "cold_start_fallback": cold_start_fallback,
            "confidence": confidence,
            "explainability": explainability,
        },
    }


__all__ = ["classify_audience", "resolve_draft_context", "VALID_AUDIENCES"]
