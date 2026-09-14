"""Seeds the read-only demo account's project data.

Reuses the real project names/URLs (these are public live websites, so
there's nothing sensitive about e.g. "NairobiStalls" being visible) but
freezes operational numbers to a fixed labeled snapshot rather than ever
live-syncing real current figures into the account a stranger logs into.
Idempotent -- safe to re-run (e.g. HELM_DEMO_MODE_SEED=true on a redeploy)
to refresh stale demo data; it deletes and recreates all is_demo rows.
"""

from datetime import date, datetime, timezone

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import PipelineSnapshot, Project, Task, TrafficSnapshot

DEMO_SNAPSHOT_LABEL_DATE = "2026-09-01"

_DEMO_PORTFOLIO = [
    {
        "slug": "demo-nairobistalls",
        "name": "NairobiStalls",
        "category": "seo-content-site",
        "url": "https://nairobistalls.com",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 4, "blocked_count": 0, "total_articles_written": 118, "severity": "green"},
    },
    {
        "slug": "demo-allmediatools",
        "name": "AllMediaTools",
        "category": "seo-content-site",
        "url": "https://allmediatools.com/blog",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 1, "blocked_count": 0, "total_articles_written": 94, "severity": "yellow"},
    },
    {
        "slug": "demo-billtoolbox",
        "name": "Billtoolbox",
        "category": "seo-content-site",
        "url": "https://billtoolbox.com",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 10, "blocked_count": 0, "total_articles_written": 140, "severity": "green"},
    },
    {
        "slug": "demo-bonbargains",
        "name": "Bonbargains",
        "category": "seo-content-site",
        "url": "https://bonbargains.com",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 29, "blocked_count": 0, "total_articles_written": 205, "severity": "green"},
    },
    {
        "slug": "demo-futboltrivia",
        "name": "FutbolTrivia",
        "category": "seo-content-site",
        "url": "https://futboltrivia.site",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 7, "blocked_count": 0, "total_articles_written": 88, "severity": "green"},
    },
    {
        "slug": "demo-pceamilimani",
        "name": "PCEAMilimani",
        "category": "seo-content-site",
        "url": "https://pceamilimanisouthpresbytery.org",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 16, "blocked_count": 0, "total_articles_written": 160, "severity": "green"},
    },
    {
        "slug": "demo-thesmokeryhub",
        "name": "TheSmokeryHub",
        "category": "seo-content-site",
        "url": "https://thesmokeryhub.com",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 11, "blocked_count": 0, "total_articles_written": 132, "severity": "green"},
    },
    {
        "slug": "demo-computeracademichelp",
        "name": "ComputerAcademicHelp",
        "category": "seo-content-site",
        "url": "https://computeracademichelp.com",
        "is_pipeline": True,
        "current_status": f"Demo data as of {DEMO_SNAPSHOT_LABEL_DATE}. Live SEO content pipeline.",
        "pipeline": {"backlog_count": 14, "blocked_count": 1, "total_articles_written": 121, "severity": "yellow"},
    },
    {
        "slug": "demo-hireessaywriters",
        "name": "HireEssayWriters",
        "category": "service business",
        "url": "https://hireessaywriters.com",
        "is_pipeline": False,
        "current_status": "Being revived from dormancy.",
    },
    {
        "slug": "demo-pimamajisystem",
        "name": "PimaMajiSystem",
        "category": "saas / iot",
        "url": "https://pimamajisystem.com",
        "is_pipeline": False,
        "current_status": "M-PESA/IoT water-billing platform.",
    },
    {
        "slug": "demo-essayparlour",
        "name": "EssayParlour",
        "category": "service business",
        "url": "https://essayparlour.com",
        "is_pipeline": False,
        "current_status": "Being revived from dormancy.",
    },
    {
        "slug": "demo-personal-portfolio",
        "name": "Personal portfolio site",
        "category": "personal",
        "url": "unconfirmed",
        "is_pipeline": False,
        "current_status": "Not yet fully live. Multi-channel presence planned.",
    },
    {
        "slug": "demo-mpesa-woocommerce-plugin",
        "name": "M-Pesa Till Gateway for WooCommerce",
        "category": "wordpress plugin (product)",
        "url": "not yet published — targeting WordPress.org",
        "is_pipeline": False,
        "goals": "Ship a WooCommerce payment gateway plugin to the public WordPress.org plugin directory.",
        "current_status": "Pre-submission, checklist mostly complete.",
    },
]

_DEMO_TASKS = {
    "demo-nairobistalls": [("Write next content batch", "todo", "normal")],
    "demo-allmediatools": [("Backlog nearly exhausted — write more articles", "todo", "high")],
    "demo-mpesa-woocommerce-plugin": [
        ("Run WordPress Plugin Check", "todo", "high"),
        ("Sandbox payment test", "in_progress", "normal"),
    ],
}


async def seed_demo_data(session: AsyncSession) -> None:
    await session.execute(delete(Task).where(Task.project_id.in_(select_demo_project_ids())))
    await session.execute(delete(PipelineSnapshot).where(PipelineSnapshot.project_id.in_(select_demo_project_ids())))
    await session.execute(delete(TrafficSnapshot).where(TrafficSnapshot.project_id.in_(select_demo_project_ids())))
    await session.execute(delete(Project).where(Project.is_demo.is_(True)))
    await session.flush()

    frozen_synced_at = datetime.combine(
        date.fromisoformat(DEMO_SNAPSHOT_LABEL_DATE), datetime.min.time(), tzinfo=timezone.utc
    )

    for entry in _DEMO_PORTFOLIO:
        project = Project(
            slug=entry["slug"],
            name=entry["name"],
            category=entry["category"],
            url=entry["url"],
            is_pipeline=entry["is_pipeline"],
            is_demo=True,
            goals=entry.get("goals"),
            current_status=entry.get("current_status"),
        )
        session.add(project)
        await session.flush()

        if "pipeline" in entry:
            p = entry["pipeline"]
            session.add(
                PipelineSnapshot(
                    project_id=project.id,
                    synced_at=frozen_synced_at,
                    total_articles_written=p["total_articles_written"],
                    backlog_count=p["backlog_count"],
                    blocked_count=p["blocked_count"],
                    oldest_backlog_age_days=2,
                    last_published_at=frozen_synced_at,
                    last_7_runs=[],
                    alert_severity=p["severity"],
                    alert_messages=[],
                )
            )
            session.add(TrafficSnapshot(project_id=project.id, synced_at=frozen_synced_at, configured=False))

        for title, status, priority in _DEMO_TASKS.get(entry["slug"], []):
            session.add(Task(project_id=project.id, title=title, status=status, priority=priority))

    await session.commit()


def select_demo_project_ids():
    from sqlalchemy import select

    return select(Project.id).where(Project.is_demo.is_(True))
