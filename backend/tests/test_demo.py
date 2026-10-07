from app.core.demo_seed import seed_demo_data
from app.db.session import async_session_maker


async def test_demo_login_creates_account_once(client):
    resp1 = await client.post("/api/auth/demo-login")
    assert resp1.status_code == 200
    token1 = resp1.json()["access_token"]

    resp2 = await client.post("/api/auth/demo-login")
    assert resp2.status_code == 200

    me1 = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token1}"})
    assert me1.json()["is_demo"] is True
    assert me1.json()["email"] == "demo@helm.billtoolbox.com"


async def test_demo_account_is_read_only_and_scoped(client, seeded_project):
    async with async_session_maker() as session:
        await seed_demo_data(session)

    demo_resp = await client.post("/api/auth/demo-login")
    token = demo_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # sees only demo projects, not the real seeded_project fixture's data
    list_resp = await client.get("/api/projects", headers=headers)
    assert list_resp.status_code == 200
    slugs = [p["slug"] for p in list_resp.json()]
    assert all(s.startswith("demo-") for s in slugs)
    assert seeded_project.slug not in slugs

    demo_project_id = list_resp.json()[0]["id"]
    update_resp = await client.patch(
        f"/api/projects/{demo_project_id}", json={"goals": "hack"}, headers=headers
    )
    assert update_resp.status_code == 403

    task_resp = await client.post(
        f"/api/projects/{demo_project_id}/tasks", json={"title": "x"}, headers=headers
    )
    assert task_resp.status_code == 403


async def test_demo_seed_includes_indexing_keywords_and_reports_and_is_idempotent(client):
    async with async_session_maker() as session:
        await seed_demo_data(session)
        await seed_demo_data(session)  # a redeploy re-seeds: must replace, not duplicate

    token = (await client.post("/api/auth/demo-login")).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    projects = (await client.get("/api/projects", headers=headers)).json()
    pipeline = next(p for p in projects if p["slug"] == "demo-nairobistalls")

    summary = (await client.get(f"/api/projects/{pipeline['id']}/indexing", headers=headers)).json()
    assert summary["total"] == 24
    assert summary["counts"]["indexed"] == 16 and summary["counts"]["thin"] == 2 and summary["counts"]["blocked"] == 1
    assert summary["counts"]["crawled_not_indexed"] == 3 and summary["counts"]["discovered_not_indexed"] == 2
    assert len(summary["history"]) == 12

    keywords = (await client.get(f"/api/projects/{pipeline['id']}/keywords", headers=headers)).json()
    assert keywords["counts"] == {"proposed": 4, "accepted": 2, "rejected": 2, "written": 0}
    assert (await client.get(f"/api/projects/{pipeline['id']}/keywords/striking-distance", headers=headers)).json()

    sitemaps = (await client.get(f"/api/projects/{pipeline['id']}/sitemaps", headers=headers)).json()
    assert sitemaps["sitemaps"][0]["submitted_urls"] == 24

    report = (await client.get("/api/reports/indexing", headers=headers)).json()
    assert len(report["rows"]) == 8 and all(row[1] == 24 for row in report["rows"])
    assert (await client.get("/api/reports/digest", headers=headers)).json()["rows"]
    assert (await client.get("/api/reports/non-indexed?format=csv", headers=headers)).text.count("\r\n") > 8
