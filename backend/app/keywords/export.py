"""Accepted keywords -> `keyword_queue.json` for the publish pipelines. One-way: Helm writes, pipelines read."""
import json
import os
import re
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.indexing import KeywordCandidate
from app.models.project import Project

QUEUE_FILENAME = "keyword_queue.json"
SAFE_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


def queue_payload(project: Project, rows: list[KeywordCandidate], now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    return {
        "project": project.slug,
        "generated_at": now.isoformat(),
        "keywords": [
            {
                "candidate_id": str(r.id),
                "keyword": r.keyword,
                "cluster": r.cluster_label or r.cluster_id,
                "intent": r.intent,
                "target_url": r.target_url,  # null means a new article; set means improve that page
                "action": "improve" if r.target_url else "new_article",
                "volume": r.volume,
                "demand_source": r.demand_source,
                "score": r.score,
            }
            for r in rows
        ],
    }


async def queue_rows(db: AsyncSession, project_id: uuid.UUID) -> list[KeywordCandidate]:
    result = await db.execute(
        select(KeywordCandidate)
        .where(KeywordCandidate.project_id == project_id, KeywordCandidate.status.in_(["accepted", "written"]))
        .order_by(KeywordCandidate.score.desc(), KeywordCandidate.keyword)
    )
    return list(result.scalars().all())


def write_queue_file(project: Project, payload: dict, export_dir: str | None = None) -> Path | None:
    """Atomic write to `<export_dir>/<slug>/keyword_queue.json`; None when file export is not configured."""
    export_dir = export_dir if export_dir is not None else settings.keyword_export_dir
    if not export_dir:
        return None
    if not SAFE_SLUG.match(project.slug):
        raise ValueError(f"unsafe project slug {project.slug!r}")
    target_dir = Path(export_dir) / project.slug
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / QUEUE_FILENAME
    handle, tmp_name = tempfile.mkstemp(dir=target_dir, suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        os.replace(tmp_name, target)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return target


async def export_queue(db: AsyncSession, project: Project, export_dir: str | None = None) -> dict:
    """Marks accepted candidates `written`, writes the file when configured, and returns the payload."""
    rows = await queue_rows(db, project.id)
    payload = queue_payload(project, rows)
    path = write_queue_file(project, payload, export_dir)
    for row in rows:
        if row.status == "accepted":
            row.status = "written"
    await db.commit()
    return {"payload": payload, "path": str(path) if path else None, "count": len(rows)}
