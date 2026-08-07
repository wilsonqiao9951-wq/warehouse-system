from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, configure_sqlite_connection
from app.models import WorkerLease
from app.services import worker_leases
from app.services.worker_leases import (
    DatabaseWorkerLease,
    run_leased_worker_cycle,
)


def _session_factory(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'leases.db'}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    event.listen(engine, "connect", configure_sqlite_connection)
    Base.metadata.create_all(engine)
    return engine, sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        info={"rls_platform_access": True},
    )


def test_worker_lease_is_exclusive_and_preserves_the_shared_schedule(tmp_path):
    engine, sessions = _session_factory(tmp_path)
    base = datetime(2026, 8, 7, 12, 0, 0)
    first = DatabaseWorkerLease(
        sessions,
        name="billing_reconciliation",
        owner_id="api-one",
        lease_seconds=90,
    )
    second = DatabaseWorkerLease(
        sessions,
        name="billing_reconciliation",
        owner_id="api-two",
        lease_seconds=90,
    )
    try:
        assert first.acquire(now=base)
        assert not second.acquire(now=base + timedelta(seconds=1))
        assert first.claim_run(now=base + timedelta(seconds=2))
        assert first.finish_run(
            interval_seconds=60,
            success=True,
            result_count=7,
            now=base + timedelta(seconds=3),
        )
        assert first.release(now=base + timedelta(seconds=4))

        assert second.acquire(now=base + timedelta(seconds=5))
        assert second.generation == 2
        assert not second.claim_run(now=base + timedelta(seconds=59))
        assert second.claim_run(now=base + timedelta(seconds=64))
        assert second.finish_run(
            interval_seconds=60,
            success=True,
            result_count=2,
            now=base + timedelta(seconds=65),
        )

        with sessions() as db:
            row = db.get(WorkerLease, "billing_reconciliation")
            assert row.owner_id == "api-two"
            assert row.generation == 2
            assert row.run_started_at is None
            assert row.last_result_count == 2
            assert row.last_success_at == base + timedelta(seconds=65)
            assert row.next_run_at == base + timedelta(seconds=125)
    finally:
        engine.dispose()


def test_expired_worker_is_fenced_and_another_replica_takes_over(tmp_path):
    engine, sessions = _session_factory(tmp_path)
    base = datetime(2026, 8, 7, 13, 0, 0)
    abandoned = DatabaseWorkerLease(
        sessions,
        name="integration_delivery",
        owner_id="abandoned-api",
        lease_seconds=10,
    )
    takeover = DatabaseWorkerLease(
        sessions,
        name="integration_delivery",
        owner_id="takeover-api",
        lease_seconds=10,
    )
    try:
        assert abandoned.acquire(now=base)
        assert abandoned.claim_run(now=base + timedelta(seconds=1))
        assert not takeover.acquire(now=base + timedelta(seconds=9))

        assert takeover.acquire(now=base + timedelta(seconds=11))
        assert takeover.generation == 2
        assert takeover.claim_run(now=base + timedelta(seconds=11))
        assert not abandoned.finish_run(
            interval_seconds=30,
            success=True,
            result_count=99,
            now=base + timedelta(seconds=12),
        )
        assert abandoned.generation is None
        assert takeover.finish_run(
            interval_seconds=30,
            success=True,
            result_count=1,
            now=base + timedelta(seconds=12),
        )
    finally:
        engine.dispose()


def test_leased_cycle_renews_records_results_and_clears_failures(
    tmp_path,
    monkeypatch,
):
    engine, sessions = _session_factory(tmp_path)
    clock = [datetime(2026, 8, 7, 14, 0, 0)]
    monkeypatch.setattr(worker_leases, "utcnow_naive", lambda: clock[0])
    lease = DatabaseWorkerLease(
        sessions,
        name="billing_reconciliation",
        owner_id="cycle-api",
        lease_seconds=30,
    )
    started: list[datetime] = []

    def successful_task(heartbeat):
        clock[0] += timedelta(seconds=5)
        heartbeat()
        return 4

    try:
        completed = run_leased_worker_cycle(
            lease,
            interval_seconds=60,
            initial_delay_seconds=0,
            task=successful_task,
            on_started=lambda: started.append(clock[0]),
        )
        assert completed.state == "completed"
        assert completed.result_count == 4
        assert started == [datetime(2026, 8, 7, 14, 0, 0)]

        waiting = run_leased_worker_cycle(
            lease,
            interval_seconds=60,
            initial_delay_seconds=0,
            task=successful_task,
        )
        assert waiting.state == "waiting"

        clock[0] += timedelta(seconds=61)

        def failing_task(heartbeat):
            heartbeat()
            raise ValueError("private worker failure detail")

        with pytest.raises(ValueError, match="private worker failure detail"):
            run_leased_worker_cycle(
                lease,
                interval_seconds=60,
                initial_delay_seconds=0,
                task=failing_task,
            )

        with sessions() as db:
            row = db.get(WorkerLease, "billing_reconciliation")
            assert row.run_started_at is None
            assert row.last_result_count == 4
            assert row.last_error_type == "ValueError"
            assert "private worker failure detail" not in str(row.__dict__)
    finally:
        engine.dispose()


def test_concurrent_replicas_elect_exactly_one_lease_owner(tmp_path):
    engine, sessions = _session_factory(tmp_path)
    base = datetime(2026, 8, 7, 15, 0, 0)

    def compete(owner_id: str) -> bool:
        lease = DatabaseWorkerLease(
            sessions,
            name="integration_delivery",
            owner_id=owner_id,
            lease_seconds=30,
        )
        return lease.acquire(now=base)

    try:
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(
                executor.map(compete, ["api-one", "api-two", "api-three", "api-four"])
            )
        assert results.count(True) == 1
        with sessions() as db:
            rows = db.scalars(select(WorkerLease)).all()
            assert len(rows) == 1
            assert rows[0].generation == 1
    finally:
        engine.dispose()
