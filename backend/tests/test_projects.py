from app.db.session import async_session_maker
from app.models.project import PipelineSnapshot


async def test_list_and_get_project(auth_client, seeded_project):
    list_resp = await auth_client.get("/api/projects")
    assert list_resp.status_code == 200
    assert any(p["id"] == str(seeded_project.id) for p in list_resp.json())

    get_resp = await auth_client.get(f"/api/projects/{seeded_project.id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["name"] == "NairobiStalls"


async def test_get_project_includes_latest_alert_severity(auth_client, seeded_project):
    async with async_session_maker() as session:
        session.add(PipelineSnapshot(project_id=seeded_project.id, alert_severity="red"))
        await session.commit()

    get_resp = await auth_client.get(f"/api/projects/{seeded_project.id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["latest_alert_severity"] == "red"


async def test_get_project_not_found(auth_client):
    resp = await auth_client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert resp.status_code == 404


async def test_update_project(auth_client, seeded_project):
    resp = await auth_client.patch(
        f"/api/projects/{seeded_project.id}", json={"goals": "Ship the sync script"}
    )
    assert resp.status_code == 200
    assert resp.json()["goals"] == "Ship the sync script"


async def test_create_and_update_task(auth_client, seeded_project):
    create_resp = await auth_client.post(
        f"/api/projects/{seeded_project.id}/tasks", json={"title": "Write portfolio_parser.py"}
    )
    assert create_resp.status_code == 201
    task_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "todo"

    update_resp = await auth_client.patch(f"/api/tasks/{task_id}", json={"status": "in_progress"})
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "in_progress"


async def test_create_task_for_missing_project(auth_client):
    resp = await auth_client.post(
        "/api/projects/00000000-0000-0000-0000-000000000000/tasks", json={"title": "x"}
    )
    assert resp.status_code == 404


async def test_update_missing_task(auth_client):
    resp = await auth_client.patch(
        "/api/tasks/00000000-0000-0000-0000-000000000000", json={"status": "done"}
    )
    assert resp.status_code == 404
