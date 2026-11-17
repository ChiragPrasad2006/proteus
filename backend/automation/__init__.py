"""Tier 4: Autonomous dispatch and self-improving style learning."""

from .dispatcher import Dispatcher
from .style_learner import StyleLearner
from .contact_resolver import Contact, ContactResolver, Resolution

__all__ = ["Dispatcher", "StyleLearner", "Contact", "ContactResolver", "Resolution"]