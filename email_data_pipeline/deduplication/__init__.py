"""
email_data_pipeline.deduplication package
"""

from .deduplicator import Deduplicator, MinHash

__all__ = ["Deduplicator", "MinHash"]
