"""Centralized, typed configuration.

Replaces scattered ``os.environ``/``os.getenv`` reads across ``api/app.py``,
``pgvector_backend.py``, ``judge.py``, and ``api/deps.py`` with one typed
object, loaded once from the process environment.

Reads ``.env`` itself (via pydantic-settings' ``env_file``) rather than
relying on some other module having already called ``load_dotenv()`` first.
That used to be the case here, and it was fragile: ``Settings()`` is built
at import time, so if anything imported this module before ``api/app.py``
got around to calling ``load_dotenv()``, values like ``CORS_ORIGINS`` would
silently resolve to their defaults for the lifetime of the process — no
error, just CORS quietly not working. Reading ``.env`` directly makes this
correct regardless of import order or which entry point is used.

Existing call sites are not required to switch over immediately — this module
is additive. New SaaS code (auth, dashboard routes) should read config from
:data:`settings` rather than calling ``os.environ`` directly.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# polynomial-learnings/.env — same file api/app.py and docker-compose.yml use.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_ENV_FILE, extra="ignore")

    # -- existing config (previously scattered os.environ reads) -----------
    database_url: str = ""
    groq_api_key: str | None = None
    reranker_model: str | None = None
    rerank_threshold: float = 0.52

    # -- new: SaaS auth/tenancy config --------------------------------------
    jwt_secret: str = "dev-only-insecure-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_access_token_ttl_seconds: int = 15 * 60
    jwt_refresh_token_ttl_seconds: int = 30 * 24 * 60 * 60

    # Comma-separated list of allowed browser origins for the dashboard SPA.
    # No wildcard default: an empty/unset value means "no cross-origin
    # access", which is the safe default for a real deployment. Local dev
    # should set this explicitly (e.g. "http://localhost:5173").
    cors_origins: str = ""

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
