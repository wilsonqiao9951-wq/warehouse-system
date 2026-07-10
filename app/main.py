from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.pages import pages_router
from app.api.routes import router
from app.core.config import settings
from app.core.database import Base, engine, ensure_schema_compatibility
from app.core.logging import setup_logging
from app.core.middleware import ErrorHandlingMiddleware
from app.models import *  # noqa: F401,F403
from app.schemas import RootInfo

setup_logging()
Base.metadata.create_all(bind=engine)
ensure_schema_compatibility()

app = FastAPI(title="OpenPartsFlow", version="0.1.0")
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
