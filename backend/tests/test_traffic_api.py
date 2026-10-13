import uuid
from datetime import date, timedelta

from sqlalchemy import select

from app.core.demo_seed import seed_demo_data
from app.db.session import async_session_maker
from app.models.project import Project, TrafficDaily, TrafficSnapshot

LAST_DAY = date(2026, 9, 10)


async def _add_days(project_id, count: int) -> None:
    async with async_session_maker() as session:
        session.add_all(
            TrafficDaily(
                project_id=project_id,
                metric_date=LAST_DAY - timedelta(days=count - 1 - i),
                clicks=i + 1,
                impressions=(i + 1) * 10,
                ctr=0.1,
                avg_position=5.0,
                sessions=i,
                engaged_sessions=i // 2,
            )
            for i in range(count)
        )
        await session.commit()


async def _new_project(**extra) -> Project:
    async with async_session_maker() as session:
        project = Project(
            slug=f"traffic-{uuid.uuid4()}", name="Traffic Test", category="seo-content-site", url="https://t.example",
            is_pipeline=True, **extra,
        )
        session.add(project)
        await session.commit()
        return project


async def _demo_headers(client) -> dict:
    async with async_session_maker() as session:
        await seed_demo_data(session)
    token = (await client.post("/api/auth/demo-login")).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def test_traffic_requires_auth(client, seeded_project):
    assert (await client.get(f"/api/projects/{seeded_project.id}/traffic")).status_code == 401
    assert (await client.get("/api/traffic/overview")).status_code == 401


async def test_traffic_returns_ascending_days_and_last_collected(auth_client):
    project = await _new_project()
    await _add_days(project.id, 5)

    body = (await auth_client.get(f"/api/projects/{project.id}/traffic")).json()

    dates = [d["metric_date"] for d in body["days"]]
    assert dates == sorted(dates)
    assert dates[-1] == LAST_DAY.isoformat()
    assert len(dates) == 5
    assert set(body["days"][0]) == {
        "metric_date", "clicks", "impressions", "ctr", "avg_position", "sessions", "engaged_sessions",
    }
    assert body["last_collected_at"] is not None


async def test_traffic_for_a_project_without_data_is_empty(auth_client):
    project = await _new_project()
    body = (await auth_client.get(f"/api/projects/{project.id}/traffic")).json()
    assert body == {"days": [], "last_collected_at": None}


async def test_traffic_days_window_is_anchored_on_the_newest_day(auth_client):
    project = await _new_project()
    await _add_days(project.id, 10)

    body = (await auth_client.get(f"/api/projects/{project.id}/traffic?days=3")).json()
    assert [d["metric_date"] for d in body["days"]] == [
        (LAST_DAY - timedelta(days=n)).isoformat() for n in (2, 1, 0)
    ]


async def test_traffic_days_window_keeps_gaps_as_gaps(auth_client):
    project = await _new_project()
    async with async_session_maker() as session:
        for offset in (0, 1, 20):
            session.add(TrafficDaily(project_id=project.id, metric_date=LAST_DAY - timedelta(days=offset), clicks=1))
        await session.commit()

    body = (await auth_client.get(f"/api/projects/{project.id}/traffic?days=7")).json()
    assert len(body["days"]) == 2  # the row 20 days back is outside the 7-day window


async def test_traffic_days_bounds(auth_client):
    project = await _new_project()
    for days, expected in [(1, 200), (500, 200), (0, 422), (501, 422), (-5, 422), ("abc", 422)]:
        resp = await auth_client.get(f"/api/projects/{project.id}/traffic?days={days}")
        assert resp.status_code == expected, days


async def test_traffic_unknown_project_is_404(auth_client):
    resp = await auth_client.get("/api/projects/00000000-0000-0000-0000-000000000000/traffic")
    assert resp.status_code == 404


async def test_demo_user_cannot_read_a_real_projects_traffic(client, seeded_project):
    headers = await _demo_headers(client)
    resp = await client.get(f"/api/projects/{seeded_project.id}/traffic", headers=headers)
    assert resp.status_code == 404


async def test_real_user_cannot_read_a_demo_projects_traffic(auth_client, client):
    await _demo_headers(client)  # seeds demo data
    async with async_session_maker() as session:
        demo_id = (await session.execute(select(Project.id).where(Project.is_demo.is_(True)).limit(1))).scalar_one()
    auth_headers = {"Authorization": auth_client.headers["Authorization"]}
    resp = await client.get(f"/api/projects/{demo_id}/traffic", headers=auth_headers)
    assert resp.status_code == 404


async def test_demo_user_sees_synthetic_series_and_frozen_collection_time(client):
    headers = await _demo_headers(client)
    projects = (await client.get("/api/projects", headers=headers)).json()
    pipeline = next(p for p in projects if p["is_pipeline"])

    body = (await client.get(f"/api/projects/{pipeline['id']}/traffic?days=500", headers=headers)).json()
    assert len(body["days"]) == 90
    assert body["days"][-1]["metric_date"] == "2026-09-01"
    assert body["last_collected_at"].startswith("2026-09-01")


async def test_demo_seed_is_deterministic_and_idempotent(client):
    async def series():
        headers = await _demo_headers(client)
        projects = (await client.get("/api/projects", headers=headers)).json()
        pipeline = next(p for p in projects if p["is_pipeline"])
        return (await client.get(f"/api/projects/{pipeline['id']}/traffic?days=500", headers=headers)).json()["days"]

    assert await series() == await series()


async def test_project_detail_includes_traffic_last_collected_at(auth_client):
    project = await _new_project()
    assert (await auth_client.get(f"/api/projects/{project.id}")).json()["traffic_last_collected_at"] is None

    await _add_days(project.id, 2)
    detail = (await auth_client.get(f"/api/projects/{project.id}")).json()
    assert detail["traffic_last_collected_at"] is not None


async def test_last_collected_ignores_a_failed_pull_snapshot(auth_client):
    project = await _new_project()
    await _add_days(project.id, 2)
    before = (await auth_client.get(f"/api/projects/{project.id}")).json()["traffic_last_collected_at"]

    async with async_session_maker() as session:
        session.add(TrafficSnapshot(project_id=project.id, configured=True, alert_severity="yellow"))
        await session.commit()

    after = (await auth_client.get(f"/api/projects/{project.id}")).json()["traffic_last_collected_at"]
    assert after == before


async def test_traffic_overview_lists_pipeline_projects_only_for_this_scope(auth_client):
    configured = await _new_project(gsc_site_url="sc-domain:o.example")
    async with async_session_maker() as session:
        session.add(
            TrafficSnapshot(
                project_id=configured.id, configured=True, clicks={"recent": 5, "prior": 10, "pct_change": -50.0},
                alert_severity="yellow", alert_messages=[{"severity": "yellow", "message": "m"}],
            )
        )
        await session.commit()
    unconfigured = await _new_project()

    items = {i["project_id"]: i for i in (await auth_client.get("/api/traffic/overview")).json()}

    assert items[str(configured.id)]["configured"] is True
    assert items[str(configured.id)]["clicks"]["pct_change"] == -50.0
    assert items[str(configured.id)]["alert_severity"] == "yellow"
    assert items[str(unconfigured.id)]["configured"] is False
    assert items[str(unconfigured.id)]["clicks"] is None
    assert all(not i["slug"].startswith("demo-") for i in items.values())


async def test_traffic_overview_for_demo_user_is_demo_only(client):
    headers = await _demo_headers(client)
    items = (await client.get("/api/traffic/overview", headers=headers)).json()
    assert len(items) == 8
    assert all(i["slug"].startswith("demo-") and i["configured"] for i in items)


async def test_traffic_overview_clicks_series_is_28_days_with_gaps_as_null(auth_client):
    project = await _new_project(gsc_site_url="sc-domain:series.example")
    last = date(2026, 9, 30)
    async with async_session_maker() as session:
        for offset, clicks in ((0, 7), (1, 5), (3, 2)):  # newest day, the day before, and one after a gap
            session.add(TrafficDaily(project_id=project.id, metric_date=last - timedelta(days=offset), clicks=clicks))
        await session.commit()

    items = {i["project_id"]: i for i in (await auth_client.get("/api/traffic/overview")).json()}
    series = items[str(project.id)]["clicks_series"]

    assert len(series) == 28
    assert series[-1] == 7 and series[-2] == 5 and series[-3] is None and series[-4] == 2
    assert series[0] is None


async def test_traffic_overview_clicks_series_is_empty_without_data(auth_client):
    project = await _new_project()
    items = {i["project_id"]: i for i in (await auth_client.get("/api/traffic/overview")).json()}
    assert items[str(project.id)]["clicks_series"] == []
