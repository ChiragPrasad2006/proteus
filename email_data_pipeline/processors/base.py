"""
email_data_pipeline.processors.base
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Abstract base class defining interface and streaming helpers for dataset processors.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Generator, Iterator, List, Optional
from ..config import PipelineConfig
from ..deduplication.deduplicator import Deduplicator


class BaseDatasetProcessor(ABC):
    """Abstract base dataset processor with batching and memory management."""

    def __init__(self, config: PipelineConfig, deduplicator: Deduplicator):
        self.config = config
        self.deduplicator = deduplicator
        self.total_processed: int = 0
        self.total_accepted: int = 0
        self.total_dropped: int = 0
        self.dropped_for_slop: int = 0
        self.dropped_for_length: int = 0
        self.dropped_for_dupe: int = 0

    @abstractmethod
    def process(self) -> Generator[Dict[str, Any], None, None]:
        """Yields processed, validated rows one-by-one or in batches."""
        pass

    def get_stats(self) -> Dict[str, Any]:
        """Returns processing metrics."""
        return {
            "processed": self.total_processed,
            "accepted": self.total_accepted,
            "dropped": self.total_dropped,
            "dropped_for_slop": self.dropped_for_slop,
            "dropped_for_length": self.dropped_for_length,
            "dropped_for_dupe": self.dropped_for_dupe,
        }
