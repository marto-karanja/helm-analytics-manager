import uuid
from datetime import datetime, timedelta, timezone

from app.db.session import async_session_maker
from app.models.project import PipelineSnapshot, Project


async def _pipeline(published_by_age: list[tuple[int, int, int]]) -> str:
    """A pipeline project with snapshots given as (days_ago, published, queued)."""
    slug = f"content-{uuid.uuid4()}"
    now = datetime.now(timezone.utc)
    async with async_session_maker() as session:
        project = Project(slug=slug, name=slug, category="seo-content-site", url="https://example.com", is_pipeline=True)
        session.add(project)
        await session.flush()
        for days_ago, published, queued in published_by_age:
            session.add(
                PipelineSnapshot(
                    project_id=project.id,
                    synced_at=now - timedelta(days=days_ago),
                    total_articles_written=published,
                    backlog_count=queued,
                    blocked_count=1,
                    alert_severity="green",
                )
            )
        await session.commit()
    return slug


def _item(body: dict, slug: str) -> dict:
    return next(i for i in body["items"] if i["slug"] == slug)


async def test_dashboard_requires_auth(client):
    assert (await client.get("/api/content/dashboard")).status_code == 401


async def test_dashboard_reports_published_queue_rate_and_days_to_clear(auth_client):
    slug = await _pipeline([(0, 120, 20), (10, 100, 30)])
    body = (await auth_client.get("/api/content/dashboard")).json()
    item = _item(body, slug)
    assert item["published"] == 120
    assert item["queued"] == 20
    assert item["blocked"] == 1
    assert item["published_per_day"] == 2.0  # 20 articles over 10 days
    assert item["days_to_clear_queue"] == 10
    assert [p["published"] for p in item["history"]] == [100, 120]  # oldest first
    assert body["totals"]["published"] >= 120 and body["totals"]["pipelines"] >= 1


async def test_dashboard_has_no_rate_with_one_snapshot_or_a_decreasing_count(auth_client):
    single = await _pipeline([(0, 50, 5)])
    reset = await _pipeline([(0, 10, 5), (7, 60, 5)])
    body = (await auth_client.get("/api/content/dashboard")).json()
    for slug in (single, reset):
        item = _item(body, slug)
        assert item["published_per_day"] is None
        assert item["days_to_clear_queue"] is None


async def test_dashboard_empty_queue_is_zero_days_not_unknown_rate(auth_client):
    slug = await _pipeline([(0, 110, 0), (10, 100, 5)])
    item = _item((await auth_client.get("/api/content/dashboard")).json(), slug)
    assert item["queued"] == 0
    assert item["days_to_clear_queue"] == 0


async def test_demo_user_sees_only_demo_pipelines(client):
    await client.post("/api/auth/demo-login")
    token = (await client.post("/api/auth/demo-login")).json()["access_token"]
    slug = await _pipeline([(0, 10, 1)])  # a real (non-demo) pipeline
    body = (await client.get("/api/content/dashboard", headers={"Authorization": f"Bearer {token}"})).json()
    assert all(i["slug"] != slug for i in body["items"])
