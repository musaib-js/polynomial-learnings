"""Unit tests for the error hierarchy and library logging conventions.

No DB, no network.
"""

from __future__ import annotations

import logging

import learnings
from learnings.exceptions import (
    CurationError,
    JudgeError,
    JudgeOutputError,
    JudgeUnavailableError,
    LearningsError,
)


def test_exception_hierarchy():
    assert issubclass(JudgeError, LearningsError)
    assert issubclass(JudgeOutputError, JudgeError)
    assert issubclass(JudgeUnavailableError, JudgeError)
    assert issubclass(CurationError, LearningsError)


def test_exceptions_are_exported_from_package_root():
    for name in (
        "LearningsError",
        "JudgeError",
        "JudgeOutputError",
        "JudgeUnavailableError",
        "CurationError",
    ):
        assert hasattr(learnings, name)


def test_package_logger_has_a_null_handler_only():
    logger = logging.getLogger("learnings")
    assert any(isinstance(h, logging.NullHandler) for h in logger.handlers)
    # The library must never configure a level or a real handler on import —
    # that would override the host application's logging setup.
    assert logger.level == logging.NOTSET
