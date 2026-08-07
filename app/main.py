import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import socket
from uuid import uuid4

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
from app.api.enterprise_agent import router as enterprise_agent_router
from app.api.inventory_ledger import router as inventory_ledger_router
from app.api.inventory_reconciliation import router as inventory_reconciliation_router
from app.api.van_inventory_planning import router as van_inventory_planning_router
from app.core.config import settings
from app.core.database import (
    SessionLocal,
    ensure_data_residency_ready,
    ensure_schema_ready,
    get_db,
)
from app.core.deployment import cors_allowed_origins, validate_deployment_settings
from app.core.logging import setup_logging
from app.core.middleware import ErrorHandlingMiddleware
from app.core.operations import operations_monitor
from app.models import *  # noqa: F401,F403
from app.schemas import RootInfo
from app.services.integration_delivery import process_due_deliveries
from app.services.billing import reconcile_billing_lifecycle
from app.services.worker_leases import (
    DatabaseWorkerLease,
    run_leased_worker_cycle,
)
from app.services.operations_history import (
    operations_instance_key,
    write_operations_health_sample,
)

setup_logging()
logger = logging.getLogger(__name__)


def _worker_owner_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex}"


async def _leased_worker_loop(
    *,
    name: str,
    owner_id: str,
    interval_seconds: int,
    initial_delay_seconds: int,
    task,
    failure_message: str,
) -> None:
    lease = DatabaseWorkerLease(
        SessionLocal,
        name=name,
        owner_id=owner_id,
        lease_seconds=settings.worker_lease_seconds,
    )
    cycle_in_flight = False
    try:
        while True:
            cycle_in_flight = True
            try:
                outcome = await asyncio.to_thread(
                    run_leased_worker_cycle,
                    lease,
                    interval_seconds=max(1, interval_seconds),
                    initial_delay_seconds=max(0, initial_delay_seconds),
                    task=task,
                    on_started=lambda: operations_monitor.worker_started(name),
                )
            except asyncio.CancelledError:
                # asyncio cannot stop a running thread. Leave the fenced lease
                # in place so another replica cannot overlap the final cycle;
                # it expires automatically if that thread cannot finish.
                raise
            except Exception as exc:
                cycle_in_flight = False
                operations_monitor.worker_failed(name, exc)
                logger.exception(failure_message)
            else:
                cycle_in_flight = False
                if outcome.state == "standby":
                    operations_monitor.worker_standby(name)
                elif outcome.state == "completed":
                    operations_monitor.worker_succeeded(
                        name,
                        result_count=outcome.result_count,
                    )
            await asyncio.sleep(
                max(
                    1,
                    min(
                        settings.worker_lease_heartbeat_seconds,
                        max(1, settings.worker_lease_seconds // 3),
                        max(1, interval_seconds),
                    ),
                )
            )
    finally:
        if not cycle_in_flight:
            await asyncio.to_thread(lease.release)


@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    delivery_task = None
    billing_task = None
    history_task = None
    testing = get_db in app_instance.dependency_overrides
    process_instance_id = _worker_owner_id()
    operations_monitor.reset(
        delivery_enabled=settings.integration_delivery_enabled and not testing,
        delivery_interval_seconds=settings.integration_delivery_poll_seconds,
        billing_enabled=settings.billing_reconciliation_enabled and not testing,
        billing_interval_seconds=settings.billing_reconciliation_poll_seconds,
        history_enabled=settings.operations_history_enabled and not testing,
        history_interval_seconds=settings.operations_history_interval_seconds,
    )
    if not testing:
        validate_deployment_settings()
        ensure_schema_ready()
        ensure_data_residency_ready()
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
        delivery_task = asyncio.create_task(
            _leased_worker_loop(
                name="integration_delivery",
                owner_id=process_instance_id,
                interval_seconds=max(5, settings.integration_delivery_poll_seconds),
                initial_delay_seconds=max(5, settings.integration_delivery_poll_seconds),
                task=lambda heartbeat: process_due_deliveries(
                    SessionLocal,
                    heartbeat=heartbeat,
                ),
                failure_message="Integration delivery worker failed",
            )
        )
    if (
        settings.billing_reconciliation_enabled
        and not testing
    ):
        billing_task = asyncio.create_task(
            _leased_worker_loop(
                name="billing_reconciliation",
                owner_id=process_instance_id,
                interval_seconds=max(60, settings.billing_reconciliation_poll_seconds),
                initial_delay_seconds=0,
                task=lambda heartbeat: reconcile_billing_lifecycle(
                    SessionLocal,
                    heartbeat=heartbeat,
                ).organizations_checked,
                failure_message="Billing lifecycle reconciliation failed",
            )
        )
    if settings.operations_history_enabled and not testing:
        instance_key = operations_instance_key(process_instance_id)

        async def operations_history_loop() -> None:
            while True:
                operations_monitor.worker_started("operations_history")
                try:
                    snapshot = operations_monitor.snapshot(
                        window_seconds=settings.operations_request_window_seconds
                    )
                    result = await asyncio.to_thread(
                        write_operations_health_sample,
                        SessionLocal,
                        instance_key=instance_key,
                        snapshot=snapshot,
                        schema_ready=bool(
                            getattr(app_instance.state, "schema_ready", False)
                        ),
                        schema_revision=str(
                            getattr(
                                app_instance.state,
                                "schema_revision",
                                "unknown",
                            )
                        ),
                        interval_seconds=settings.operations_history_interval_seconds,
                        retention_days=settings.operations_history_retention_days,
                    )
                    operations_monitor.worker_succeeded(
                        "operations_history",
                        result_count=1 if result.created else 0,
                    )
                except Exception as exc:
                    operations_monitor.worker_failed("operations_history", exc)
                    logger.exception("Operations history sampling failed")
                await asyncio.sleep(
                    max(30, settings.operations_history_interval_seconds)
                )

        history_task = asyncio.create_task(operations_history_loop())
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
        if history_task:
            history_task.cancel()
            try:
                await history_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="OpenPartsFlow", version="0.1.0", lifespan=lifespan)
app.add_middleware(ErrorHandlingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
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
app.include_router(enterprise_agent_router, prefix="/api")
app.include_router(inventory_ledger_router, prefix="/api")
app.include_router(inventory_reconciliation_router, prefix="/api")
app.include_router(van_inventory_planning_router, prefix="/api")
app.include_router(operations_router)
app.include_router(pages_router)
uploads_dir = Path(settings.data_export_public_files_root)
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
