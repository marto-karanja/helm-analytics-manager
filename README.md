# Helm Analytics Manager

A project management and analytics hub that unifies live health/traffic data from 8 SEO
publishing pipelines with portfolio-wide project tracking (goals, blockers, tasks) across
13 businesses/projects.

**Status:** early scaffold (backend auth + data model + local Postgres). See `PLAN.md` in
the `Shared Context` repo for the full design and build order.

## Architecture

- **Backend**: FastAPI + Postgres + SQLAlchemy (async) + `fastapi-users` for JWT auth.
- **Frontend**: Vite + React + shadcn/ui (not yet scaffolded).
- **Data ingestion**: a local script (`seo_dashboard/sync_to_hub.py`, lives alongside the
  data sources, not in this repo) pushes a combined payload to `POST /api/sync`. This app
  never reaches into the local dev machine — it only ever receives pushed data.

## Local development

Requires [`uv`](https://docs.astral.sh/uv/) and Docker.

```bash
cp .env.example .env        # then fill in real secrets
docker compose up -d postgres
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Run tests (uses the same Postgres instance, tables are created/dropped per session):

```bash
cd backend
uv run pytest --cov=app
```

## Environment variables

All prefixed `HELM_` — see `.env.example`. Never commit a real `.env`.
