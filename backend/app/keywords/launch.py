"""Starting a keyword run in the background, shared by the REST API and the MCP server."""
import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_settings import get_setting
from app.db.session import async_session_maker
from app.keywords import generator
from app.keywords import llm as llm_mod
from app.models.indexing import KeywordRun
from app.models.project import Project

logger = logging.getLogger("helm.keywords")

# Background run tasks are held here so the event loop cannot garbage-collect them mid-run.
running: set[asyncio.Task] = set()


async def _run_in_background(run_id: uuid.UUID) -> None:
    try:
        await generator.execute_run(async_session_maker, run_id)
    except Exception:  # noqa: BLE001 -- execute_run records its own failures; this is the last line of defence
        logger.exception("keyword run %s crashed", run_id)


async def launch_run(session: AsyncSession, project: Project) -> KeywordRun:
    """Checks the daily LLM cap, creates the run row and starts the pipeline. May raise DailyCapReached or GeneratorError."""
    await llm_mod.check_cap(session, await get_setting(session, "llm_daily_cap_usd"))
    run = await generator.start_run(session, project.id)
    task = asyncio.create_task(_run_in_background(run.id))
    running.add(task)
    task.add_done_callback(running.discard)
    return run
