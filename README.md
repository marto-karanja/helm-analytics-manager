# Helm Analytics Manager

A project management and analytics hub that unifies live health/traffic data from 8 SEO
publishing pipelines with portfolio-wide project tracking (goals, blockers, tasks) across
13 businesses/projects.

## Architecture

- **Backend** (`backend/`): FastAPI + async SQLAlchemy + Postgres 16, `fastapi-users` for JWT auth,
  Alembic migrations.
- **Frontend** (`frontend/`): Vite + React 19 + Tailwind + shadcn/ui + Recharts. Light/Dark/System theme.
  Talks to the API at the relative path `/api`.
- **Collector** (`backend/app/collector/`): a separate `collector` compose service that pulls Search
  Console and GA4 data server-side using a Google service-account key, on a schedule
  (`HELM_COLLECT_INTERVAL_HOURS`). It idles if no key is configured.
- **Data ingestion**: a local script (`seo_dashboard/sync_to_hub.py`, lives alongside the data sources,
  not in this repo) pushes pipeline health and portfolio data to `POST /api/sync`, authenticated with
  `HELM_SYNC_TOKEN`. The app never reaches into the dev machine; it only receives pushed data.
- **Demo mode**: `HELM_DEMO_MODE_SEED=true` seeds a frozen, read-only demo dataset.

Full design: `projecthub/PLAN.md` and `projecthub/ANALYTICS_IMPLEMENTATION_PLAN.md` in the
`Shared Context` workspace.

## Requirements

- [`uv`](https://docs.astral.sh/uv/) (installs Python 3.12+ for you)
- Docker with Compose v2 (Postgres, and the full stack in production)
- Node 20+ / npm (frontend)

## Local development

```bash
cp .env.example .env        # then edit: set HELM_SECRET_KEY and HELM_SYNC_TOKEN
```

For local runs outside Docker, point the database URL at the published Postgres port:
`HELM_DATABASE_URL=postgresql+asyncpg://helm:helm@localhost:5433/helm`
(the `.env.example` value uses the in-network hostname `postgres`, which only resolves inside compose).

```bash
# 1. Database
docker compose up -d postgres

# 2. Backend (http://127.0.0.1:8010)
cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli create-user you@example.com      # prompts for a 12+ char password
uv run uvicorn app.main:app --reload --port 8010

# 3. Frontend (http://localhost:5173, proxies /api to 127.0.0.1:8010)
cd ../frontend
npm ci
npm run dev
```

Public registration is disabled by default (`HELM_ALLOW_REGISTRATION=false`); accounts are created
with the CLI above.

### Tests

```bash
cd backend
uv run pytest --cov=app --cov-fail-under=70
```

Tests create and drop tables in a separate `<dbname>_test` database on the same server, never the
dev database. CI (`.github/workflows/backend-ci.yml`) runs migrations and the same coverage gate.

Frontend type-check and build: `cd frontend && npm run build`.

## Environment variables

All prefixed `HELM_`; see `.env.example`. Never commit a real `.env`.

| Variable | Purpose |
| --- | --- |
| `HELM_SECRET_KEY` | JWT signing key. Long random value. |
| `HELM_DATABASE_URL` | `postgresql+asyncpg://user:pass@host:port/db` |
| `HELM_ALLOWED_HOSTS` | JSON list of allowed CORS origins, e.g. `["https://helm.billtoolbox.com"]` |
| `HELM_SYNC_TOKEN` | Shared secret for `POST /api/sync` (the local sync script sends it as a Bearer token). |
| `HELM_DEMO_MODE_SEED` | `true` seeds the read-only demo dataset on startup. |
| `HELM_ALLOW_REGISTRATION` | Public sign-up. Leave `false`. |
| `HELM_GOOGLE_CREDENTIALS_FILE` | Service-account key path (set by compose for the collector). Empty = collector idles. |
| `HELM_COLLECT_INTERVAL_HOURS` | Hours between collector passes (default 24). |
| `HELM_COLLECT_BACKFILL_DAYS` | History pulled on a project's first collection (default 480). |

Compose-only: `HELM_POSTGRES_USER` / `HELM_POSTGRES_PASSWORD` / `HELM_POSTGRES_DB` /
`HELM_POSTGRES_PORT` (default 5433) / `HELM_WEB_PORT` (default 8010).

## Production deployment (main_server)

Live at `https://helm.billtoolbox.com`. On the server the app lives in
`/wp-data/websites/helm.billtoolbox.com-django/`:

- `docker compose` runs `postgres` (127.0.0.1:5433), `web` (127.0.0.1:8010) and `collector`; all ports
  are bound to localhost only.
- nginx serves `frontend/dist` as static files and proxies `/api/` to `127.0.0.1:8010`. TLS is
  terminated by Cloudflare; a Cloudflare Tunnel feeds nginx on port 80.
- `.env` on the server is mode 600 and must use `HELM_DATABASE_URL=postgresql+asyncpg://helm:<pw>@postgres:5432/helm`
  and `HELM_ALLOWED_HOSTS=["https://helm.billtoolbox.com"]`. Use the same password in
  `HELM_POSTGRES_PASSWORD`.

### Deploying an update

The frontend is built on the dev machine and uploaded (the server does not run Node), so the order is:

```bash
# on the dev machine, from the repo root
git push origin main
cd frontend && npm ci && npm run build                # produces frontend/dist

# copy source and the built frontend to the server (exclude .env, secrets/, node_modules, .venv, .git)
rsync -az --delete --exclude '.env' --exclude 'secrets/' --exclude '.git/' \
      --exclude 'node_modules/' --exclude '.venv/' --exclude '__pycache__/' \
      ./ main_server:/wp-data/websites/helm.billtoolbox.com-django/

# on the server
cd /wp-data/websites/helm.billtoolbox.com-django
docker compose build web collector
docker compose run --rm web uv run alembic upgrade head    # migrations BEFORE restarting
docker compose up -d
curl -s http://127.0.0.1:8010/api/health                   # {"status":"ok"}
```

Deploy the backend before using a newer `sync_to_hub.py`, since the sync payload contract changed.

### Enabling the Search Console / GA4 collector

1. Create a Google Cloud service account with the Search Console API and Analytics Data API enabled.
2. Add the service-account email as a user on each Search Console property and each GA4 property.
3. Put the key at `secrets/google-sa.json` on the server (`secrets/` is gitignored and mounted read-only
   into the collector only).
4. Tell Helm which properties belong to which project:
   ```bash
   docker compose run --rm web uv run python -m app.cli set-analytics <project-slug> \
       --gsc sc-domain:example.com --ga4 properties/123456789
   ```
5. The collector picks the key up on its own (it re-checks hourly while idle); run
   `docker compose restart collector` to start immediately. It then collects every
   `HELM_COLLECT_INTERVAL_HOURS`. Force a single pass with
   `docker compose run --rm collector uv run --no-dev python -m app.collector --once`.

### Pushing pipeline data from the dev machine

Put the value of `HELM_SYNC_TOKEN` in `seo_dashboard/credentials/helm_sync_token.txt`, then run
`python sync_to_hub.py` (add `--dry-run` to print the payload instead of sending it).
