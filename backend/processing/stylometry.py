"""Fast deterministic stylometry over a locally cleaned Sent-mail corpus."""

from __future__ import annotations

import re
from collections import Counter

from backend.schemas import CleanedSentEmail, GreetingFrequency, StylometryMetrics

_GREETING_RE = re.compile(
    r"^(?P<greeting>dear|hi|hello|hey)\s+(?P<recipient>[^,\n]{1,80})(?P<comma>,)?$",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+", re.MULTILINE)
_EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF\U00002600-\U000027BF]")
_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def _greeting_pattern(text: str) -> str | None:
    """Return a greeting normalized enough to aggregate recipient names."""
    for line in text.splitlines()[:3]:
        line = line.strip()
        if not line:
            continue
        match = _GREETING_RE.match(line)
        if not match:
            return None
        greeting = match.group("greeting").title()
        recipient = match.group("recipient").strip()
        if recipient.lower() in {"team", "all", "everyone"}:
            return f"{greeting} {recipient.title()}{match.group('comma') or ''}"
        return f"{greeting} {{first_name}}{match.group('comma') or ''}"
    return None


def _sentence_lengths(text: str) -> list[int]:
    """Return word counts for non-empty sentence-like spans."""
    spans = re.split(r"(?<=[.!?])(?:\s+|$)", text)
    return [len(_WORD_RE.findall(span)) for span in spans if _WORD_RE.findall(span)]


def compute_stylometry(messages: list[CleanedSentEmail]) -> StylometryMetrics:
    """Compute deterministic corpus metrics using only Python and regular expressions."""
    if not messages:
        return StylometryMetrics()

    greetings = Counter(filter(None, (_greeting_pattern(message.clean_body) for message in messages)))
    signoffs = Counter(message.signature for message in messages if message.signature)
    total_words = sum(message.word_count for message in messages)
    sentence_lengths = [
        length for message in messages for length in _sentence_lengths(message.clean_body)
    ]
    paragraph_counts = [
        len([part for part in re.split(r"\n\s*\n", message.clean_body) if part.strip()])
        for message in messages
    ]
    greeting_total = sum(greetings.values())
    top_greetings = [
        GreetingFrequency(pattern=pattern, pct=round(count * 100 / greeting_total, 1))
        for pattern, count in sorted(greetings.items(), key=lambda item: (-item[1], item[0]))[:3]
    ]

    return StylometryMetrics(
        top_greetings=top_greetings,
        exact_signoff=signoffs.most_common(1)[0][0] if signoffs else "",
        avg_sentence_length_words=round(sum(sentence_lengths) / len(sentence_lengths), 2)
        if sentence_lengths
        else 0.0,
        avg_email_length_words=round(total_words / len(messages), 2),
        avg_paragraph_count=round(sum(paragraph_counts) / len(paragraph_counts), 2),
        exclamation_rate=round(
            sum(message.clean_body.count("!") for message in messages) * 100 / total_words, 3
        )
        if total_words
        else 0.0,
        emoji_rate=round(
            sum(len(_EMOJI_RE.findall(message.clean_body)) for message in messages) * 100 / total_words,
            3,
        )
        if total_words
        else 0.0,
        uses_bullet_lists_pct=round(
            sum(bool(_BULLET_RE.search(message.clean_body)) for message in messages)
            * 100
            / len(messages),
            1,
        ),
    )
