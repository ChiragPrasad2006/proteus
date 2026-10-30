"""
email_data_pipeline.synthesis package
"""

from .scenarios import get_random_scenario, sample_scenarios_for_personas
from .style_extractor import (
    extract_style_metadata,
    extract_user_intent_bullets,
    extract_greeting_style,
    extract_sign_off_style,
    infer_tone,
)
from .llm_synthesizer import AsyncEmailSynthesizer

__all__ = [
    "get_random_scenario",
    "sample_scenarios_for_personas",
    "extract_style_metadata",
    "extract_user_intent_bullets",
    "extract_greeting_style",
    "extract_sign_off_style",
    "infer_tone",
    "AsyncEmailSynthesizer",
]
