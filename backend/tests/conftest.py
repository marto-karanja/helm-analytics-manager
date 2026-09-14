import asyncio
import os
import re
import uuid

import asyncpg

# Tests must never touch the dev database -- point HELM_DATABASE_URL at a
# separate "_test" database *before* app.db.session (and its module-level
# engine) is imported anywhere below. A prior version of this fixture ran
# drop_all/create_all against the shared dev DB and its teardown wiped it.
_dev_url = os.environ.get("HELM_DATABASE_URL", "postgresql+asyncpg://helm:helm@localhost:5433/helm")
_test_db_name = re.search(r"/([^/]+)$", _dev_url).group(1) + "_test"
os.environ["HELM_DATABASE_URL"] = re.sub(r"/[^/]+$", f"/{_test_db_name}", _dev_url)


async def _ensure_test_database_exists() -> None:
    maintenance_url = re.sub(r"^postgresql\+asyncpg://", "postgresql://", _dev_url)
    conn = await asyncpg.connect(maintenance_url)
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", _test_db_name)
        if not exists:
            await conn.execute(f'CREATE DATABASE "{_test_db_name}"')
    finally:
        await conn.close()


asyncio.run(_ensure_test_database_exists())

import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import async_session_maker, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.project import Project  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_database():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def auth_client(client):
    email = f"{uuid.uuid4()}@example.com"
    await client.post("/api/auth/register", json={"email": email, "password": "supersecret123"})
    login_resp = await client.post(
        "/api/auth/login", data={"username": email, "password": "supersecret123"}
    )
    token = login_resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client


@pytest_asyncio.fixture
async def seeded_project():
    async with async_session_maker() as session:
        project = Project(
            slug=f"nairobistalls-{uuid.uuid4()}",
            name="NairobiStalls",
            category="seo-content-site",
            url="https://nairobistalls.com",
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        return project
