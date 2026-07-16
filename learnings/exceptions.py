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
