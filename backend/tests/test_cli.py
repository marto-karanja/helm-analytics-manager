import asyncio
import sys
import uuid

import pytest
from sqlalchemy import select

from app import cli
from app.db.session import async_session_maker
from app.models.project import Project


async def _project(**extra) -> Project:
    async with async_session_maker() as session:
        project = Project(
            slug=f"cli-{uuid.uuid4()}", name="Cli", category="seo-content-site", url="https://c.example", **extra
        )
        session.add(project)
        await session.commit()
        return project


async def _reload(slug: str) -> Project:
    async with async_session_maker() as session:
        return (await session.execute(select(Project).where(Project.slug == slug))).scalar_one()


async def test_set_analytics_sets_both():
    project = await _project()
    await cli.set_analytics(project.slug, "sc-domain:example.com", "properties/123")
    saved = await _reload(project.slug)
    assert (saved.gsc_site_url, saved.ga4_property_id) == ("sc-domain:example.com", "properties/123")


async def test_set_analytics_one_flag_leaves_the_other_alone():
    project = await _project(gsc_site_url="https://old.example/", ga4_property_id="properties/1")
    await cli.set_analytics(project.slug, None, "properties/2")
    saved = await _reload(project.slug)
    assert (saved.gsc_site_url, saved.ga4_property_id) == ("https://old.example/", "properties/2")


async def test_set_analytics_accepts_url_prefix():
    project = await _project()
    await cli.set_analytics(project.slug, "https://example.com/", None)
    assert (await _reload(project.slug)).gsc_site_url == "https://example.com/"


@pytest.mark.parametrize(
    "gsc, ga4, message",
    [
        (None, None, "at least one"),
        ("example.com", None, "--gsc must be"),
        (None, "123456", "--ga4 must look like"),
        (None, "property/123", "--ga4 must look like"),
    ],
)
async def test_set_analytics_rejects_bad_input(gsc, ga4, message):
    project = await _project()
    with pytest.raises(ValueError, match=message):
        await cli.set_analytics(project.slug, gsc, ga4)
    saved = await _reload(project.slug)
    assert (saved.gsc_site_url, saved.ga4_property_id) == (None, None)


async def test_set_analytics_unknown_slug():
    with pytest.raises(ValueError, match="No project with slug 'nope-does-not-exist'"):
        await cli.set_analytics("nope-does-not-exist", "sc-domain:example.com", None)


async def test_set_analytics_ignores_demo_projects():
    project = await _project(is_demo=True)
    with pytest.raises(ValueError, match="No project with slug"):
        await cli.set_analytics(project.slug, "sc-domain:example.com", None)


async def test_main_reports_argument_errors_without_touching_the_database(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["app.cli", "set-analytics", "whatever"])
    assert await asyncio.to_thread(cli.main) == 1
    assert "at least one" in capsys.readouterr().err


def test_main_requires_a_subcommand(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["app.cli"])
    with pytest.raises(SystemExit):
        cli.main()
