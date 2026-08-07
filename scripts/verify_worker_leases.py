from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.core.database import SessionLocal, engine, set_platform_database_scope
from app.models import WorkerLease
from app.services.worker_leases import DatabaseWorkerLease


VERIFY_WORKER = "verification_scheduler"


def _clear_verification_row() -> None:
    with SessionLocal() as db:
        set_platform_database_scope(db)
        db.execute(delete(WorkerLease).where(WorkerLease.name == VERIFY_WORKER))
        db.commit()


def main() -> int:
    if engine.dialect.name != "postgresql":
        print("Worker lease verification skipped for non-PostgreSQL database.")
        return 0

    base = datetime.now(timezone.utc).replace(tzinfo=None)
    _clear_verification_row()

    def compete(owner_id: str) -> DatabaseWorkerLease | None:
        lease = DatabaseWorkerLease(
            SessionLocal,
            name=VERIFY_WORKER,
            owner_id=owner_id,
            lease_seconds=30,
        )
        return lease if lease.acquire(now=base) else None

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(
                executor.map(compete, [f"verification-api-{index}" for index in range(8)])
            )
        winners = [lease for lease in results if lease is not None]
        assert len(winners) == 1, "PostgreSQL elected more than one live worker"
        winner = winners[0]
        assert winner.generation == 1
        assert winner.acquire(now=base + timedelta(seconds=1))
        assert winner.generation == 1
        assert winner.claim_run(now=base + timedelta(seconds=2))
        assert winner.finish_run(
            interval_seconds=30,
            success=True,
            result_count=8,
            now=base + timedelta(seconds=3),
        )
        assert winner.release(now=base + timedelta(seconds=4))

        successor = DatabaseWorkerLease(
            SessionLocal,
            name=VERIFY_WORKER,
            owner_id="verification-successor",
            lease_seconds=30,
        )
        assert successor.acquire(now=base + timedelta(seconds=5))
        assert successor.generation == 2
        assert not successor.claim_run(now=base + timedelta(seconds=32))
        assert successor.acquire(now=base + timedelta(seconds=32))
        assert successor.claim_run(now=base + timedelta(seconds=34))

        replacement = DatabaseWorkerLease(
            SessionLocal,
            name=VERIFY_WORKER,
            owner_id="verification-replacement",
            lease_seconds=30,
        )
        assert replacement.acquire(now=base + timedelta(seconds=65))
        assert replacement.generation == 3
        assert replacement.claim_run(now=base + timedelta(seconds=65))
        assert not successor.finish_run(
            interval_seconds=30,
            success=True,
            result_count=999,
            now=base + timedelta(seconds=66),
        )
        assert replacement.finish_run(
            interval_seconds=30,
            success=True,
            result_count=1,
            now=base + timedelta(seconds=66),
        )
        print(
            "PostgreSQL worker lease election, schedule, fencing, and takeover verification passed."
        )
        return 0
    finally:
        _clear_verification_row()


if __name__ == "__main__":
    raise SystemExit(main())
