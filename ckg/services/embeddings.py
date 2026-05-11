"""Local sentence-transformers embeddings.

First call loads the model into memory (one-off cost, ~80MB for MiniLM).
Subsequent calls are cheap.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

from ckg.config import get_settings

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def _model() -> "SentenceTransformer":
    from sentence_transformers import SentenceTransformer  # heavy import

    return SentenceTransformer(get_settings().embedding_model)


def embed_text(text: str) -> np.ndarray:
    """Returns a (dim,) float32 numpy array."""
    vec = _model().encode(text, normalize_embeddings=True)
    return np.asarray(vec, dtype=np.float32)


def embed_batch(texts: list[str]) -> np.ndarray:
    """(n, dim) float32."""
    if not texts:
        return np.zeros((0, get_settings().embedding_dim), dtype=np.float32)
    arr = _model().encode(texts, normalize_embeddings=True, batch_size=32, show_progress_bar=False)
    return np.asarray(arr, dtype=np.float32)
