async def test_register_login_and_me(client):
    register_resp = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "supersecret123"},
    )
    assert register_resp.status_code == 201

    login_resp = await client.post(
        "/api/auth/login",
        data={"username": "test@example.com", "password": "supersecret123"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]

    me_resp = await client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me_resp.status_code == 200
    assert me_resp.json()["email"] == "test@example.com"


async def test_projects_requires_auth(client):
    resp = await client.get("/api/projects")
    assert resp.status_code == 401
