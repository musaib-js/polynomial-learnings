# Changelog

## 0.1.0

### Added

- Initial SDK packaging: `src/` layout, setuptools build backend, and
  optional-dependency extras (`huggingface`, `pydantic-ai`, `api`, `client`,
  `groq`, `all`, `dev`).

### Changed

- `schema.sql` now ships inside the `learnings` package, so `init_schema()`
  works from an installed wheel and not only from a source checkout.
- The Vite dashboard, `docker-compose.yml`, and the `test_score.py` scratch
  script are no longer part of the repo.
