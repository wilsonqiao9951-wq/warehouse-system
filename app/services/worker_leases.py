from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import and_, case, or_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.database import set_platform_database_scope
from app.models import WorkerLease


class WorkerLeaseLost(RuntimeError):
    """Raised when a task can no longer prove it owns the scheduler lease."""


@dataclass(frozen=True)
class WorkerCycleResult:
    state: Literal["standby", "waiting", "completed"]
    result_count: int | None = None


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class DatabaseWorkerLease:
    """A fenced, renewable scheduler lease shared by every API replica."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        name: str,
        owner_id: str,
        lease_seconds: int,
    ) -> None:
        normalized_name = name.strip()
        normalized_owner = owner_id.strip()
        if not normalized_name or len(normalized_name) > 80:
            raise ValueError("Worker lease name must contain 1 to 80 characters")
        if not normalized_owner or len(normalized_owner) > 200:
            raise ValueError("Worker lease owner must contain 1 to 200 characters")
        if lease_seconds < 10:
            raise ValueError("Worker lease duration must be at least 10 seconds")
        self.session_factory = session_factory
        self.name = normalized_name
        self.owner_id = normalized_owner
        self.lease_seconds = lease_seconds
        self.generation: int | None = None

    def _expiration(self, now: datetime) -> datetime:
        return now + timedelta(seconds=self.lease_seconds)

    @staticmethod
    def _insert_for(db: Session):
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            return postgresql_insert(WorkerLease.__table__)
        if dialect == "sqlite":
            return sqlite_insert(WorkerLease.__table__)
        raise RuntimeError(
            f"Worker leases do not support database dialect {dialect!r}"
        )

    def acquire(
        self,
        *,
        initial_delay_seconds: int = 0,
        now: datetime | None = None,
    ) -> bool:
        checked_at = now or utcnow_naive()
        expires_at = self._expiration(checked_at)
        initial_run_at = checked_at + timedelta(
            seconds=max(0, initial_delay_seconds)
        )
        table = WorkerLease.__table__
        active_same_owner = and_(
            table.c.owner_id == self.owner_id,
            table.c.lease_expires_at > checked_at,
        )
        with self.session_factory() as db:
            set_platform_database_scope(db)
            insert_statement = self._insert_for(db).values(
                name=self.name,
                owner_id=self.owner_id,
                generation=1,
                acquired_at=checked_at,
                heartbeat_at=checked_at,
                lease_expires_at=expires_at,
                next_run_at=initial_run_at,
                run_started_at=None,
                last_completed_at=None,
                last_success_at=None,
                last_error_at=None,
                last_error_type=None,
                last_result_count=None,
                created_at=checked_at,
                updated_at=checked_at,
            )
            statement = insert_statement.on_conflict_do_update(
                index_elements=[table.c.name],
                set_={
                    "owner_id": self.owner_id,
                    "generation": case(
                        (active_same_owner, table.c.generation),
                        else_=table.c.generation + 1,
                    ),
                    "acquired_at": case(
                        (active_same_owner, table.c.acquired_at),
                        else_=checked_at,
                    ),
                    "heartbeat_at": checked_at,
                    "lease_expires_at": expires_at,
                    "run_started_at": case(
                        (active_same_owner, table.c.run_started_at),
                        else_=None,
                    ),
                    "updated_at": checked_at,
                },
                where=or_(
                    table.c.owner_id == self.owner_id,
                    table.c.lease_expires_at <= checked_at,
                ),
            ).returning(table.c.generation)
            row = db.execute(statement).first()
            db.commit()
        if row is None:
            self.generation = None
            return False
        self.generation = int(row[0])
        return True

    def renew(self, *, now: datetime | None = None) -> bool:
        if self.generation is None:
            return False
        checked_at = now or utcnow_naive()
        table = WorkerLease.__table__
        with self.session_factory() as db:
            set_platform_database_scope(db)
            row = db.execute(
                update(table)
                .where(
                    table.c.name == self.name,
                    table.c.owner_id == self.owner_id,
                    table.c.generation == self.generation,
                    table.c.lease_expires_at > checked_at,
                )
                .values(
                    heartbeat_at=checked_at,
                    lease_expires_at=self._expiration(checked_at),
                    updated_at=checked_at,
                )
                .returning(table.c.generation)
            ).first()
            db.commit()
        if row is None:
            self.generation = None
            return False
        return True

    def require_renewed(self) -> None:
        if not self.renew():
            raise WorkerLeaseLost(
                f"Worker {self.name!r} lost its database lease"
            )

    def claim_run(self, *, now: datetime | None = None) -> bool:
        if self.generation is None:
            return False
        checked_at = now or utcnow_naive()
        table = WorkerLease.__table__
        with self.session_factory() as db:
            set_platform_database_scope(db)
            row = db.execute(
                update(table)
                .where(
                    table.c.name == self.name,
                    table.c.owner_id == self.owner_id,
                    table.c.generation == self.generation,
                    table.c.lease_expires_at > checked_at,
                    table.c.run_started_at.is_(None),
                    table.c.next_run_at <= checked_at,
                )
                .values(
                    heartbeat_at=checked_at,
                    lease_expires_at=self._expiration(checked_at),
                    run_started_at=checked_at,
                    updated_at=checked_at,
                )
                .returning(table.c.generation)
            ).first()
            db.commit()
        if row is None:
            return False
        return True

    def finish_run(
        self,
        *,
        interval_seconds: int,
        success: bool,
        result_count: int | None = None,
        error_type: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        if self.generation is None:
            return False
        finished_at = now or utcnow_naive()
        table = WorkerLease.__table__
        values: dict = {
            "heartbeat_at": finished_at,
            "lease_expires_at": self._expiration(finished_at),
            "next_run_at": finished_at
            + timedelta(seconds=max(1, interval_seconds)),
            "run_started_at": None,
            "last_completed_at": finished_at,
            "updated_at": finished_at,
        }
        if success:
            values.update(
                last_success_at=finished_at,
                last_error_type=None,
                last_result_count=max(0, result_count or 0),
            )
        else:
            values.update(
                last_error_at=finished_at,
                last_error_type=(error_type or "WorkerError")[:160],
            )
        with self.session_factory() as db:
            set_platform_database_scope(db)
            row = db.execute(
                update(table)
                .where(
                    table.c.name == self.name,
                    table.c.owner_id == self.owner_id,
                    table.c.generation == self.generation,
                    table.c.lease_expires_at > finished_at,
                    table.c.run_started_at.is_not(None),
                )
                .values(**values)
                .returning(table.c.generation)
            ).first()
            db.commit()
        if row is None:
            self.generation = None
            return False
        return True

    def release(self, *, now: datetime | None = None) -> bool:
        if self.generation is None:
            return False
        released_at = now or utcnow_naive()
        table = WorkerLease.__table__
        with self.session_factory() as db:
            set_platform_database_scope(db)
            row = db.execute(
                update(table)
                .where(
                    table.c.name == self.name,
                    table.c.owner_id == self.owner_id,
                    table.c.generation == self.generation,
                    table.c.run_started_at.is_(None),
                )
                .values(
                    heartbeat_at=released_at,
                    lease_expires_at=released_at,
                    updated_at=released_at,
                )
                .returning(table.c.generation)
            ).first()
            db.commit()
        self.generation = None
        return row is not None


def run_leased_worker_cycle(
    lease: DatabaseWorkerLease,
    *,
    interval_seconds: int,
    initial_delay_seconds: int,
    task: Callable[[Callable[[], None]], int],
    on_started: Callable[[], None] | None = None,
) -> WorkerCycleResult:
    if not lease.acquire(initial_delay_seconds=initial_delay_seconds):
        return WorkerCycleResult("standby")
    if not lease.claim_run():
        return WorkerCycleResult("waiting")
    if on_started:
        on_started()
    try:
        result_count = max(0, int(task(lease.require_renewed)))
    except Exception as exc:
        lease.finish_run(
            interval_seconds=interval_seconds,
            success=False,
            error_type=type(exc).__name__,
        )
        raise
    if not lease.finish_run(
        interval_seconds=interval_seconds,
        success=True,
        result_count=result_count,
    ):
        raise WorkerLeaseLost(
            f"Worker {lease.name!r} lost its database lease before completion"
        )
    return WorkerCycleResult("completed", result_count)
