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
- **Indexing analysis** (`backend/app/indexing/`): the collector walks each project's sitemaps daily, fetches
  pages for content signals (title, word count, noindex, canonical, content hash), and spends a daily
  budget on Search Console URL Inspection. Every URL gets one primary issue: fetch error, blocked,
  duplicate risk, thin, crawled-not-indexed, discovered-not-indexed, or indexed. The rules live in
  `indexing/classify.py`.
- **Keyword generator** (`backend/app/keywords/`): weekly Search Console query rollups, Claude expansion into
  clusters, optional Keyword Planner volume, a score, and a human review step. Nothing publishes
  automatically; accepted keywords export to a `keyword_queue.json` per site.
- **MCP server** (`backend/app/mcp_server/`): a separate `mcp` compose service, streamable HTTP at `/mcp`,
  with scoped bearer tokens (created in Settings). A sibling public endpoint for the crawler lives in the
  `crawler-service` repo.
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

- `docker compose` runs `postgres` (127.0.0.1:5433), `web` (127.0.0.1:8010), `collector` and `mcp` (127.0.0.1:8020); all ports
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
docker compose build web collector mcp
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

## Indexing, keywords and MCP

### How the collector schedules work

One `collector` process runs a small scheduler (`HELM_SCHEDULER_TICK_SECONDS`, default 60). Each job runs when its
own interval has elapsed, tracked in `collector_runs.kind`; a job that failed or was skipped retries after an hour.

| Job (`kind`) | Interval | Needs Google key | What it does |
|---|---|---|---|
| `traffic` | `HELM_COLLECT_INTERVAL_HOURS` | yes | Search Console + GA4 daily rows |
| `sitemap_walk` | daily | no (sitemap status uses it) | Walk sitemaps, diff against `sitemap_urls`, read `sitemaps.list` |
| `page_signals` | daily | no | Fetch new/changed/stale URLs (300 per project per run, 1 request/second per host); JS-only pages fall back to the crawler service |
| `url_inspection` | daily | yes | Spend the inspection budget: never inspected first, then changed pages, then oldest |
| `gsc_query_rollup` | weekly | yes | Query+page rollups for the keyword generator, plus the weekly digest |

Queued "Inspect now" clicks are processed on every tick. The `web` container holds no Google credentials, so
it queues the request in `inspect_requests` and the collector, which does, runs it.

The container healthcheck requires a recent `traffic` run, and checks each other kind once it has run at all
(36 hours for daily jobs, 8 days for the weekly one).

Run a job on demand: `docker compose run --rm collector uv run --no-dev python -m app.collector --once --job sitemap_walk`
(`--job` takes any kind above; without it every job runs).

### Inspection budget

Settings holds the daily budget (default 500). The server clamps whatever is stored to a hard ceiling of
1,500, scheduled and manual inspections share the same count, and an optional per-project cap stops one big
site from using it all. A 429 from Google stops the run for the day.

### Keyword generator

Needs `HELM_ANTHROPIC_API_KEY`. Each run reads the last four complete weeks of Search Console queries and the
page titles, asks Claude for new keyword clusters (structured JSON output), and merges them with
**striking-distance** queries already ranking at positions 8 to 20. Demand per keyword is the best available of:

1. Keyword Planner volume, if `volume_source` is `keyword_planner` and Google Ads credentials are set;
2. Search Console impressions, divided by the share of searchers who reach that position;
3. a Keyword Planner range (Google gives only ranges to accounts without ad spend), ranked last;
4. nothing, shown as `n/a`.

Cost is recorded per call in `llm_spend` and runs stop at the daily cap in Settings. Keyword Planner answers are cached
for 90 days in `keyword_metrics`. Set the Google Ads variables in `.env.example` to enable it; the developer token needs
Basic access, and the API version is `HELM_GOOGLE_ADS_API_VERSION` because Google retires versions on a schedule.

Accepted keywords are exported to `HELM_KEYWORD_EXPORT_DIR/<slug>/keyword_queue.json` (the `web` and `mcp`
services share a volume at `/data/keyword-queues`). Helm cannot write into the sites' own directories, so
pipelines should pull the queue instead: `GET /api/keyword-queue/<slug>` with a read-scope token as the Bearer.

### Page rankings and the manual check

`gsc_query_rollups` keeps weekly clicks, impressions and average position per (query, page). `get_page_rankings`
(MCP) and `GET /api/v1/projects/<slug>/rankings` (REST, same bearer tokens) turn that into one row per page: the
impression-weighted position over the last N weeks, the change against the previous N weeks (positive means the
page moved up), top queries and indexing state. The weekly job is the default; **Refresh now** on the project's
Rankings tab, `POST /api/v1/projects/<slug>/rankings/refresh` and the `refresh_rankings` tool queue an on-demand
pull instead. The collector runs it within about a minute; the limit is one per project every 30 minutes.

### REST API for other projects

`/api/v1/...` takes the same bearer tokens as MCP, with the same per-project scoping, rate limit and audit log.
It is served by the `web` container, so it needs no tunnel entry beyond the one Helm already has.

### MCP server

`mcp` serves `https://mcp.billtoolbox.com/mcp` once the Cloudflare tunnel routes it to `127.0.0.1:8020`
(`HELM_MCP_ALLOWED_HOSTS` must include the public hostname). Create a token in Settings and add it to a client:

```bash
claude mcp add --transport http helm https://mcp.billtoolbox.com/mcp --header "Authorization: Bearer helm_..."
```

- Read tools: `list_projects`, `get_traffic`, `get_indexing_summary`, `list_urls`, `get_url_history`,
  `get_page_rankings`, `get_alerts`, `list_keyword_candidates`, `get_sitemap_status`, `get_keyword_run_status`.
- Write tools (write-scope tokens only): `inspect_url`, `refresh_rankings`, `run_keyword_generator`,
  `set_candidate_status`, `export_keyword_queue`.
- A token can be limited to named projects (`project_slugs`). A project outside the list answers exactly like one
  that does not exist.
- 60 calls a minute per token. Every call is logged to `mcp_calls` (token label, tool, a hash of the arguments, status).
- Tools return data only: never credentials, key-file contents or raw table dumps. `HELM_SYNC_TOKEN` is not accepted.
- Demo projects are not visible through MCP.

Consider putting Cloudflare Access in front of the hostname as a second layer, and revoke tokens you no longer use.
