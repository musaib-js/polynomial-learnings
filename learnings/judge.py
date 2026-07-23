"""Pluggable Judge model (see SDD §9/§10).

A ``Judge`` is a callable-shaped object that takes a structured prompt and
returns a structured verdict — symmetric with ``Embedder``. Callers may bring
their own; the default ships a Groq-backed implementation so the library
produces genuine curated verdicts out of the box.
"""

from __future__ import annotations

import os
from typing import Callable, Protocol, runtime_checkable

from pydantic import ValidationError

from .exceptions import JudgeOutputError, JudgeUnavailableError
from .models import JudgeVerdict, TokenUsage

# Models Groq currently supports for strict, schema-enforced structured
# output (constrained decoding). Every other model falls back to plain
# JSON-object mode, which guarantees valid JSON but not schema compliance —
# we lean on Pydantic validation (with a retry) to catch the difference.
_STRICT_CAPABLE_MODELS = {"openai/gpt-oss-20b", "openai/gpt-oss-120b"}


@runtime_checkable
class Judge(Protocol):
    """Takes a structured prompt, returns a structured verdict.

    A Judge may *optionally* also implement
    ``evaluate_with_usage(prompt) -> (JudgeVerdict, TokenUsage | None)`` to
    report token consumption. Callers that want token accounting duck-type for
    it (``hasattr(judge, "evaluate_with_usage")``) and fall back to ``evaluate``
    otherwise, so this stays off the required interface.
    """

    def evaluate(self, prompt: str) -> JudgeVerdict:
        """Classify a persist candidate and, if warranted, generate it."""
        ...


class FakeJudge:
    """Test double — returns a scripted verdict (or one computed from the
    prompt), without any network call. Ships in the package so SDK
    consumers can test their own integrations against it too.
    """

    def __init__(self, verdict: JudgeVerdict | Callable[[str], JudgeVerdict]):
        self._verdict = verdict

    def evaluate(self, prompt: str) -> JudgeVerdict:
        if callable(self._verdict):
            return self._verdict(prompt)
        return self._verdict


def _force_strict(node: object) -> None:
    """Mutate a JSON-schema node in place to satisfy Groq strict mode:
    every object gets ``additionalProperties: false`` and *all* of its
    properties listed in ``required`` (optional fields stay optional via
    their ``anyOf [..., {"type": "null"}]`` shape, not by omission).
    """
    if not isinstance(node, dict):
        return
    props = node.get("properties")
    if props is not None:
        node["required"] = list(props.keys())
        node["additionalProperties"] = False
        for sub in props.values():
            _force_strict(sub)
    if "items" in node:
        _force_strict(node["items"])
    for key in ("anyOf", "oneOf", "allOf"):
        for sub in node.get(key, []):
            _force_strict(sub)


def _strict_schema() -> dict:
    """``JudgeVerdict.model_json_schema()``, patched to satisfy Groq's
    strict-mode requirements. ``$defs`` (nested models like
    ``GeneratedLearning``) are supported natively and just need the same
    per-object patch applied.
    """
    schema = JudgeVerdict.model_json_schema()
    _force_strict(schema)
    for sub in schema.get("$defs", {}).values():
        _force_strict(sub)
    return schema


class GroqJudge:
    """Judge backed by a Groq-hosted LLM.

    Requires the ``groq`` extra (``pip install polynomial-learnings[groq]``)
    and a ``GROQ_API_KEY`` (env var, or pass ``api_key`` explicitly).
    """

    def __init__(
        self,
        model: str = "openai/gpt-oss-20b",
        api_key: str | None = None,
        temperature: float = 0.0,
        max_retries: int = 1,
    ):
        from groq import Groq  # optional dep, per HuggingFaceEmbedder's pattern

        self._client = Groq(api_key=api_key or os.environ["GROQ_API_KEY"])
        self._model = model
        self._temperature = temperature
        self._max_retries = max_retries
        self._strict = model in _STRICT_CAPABLE_MODELS
        self._response_format = self._build_response_format()

    def _build_response_format(self) -> dict:
        if self._strict:
            return {
                "type": "json_schema",
                "json_schema": {
                    "name": "judge_verdict",
                    "strict": True,
                    "schema": _strict_schema(),
                },
            }
        # Non-strict models: valid JSON is guaranteed, schema compliance is not.
        return {"type": "json_object"}

    def evaluate(self, prompt: str) -> JudgeVerdict:
        verdict, _ = self.evaluate_with_usage(prompt)
        return verdict

    def evaluate_with_usage(self, prompt: str) -> tuple[JudgeVerdict, TokenUsage]:
        """Like :meth:`evaluate`, but also returns the tokens consumed.

        Token counts accumulate across retries, since every attempt is a real
        API call that burns tokens — the returned :class:`TokenUsage` reflects
        the full cost of producing the verdict, not just the successful call.
        """
        last_error: Exception | None = None
        usage = TokenUsage(model=self._model)
        for _ in range(self._max_retries + 1):
            try:
                completion = self._client.chat.completions.create(
                    model=self._model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self._temperature,
                    response_format=self._response_format,
                )
            except Exception as exc:  # network / API-level failure, not retried here
                raise JudgeUnavailableError(str(exc)) from exc

            self._accumulate_usage(usage, completion)

            raw = completion.choices[0].message.content
            try:
                return JudgeVerdict.model_validate_json(raw), usage
            except (ValidationError, ValueError) as exc:
                last_error = exc
                continue

        raise JudgeOutputError(
            f"Judge output failed validation after {self._max_retries + 1} "
            f"attempt(s): {last_error}"
        )

    @staticmethod
    def _accumulate_usage(usage: TokenUsage, completion: object) -> None:
        """Add one completion's token counts into ``usage`` (best-effort).

        Providers may omit usage on some responses; a missing block simply
        contributes nothing rather than failing the call.
        """
        raw = getattr(completion, "usage", None)
        if raw is None:
            return
        usage.prompt_tokens += int(getattr(raw, "prompt_tokens", 0) or 0)
        usage.completion_tokens += int(getattr(raw, "completion_tokens", 0) or 0)
        total = getattr(raw, "total_tokens", None)
        usage.total_tokens += (
            int(total) if total is not None
            else int(getattr(raw, "prompt_tokens", 0) or 0)
            + int(getattr(raw, "completion_tokens", 0) or 0)
        )
