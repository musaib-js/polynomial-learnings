"""Unit tests for the Judge interface: FakeJudge, the strict-schema
transform, and (opt-in) a real Groq call.

No DB. The live test only runs when GROQ_API_KEY is set.
"""

from __future__ import annotations

import os

import pytest

from learnings.exceptions import JudgeOutputError, JudgeUnavailableError
from learnings.judge import Judge, _force_strict, _strict_schema
from learnings.models import GeneratedLearning, JudgeVerdict, Verdict

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")


# -- FakeJudge ---------------------------------------------------------------


def test_fake_judge_returns_scripted_verdict():
    from learnings.judge import FakeJudge

    verdict = JudgeVerdict(verdict=Verdict.reject, reason="trivial")
    judge = FakeJudge(verdict)
    assert judge.evaluate("any prompt") is verdict


def test_fake_judge_supports_a_callable():
    from learnings.judge import FakeJudge

    def scripted(prompt: str) -> JudgeVerdict:
        if "contradiction" in prompt:
            return JudgeVerdict(
                verdict=Verdict.contradict,
                related_learning_id="old-id",
                learning=GeneratedLearning(context="c", content="new lesson"),
            )
        return JudgeVerdict(verdict=Verdict.reject)

    judge = FakeJudge(scripted)
    assert judge.evaluate("a contradiction here").verdict is Verdict.contradict
    assert judge.evaluate("small talk").verdict is Verdict.reject


def test_fake_judge_satisfies_judge_protocol():
    from learnings.judge import FakeJudge

    judge = FakeJudge(JudgeVerdict(verdict=Verdict.reject))
    assert isinstance(judge, Judge)


# -- strict schema transform ---------------------------------------------


def test_strict_schema_top_level_has_all_required_and_no_extras():
    schema = _strict_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"].keys())


def test_strict_schema_nested_defs_are_also_forced():
    schema = _strict_schema()
    defs = schema.get("$defs", {})
    assert "GeneratedLearning" in defs
    generated = defs["GeneratedLearning"]
    assert generated["additionalProperties"] is False
    assert set(generated["required"]) == set(generated["properties"].keys())


def test_force_strict_ignores_non_object_nodes():
    # Must not raise on scalars/lists/enum-shaped nodes.
    _force_strict({"type": "string"})
    _force_strict({"enum": ["a", "b"], "type": "string"})
    _force_strict("not a dict")
    _force_strict(None)


# -- GroqJudge: constructor / model-import behaviour --------------------


def test_groq_judge_requires_api_key_when_none_supplied(monkeypatch):
    from learnings.judge import GroqJudge

    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(KeyError):
        GroqJudge()


def test_groq_judge_strict_mode_flag_by_model():
    from learnings.judge import GroqJudge

    strict = GroqJudge(model="openai/gpt-oss-20b", api_key="fake-key-for-init-only")
    assert strict._strict is True
    assert strict._response_format["type"] == "json_schema"

    non_strict = GroqJudge(
        model="llama-3.3-70b-versatile", api_key="fake-key-for-init-only"
    )
    assert non_strict._strict is False
    assert non_strict._response_format == {"type": "json_object"}


# -- GroqJudge: output handling (mocked client, no network) --------------


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("Msg", (), {"content": content})()


class _FakeCompletion:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


class _FakeCompletionsAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return _FakeCompletion(item)


class _FakeChat:
    def __init__(self, completions_api):
        self.completions = completions_api


class _FakeGroqClient:
    def __init__(self, responses):
        self.chat = _FakeChat(_FakeCompletionsAPI(responses))


def _make_groq_judge(responses, max_retries=1):
    from learnings.judge import GroqJudge

    judge = GroqJudge(api_key="fake-key-for-init-only", max_retries=max_retries)
    judge._client = _FakeGroqClient(responses)
    return judge


def test_groq_judge_parses_valid_json_response():
    valid = JudgeVerdict(verdict=Verdict.reject, reason="ok").model_dump_json()
    judge = _make_groq_judge([valid])
    verdict = judge.evaluate("some prompt")
    assert verdict.verdict is Verdict.reject


def test_groq_judge_retries_once_on_malformed_json_then_succeeds():
    valid = JudgeVerdict(verdict=Verdict.reject).model_dump_json()
    judge = _make_groq_judge(["not json at all", valid], max_retries=1)
    verdict = judge.evaluate("some prompt")
    assert verdict.verdict is Verdict.reject
    assert judge._client.chat.completions.calls == 2


def test_groq_judge_raises_judge_output_error_after_exhausting_retries():
    judge = _make_groq_judge(["garbage", "still garbage"], max_retries=1)
    with pytest.raises(JudgeOutputError):
        judge.evaluate("some prompt")


def test_groq_judge_wraps_api_failure_as_judge_unavailable():
    judge = _make_groq_judge([RuntimeError("connection refused")], max_retries=1)
    with pytest.raises(JudgeUnavailableError):
        judge.evaluate("some prompt")


# -- Live Groq call (opt-in) ----------------------------------------------


@pytest.mark.skipif(not GROQ_API_KEY, reason="GROQ_API_KEY not set")
def test_live_groq_judge_returns_a_valid_verdict():
    from learnings.judge import GroqJudge

    judge = GroqJudge()
    prompt = (
        "Conversation:\nuser: Always format currency as $X.XX, never X.XX USD.\n\n"
        "No similar existing learnings were found.\n\n"
        "Decide: reject, or persist as a new learning. Respond with the "
        "structured verdict."
    )
    verdict = judge.evaluate(prompt)
    assert isinstance(verdict, JudgeVerdict)
