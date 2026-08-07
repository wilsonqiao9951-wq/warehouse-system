from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import SessionLocal, engine, set_platform_database_scope
from app.models import OperationsHealthSample
from app.services.operations_history import (
    aggregate_operations_history,
    operations_instance_key,
    write_operations_health_sample,
)


VERIFY_PREFIX = "openpartsflow-operations-history-verifier"


def _snapshot(now: datetime, request_total: int) -> dict:
    return {
        "started_at": (now - timedelta(minutes=10))
        .replace(tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "uptime_seconds": 600,
        "requests": {
            "window_seconds": 300,
            "total": request_total,
            "server_errors": 0,
            "average_duration_ms": float(request_total),
            "p95_duration_ms": float(request_total * 2),
        },
        "workers": [
            {
                "name": "integration_delivery",
                "enabled": True,
                "status": "ok",
            }
        ],
    }


def _verification_keys() -> list[str]:
    return [
        operations_instance_key(f"{VERIFY_PREFIX}-{index}")
        for index in range(8)
    ]


def _clear_verification_rows(keys: list[str]) -> None:
    with SessionLocal() as db:
        set_platform_database_scope(db)
        db.execute(
            delete(OperationsHealthSample).where(
                OperationsHealthSample.instance_key.in_(keys)
            )
        )
        db.commit()


def main() -> int:
    if engine.dialect.name != "postgresql":
        print("Operations history verification skipped for non-PostgreSQL database.")
        return 0

    keys = _verification_keys()
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=10, microsecond=0)
    _clear_verification_rows(keys)
    try:
        old = write_operations_health_sample(
            SessionLocal,
            instance_key=keys[0],
            snapshot=_snapshot(now - timedelta(days=31), 1),
            schema_ready=True,
            schema_revision="verification",
            interval_seconds=60,
            retention_days=30,
            now=now - timedelta(days=31),
        )
        assert old.created

        def write_replica(index: int):
            return write_operations_health_sample(
                SessionLocal,
                instance_key=keys[index],
                snapshot=_snapshot(now, index + 1),
                schema_ready=True,
                schema_revision="verification",
                interval_seconds=60,
                retention_days=30,
                now=now,
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(write_replica, range(8)))
        assert all(result.created for result in results)
        assert any(result.purged_count >= 1 for result in results)

        repeated = write_operations_health_sample(
            SessionLocal,
            instance_key=keys[0],
            snapshot=_snapshot(now + timedelta(seconds=20), 99),
            schema_ready=True,
            schema_revision="verification",
            interval_seconds=60,
            retention_days=30,
            now=now + timedelta(seconds=20),
        )
        assert not repeated.created

        with SessionLocal() as db:
            set_platform_database_scope(db)
            rows = db.scalars(
                select(OperationsHealthSample).where(
                    OperationsHealthSample.instance_key.in_(keys)
                )
            ).all()
            assert len(rows) == 8
            history = aggregate_operations_history(
                db,
                from_at=now - timedelta(minutes=5),
                to_at=now + timedelta(minutes=5),
                bucket_minutes=5,
                max_samples=100,
            )
        points = [
            point
            for point in history["points"]
            if point["instances_reporting"] == 8
        ]
        assert len(points) == 1
        assert points[0]["request_total"] == 99 + sum(range(2, 9))
        assert history["truncated"] is False
        serialized = repr(history)
        assert VERIFY_PREFIX not in serialized
        assert all(key not in serialized for key in keys)
        print(
            "PostgreSQL operations history verification passed: "
            "8 replicas, idempotency, retention, aggregation, and privacy."
        )
        return 0
    finally:
        _clear_verification_rows(keys)


if __name__ == "__main__":
    raise SystemExit(main())
