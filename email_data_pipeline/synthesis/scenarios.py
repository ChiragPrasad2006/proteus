"""
email_data_pipeline.synthesis.scenarios
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Email scenario repository covering complex real-world workplace situations
(salary negotiation, project delays, cold B2B pitch, critical bug escalations,
board updates, vendor disputes, etc.).
"""

import random
from typing import Dict, List, Tuple
from ..config import EMAIL_SCENARIOS


def get_random_scenario(seed: int = None) -> Dict[str, str]:
    """Randomly selects a workplace scenario with category, prompt context, and default intents."""
    if seed is not None:
        rng = random.Random(seed)
        return rng.choice(EMAIL_SCENARIOS)
    return random.choice(EMAIL_SCENARIOS)


def sample_scenarios_for_personas(
    personas: List[str], base_seed: int = 42
) -> List[Tuple[str, Dict[str, str]]]:
    """
    Pairs each persona deterministically with a workplace scenario.
    """
    rng = random.Random(base_seed)
    pairs = []
    for p in personas:
        scen = rng.choice(EMAIL_SCENARIOS)
        pairs.append((p, scen))
    return pairs
