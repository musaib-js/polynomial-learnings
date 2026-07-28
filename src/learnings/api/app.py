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

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..embedder import HuggingFaceEmbedder
from ..judge import GroqJudge
from ..pgvector_backend import PgVectorBackend, init_schema
from .routes import router

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    try:
        yield
    finally:
        backend.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="polynomial-learnings API",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Demo-friendly CORS: the static UI may be opened from file:// or a
    # different port. Wide-open is fine here because there is no auth and no
    # cookies; tighten allow_origins for any real deployment.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router)

    @app.get("/health", summary="Liveness/readiness probe")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
