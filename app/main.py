import asyncio
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.pages import pages_router
from app.api.integrations import router as integrations_router
from app.api.work_order_forms import router as work_order_forms_router
from app.api.routes import router
from app.api.billing import router as billing_router
from app.api.data_exports import router as data_exports_router
from app.api.data_restores import router as data_restores_router
from app.api.audit_logs import router as audit_logs_router
from app.api.operations import router as operations_router
from app.api.permissions import router as permissions_router
from app.api.regions import router as regions_router
from app.api.analytics import router as analytics_router
from app.core.config import settings
from app.core.database import SessionLocal, ensure_schema_ready, get_db
from app.core.logging import setup_logging
from app.core.middleware import ErrorHandlingMiddleware
from app.core.operations import operations_monitor
from app.models import *  # noqa: F401,F403
from app.schemas import RootInfo
from app.services.integration_delivery import process_due_deliveries
from app.services.billing import reconcile_billing_lifecycle

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    delivery_task = None
    billing_task = None
    testing = get_db in app_instance.dependency_overrides
    operations_monitor.reset(
        delivery_enabled=settings.integration_delivery_enabled and not testing,
        delivery_interval_seconds=settings.integration_delivery_poll_seconds,
        billing_enabled=settings.billing_reconciliation_enabled and not testing,
        billing_interval_seconds=settings.billing_reconciliation_poll_seconds,
    )
    if not testing:
        ensure_schema_ready()
        from app.services.legacy_database_adoption import current_schema_head

        app_instance.state.schema_revision = current_schema_head()
    else:
        app_instance.state.schema_revision = "test"
    app_instance.state.schema_ready = True
    # Tests replace the database dependency with an isolated session. Skipping
    # the production worker prevents it from touching the developer database.
    if (
        settings.integration_delivery_enabled
        and not testing
    ):
        async def delivery_loop() -> None:
            while True:
                await asyncio.sleep(max(5, settings.integration_delivery_poll_seconds))
                operations_monitor.worker_started("integration_delivery")
                try:
                    processed = await asyncio.to_thread(process_due_deliveries, SessionLocal)
                    operations_monitor.worker_succeeded(
                        "integration_delivery",
                        result_count=processed,
                    )
                except Exception as exc:
                    operations_monitor.worker_failed("integration_delivery", exc)
                    logger.exception("Integration delivery worker failed")

        delivery_task = asyncio.create_task(delivery_loop())
    if (
        settings.billing_reconciliation_enabled
        and not testing
    ):
        async def billing_loop() -> None:
            while True:
                operations_monitor.worker_started("billing_reconciliation")
                try:
                    stats = await asyncio.to_thread(reconcile_billing_lifecycle, SessionLocal)
                    operations_monitor.worker_succeeded(
                        "billing_reconciliation",
                        result_count=stats.organizations_checked,
                    )
                except Exception as exc:
                    operations_monitor.worker_failed("billing_reconciliation", exc)
                    logger.exception("Billing lifecycle reconciliation failed")
                await asyncio.sleep(max(60, settings.billing_reconciliation_poll_seconds))

        billing_task = asyncio.create_task(billing_loop())
    try:
        yield
    finally:
        if delivery_task:
            delivery_task.cancel()
            try:
                await delivery_task
            except asyncio.CancelledError:
                pass
        if billing_task:
            billing_task.cancel()
            try:
                await billing_task
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
    expose_headers=["Content-Disposition", "X-Content-SHA256", "X-Record-Count"],
)
app.include_router(router, prefix="/api")
app.include_router(billing_router, prefix="/api")
app.include_router(data_exports_router, prefix="/api")
app.include_router(data_restores_router, prefix="/api")
app.include_router(audit_logs_router, prefix="/api")
app.include_router(integrations_router, prefix="/api")
app.include_router(work_order_forms_router, prefix="/api")
app.include_router(permissions_router, prefix="/api")
app.include_router(regions_router, prefix="/api")
app.include_router(analytics_router, prefix="/api")
app.include_router(operations_router)
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
