"""
email_data_pipeline.filters package
"""

from .deslop import (
    contains_ai_slop,
    find_ai_buzzwords,
    clean_markdown_and_html,
    is_valid_email_candidate,
    inject_robotic_slop,
)
from .persona_filter import is_workplace_persona, sanitize_persona_description
from .text_cleaner import matches_email_keywords, clean_email_body

__all__ = [
    "contains_ai_slop",
    "find_ai_buzzwords",
    "clean_markdown_and_html",
    "is_valid_email_candidate",
    "inject_robotic_slop",
    "is_workplace_persona",
    "sanitize_persona_description",
    "matches_email_keywords",
    "clean_email_body",
]
