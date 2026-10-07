"""Google Ads Keyword Planner over REST (no client library), plus the quarterly metrics cache.

Needs a developer token with Basic access for real data, a Google Ads customer id and an OAuth refresh
token for a user who can access it. Without them `PlannerClient.configured` is False and callers fall back
to Search Console demand.
"""
import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.keywords.scoring import looks_like_bucket, normalise_keyword
from app.models.indexing import KeywordMetric

logger = logging.getLogger("helm.keywords")

PROVIDER = "keyword_planner"
CACHE_DAYS = 90
BATCH_SIZE = 700  # the historical-metrics call accepts up to 10,000 keywords; stay small and quick
MAX_LOOKUPS_PER_RUN = 1000
TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://googleads.googleapis.com/{version}/customers/{customer}"
# Google retires Ads API versions on a schedule; confirm the current one in Google's docs before deploying.
DEFAULT_API_VERSION = "v21"


class PlannerError(RuntimeError):
    pass


@dataclass
class PlannerMetric:
    keyword: str
    avg_monthly_searches: int | None
    competition_index: float | None  # 0-1
    monthly_series: list[int]
    is_bucket: bool


class PlannerClient:
    def __init__(self, http=None, geo: str | None = None, language: str | None = None, version: str | None = None):
        self.http = http or requests
        self.geo = geo or settings.keyword_geo
        self.language = language or settings.keyword_language
        self.version = version or settings.google_ads_api_version or DEFAULT_API_VERSION
        self._token: tuple[str, float] | None = None

    @property
    def configured(self) -> bool:
        return all(
            (
                settings.google_ads_developer_token,
                settings.google_ads_client_id,
                settings.google_ads_client_secret,
                settings.google_ads_refresh_token,
                settings.google_ads_customer_id,
            )
        )

    def _access_token(self) -> str:
        if self._token and self._token[1] > time.monotonic() + 60:
            return self._token[0]
        response = self.http.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_ads_client_id,
                "client_secret": settings.google_ads_client_secret,
                "refresh_token": settings.google_ads_refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            raise PlannerError(f"OAuth refresh failed: HTTP {response.status_code}")
        body = response.json()
        self._token = (body["access_token"], time.monotonic() + int(body.get("expires_in", 3600)))
        return self._token[0]

    def _post(self, method: str, body: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "developer-token": settings.google_ads_developer_token,
            "Content-Type": "application/json",
        }
        if settings.google_ads_login_customer_id:
            headers["login-customer-id"] = settings.google_ads_login_customer_id
        url = API_ROOT.format(version=self.version, customer=settings.google_ads_customer_id) + f":{method}"
        response = self.http.post(url, json=body, headers=headers, timeout=60)
        if response.status_code >= 400:
            raise PlannerError(f"{method} failed: HTTP {response.status_code}")
        return response.json()

    def _targeting(self) -> dict:
        return {
            "geoTargetConstants": [f"geoTargetConstants/{self.geo}"],
            "language": f"languageConstants/{self.language}",
            "keywordPlanNetwork": "GOOGLE_SEARCH",
        }

    @staticmethod
    def _parse(entries: list[dict], text_key: str) -> list[PlannerMetric]:
        out = []
        for entry in entries:
            metrics = entry.get("keywordMetrics") or {}
            avg = metrics.get("avgMonthlySearches")
            series = [int(m.get("monthlySearches", 0)) for m in metrics.get("monthlySearchVolumes", [])]
            avg = int(avg) if avg is not None else None
            competition = metrics.get("competitionIndex")
            out.append(
                PlannerMetric(
                    keyword=normalise_keyword(entry.get(text_key, "")),
                    avg_monthly_searches=avg,
                    competition_index=float(competition) / 100 if competition is not None else None,
                    monthly_series=series,
                    is_bucket=looks_like_bucket(avg, series),
                )
            )
        return out

    def historical_metrics(self, keywords: list[str]) -> list[PlannerMetric]:
        body = {"keywords": keywords, **self._targeting()}
        return self._parse(self._post("generateKeywordHistoricalMetrics", body).get("results", []), "text")

    def keyword_ideas(self, seeds: list[str] | None = None, url: str | None = None, limit: int = 200) -> list[PlannerMetric]:
        """Ideas from keyword seeds (up to 20) and/or a page URL, e.g. a competitor's page."""
        body: dict = {**self._targeting(), "pageSize": limit}
        if seeds and url:
            body["keywordAndUrlSeed"] = {"keywords": seeds[:20], "url": url}
        elif url:
            body["urlSeed"] = {"url": url}
        elif seeds:
            body["keywordSeed"] = {"keywords": seeds[:20]}
        else:
            raise PlannerError("give seeds or a url")
        return self._parse(self._post("generateKeywordIdeas", body).get("results", []), "text")


async def cached_metrics(db: AsyncSession, keywords: list[str], geo: str, language: str, now: datetime | None = None) -> dict[str, KeywordMetric]:
    now = now or datetime.now(timezone.utc)
    if not keywords:
        return {}
    rows = await db.execute(
        select(KeywordMetric).where(
            KeywordMetric.keyword.in_(keywords),
            KeywordMetric.geo == geo,
            KeywordMetric.language == language,
            KeywordMetric.provider == PROVIDER,
            KeywordMetric.fetched_at > now - timedelta(days=CACHE_DAYS),
        )
    )
    return {row.keyword: row for row in rows.scalars()}


async def store_metrics(db: AsyncSession, metrics: list[PlannerMetric], geo: str, language: str) -> None:
    for i in range(0, len(metrics), 500):
        values = [
            {
                "keyword": m.keyword,
                "geo": geo,
                "language": language,
                "provider": PROVIDER,
                "avg_monthly_searches": m.avg_monthly_searches,
                "is_bucket": m.is_bucket,
                "competition_index": m.competition_index,
                "monthly_series": m.monthly_series,
                "fetched_at": datetime.now(timezone.utc),
            }
            for m in metrics[i : i + 500]
        ]
        statement = insert(KeywordMetric).values(values)
        await db.execute(
            statement.on_conflict_do_update(
                constraint="uq_keyword_metrics_key",
                set_={c: statement.excluded[c] for c in ("avg_monthly_searches", "is_bucket", "competition_index", "monthly_series", "fetched_at")},
            )
        )
    await db.commit()


async def lookup(db: AsyncSession, client: PlannerClient, keywords: list[str]) -> dict[str, KeywordMetric | PlannerMetric]:
    """Cache first, then the API for the misses (capped per run). Keywords are matched on their normalised form."""
    wanted = list(dict.fromkeys(normalise_keyword(k) for k in keywords if k.strip()))
    found: dict = dict(await cached_metrics(db, wanted, client.geo, client.language))
    misses = [k for k in wanted if k not in found][:MAX_LOOKUPS_PER_RUN]
    if misses and client.configured:
        for i in range(0, len(misses), BATCH_SIZE):
            batch = misses[i : i + BATCH_SIZE]
            try:
                fetched = await asyncio.to_thread(client.historical_metrics, batch)
            except PlannerError as exc:
                logger.warning("Keyword Planner lookup failed: %s", exc)
                break
            await store_metrics(db, fetched, client.geo, client.language)
            found.update({m.keyword: m for m in fetched})
    return found
