"""
email_data_pipeline.filters.text_cleaner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
General text cleaning, email keyword validation, and normalization.
"""

from typing import Optional
from ..config import EMAIL_KEYWORDS_REGEX
from .deslop import clean_markdown_and_html, is_valid_email_candidate


def matches_email_keywords(text: Optional[str]) -> bool:
    """
    Checks if text matches case-insensitive email-specific indicators
    ('email', 'subject:', 'dear ', 'sincerely', 'best regards',
    'follow-up', 'cold outreach', 'reply to').
    """
    if not text or not isinstance(text, str):
        return False
    return bool(EMAIL_KEYWORDS_REGEX.search(text))


def clean_email_body(text: Optional[str], min_chars: int = 150) -> Optional[str]:
    """
    Cleans email text by fixing markdown/HTML issues, trimming headers/trailers,
    and returns None if the output fails minimum length or quality requirements.
    """
    if not text:
        return None

    cleaned = clean_markdown_and_html(text)

    # Check validity criteria
    if not is_valid_email_candidate(cleaned, min_chars=min_chars):
        return None

    return cleaned
