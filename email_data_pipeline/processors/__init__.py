"""
email_data_pipeline.processors package
"""

from .base import BaseDatasetProcessor
from .dataset_a import DatasetAProcessor
from .dataset_b import DatasetBProcessor
from .dataset_c import DatasetCProcessor

__all__ = [
    "BaseDatasetProcessor",
    "DatasetAProcessor",
    "DatasetBProcessor",
    "DatasetCProcessor",
]
