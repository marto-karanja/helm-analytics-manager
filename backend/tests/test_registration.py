import uuid

import pytest
from fastapi_users.exceptions import UserAlreadyExists

from app.cli import create_user
from app.core.config import Settings, settings


def test_registration_is_off_by_default():
    assert Settings.model_fields["allow_registration"].default is False


async def test_register_endpoint_blocked_when_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "allow_registration", False)
    resp = await client.post(
        "/api/auth/register", json={"email": f"{uuid.uuid4()}@example.com", "password": "supersecret123"}
    )
    assert resp.status_code == 403


async def test_login_still_works_when_registration_disabled(client, monkeypatch):
    email = f"{uuid.uuid4()}@example.com"
    await create_user(email, "a-long-enough-password")
    monkeypatch.setattr(settings, "allow_registration", False)

    resp = await client.post("/api/auth/login", data={"username": email, "password": "a-long-enough-password"})
    assert resp.status_code == 200


async def test_cli_create_user_makes_a_working_non_demo_account(client):
    email = f"{uuid.uuid4()}@example.com"
    user = await create_user(email, "a-long-enough-password")
    assert user.is_demo is False

    login = await client.post("/api/auth/login", data={"username": email, "password": "a-long-enough-password"})
    assert login.status_code == 200


async def test_cli_rejects_short_password_and_duplicates():
    with pytest.raises(ValueError):
        await create_user(f"{uuid.uuid4()}@example.com", "short")

    email = f"{uuid.uuid4()}@example.com"
    await create_user(email, "a-long-enough-password")
    with pytest.raises(UserAlreadyExists):
        await create_user(email, "a-long-enough-password")
