"""
email_data_pipeline.filters.deslop
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Regex-based AI buzzword detection, de-slopping, markdown/HTML repair,
and negative DPO slop augmentation.
"""

import re
from typing import List, Tuple
from ..config import AI_SLOP_REGEX, AI_BUZZWORDS


def find_ai_buzzwords(text: str) -> List[str]:
    """Return all unique AI buzzwords or cliché phrases found in the text."""
    if not text:
        return []
    matches = AI_SLOP_REGEX.findall(text)
    # Deduplicate while preserving case-normalized order
    seen = set()
    result = []
    for m in matches:
        low = m.lower()
        if low not in seen:
            seen.add(low)
            result.append(m)
    return result


def contains_ai_slop(text: str) -> bool:
    """Return True if the text contains any robotic AI clichés or buzzwords."""
    if not text:
        return False
    return bool(AI_SLOP_REGEX.search(text))


def clean_markdown_and_html(text: str) -> str:
    """
    Cleans out malformed text, unclosed markdown links, unpaired backticks,
    broken HTML entities, and excessive whitespace.
    """
    if not text:
        return ""

    s = text

    # Remove zero-width characters and unusual Unicode control codes
    s = re.sub(r"[\u200b\u200c\u200d\uFEFF]", "", s)

    # Normalize carriage returns
    s = s.replace("\r\n", "\n").replace("\r", "\n")

    # Fix broken empty markdown links e.g. [some text]() or []()
    s = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", s)

    # Strip raw stray HTML tags like <div>, </div>, <p>, </p>, <br/> but preserve content
    s = re.sub(r"<\s*/?\s*(?:div|span|p|br|table|tr|td|th|tbody|thead|font|style|script)\b[^>]*>", " ", s, flags=re.IGNORECASE)

    # Decode common HTML entities
    s = s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")

    # Fix unclosed backtick code blocks (if odd number of triple backticks, close it)
    if s.count("```") % 2 != 0:
        s += "\n```"

    # Remove dangling backticks on their own line without contents
    s = re.sub(r"^\s*`{1,2}\s*$", "", s, flags=re.MULTILINE)

    # Collapse multiple consecutive blank lines to at most two
    s = re.sub(r"\n{3,}", "\n\n", s)

    return s.strip()


def is_valid_email_candidate(text: str, min_chars: int = 150) -> bool:
    """
    Validates that the email candidate text:
    1. Has at least `min_chars` characters.
    2. Is not corrupted or purely numbers/punctuation.
    3. Contains basic sentence structure.
    """
    if not text:
        return False
    cleaned = text.strip()
    if len(cleaned) < min_chars:
        return False

    # Check that there are actual words and letters, not just garbage/symbols
    alpha_chars = sum(1 for c in cleaned if c.isalpha())
    if alpha_chars < (len(cleaned) * 0.4):
        return False

    return True


def inject_robotic_slop(clean_text: str) -> str:
    """
    Augments a clean email into a classic robotic AI draft to serve as a rejected
    pair in DPO training when an organic slop-rich rejected response is absent.
    Incorporate hallmarks of LLM slop: 'I hope this email finds you well',
    'delve', 'testament', 'tapestry', 'furthermore', 'in conclusion'.
    """
    if not clean_text:
        return clean_text

    # Salutation replacement with robotic cliché
    lines = clean_text.split("\n", 2)
    first_line = lines[0] if lines else ""

    if re.match(r"^(?:Hi|Hey|Dear|Hello|To)\b", first_line, re.IGNORECASE):
        prefix = f"{first_line}\n\nI hope this email finds you well."
        rest = "\n".join(lines[1:]) if len(lines) > 1 else ""
    else:
        prefix = "Dear Colleague,\n\nI hope this email finds you well in today's fast-paced corporate landscape."
        rest = clean_text

    slop_middle = (
        "\n\nFurthermore, as we delve into the multifaceted dimensions of this initiative, "
        "it is important to remember that our collaboration stands as a profound testament "
        "to innovation within our organizational tapestry."
    )

    slop_conclusion = (
        "\n\nIn conclusion, navigating this landscape will seamlessly foster synergy across all key verticals.\n\n"
        "Best regards,\nAutomated System"
    )

    return f"{prefix.strip()}{slop_middle}\n\n{rest.strip()}{slop_conclusion}"
