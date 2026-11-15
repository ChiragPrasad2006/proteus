"""Local few-shot retrieval using sentence-transformers + LanceDB."""

from .embedder import LocalEmbedder
from .vector_store import LanceDBVectorStore

__all__ = ["LocalEmbedder", "LanceDBVectorStore"]