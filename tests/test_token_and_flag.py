"""Unit tests for token accounting and the empty-DB store short-circuit.

No live database: an in-memory fake backend records what the curator/manager
ask of it, so we can assert the neighbour search is skipped for a brand-new
agent and that judge token usage is persisted. DB-backed behaviour (the SQL
aggregation itself) is covered by the integration suites gated on DATABASE_URL.
"""

from __future__ import annotations

from learnings.curator import LearningCurator
from learnings.judge import FakeJudge
from learnings.manager import LearningManager
from learnings.models import (
    GeneratedLearning,
    JudgeVerdict,
    Learning,
    Message,
    Scope,
    TokenUsage,
    Verdict,
)

# -- fakes -------------------------------------------------------------------


class FakeEmbedder:
    dimension = 3

    def embed(self, texts):
        return [[0.0, 0.0, 0.0] for _ in texts]


class FakeRetriever:
    def __init__(self, result=None):
        self.result = result or []
        self.calls = 0

    def retrieve(self, **kwargs):
        self.calls += 1
        return list(self.result)


class FakeBackend:
    """Minimal in-memory VectorStoreBackend covering what the curator touches."""

    def __init__(self):
        self.rows: dict[str, Learning] = {}
        self.flags: dict[str, bool] = {}
        self.token_records = []

    # writes
    def upsert(self, learning, embedding):
        self.rows[learning.id] = learning

    def update(self, learning_id, **fields):
        row = self.rows.get(learning_id)
        if row is not None:
            for k, v in fields.items():
                setattr(row, k, v)

    def get(self, learning_id):
        return self.rows.get(learning_id)

    # token accounting
    def record_token_usage(self, record):
        self.token_records.append(record)

    def token_usage_stats(self, agent_id):
        recs = [r for r in self.token_records if r.agent_id == agent_id]
        return {
            "total_calls": len(recs),
            "prompt_tokens": sum(r.prompt_tokens for r in recs),
            "completion_tokens": sum(r.completion_tokens for r in recs),
            "total_tokens": sum(r.total_tokens for r in recs),
            "by_operation": [],
            "by_model": {},
        }

    # agent flag
    def get_agent_has_learnings(self, agent_id):
        return self.flags.get(agent_id, False)

    def set_agent_has_learnings(self, agent_id, has_learnings=True):
        self.flags[agent_id] = has_learnings


class UsageJudge:
    """A judge that reports token usage, exercising evaluate_with_usage."""

    def __init__(self, verdict, usage):
        self._verdict = verdict
        self._usage = usage

    def evaluate_with_usage(self, prompt):
        return self._verdict, self._usage

    def evaluate(self, prompt):
        return self._verdict


def _curator(backend, judge, retriever):
    return LearningCurator(backend, FakeEmbedder(), judge, retriever)


def _new_verdict():
    return JudgeVerdict(
        verdict=Verdict.new,
        learning=GeneratedLearning(
            context="ctx", content="lesson", scope=Scope.personal
        ),
    )


# -- empty-DB short-circuit --------------------------------------------------


def test_new_agent_skips_neighbour_search():
    backend = FakeBackend()
    retriever = FakeRetriever(result=[Learning(agent_id="a", context="x", content="y")])
    judge = UsageJudge(
        _new_verdict(),
        TokenUsage(model="m", prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    curator = _curator(backend, judge, retriever)

    result = curator.persist(
        "agent-1", [Message(role="user", content="hi")], entity_id="alice"
    )

    assert result.decision == "persisted"
    assert retriever.calls == 0  # neighbour search skipped entirely
    assert backend.flags["agent-1"] is True  # flag flipped after first persist


def test_existing_agent_runs_neighbour_search():
    backend = FakeBackend()
    backend.set_agent_has_learnings("agent-1", True)
    retriever = FakeRetriever(result=[])
    judge = UsageJudge(_new_verdict(), TokenUsage(model="m", total_tokens=15))
    curator = _curator(backend, judge, retriever)

    curator.persist("agent-1", [Message(role="user", content="hi")], entity_id="alice")

    assert retriever.calls == 1  # existing agent: search runs


def test_no_user_messages_short_circuits_before_flag_check():
    backend = FakeBackend()
    retriever = FakeRetriever()
    judge = UsageJudge(_new_verdict(), TokenUsage())
    curator = _curator(backend, judge, retriever)

    result = curator.persist("agent-1", [Message(role="assistant", content="hi")])

    assert result.decision == "rejected"
    assert retriever.calls == 0
    assert backend.token_records == []  # judge never called, no tokens


# -- token accounting --------------------------------------------------------


def test_judge_tokens_are_recorded_on_persist():
    backend = FakeBackend()
    judge = UsageJudge(
        _new_verdict(),
        TokenUsage(
            model="gpt-x", prompt_tokens=100, completion_tokens=40, total_tokens=140
        ),
    )
    curator = _curator(backend, judge, FakeRetriever())

    curator.persist("agent-1", [Message(role="user", content="hi")], entity_id="alice")

    assert len(backend.token_records) == 1
    rec = backend.token_records[0]
    assert rec.operation == "judge"
    assert rec.model == "gpt-x"
    assert (rec.prompt_tokens, rec.completion_tokens, rec.total_tokens) == (
        100,
        40,
        140,
    )
    assert rec.entity_id == "alice"


def test_tokens_recorded_even_when_rejected():
    backend = FakeBackend()
    judge = UsageJudge(
        JudgeVerdict(verdict=Verdict.reject, reason="trivial"),
        TokenUsage(model="gpt-x", total_tokens=25),
    )
    curator = _curator(backend, judge, FakeRetriever())

    result = curator.persist(
        "agent-1", [Message(role="user", content="hi")], entity_id="alice"
    )

    assert result.decision == "rejected"
    assert len(backend.token_records) == 1  # the judge call still cost tokens
    assert backend.flags.get("agent-1") is None  # nothing persisted, flag untouched


def test_judge_without_usage_support_records_nothing():
    backend = FakeBackend()
    judge = FakeJudge(_new_verdict())  # no evaluate_with_usage
    curator = _curator(backend, judge, FakeRetriever())

    result = curator.persist(
        "agent-1", [Message(role="user", content="hi")], entity_id="alice"
    )

    assert result.decision == "persisted"
    assert backend.token_records == []  # no usage reported, none recorded


# -- manager wiring ----------------------------------------------------------


def test_manager_record_sets_flag():
    backend = FakeBackend()
    manager = LearningManager(
        agent_id="agent-1", backend=backend, embedder=FakeEmbedder()
    )

    manager.record(context="ctx", content="content", entity_id="alice")

    assert backend.flags["agent-1"] is True


def test_manager_token_stats_assembles_model():
    backend = FakeBackend()
    manager = LearningManager(
        agent_id="agent-1", backend=backend, embedder=FakeEmbedder()
    )
    judge = UsageJudge(
        _new_verdict(),
        TokenUsage(model="m", prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    # Persist once through a curator sharing the same backend to generate a record.
    LearningCurator(backend, FakeEmbedder(), judge, FakeRetriever()).persist(
        "agent-1", [Message(role="user", content="hi")], entity_id="alice"
    )

    stats = manager.token_stats()

    assert stats.agent_id == "agent-1"
    assert stats.total_calls == 1
    assert stats.total_tokens == 15
