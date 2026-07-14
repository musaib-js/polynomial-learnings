"""Pluggable embedder (see §9/§10 of the design doc).

An ``Embedder`` turns text into vectors and is used identically for writes and
reads. Callers may bring their own; the default ships a real Hugging Face
sentence-transformer model so the library produces genuine semantic embeddings
out of the box.
"""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class Embedder(Protocol):
    """Turns text into fixed-length vectors."""

    @property
    def dimension(self) -> int:
        """Length of every vector this embedder produces."""
        ...

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts, preserving order."""
        ...


class HuggingFaceEmbedder:
    """Default embedder backed by a Hugging Face sentence-transformer.

    Requires the ``huggingface`` extra
    (``pip install polynomial-learnings[huggingface]``). The model is downloaded
    once and cached locally, then runs fully offline.

    ``all-MiniLM-L6-v2`` (384 dims) is a small, fast, general-purpose default;
    pass any other sentence-transformers model name to swap it.
    """

    def __init__(
        self,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        device: str | None = None,
    ):
        from sentence_transformers import SentenceTransformer  # optional dep

        self._model = SentenceTransformer(model, device=device)
        # method was renamed across sentence-transformers versions.
        get_dim = getattr(
            self._model,
            "get_embedding_dimension",
            self._model.get_sentence_embedding_dimension,
        )
        self._dimension = get_dim()

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        # normalize so cosine distance in pgvector is well behaved.
        vectors = self._model.encode(
            list(texts), normalize_embeddings=True, convert_to_numpy=True
        )
        return [v.tolist() for v in vectors]
