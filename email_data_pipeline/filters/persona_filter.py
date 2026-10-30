"""
email_data_pipeline.filters.persona_filter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Filters and validates personas from PersonaHub and FinePersonas,
ensuring strict adherence to professional, corporate, academic,
and workplace profiles while excluding fantasy, medieval, and gaming NPCs.
"""

from typing import Optional
from ..config import WORKPLACE_INCLUDE_REGEX, FANTASY_EXCLUDE_REGEX


def is_workplace_persona(persona: Optional[str]) -> bool:
    """
    Evaluates whether a given persona string represents a professional, corporate,
    academic, founder, freelance, or workplace identity.

    Rules:
    - Must NOT match any fantasy, medieval, ancient, mythical, or gaming NPC patterns.
    - Must match at least one professional, workplace, or business keyword pattern.
    - Must be of reasonable descriptive length (> 15 characters).
    """
    if not persona or not isinstance(persona, str):
        return False

    cleaned = persona.strip()
    if len(cleaned) < 15:
        return False

    # Immediate rejection if fantasy, gaming, or historical NPC
    if FANTASY_EXCLUDE_REGEX.search(cleaned):
        return False

    # Match workplace, corporate, academic, engineering, management, freelance keywords
    if WORKPLACE_INCLUDE_REGEX.search(cleaned):
        return True

    return False


def sanitize_persona_description(persona: str) -> str:
    """
    Cleans up leading/trailing filler in persona descriptions
    (e.g., 'A persona of ...', 'This user is a ...').
    """
    if not persona:
        return ""
    p = persona.strip()
    # Normalize excessive internal spacing
    p = " ".join(p.split())
    # Ensure it ends with punctuation
    if p and p[-1] not in ".!?":
        p += "."
    return p
