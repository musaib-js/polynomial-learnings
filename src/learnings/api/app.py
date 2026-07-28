"""FastAPI application factory and ASGI entry point.

Run with::

    uvicorn learnings.api.app:app

``DATABASE_URL`` must be set. The embedder, pgvector backend, and (if
``GROQ_API_KEY`` is set) judge are created once at startup and shared across
requests via ``app.state``.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..auth.store import AuthStore
from ..embedder import HuggingFaceEmbedder
from ..judge import GroqJudge
from ..pgvector_backend import PgVectorBackend, init_schema
from ..settings import INSECURE_JWT_SECRET, settings
from .auth_routes import router as auth_router
from .dashboard_routes import router as dashboard_router
from .routes import router

# Only needed for the plain os.environ reads below (DATABASE_URL,
# GROQ_API_KEY) — learnings/settings.py reads .env itself via pydantic-
# settings' env_file, so Settings() is correct regardless of import order or
# whether load_dotenv() has run yet.
load_dotenv()

# Surfaced in the startup error below so a mislocated .env is obvious.
_ENV_FILE_HINT = Path(__file__).resolve().parent.parent.parent.parent / ".env"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fail loudly rather than serving with a known secret. Anyone holding it
    # can mint a valid session token for any user, and the failure mode is
    # otherwise silent: pydantic-settings leaves fields at their defaults when
    # it cannot find .env, so a mislocated env file alone would trigger this.
    if settings.jwt_secret == INSECURE_JWT_SECRET:
        raise RuntimeError(
            "JWT_SECRET is still the built-in placeholder. Set JWT_SECRET in "
            ".env (or the environment) to a random secret before starting the "
            "API. If you did set it, check that .env is where settings.py "
            f"looks for it: {_ENV_FILE_HINT}"
        )

    dsn = os.environ["DATABASE_URL"]
    # No hardcoded fallback string here on purpose, matching get_reranker:
    # deferring to HuggingFaceEmbedder's own default keeps that class the
    # single source of truth for which model ships.
    embedder_model = os.getenv("EMBEDDER_MODEL")
    embedder = (
        HuggingFaceEmbedder(model=embedder_model)
        if embedder_model
        else HuggingFaceEmbedder()
    )
    # Raises SchemaDimensionError if this model's width disagrees with an
    # existing table — better a failed startup than writes that fail later.
    init_schema(dsn, embedder.dimension)
    backend = PgVectorBackend(dsn)
    app.state.embedder = embedder
    app.state.backend = backend
    # Nullable by design: GROQ_API_KEY is optional at deploy time. Retrieval
    # routes never touch app.state.judge; only /persist needs it, and
    # returns 503 (not a crash) when it's None. See deps.get_manager.
    app.state.judge = GroqJudge() if os.environ.get("GROQ_API_KEY") else None
    # Tenancy/identity store (users, orgs, api keys, agent ownership) — a
    # separate pool from the vector-store backend since this data has no
    # vectors and can scale/fail independently. See learnings/auth/store.py.
    app.state.auth_store = AuthStore(dsn)
    try:
        yield
    finally:
        backend.close()
        app.state.auth_store.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="polynomial-learnings API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS_ORIGINS is an explicit allowlist (see learnings/settings.py) — no
    # wildcard default. Auth uses Authorization: Bearer (not cookies), so
    # allow_credentials=True is not needed here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth_router)
    app.include_router(dashboard_router)
    app.include_router(router)

    @app.get("/health", summary="Liveness/readiness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
