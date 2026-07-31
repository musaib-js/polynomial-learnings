"""polynomial-learnings — vector ingestion and retrieval for agent learnings."""

import logging

from .backend import SearchFilter, VectorStoreBackend
from .embedder import Embedder, HuggingFaceEmbedder
from .exceptions import (
    CurationError,
    JudgeError,
    JudgeOutputError,
    JudgeUnavailableError,
    LearningsError,
    SchemaDimensionError,
)
from .judge import FakeJudge, GroqJudge, Judge
from .manager import LearningManager
from .models import (
    AgentStats,
    GeneratedLearning,
    JudgeVerdict,
    Learning,
    Message,
    MostUsedLearning,
    OperationTokenTotals,
    Outcome,
    PersistResult,
    Scope,
    Status,
    TokenUsage,
    TokenUsageRecord,
    TokenUsageStats,
    Verdict,
)
from .reranker import CrossEncoderReranker, FakeReranker, Reranker
from .retriever import HybridRetriever, reciprocal_rank_fusion

# ``pgvector_backend`` is the only module that imports psycopg, so importing it
# here would force every agent-side SDK install to carry a Postgres driver it
# never uses. Resolved lazily instead (PEP 562), so ``from learnings import
# PgVectorBackend`` still works wherever the ``server`` extra is installed.
_SERVER_ONLY = {"PgVectorBackend", "init_schema"}


def __getattr__(name: str):
    if name in _SERVER_ONLY:
        try:
            from . import pgvector_backend
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                f"{name} needs the Postgres backend, which ships in the 'server' "
                f"extra: pip install polynomial-learnings[server]"
            ) from exc
        return getattr(pgvector_backend, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Library convention: never configure handlers here — that's the
# application's job. A NullHandler silences "no handlers found" warnings
# for callers who haven't configured logging at all.
logging.getLogger("learnings").addHandler(logging.NullHandler())

__all__ = [
    "Learning",
    "Message",
    "AgentStats",
    "MostUsedLearning",
    "TokenUsage",
    "TokenUsageRecord",
    "TokenUsageStats",
    "OperationTokenTotals",
    "Scope",
    "Outcome",
    "Status",
    "Verdict",
    "GeneratedLearning",
    "JudgeVerdict",
    "PersistResult",
    "Embedder",
    "HuggingFaceEmbedder",
    "Judge",
    "FakeJudge",
    "GroqJudge",
    "VectorStoreBackend",
    "SearchFilter",
    "PgVectorBackend",
    "init_schema",
    "Reranker",
    "FakeReranker",
    "CrossEncoderReranker",
    "HybridRetriever",
    "reciprocal_rank_fusion",
    "LearningManager",
    "LearningsError",
    "JudgeError",
    "JudgeUnavailableError",
    "JudgeOutputError",
    "CurationError",
    "SchemaDimensionError",
]
