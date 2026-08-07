from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import OperationsHealthSample
from app.services.operations_history import (
    aggregate_operations_history,
    bucket_timestamp,
    operations_instance_key,
    write_operations_health_sample,
)


def _snapshot(
    now: datetime,
    *,
    request_total: int,
    server_errors: int,
    average_duration_ms: float,
    p95_duration_ms: float,
    worker_status: str = "ok",
) -> dict:
    started_at = (now - timedelta(minutes=10)).replace(
        tzinfo=timezone.utc
    ).isoformat().replace("+00:00", "Z")
    return {
        "checked_at": now.replace(tzinfo=timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "started_at": started_at,
        "uptime_seconds": 600,
        "requests": {
            "window_seconds": 300,
            "total": request_total,
            "server_errors": server_errors,
            "server_error_rate": (
                server_errors / request_total if request_total else 0.0
            ),
            "average_duration_ms": average_duration_ms,
            "p95_duration_ms": p95_duration_ms,
        },
        "workers": [
            {
                "name": "integration_delivery",
                "enabled": True,
                "status": worker_status,
            }
        ],
    }


def test_operations_history_is_bucket_idempotent_hashed_and_retained(client):
    sessions = client.app.state.testing_session_local
    base = datetime(2026, 8, 7, 18, 0, 0)
    instance_key = operations_instance_key("private-host:1234:raw-instance")
    assert len(instance_key) == 64
    assert "private-host" not in instance_key

    old = write_operations_health_sample(
        sessions,
        instance_key=instance_key,
        snapshot=_snapshot(
            base - timedelta(days=31),
            request_total=2,
            server_errors=0,
            average_duration_ms=10,
            p95_duration_ms=15,
        ),
        schema_ready=True,
        schema_revision="20260807_0057",
        interval_seconds=60,
        retention_days=30,
        now=base - timedelta(days=31),
    )
    assert old.created

    current = write_operations_health_sample(
        sessions,
        instance_key=instance_key,
        snapshot=_snapshot(
            base,
            request_total=10,
            server_errors=1,
            average_duration_ms=30,
            p95_duration_ms=70,
            worker_status="error",
        ),
        schema_ready=False,
        schema_revision="20260807_0057",
        interval_seconds=60,
        retention_days=30,
        now=base,
    )
    assert current.created
    assert current.purged_count == 1

    repeated = write_operations_health_sample(
        sessions,
        instance_key=instance_key,
        snapshot=_snapshot(
            base + timedelta(seconds=30),
            request_total=12,
            server_errors=2,
            average_duration_ms=40,
            p95_duration_ms=90,
        ),
        schema_ready=True,
        schema_revision="20260807_0057",
        interval_seconds=60,
        retention_days=30,
        now=base + timedelta(seconds=30),
    )
    assert not repeated.created
    assert repeated.sampled_at == current.sampled_at

    with sessions() as db:
        rows = db.scalars(select(OperationsHealthSample)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.instance_key == instance_key
        assert row.request_total == 12
        assert row.server_errors == 2
        assert row.schema_ready is True
        assert row.worker_health == "ok"
        assert row.p95_duration_ms == 90


def test_platform_history_aggregates_instances_without_exposing_identity(client):
    sessions = client.app.state.testing_session_local
    now = datetime.now(timezone.utc).replace(tzinfo=None, second=0, microsecond=0)
    combined_bucket = bucket_timestamp(now - timedelta(minutes=10), 300)
    first_key = operations_instance_key("first-private-instance")
    second_key = operations_instance_key("second-private-instance")

    for instance_key, total, errors, average, p95 in (
        (first_key, 10, 1, 100, 200),
        (second_key, 30, 0, 50, 100),
    ):
        write_operations_health_sample(
            sessions,
            instance_key=instance_key,
            snapshot=_snapshot(
                now - timedelta(minutes=10),
                request_total=total,
                server_errors=errors,
                average_duration_ms=average,
                p95_duration_ms=p95,
            ),
            schema_ready=True,
            schema_revision="20260807_0057",
            interval_seconds=60,
            retention_days=30,
            now=combined_bucket + timedelta(minutes=1),
        )
    # A later sample from the same instance in the same output bucket replaces
    # that instance's rolling request snapshot instead of double counting it.
    write_operations_health_sample(
        sessions,
        instance_key=first_key,
        snapshot=_snapshot(
            combined_bucket + timedelta(minutes=2),
            request_total=12,
            server_errors=2,
            average_duration_ms=75,
            p95_duration_ms=250,
        ),
        schema_ready=True,
        schema_revision="20260807_0057",
        interval_seconds=60,
        retention_days=30,
        now=combined_bucket + timedelta(minutes=2),
    )
    write_operations_health_sample(
        sessions,
        instance_key=first_key,
        snapshot=_snapshot(
            combined_bucket - timedelta(minutes=10),
            request_total=5,
            server_errors=0,
            average_duration_ms=20,
            p95_duration_ms=30,
            worker_status="stale",
        ),
        schema_ready=False,
        schema_revision="20260807_0057",
        interval_seconds=60,
        retention_days=30,
        now=combined_bucket - timedelta(minutes=10),
    )

    response = client.get(
        "/api/platform/operations/history?hours=1&bucket_minutes=5"
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["instances_seen"] == 2
    assert payload["sample_count"] == 4
    assert payload["expected_buckets"] == 12
    assert payload["buckets_present"] == 2
    assert payload["bucket_coverage_rate"] == round(2 / 12, 6)
    assert payload["truncated"] is False
    assert len(payload["points"]) == 2

    combined = next(
        point for point in payload["points"]
        if point["instances_reporting"] == 2
    )
    assert combined["sample_count"] == 3
    assert combined["request_total"] == 42
    assert combined["server_errors"] == 2
    assert combined["server_error_rate"] == round(2 / 42, 6)
    assert combined["average_duration_ms"] == round((12 * 75 + 30 * 50) / 42, 3)
    assert combined["p95_duration_ms"] == 250

    degraded = next(
        point for point in payload["points"]
        if point["instances_reporting"] == 1
    )
    assert degraded["schema_not_ready_samples"] == 1
    assert degraded["worker_degraded_samples"] == 1
    assert first_key not in response.text
    assert second_key not in response.text
    assert "first-private-instance" not in response.text

    with sessions() as db:
        bounded = aggregate_operations_history(
            db,
            from_at=now - timedelta(hours=1),
            to_at=now + timedelta(minutes=1),
            bucket_minutes=5,
            max_samples=2,
        )
    assert bounded["truncated"] is True
    assert bounded["sample_count"] == 2


def test_platform_history_rejects_unbounded_periods(client):
    assert client.get(
        "/api/platform/operations/history?hours=169&bucket_minutes=5"
    ).status_code == 422
    assert client.get(
        "/api/platform/operations/history?hours=24&bucket_minutes=0"
    ).status_code == 422
