"""
email_data_pipeline
~~~~~~~~~~~~~~~~~~~
Complete, modular data engineering pipeline for fine-tuning Qwen2.5-3B-Instruct
into a Personalized AI Email Writer (Stage 1: SFT, Stage 2: DPO).
"""

from .config import PipelineConfig, StyleMetadata, SFTRow, DPORow
from .deduplication.deduplicator import Deduplicator
from .pipeline import DataPipeline

__all__ = [
    "PipelineConfig",
    "StyleMetadata",
    "SFTRow",
    "DPORow",
    "Deduplicator",
    "DataPipeline",
]
