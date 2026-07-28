"""Reranking + thresholding stage for retrieval (see ``retriever.py``).

Inserted after RRF fusion and before results are returned: each fused
candidate is scored against the *original query* by a pluggable
``Reranker``, low-relevance candidates are dropped via a threshold, and only
survivors are touched/returned. Purely an in-process scoring step over
already-fetched ``Learning`` objects — no schema changes, no new tables, no
new database round-trips.

Disabled by default (``HybridRetriever(reranker=None)``), so this stage is
fully additive: existing retrieval behavior, and the persist flow's reuse of
this same retriever for novelty-check neighbours, are byte-identical unless
a reranker is explicitly configured.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

from .models import Learning


@runtime_checkable
class Reranker(Protocol):
    """Scores candidates against a query. Higher score = more relevant.

    Deliberately narrow: a ``Reranker`` only scores. Sorting, thresholding,
    and ``touch()`` stay the retriever's job — that keeps implementations
    trivially swappable and testable (see ``FakeReranker``), and keeps the
    threshold/top-k policy in one place (``HybridRetriever``) rather than
    duplicated across reranker implementations.
    """

    def score(self, query: str, candidates: Sequence[Learning]) -> list[float]:
        """Return one score per candidate, aligned by index with ``candidates``."""
        ...


class FakeReranker:
    """Test double — returns scripted scores without loading any model.

    Mirrors ``judge.FakeJudge``: pass either a fixed list of scores (must
    match ``len(candidates)`` at call time) or a callable for scores that
    depend on the query/candidates.
    """

    def __init__(
        self,
        scores: list[float] | Callable[[str, Sequence[Learning]], list[float]],
    ):
        self._scores = scores

    def score(self, query: str, candidates: Sequence[Learning]) -> list[float]:
        if callable(self._scores):
            return self._scores(query, candidates)
        if len(self._scores) != len(candidates):
            raise ValueError(
                f"FakeReranker was given {len(self._scores)} scripted scores "
                f"but {len(candidates)} candidates to score"
            )
        return list(self._scores)


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class CrossEncoderReranker:
    """Reranker backed by a Hugging Face cross-encoder.

    Default model: ``mixedbread-ai/mxbai-rerank-base-v1`` — free (Apache 2.0
    license), ~184M params, CPU-tractable, loadable via
    ``sentence-transformers.CrossEncoder`` like any other model here, so
    choosing it adds *zero* new dependencies.

    Why not ``cross-encoder/ms-marco-MiniLM-L-6-v2`` (the original default):
    it's trained on MS MARCO, a keyword-search dataset, so it rewards
    *lexical overlap* between query and document rather than semantic
    equivalence — measured on this project's data, "Should I write USD or
    use the dollar symbol?" (shares "USD"/"dollar"/"symbol" with the
    document) scored 0.9995, while "How should I mention currency?" (same
    question, no shared words) scored 0.0025. That's a model limitation,
    not a threshold problem — no threshold value distinguishes a true
    positive at 0.0025 from a true negative at 0.0000.

    Why not ``BAAI/bge-reranker-base`` (also considered): despite strong
    published benchmarks, empirically it produced near-identical ~0.50
    scores for both clearly relevant and clearly irrelevant inputs on this
    project's data (verified against both structured and plain-prose
    documents) — the signature of a classification head not loading
    correctly through the generic ``CrossEncoder`` wrapper for that
    checkpoint. Measured, not assumed: disqualified on hard evidence.

    ``mxbai-rerank-base-v1`` measured on the same failing cases: "How should
    I mention currency?" 0.0025 → 0.5717, "What is the preferred way to
    write money amounts?" 0.0711 → 0.5869 — while five different irrelevant
    queries (Kubernetes, pizza, timezones, testing frameworks, ...) all
    still land at ~0.50. Real caveat, not hidden: a maximally abstract
    paraphrase sharing zero vocabulary with the document ("How do I write
    money in reports?") measured only 0.5058 — barely above the irrelevant
    baseline. No small open-source reranker fully solves unlimited
    paraphrase; this remains a known, documented limitation.

    Why a cross-encoder and not another embedding-cosine pass: a
    cross-encoder scores the (query, document) pair *jointly* through the
    transformer, attending across both texts at once. The retrieval stage
    that already ran (vector search via cosine similarity) instead compares
    two *independently* computed embeddings — cheap and good for recall over
    a large candidate pool, but a materially weaker relevance signal than a
    joint pass. That accuracy gap is exactly what a rerank stage is for in a
    retrieve-then-rerank pipeline: cheap/wide first pass, expensive/precise
    second pass over a small candidate set.

    Requires the ``huggingface`` extra, same as ``HuggingFaceEmbedder``.

    Documents are rendered via ``Learning.rerank_text()`` — structured
    context/content plus ``category``/``tags`` when present.

    Score scale: sigmoid-normalized to [0, 1] by default
    (``apply_sigmoid=True``). Calibration measured on this model: irrelevant
    queries consistently land at ~0.50-0.503, the previously-failing
    paraphrases land at ~0.57-0.71, and realistic-but-terse relevant queries
    (e.g. "how do I get revenue by region?" against an unrelated stored
    lesson's real content) can land as low as ~0.545. ``HybridRetriever``'s
    default threshold of 0.52 sits just above the irrelevant baseline and
    below that terse-but-relevant floor — a tighter 0.55 was tried first and
    incorrectly rejected the revenue example. One honest limitation this
    doesn't fix: maximally abstract paraphrases sharing zero vocabulary with
    the document, and degenerate/placeholder text, can score in the same
    ~0.50 band as genuinely irrelevant queries — no threshold separates
    those cases from true negatives. Pass ``apply_sigmoid=False`` for raw
    unbounded logits (monotonically identical ordering; only the threshold
    scale changes).
    """

    def __init__(
        self,
        model: str = "mixedbread-ai/mxbai-rerank-base-v1",
        device: str | None = None,
        apply_sigmoid: bool = True,
    ):
        from sentence_transformers import CrossEncoder  # optional dep

        self._model = CrossEncoder(model, device=device)
        self._apply_sigmoid = apply_sigmoid

    def score(self, query: str, candidates: Sequence[Learning]) -> list[float]:
        if not candidates:
            return []
        pairs = [(query, candidate.rerank_text()) for candidate in candidates]
        raw = self._model.predict(pairs)

        if hasattr(raw, "tolist"):
            raw_list = raw.tolist()
        elif isinstance(raw, (list, tuple)):
            raw_list = list(raw)
        else:
            raw_list = [float(raw)]

        self._last_raw = raw_list
        if self._apply_sigmoid:
            return [_sigmoid(float(s)) for s in raw_list]
        return [float(s) for s in raw_list]
