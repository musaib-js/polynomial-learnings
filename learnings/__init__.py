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
    Outcome,
    PersistResult,
    Scope,
    Status,
    Verdict,
)
from .pgvector_backend import PgVectorBackend, init_schema
from .retriever import HybridRetriever, reciprocal_rank_fusion

# Library convention: never configure handlers here — that's the
# application's job. A NullHandler silences "no handlers found" warnings
# for callers who haven't configured logging at all.
logging.getLogger("learnings").addHandler(logging.NullHandler())

__all__ = [
    "Learning",
    "Message",
    "AgentStats",
    "MostUsedLearning",
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
    "HybridRetriever",
    "reciprocal_rank_fusion",
    "LearningManager",
    "LearningsError",
    "JudgeError",
    "JudgeUnavailableError",
    "JudgeOutputError",
    "CurationError",
]
