"""Privacy-preserving email cleanup for sent-mail style analysis."""

from __future__ import annotations

import re
from html import unescape

from backend.schemas import CleanedSentEmail, RawSentEmail

_REPLY_BOUNDARY = re.compile(
    r"^(?:>{1,}|On .{0,180} wrote:|-----Original Message-----|"
    r"Begin forwarded message:|From:\s.+|Sent:\s.+|To:\s.+|Subject:\s.+)$",
    re.IGNORECASE,
)
_SIGNATURE_DELIMITER = re.compile(r"\n--\s*\n")
_SIGNOFF_LINE = re.compile(
    r"^(?:best(?: regards)?|kind regards|warm regards|regards|thanks(?: again)?|"
    r"thank you|cheers|sincerely|respectfully|take care|all the best)[,!]?$",
    re.IGNORECASE,
)
_AUTOMATED_SUBJECT = re.compile(r"(?:out of office|automatic reply|calendar response|delivery status)", re.IGNORECASE)


def _html_to_text(raw_body: str) -> str:
    """Convert HTML to readable lines while retaining paragraph and break boundaries."""
    text = unescape(raw_body or "")
    try:
        from bs4 import BeautifulSoup  # Imported lazily so core cleanup remains portable.

        soup = BeautifulSoup(text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        for tag in soup.find_all(["br", "p", "div", "li", "tr"]):
            tag.insert_before("\n")
        text = soup.get_text(" ")
    except ImportError:
        text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", text)
        text = re.sub(r"(?i)</?\s*(?:p|div|li|tr|blockquote)[^>]*>", "\n", text)
        text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)
    return re.sub(r"[ \t]+", " ", text)


def _remove_reply_history(text: str) -> str:
    """Keep the authored top message and stop at a reply or forwarded-message boundary."""
    kept: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(">") or _REPLY_BOUNDARY.match(stripped):
            # A standalone "From:" may occur in prose, so require header context for it.
            if stripped.lower().startswith(("from:", "sent:", "to:", "subject:")) and index == 0:
                kept.append(line)
                continue
            break
        kept.append(line.rstrip())
    return "\n".join(kept).strip()


def _extract_signature(text: str) -> tuple[str, str]:
    """Split a trailing email signature from content without treating it as prose."""
    delimiter = _SIGNATURE_DELIMITER.search(text)
    if delimiter:
        return text[: delimiter.start()].rstrip(), text[delimiter.end() :].strip()

    lines = text.rstrip().splitlines()
    non_empty = [index for index, line in enumerate(lines) if line.strip()]
    if not non_empty:
        return "", ""

    # Look only near the end, preventing ordinary uses of "Thanks" from splitting a body.
    start = max(0, len(lines) - 7)
    for index in range(start, len(lines)):
        if _SIGNOFF_LINE.match(lines[index].strip()):
            signature = "\n".join(line.strip() for line in lines[index:] if line.strip())
            return "\n".join(lines[:index]).rstrip(), signature
    return text.strip(), ""


def _normalize_paragraphs(text: str) -> str:
    """Collapse noise while retaining paragraph structure and bullets."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    output: list[str] = []
    previous_blank = False
    for line in lines:
        if not line:
            if output and not previous_blank:
                output.append("")
            previous_blank = True
            continue
        output.append(line)
        previous_blank = False
    return "\n".join(output).strip()


def clean_raw_email(raw: RawSentEmail, minimum_words: int = 20) -> CleanedSentEmail | None:
    """Remove noise and reject short or automated sent messages.

    The signature remains available for sign-off analysis but is excluded from the
    cleaned body and its word-count denominator.
    """
    if _AUTOMATED_SUBJECT.search(raw.subject):
        return None
    text = _normalize_paragraphs(_remove_reply_history(_html_to_text(raw.raw_body)))
    body, signature = _extract_signature(text)
    body = _normalize_paragraphs(body)
    word_count = len(re.findall(r"\b[\w'-]+\b", body, flags=re.UNICODE))
    if word_count < minimum_words:
        return None
    return CleanedSentEmail(
        **raw.model_dump(), clean_body=body, signature=signature, word_count=word_count
    )
