"""Seeds a LOCAL scratch database for screenshots and UI checks. Never run it against production.

    cd backend
    HELM_DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:<port>/<db> HELM_SECRET_KEY=... HELM_SYNC_TOKEN=... \
        uv run python ../e2e/seed_local.py

Creates the frozen demo dataset (HELM_DEMO_MODE_SEED data), 30 days of backdated pipeline snapshots so the Content
page has a publishing rate, and an owner account `owner@example.com` / `local-test-password-1` whose projects are
a copy of the demo ones (is_demo false), so the owner views can be screenshotted with realistic data.
"""
import asyncio
import copy
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.cli import create_user
from app.core.demo_seed import seed_demo_data
from app.core.demo_seed_indexing import seed_project_indexing
from app.db.session import async_session_maker
from app.models.project import PipelineSnapshot, Project, Task, TrafficDaily, TrafficSnapshot
from app.models.user import User

OWNER_EMAIL = "owner@example.com"
OWNER_PASSWORD = "local-test-password-1"


async def main() -> None:
    async with async_session_maker() as session:
        await seed_demo_data(session)
        demo = (await session.execute(select(Project).where(Project.is_demo.is_(True)).order_by(Project.name))).scalars().all()
        now = datetime.now(timezone.utc)
        idx = 0
        for p in demo:
            snaps = (await session.execute(select(PipelineSnapshot).where(PipelineSnapshot.project_id == p.id))).scalars().all()
            if snaps and snaps[0].total_articles_written is not None:
                s = snaps[0]
                # Backdate the frozen snapshot is not needed; add 28 earlier daily snapshots, publishing about 1 a day.
                for d in range(1, 29):
                    session.add(
                        PipelineSnapshot(
                            project_id=p.id,
                            synced_at=now - timedelta(days=d),
                            total_articles_written=max(0, s.total_articles_written - d * (1 + idx % 3)),
                            backlog_count=s.backlog_count + d * (idx % 2),
                            blocked_count=s.blocked_count,
                            alert_severity=s.alert_severity,
                            last_published_at=now - timedelta(days=d),
                        )
                    )
                s.synced_at = now
                idx += 1
        await session.commit()

        # An owner copy of every demo project, with its own data.
        copies: list[tuple[Project, Project]] = []
        for p in demo:
            q = Project(
                slug=p.slug.removeprefix("demo-") + "-owner" if p.slug.startswith("demo-") else p.slug + "-owner",
                name=p.name,
                category=p.category,
                url=p.url,
                is_pipeline=p.is_pipeline,
                is_demo=False,
                goals=p.goals,
                current_status=p.current_status,
                gsc_site_url=p.gsc_site_url,
            )
            session.add(q)
            await session.flush()
            copies.append((p, q))
        for src, dst in copies:
            for t in (await session.execute(select(Task).where(Task.project_id == src.id))).scalars():
                session.add(Task(project_id=dst.id, title=t.title, status=t.status, priority=t.priority))
            for model in (PipelineSnapshot, TrafficDaily, TrafficSnapshot):
                for row in (await session.execute(select(model).where(model.project_id == src.id))).scalars():
                    data = {c.name: getattr(row, c.name) for c in row.__table__.columns if c.name not in ("id", "project_id")}
                    session.add(model(project_id=dst.id, **copy.deepcopy(data)))
        await session.commit()
        for i, (src, dst) in enumerate([c for c in copies if c[1].is_pipeline]):
            await seed_project_indexing(session, dst, i, now.date())
        await session.commit()

        exists = (await session.execute(select(User).where(User.email == OWNER_EMAIL))).scalar_one_or_none()
    if exists is None:
        await create_user(OWNER_EMAIL, OWNER_PASSWORD)
    print(f"seeded {len(demo)} demo projects, {len(copies)} owner copies; owner {OWNER_EMAIL}")


asyncio.run(main())
