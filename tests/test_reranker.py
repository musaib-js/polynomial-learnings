"""Unit tests for the Reranker abstraction: protocol conformance,
FakeReranker, and a real (small, CPU-fast) CrossEncoderReranker smoke test.

No DB. The CrossEncoderReranker test downloads a real ~80MB model on first
run (cached after), same convention as tests/test_bge_embedder.py.
"""

from __future__ import annotations

import pytest

from learnings.models import Learning
from learnings.reranker import CrossEncoderReranker, FakeReranker, Reranker


def _learning(content: str, **overrides) -> Learning:
    fields = dict(agent_id="agent-1", entity_id="alice", context="ctx", content=content)
    fields.update(overrides)
    return Learning(**fields)


# -- FakeReranker -----------------------------------------------------------


def test_fake_reranker_returns_fixed_scores_aligned_to_input_order():
    candidates = [_learning("a"), _learning("b"), _learning("c")]
    reranker = FakeReranker([9.0, 1.0, 5.0])

    scores = reranker.score("query", candidates)

    assert scores == [9.0, 1.0, 5.0]


def test_fake_reranker_rejects_mismatched_score_count():
    candidates = [_learning("a"), _learning("b")]
    reranker = FakeReranker([9.0])

    with pytest.raises(ValueError, match="scripted scores"):
        reranker.score("query", candidates)


def test_fake_reranker_supports_a_callable():
    def scorer(query, candidates):
        return [10.0 if "relevant" in c.content else 0.0 for c in candidates]

    reranker = FakeReranker(scorer)
    candidates = [_learning("relevant answer"), _learning("unrelated answer")]

    assert reranker.score("q", candidates) == [10.0, 0.0]


def test_fake_reranker_satisfies_reranker_protocol():
    reranker = FakeReranker([1.0])
    assert isinstance(reranker, Reranker)


def test_fake_reranker_handles_empty_candidates_via_callable():
    reranker = FakeReranker(lambda query, candidates: [])
    assert reranker.score("q", []) == []


# -- CrossEncoderReranker (real model, small + cached) -----------------


def test_cross_encoder_reranker_satisfies_protocol():
    reranker = CrossEncoderReranker()
    assert isinstance(reranker, Reranker)


def test_cross_encoder_reranker_scores_relevant_higher_than_irrelevant():
    reranker = CrossEncoderReranker()
    candidates = [
        _learning("Paris is the capital of France."),
        _learning("Bananas are a good source of potassium."),
    ]

    scores = reranker.score("What is the capital of France?", candidates)

    assert len(scores) == 2
    assert scores[0] > scores[1]


def test_cross_encoder_reranker_empty_candidates_returns_empty_list():
    reranker = CrossEncoderReranker()
    assert reranker.score("anything", []) == []


def test_cross_encoder_reranker_default_scores_are_sigmoid_bounded():
    """apply_sigmoid=True is the default: scores land in [0, 1] so the
    retriever's 0.52 default threshold reads on the right scale."""
    reranker = CrossEncoderReranker()
    candidates = [
        _learning("Paris is the capital of France."),
        _learning("Bananas are a good source of potassium."),
    ]

    scores = reranker.score("What is the capital of France?", candidates)

    assert all(0.0 <= s <= 1.0 for s in scores)


def test_cross_encoder_reranker_raw_logits_preserve_sigmoid_ordering():
    """apply_sigmoid=False opts back into raw logits; ordering must be
    identical since sigmoid is monotonic."""
    candidates = [
        _learning("Paris is the capital of France."),
        _learning("Bananas are a good source of potassium."),
    ]
    query = "What is the capital of France?"

    raw = CrossEncoderReranker(apply_sigmoid=False).score(query, candidates)
    sig = CrossEncoderReranker(apply_sigmoid=True).score(query, candidates)

    assert (raw[0] > raw[1]) == (sig[0] > sig[1])
    assert raw != sig  # raw logits are a different (unbounded) scale


# -- rerank_text document rendering ------------------------------------


def test_rerank_text_includes_category_and_tags_when_present():
    learning = _learning(
        "Never use the $ symbol; always write USD after the amount.",
        context="user asks how to format currency",
        category="formatting",
        tags=["currency", "usd"],
    )

    doc = learning.rerank_text()

    assert "Situation: user asks how to format currency" in doc
    assert "Lesson: Never use the $ symbol" in doc
    assert "Category: formatting" in doc
    assert "Tags: currency, usd" in doc


def test_rerank_text_omits_missing_metadata_lines():
    learning = _learning("some lesson")  # no category, no tags

    doc = learning.rerank_text()

    assert "Category:" not in doc
    assert "Tags:" not in doc
    assert doc.startswith("Situation: ")


def test_metadata_lifts_cross_encoder_score_for_topic_queries():
    """The measured motivation for rerank_text(): a topic query whose words
    never appear in the lesson body only clears the bar via category/tags."""
    reranker = CrossEncoderReranker()
    bare = _learning(
        "Never use the $ symbol; always write USD after the amount.",
        context="user asks about writing amounts",
    )
    tagged = _learning(
        "Never use the $ symbol; always write USD after the amount.",
        context="user asks about writing amounts",
        category="formatting",
        tags=["currency", "usd"],
    )

    bare_score, tagged_score = reranker.score("currency formatting", [bare, tagged])

    assert tagged_score > bare_score


# -- model selection: paraphrase acceptance / irrelevance rejection ------
#
# Regression coverage for the ms-marco-MiniLM-L-6-v2 -> mxbai-rerank-base-v1
# swap: that model rewarded lexical overlap over semantic equivalence, so a
# true paraphrase with zero shared vocabulary scored as if it were
# irrelevant (measured live: 0.0025, indistinguishable from an actually
# irrelevant query's 0.0000). These tests pin the fix against the default
# model and threshold, using the exact production document shape.

_CURRENCY_LEARNING = _learning(
    "Never use the $ symbol; always write USD after the amount.",
    context="user: Actually, never use $. Always write USD after the amount.",
    category="currency formatting",
    tags=["currency", "formatting", "personal"],
)

_DEFAULT_THRESHOLD = 0.52  # kept in sync with HybridRetriever's default


def test_paraphrased_relevant_queries_clear_the_default_threshold():
    """The two queries measured live as failing under the old model
    (0.0025 and 0.0711) must now clear the new default threshold."""
    reranker = CrossEncoderReranker()
    queries = [
        "How should I mention currency?",
        "What is the preferred way to write money amounts?",
        "Should I write USD or use the dollar symbol?",
    ]

    for query in queries:
        (score,) = reranker.score(query, [_CURRENCY_LEARNING])
        assert score >= _DEFAULT_THRESHOLD, (
            f"{query!r} scored {score}, expected >= {_DEFAULT_THRESHOLD}"
        )


def test_unrelated_queries_stay_below_the_default_threshold():
    reranker = CrossEncoderReranker()
    queries = [
        "How do I deploy Kubernetes on AWS?",
        "best pizza toppings",
        "what time zone should I use for logs",
        "recommend a python testing framework",
    ]

    for query in queries:
        (score,) = reranker.score(query, [_CURRENCY_LEARNING])
        assert score < _DEFAULT_THRESHOLD, (
            f"{query!r} scored {score}, expected < {_DEFAULT_THRESHOLD}"
        )


# -- runtime wiring: guards against the deps.py hardcoded-fallback bug ---
#
# get_reranker() previously hardcoded "cross-encoder/ms-marco-MiniLM-L-6-v2"
# as its RERANKER_MODEL fallback, which would have silently kept serving
# the old model even after CrossEncoderReranker's own default was upgraded.
# These pin both halves: the class default, and the composition root's use
# of it (no env var set).


def test_cross_encoder_reranker_default_model_is_mxbai():
    reranker = CrossEncoderReranker()
    assert reranker._model.config.name_or_path == "mixedbread-ai/mxbai-rerank-base-v1"


def test_deps_get_reranker_resolves_to_the_class_default(monkeypatch):
    monkeypatch.delenv("RERANKER_MODEL", raising=False)
    from learnings.api import deps

    deps.get_reranker.cache_clear()
    try:
        reranker = deps.get_reranker()
        assert (
            reranker._model.config.name_or_path == "mixedbread-ai/mxbai-rerank-base-v1"
        )
    finally:
        deps.get_reranker.cache_clear()


def test_deps_get_reranker_respects_env_override(monkeypatch):
    monkeypatch.setenv("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
    from learnings.api import deps

    deps.get_reranker.cache_clear()
    try:
        reranker = deps.get_reranker()
        assert (
            reranker._model.config.name_or_path
            == "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
    finally:
        deps.get_reranker.cache_clear()
