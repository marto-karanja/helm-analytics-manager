from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import auth, projects, sync
from app.core.config import settings
from app.core.demo_seed import seed_demo_data
from app.db.session import async_session_maker


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.demo_mode_seed:
        async with async_session_maker() as session:
            await seed_demo_data(session)
    yield


app = FastAPI(title="Helm Analytics Manager", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_hosts,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(projects.router, prefix="/api", tags=["projects"])
app.include_router(sync.router, prefix="/api", tags=["sync"])


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
