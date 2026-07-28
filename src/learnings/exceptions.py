"""Error hierarchy for the library.

Every exception the library deliberately raises subclasses ``LearningsError``,
so callers can catch broadly (``except LearningsError``) or narrowly.
"""

from __future__ import annotations


class LearningsError(Exception):
    """Base class for all errors raised by this library."""


class JudgeError(LearningsError):
    """Base class for errors from a ``Judge`` implementation."""


class JudgeUnavailableError(JudgeError):
    """The Judge could not be reached (network/API failure)."""


class JudgeOutputError(JudgeError):
    """The Judge responded, but its output could not be parsed/validated
    into a :class:`~learnings.models.JudgeVerdict` after all retries."""


class CurationError(LearningsError):
    """Raised for curator-level failures that aren't the Judge's fault —
    e.g. a verdict referencing a learning outside the isolation boundary."""


class SchemaDimensionError(LearningsError):
    """The embedder's vector dimension disagrees with the existing table.

    ``schema.sql`` fixes the width of ``learnings.embedding`` when the table is
    first created, and every statement in it is ``IF NOT EXISTS`` — so pointing
    a different-dimension model at a populated database would otherwise be a
    silent no-op that only surfaces on the first read or write.
    """


class LearningsAPIError(LearningsError):
    """Raised by ``LearningClient`` when an HTTP call to the API fails —
    either transport-level (unreachable, timeout) or a non-2xx response.

    ``status_code`` is ``None`` for transport failures (nothing came back),
    and the server's ``detail`` string otherwise.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
