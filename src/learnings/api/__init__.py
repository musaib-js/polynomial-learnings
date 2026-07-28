"""HTTP API layer for polynomial-learnings.

A thin FastAPI suite on top of ``LearningManager`` — the integration surface for
the SDK platform (dashboards, other agents, cross-language clients). Requires the
``api`` extra (``pip install polynomial-learnings[api]``).
"""

from .app import app, create_app

__all__ = ["app", "create_app"]
