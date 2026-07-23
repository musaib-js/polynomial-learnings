"""Unit tests for the Persist Learning API's decision models.

Pure model-invariant tests — no DB, no network, no embedder.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from learnings.models import GeneratedLearning, JudgeVerdict, PersistResult, Verdict


def _learning(**overrides) -> GeneratedLearning:
    fields = dict(context="user asks about X", content="always do Y")
    fields.update(overrides)
    return GeneratedLearning(**fields)


# -- JudgeVerdict ----------------------------------------------------------


def test_reject_verdict_requires_no_learning():
    verdict = JudgeVerdict(verdict=Verdict.reject, reason="trivial restatement")
    assert verdict.learning is None


def test_reject_verdict_rejects_a_generated_learning():
    with pytest.raises(ValidationError, match="must not carry a generated learning"):
        JudgeVerdict(verdict=Verdict.reject, learning=_learning())


@pytest.mark.parametrize("verdict", [Verdict.same, Verdict.refine, Verdict.contradict])
def test_related_verdicts_require_related_learning_id(verdict):
    with pytest.raises(ValidationError, match="requires related_learning_id"):
        JudgeVerdict(
            verdict=verdict, learning=_learning() if verdict != Verdict.same else None
        )


@pytest.mark.parametrize("verdict", [Verdict.new, Verdict.refine, Verdict.contradict])
def test_persisting_verdicts_require_a_generated_learning(verdict):
    kwargs = {"verdict": verdict}
    if verdict is not Verdict.new:
        kwargs["related_learning_id"] = "existing-id"
    with pytest.raises(ValidationError, match="requires a generated learning"):
        JudgeVerdict(**kwargs)


def test_new_verdict_is_valid_without_related_id():
    verdict = JudgeVerdict(verdict=Verdict.new, learning=_learning())
    assert verdict.related_learning_id is None


def test_same_verdict_valid_without_a_generated_learning():
    verdict = JudgeVerdict(verdict=Verdict.same, related_learning_id="existing-id")
    assert verdict.learning is None


def test_refine_verdict_valid_with_learning_and_related_id():
    verdict = JudgeVerdict(
        verdict=Verdict.refine, related_learning_id="existing-id", learning=_learning()
    )
    assert verdict.learning.content == "always do Y"


# -- PersistResult -----------------------------------------------------------


def test_rejected_result_requires_no_learning_ids():
    result = PersistResult(decision="rejected", verdict=Verdict.reject, reason="unsafe")
    assert result.learning_id is None


def test_rejected_result_rejects_a_learning_id():
    with pytest.raises(ValidationError, match="must not carry learning ids"):
        PersistResult(decision="rejected", verdict=Verdict.reject, learning_id="abc")


def test_persisted_result_requires_a_learning_id():
    with pytest.raises(ValidationError, match="requires learning_id"):
        PersistResult(decision="persisted", verdict=Verdict.new)


def test_persisted_new_is_valid():
    result = PersistResult(decision="persisted", verdict=Verdict.new, learning_id="abc")
    assert result.superseded_id is None


def test_superseded_id_requires_contradict_verdict():
    with pytest.raises(ValidationError, match="only set for verdict=contradict"):
        PersistResult(
            decision="persisted",
            verdict=Verdict.new,
            learning_id="new-id",
            superseded_id="old-id",
        )


def test_contradict_result_carries_superseded_id():
    result = PersistResult(
        decision="persisted",
        verdict=Verdict.contradict,
        learning_id="new-id",
        superseded_id="old-id",
    )
    assert result.superseded_id == "old-id"


# -- GeneratedLearning defaults ----------------------------------------------


def test_generated_learning_defaults():
    learning = _learning()
    assert learning.tags == []
    assert learning.reason is None
