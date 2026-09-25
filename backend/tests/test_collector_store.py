import asyncio
from datetime import date

from sqlalchemy import select

from app.collector.store import upsert_traffic_daily
from app.db.session import async_session_maker
from app.models.project import TrafficDaily

DAY = date(2026, 9, 1)


async def _rows(project_id) -> list[TrafficDaily]:
    async with async_session_maker() as session:
        result = await session.execute(select(TrafficDaily).where(TrafficDaily.project_id == project_id))
        return list(result.scalars().all())


async def test_upserting_the_same_day_twice_leaves_one_row(seeded_project):
    gsc = [{"metric_date": DAY, "clicks": 5, "impressions": 50, "ctr": 0.1, "avg_position": 7.0}]
    async with async_session_maker() as session:
        assert await upsert_traffic_daily(session, seeded_project.id, gsc) == 1
        assert await upsert_traffic_daily(session, seeded_project.id, gsc) == 1
    assert len(await _rows(seeded_project.id)) == 1


async def test_gsc_upsert_keeps_existing_ga4_columns_and_vice_versa(seeded_project):
    ga4 = [{"metric_date": DAY, "sessions": 40, "engaged_sessions": 30}]
    gsc = [{"metric_date": DAY, "clicks": 5, "impressions": 50, "ctr": 0.1, "avg_position": 7.0}]
    async with async_session_maker() as session:
        await upsert_traffic_daily(session, seeded_project.id, ga4)
        await upsert_traffic_daily(session, seeded_project.id, gsc)
    (row,) = await _rows(seeded_project.id)
    assert (row.sessions, row.engaged_sessions, row.clicks, row.impressions) == (40, 30, 5, 50)

    async with async_session_maker() as session:
        await upsert_traffic_daily(
            session, seeded_project.id, [{"metric_date": DAY, "sessions": 41, "engaged_sessions": 31}]
        )
    (row,) = await _rows(seeded_project.id)
    assert (row.sessions, row.clicks, row.avg_position) == (41, 5, 7.0)


async def test_revised_value_overwrites_and_bumps_updated_at(seeded_project):
    first = [{"metric_date": DAY, "clicks": 5, "impressions": 50, "ctr": 0.1, "avg_position": 7.0}]
    async with async_session_maker() as session:
        await upsert_traffic_daily(session, seeded_project.id, first)
    (before,) = await _rows(seeded_project.id)

    await asyncio.sleep(0.05)
    async with async_session_maker() as session:
        await upsert_traffic_daily(session, seeded_project.id, [{**first[0], "clicks": 9}])
    (after,) = await _rows(seeded_project.id)
    assert after.clicks == 9
    assert after.updated_at > before.updated_at


async def test_empty_rows_is_a_noop(seeded_project):
    async with async_session_maker() as session:
        assert await upsert_traffic_daily(session, seeded_project.id, []) == 0
    assert await _rows(seeded_project.id) == []
