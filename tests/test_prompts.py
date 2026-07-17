"""Unit tests for Judge prompt construction. Pure function, no I/O."""

from __future__ import annotations

from learnings.models import Learning, Message, Scope
from learnings.prompts import build_judge_prompt


def _messages() -> list[Message]:
    return [
        Message(role="user", content="Always format currency as $X.XX"),
        Message(role="user", content="not X.XX USD, just the dollar sign"),
    ]


def _learning(**overrides) -> Learning:
    fields = dict(
        agent_id="agent-1",
        entity_id="alice",
        scope=Scope.personal,
        context="user asks about currency formatting",
        content="format as X.XX USD",
    )
    fields.update(overrides)
    return Learning(**fields)


def test_prompt_includes_every_conversation_message():
    prompt = build_judge_prompt(_messages(), [])
    assert "Always format currency as $X.XX" in prompt
    assert "not X.XX USD, just the dollar sign" in prompt


def test_prompt_with_no_neighbours_says_none_found():
    prompt = build_judge_prompt(_messages(), [])
    assert "none found" in prompt.lower()


def test_prompt_includes_every_neighbour_id_and_content():
    neighbours = [
        _learning(id="learning-a"),
        _learning(id="learning-b", content="other lesson"),
    ]
    prompt = build_judge_prompt(_messages(), neighbours)
    assert "learning-a" in prompt
    assert "learning-b" in prompt
    assert "other lesson" in prompt


def test_prompt_mentions_both_judgement_gates():
    prompt = build_judge_prompt(_messages(), [])
    lower = prompt.lower()
    assert "novelty" in lower
    assert "worth-keeping" in lower


def test_prompt_mentions_scope_decision():
    prompt = build_judge_prompt(_messages(), [])
    assert "personal" in prompt.lower()
    assert "global" in prompt.lower()
