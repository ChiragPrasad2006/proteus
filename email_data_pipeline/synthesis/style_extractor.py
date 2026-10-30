"""
email_data_pipeline.synthesis.style_extractor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
High-speed deterministic extractors for style metadata (tone, greeting style,
sign-off style, sentence length) and 3-bullet user intents from email text.
Used for Dataset A and offline fallback synthesis.
"""

import re
from typing import List, Optional
from ..config import StyleMetadata


# ---------------------------------------------------------------------------
# Greeting Style Detection
# ---------------------------------------------------------------------------
GREETING_PATTERNS = [
    (re.compile(r"^\s*Dear\s+[a-zA-Z\.\s]+,", re.IGNORECASE), "Formal ('Dear [Name]')"),
    (re.compile(r"^\s*Hi\s+[a-zA-Z\.\s]+,", re.IGNORECASE), "Casual / Modern ('Hi [Name]')"),
    (re.compile(r"^\s*Hey\s+[a-zA-Z\.\s]+,", re.IGNORECASE), "Informal / Peer ('Hey [Name]')"),
    (re.compile(r"^\s*Hello\s+[a-zA-Z\.\s]+,", re.IGNORECASE), "Standard Professional ('Hello [Name]')"),
    (re.compile(r"^\s*Good\s+(?:morning|afternoon|evening)\b", re.IGNORECASE), "Time-Based Professional ('Good morning')"),
    (re.compile(r"^\s*(?:Hi|Hello|Hey)\s+(?:Team|All|Everyone)\b", re.IGNORECASE), "Group / Broadcast ('Hi Team')"),
]


# ---------------------------------------------------------------------------
# Sign-Off Style Detection
# ---------------------------------------------------------------------------
SIGNOFF_PATTERNS = [
    (re.compile(r"\b(?:Best\s+regards|Warm\s+regards|Kind\s+regards)\b", re.IGNORECASE), "Standard Professional ('Best regards')"),
    (re.compile(r"\b(?:Sincerely|Yours\s+faithfully|Respectfully)\b", re.IGNORECASE), "Formal ('Sincerely')"),
    (re.compile(r"\b(?:Cheers|Talk\s+soon)\b", re.IGNORECASE), "Casual Peer ('Cheers')"),
    (re.compile(r"\b(?:Thanks|Thank\s+you|Many\s+thanks)\b", re.IGNORECASE), "Action-Oriented ('Thanks')"),
    (re.compile(r"\b(?:Best|Regards)\b", re.IGNORECASE), "Concise ('Best')"),
]


def extract_greeting_style(text: str) -> str:
    """Identifies the salutation style used in the email."""
    first_lines = "\n".join(text.strip().split("\n")[:3])
    for pattern, label in GREETING_PATTERNS:
        if pattern.search(first_lines):
            return label
    return "Direct (No Salutation)"


def extract_sign_off_style(text: str) -> str:
    """Identifies the sign-off closing used in the email."""
    last_lines = "\n".join(text.strip().split("\n")[-4:])
    for pattern, label in SIGNOFF_PATTERNS:
        if pattern.search(last_lines):
            return label
    return "Minimalist / Unsigned"


def analyze_sentence_length(text: str) -> str:
    """Computes average words per sentence and categorizes sentence length."""
    # Split text into sentences
    sentences = re.split(r"[.!?]+(?:\s+|\n+)", text.strip())
    sentences = [s.strip() for s in sentences if s.strip()]
    if not sentences:
        return "Moderate (12-18 words/sentence)"

    total_words = sum(len(s.split()) for s in sentences)
    avg_words = total_words / len(sentences)

    if avg_words < 12.0:
        return f"Short & Punchy (~{int(avg_words)} words/sentence)"
    elif avg_words <= 20.0:
        return f"Moderate & Balanced (~{int(avg_words)} words/sentence)"
    else:
        return f"Detailed & Thorough (~{int(avg_words)} words/sentence)"


def infer_tone(text: str, persona: Optional[str] = None) -> str:
    """
    Infers the emotional and professional tone based on linguistic indicators,
    contractions, urgency words, and optional persona context.
    """
    t_lower = text.lower()
    p_lower = (persona or "").lower()

    # Urgency & executive directness
    if re.search(r"\b(?:critical|urgent|immediately|action required|blocker|outage|asap)\b", t_lower):
        return "Assertive, Urgent & Action-Oriented"

    # Executive / concise
    if any(k in p_lower for k in ["executive", "director", "vp", "chief", "founder", "lead"]):
        if len(text.split()) < 120:
            return "Executive, Decisive & Concise"

    # Academic / analytical
    if any(k in p_lower for k in ["professor", "researcher", "scientist", "analyst", "academic"]):
        return "Analytical, Rigorous & Objective"

    # Diplomatic / formal
    if re.search(r"\b(?:appreciate|kindly|request|assistance|cordially|respectfully)\b", t_lower):
        return "Diplomatic, Polite & Measured"

    # Engineering / technical
    if any(k in p_lower for k in ["engineer", "developer", "architect", "sre"]):
        return "Pragmatic, Technical & Direct"

    # Default professional tone
    return "Clear, Professional & Collaborative"


def extract_style_metadata(email_text: str, persona: Optional[str] = None) -> StyleMetadata:
    """Extracts a complete StyleMetadata object from email content."""
    return StyleMetadata(
        tone=infer_tone(email_text, persona),
        greeting_style=extract_greeting_style(email_text),
        sign_off_style=extract_sign_off_style(email_text),
        sentence_length=analyze_sentence_length(email_text),
    )


def extract_user_intent_bullets(email_text: str, max_bullets: int = 3) -> str:
    """
    Extracts 3 concise, actionable intent bullet points from the email body.
    Transforms passive paragraphs into active 'Draft an email covering these points' requirements.
    """
    cleaned = email_text.strip()
    paragraphs = [p.strip() for p in cleaned.split("\n\n") if len(p.strip()) > 20]

    # Remove salutation and sign-off paragraphs
    core_paragraphs = []
    for p in paragraphs:
        if re.match(r"^(?:Hi|Hey|Dear|Hello|To\b)", p, re.IGNORECASE) and len(p.split()) < 8:
            continue
        if re.search(r"^(?:Best regards|Sincerely|Cheers|Thanks|Warmly)\b", p, re.IGNORECASE) and len(p.split()) < 8:
            continue
        core_paragraphs.append(p)

    if not core_paragraphs:
        core_paragraphs = paragraphs

    # Split into actionable sentences
    sentences = []
    for cp in core_paragraphs:
        sents = re.split(r"(?<=[.!?])\s+", cp)
        for s in sents:
            s_clean = s.strip()
            # Drop very short fragments or pure questions
            if len(s_clean.split()) >= 6:
                sentences.append(s_clean)

    bullets: List[str] = []

    # Heuristic 1: If paragraphs exist, take key intent from up to 3 paragraphs
    if len(core_paragraphs) >= 3:
        for p in core_paragraphs[:max_bullets]:
            first_sent = re.split(r"(?<=[.!?])\s+", p)[0]
            # Convert into imperative/active bullet
            bullet = _sentence_to_intent_bullet(first_sent)
            bullets.append(bullet)
    elif len(sentences) >= 3:
        # Take beginning, middle, and ending key sentences
        indices = [0, len(sentences) // 2, len(sentences) - 1]
        for idx in indices:
            bullets.append(_sentence_to_intent_bullet(sentences[idx]))
    elif sentences:
        for s in sentences[:max_bullets]:
            bullets.append(_sentence_to_intent_bullet(s))
    else:
        bullets = [
            "Clearly state the core purpose and current status of the initiative.",
            "Highlight key dependencies, timeline considerations, and critical deliverables.",
            "Propose concrete next steps and request alignment from the recipient.",
        ]

    # Ensure exactly 3 bullets
    while len(bullets) < 3:
        bullets.append("Request confirmation on proposed timelines and schedule a sync.")

    return "\n".join(f"- {b}" for b in bullets[:3])


def _sentence_to_intent_bullet(sentence: str) -> str:
    """Transforms a declarative sentence into an active intent bullet point."""
    s = sentence.strip().rstrip(".!?")
    # Clean leading filler
    s = re.sub(
        r"^(?:I am writing to|I would like to|Please note that|I wanted to let you know that|We need to|I hope that)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip()
    if s:
        # Capitalize first letter
        s = s[0].upper() + s[1:]
    return s
