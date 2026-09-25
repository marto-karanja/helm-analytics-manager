from sqlalchemy import select

from app.core.config import settings
from app.db.session import async_session_maker
from app.models.project import PipelineSnapshot, Project, TrafficSnapshot


async def test_sync_rejects_bad_token(client):
    resp = await client.post("/api/sync", json={}, headers={"Authorization": "Bearer wrong-token"})
    assert resp.status_code == 401


async def test_sync_accepts_valid_token_with_empty_payload(client):
    resp = await client.post(
        "/api/sync", json={}, headers={"Authorization": f"Bearer {settings.sync_token}"}
    )
    assert resp.status_code == 202
    assert resp.json() == {
        "portfolio_created": 0,
        "portfolio_updated": 0,
        "pipelines_created": 0,
        "pipelines_updated": 0,
    }


async def test_sync_creates_then_updates_portfolio_project(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    item = {
        "slug": "sync-test-project",
        "name": "Sync Test Project",
        "category": "seo-content-site",
        "url": "https://example.com",
        "local_repo": r"D:\staging\sync-test",
        "operational_signals": "seo_dashboard (live)",
        "last_updated": "2026-09-01",
        "goals": "Ship it",
        "current_status": "In progress",
        "blockers": None,
        "priority_notes": None,
    }

    create_resp = await client.post("/api/sync", json={"portfolio": [item]}, headers=headers)
    assert create_resp.status_code == 202
    assert create_resp.json()["portfolio_created"] == 1
    assert create_resp.json()["portfolio_updated"] == 0

    async with async_session_maker() as session:
        result = await session.execute(select(Project).where(Project.slug == "sync-test-project"))
        project = result.scalar_one()
        assert project.goals == "Ship it"

    # Re-sync with a changed metadata field and an attempted (and ignored) goals edit.
    item["category"] = "renamed-category"
    item["goals"] = "This should not overwrite the UI-edited value"
    update_resp = await client.post("/api/sync", json={"portfolio": [item]}, headers=headers)
    assert update_resp.status_code == 202
    assert update_resp.json()["portfolio_created"] == 0
    assert update_resp.json()["portfolio_updated"] == 1

    async with async_session_maker() as session:
        result = await session.execute(select(Project).where(Project.slug == "sync-test-project"))
        project = result.scalar_one()
        assert project.category == "renamed-category"
        assert project.goals == "Ship it"


def _pipeline_item(**overrides):
    item = {
        "slug": "sync-test-pipeline",
        "name": "Sync Test Pipeline",
        "url": "https://example.com",
        "metrics": {
            "total_articles_written": 20,
            "backlog_count": 4,
            "blocked_count": 0,
            "oldest_backlog_age_days": 2,
            "last_published_at": "2026-09-01T12:00:00+00:00",
            "last_7_runs": [{"start": "2026-09-01T12:00:00+00:00", "end": "2026-09-01T12:01:00+00:00", "exit_code": 0, "failed": False}],
        },
        "pipeline_alert_severity": "green",
        "pipeline_alert_messages": [],
    }
    item.update(overrides)
    return item


async def test_sync_creates_pipeline_project_with_pipeline_snapshot_only(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    resp = await client.post("/api/sync", json={"pipelines": [_pipeline_item()]}, headers=headers)
    assert resp.status_code == 202
    assert resp.json()["pipelines_created"] == 1

    async with async_session_maker() as session:
        result = await session.execute(select(Project).where(Project.slug == "sync-test-pipeline"))
        project = result.scalar_one()
        assert project.is_pipeline is True
        assert project.category == "seo-content-site"

        snap_result = await session.execute(
            select(PipelineSnapshot).where(PipelineSnapshot.project_id == project.id)
        )
        snapshot = snap_result.scalar_one()
        assert snapshot.backlog_count == 4
        assert snapshot.alert_severity == "green"

        traffic_result = await session.execute(
            select(TrafficSnapshot).where(TrafficSnapshot.project_id == project.id)
        )
        assert traffic_result.scalars().all() == []


async def test_sync_unifies_pipeline_and_portfolio_by_slug(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    portfolio_item = {
        "slug": "unified-project",
        "name": "UnifiedProject",
        "category": "seo-content-site",
        "url": "https://unified.example.com",
        "goals": "Grow traffic",
    }
    await client.post("/api/sync", json={"portfolio": [portfolio_item]}, headers=headers)

    pipeline_resp = await client.post(
        "/api/sync",
        json={"pipelines": [_pipeline_item(slug="unified-project", name="UnifiedProject")]},
        headers=headers,
    )
    assert pipeline_resp.status_code == 202
    assert pipeline_resp.json()["pipelines_created"] == 0
    assert pipeline_resp.json()["pipelines_updated"] == 1

    async with async_session_maker() as session:
        result = await session.execute(select(Project).where(Project.slug == "unified-project"))
        matches = result.scalars().all()
        assert len(matches) == 1
        project = matches[0]
        assert project.is_pipeline is True
        assert project.goals == "Grow traffic"


async def test_sync_leaves_analytics_identifiers_untouched(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    await client.post("/api/sync", json={"pipelines": [_pipeline_item(slug="ids-project")]}, headers=headers)

    async with async_session_maker() as session:
        project = (await session.execute(select(Project).where(Project.slug == "ids-project"))).scalar_one()
        project.gsc_site_url = "sc-domain:example.com"
        project.ga4_property_id = "properties/123"
        await session.commit()

    resp = await client.post("/api/sync", json={"pipelines": [_pipeline_item(slug="ids-project")]}, headers=headers)
    assert resp.status_code == 202

    async with async_session_maker() as session:
        project = (await session.execute(select(Project).where(Project.slug == "ids-project"))).scalar_one()
        assert project.gsc_site_url == "sc-domain:example.com"
        assert project.ga4_property_id == "properties/123"


async def test_sync_ignores_identifiers_sent_by_older_clients(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    item = _pipeline_item(slug="legacy-ids", gsc_site_url="https://old.example.com/", ga4_property_id="properties/9")
    await client.post("/api/sync", json={"pipelines": [item]}, headers=headers)

    async with async_session_maker() as session:
        project = (await session.execute(select(Project).where(Project.slug == "legacy-ids"))).scalar_one()
        assert project.gsc_site_url is None
        assert project.ga4_property_id is None


async def test_sync_accepts_legacy_traffic_keys(client):
    headers = {"Authorization": f"Bearer {settings.sync_token}"}
    item = _pipeline_item(
        slug="legacy-traffic",
        traffic={"configured": True, "clicks": {"recent": 1, "prior": 2, "pct_change": -50.0}},
        traffic_alert_severity="yellow",
        traffic_alert_messages=[{"severity": "yellow", "message": "old"}],
    )
    resp = await client.post("/api/sync", json={"pipelines": [item]}, headers=headers)
    assert resp.status_code == 202

    async with async_session_maker() as session:
        project = (await session.execute(select(Project).where(Project.slug == "legacy-traffic"))).scalar_one()
        traffic = (
            await session.execute(select(TrafficSnapshot).where(TrafficSnapshot.project_id == project.id))
        ).scalars().all()
        assert traffic == []
