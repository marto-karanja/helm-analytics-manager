import uuid

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import TrafficDaily

KEY_COLUMNS = {"project_id", "metric_date"}


async def upsert_traffic_daily(db: AsyncSession, project_id: uuid.UUID, rows: list[dict]) -> int:
    if not rows:
        return 0
    statement = insert(TrafficDaily).values([{**row, "project_id": project_id} for row in rows])
    # Only the incoming row's columns are overwritten: a GSC pull must not null the GA4 columns and vice versa.
    # updated_at is set by hand because Column.onupdate is not applied to ON CONFLICT DO UPDATE.
    update_columns = {column: statement.excluded[column] for column in rows[0] if column not in KEY_COLUMNS}
    statement = statement.on_conflict_do_update(
        index_elements=["project_id", "metric_date"],
        set_={**update_columns, "updated_at": func.now()},
    )
    await db.execute(statement)
    await db.commit()
    return len(rows)
