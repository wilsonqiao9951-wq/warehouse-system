import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.pages import pages_router
from app.api.integrations import router as integrations_router
from app.api.routes import router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine, ensure_schema_compatibility, get_db
from app.core.logging import setup_logging
from app.core.middleware import ErrorHandlingMiddleware
from app.models import *  # noqa: F401,F403
from app.schemas import RootInfo
from app.services.integration_delivery import process_due_deliveries

setup_logging()
Base.metadata.create_all(bind=engine)
ensure_schema_compatibility()

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    delivery_task = None
    # Tests replace the database dependency with an isolated session. Skipping
    # the production worker prevents it from touching the developer database.
    if (
        settings.integration_delivery_enabled
        and get_db not in app_instance.dependency_overrides
    ):
        async def delivery_loop() -> None:
            while True:
                await asyncio.sleep(max(5, settings.integration_delivery_poll_seconds))
                await asyncio.to_thread(process_due_deliveries, SessionLocal)

        delivery_task = asyncio.create_task(delivery_loop())
    try:
        yield
    finally:
        if delivery_task:
            delivery_task.cancel()
            try:
                await delivery_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="OpenPartsFlow", version="0.1.0", lifespan=lifespan)
app.add_middleware(ErrorHandlingMiddleware)
_cors_extra = [o.strip() for o in (settings.cors_extra_origins or "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
        "http://localhost:3002",
        "http://127.0.0.1:3002",
        *_cors_extra,
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router, prefix="/api")
app.include_router(integrations_router, prefix="/api")
app.include_router(pages_router)
uploads_dir = Path("uploads")
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")


@app.get("/", response_model=RootInfo)
def root():
    return {
        "name": "OpenPartsFlow",
        "version": "0.1.0",
        "docs": "/docs",
        "api_prefix": "/api",
    }
