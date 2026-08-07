from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import math

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.database import set_platform_database_scope
from app.models import OperationsHealthSample


@dataclass(frozen=True)
class OperationsSampleWriteResult:
    created: bool
    purged_count: int
    sampled_at: datetime


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def operations_instance_key(instance_id: str) -> str:
    normalized = instance_id.strip()
    if not normalized:
        raise ValueError("Operations history instance identifier cannot be blank")
    return sha256(normalized.encode("utf-8")).hexdigest()


def bucket_timestamp(value: datetime, seconds: int) -> datetime:
    size = max(1, seconds)
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    epoch = int(aware.timestamp())
    return datetime.fromtimestamp(epoch - (epoch % size), tz=timezone.utc).replace(
        tzinfo=None
    )


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).replace(tzinfo=None)


def write_operations_health_sample(
    session_factory,
    *,
    instance_key: str,
    snapshot: dict,
    schema_ready: bool,
    schema_revision: str,
    interval_seconds: int,
    retention_days: int,
    now: datetime | None = None,
) -> OperationsSampleWriteResult:
    checked_at = now or utcnow_naive()
    sampled_at = bucket_timestamp(checked_at, max(1, interval_seconds))
    request_metrics = snapshot["requests"]
    worker_health = (
        "degraded"
        if any(
            row["enabled"] and row["status"] in {"error", "stale"}
            for row in snapshot["workers"]
        )
        else "ok"
    )
    cutoff = checked_at - timedelta(days=max(1, retention_days))
    with session_factory() as db:
        set_platform_database_scope(db)
        row = db.scalar(
            select(OperationsHealthSample).where(
                OperationsHealthSample.instance_key == instance_key,
                OperationsHealthSample.sampled_at == sampled_at,
            )
        )
        created = row is None
        if row is None:
            row = OperationsHealthSample(
                instance_key=instance_key,
                sampled_at=sampled_at,
                process_started_at=_parse_utc(snapshot["started_at"]),
                uptime_seconds=max(0, int(snapshot["uptime_seconds"])),
                schema_revision=(schema_revision or "unknown")[:64],
                schema_ready=bool(schema_ready),
                worker_health=worker_health,
                request_window_seconds=max(
                    1, int(request_metrics["window_seconds"])
                ),
                request_total=max(0, int(request_metrics["total"])),
                server_errors=max(0, int(request_metrics["server_errors"])),
                average_duration_ms=max(
                    0.0, float(request_metrics["average_duration_ms"])
                ),
                p95_duration_ms=max(
                    0.0, float(request_metrics["p95_duration_ms"])
                ),
                created_at=checked_at,
                updated_at=checked_at,
            )
        else:
            row.process_started_at = _parse_utc(snapshot["started_at"])
            row.uptime_seconds = max(0, int(snapshot["uptime_seconds"]))
            row.schema_revision = (schema_revision or "unknown")[:64]
            row.schema_ready = bool(schema_ready)
            row.worker_health = worker_health
            row.request_window_seconds = max(
                1, int(request_metrics["window_seconds"])
            )
            row.request_total = max(0, int(request_metrics["total"]))
            row.server_errors = max(0, int(request_metrics["server_errors"]))
            row.average_duration_ms = max(
                0.0, float(request_metrics["average_duration_ms"])
            )
            row.p95_duration_ms = max(
                0.0, float(request_metrics["p95_duration_ms"])
            )
            row.updated_at = checked_at
        if row.server_errors > row.request_total:
            row.server_errors = row.request_total
        db.add(row)
        purged = db.execute(
            delete(OperationsHealthSample).where(
                OperationsHealthSample.sampled_at < cutoff
            )
        ).rowcount or 0
        db.commit()
    return OperationsSampleWriteResult(created, int(purged), sampled_at)


def aggregate_operations_history(
    db: Session,
    *,
    from_at: datetime,
    to_at: datetime,
    bucket_minutes: int,
    max_samples: int,
) -> dict:
    set_platform_database_scope(db)
    bounded_limit = max(1, max_samples)
    rows = db.scalars(
        select(OperationsHealthSample)
        .where(
            OperationsHealthSample.sampled_at >= from_at,
            OperationsHealthSample.sampled_at <= to_at,
        )
        .order_by(OperationsHealthSample.sampled_at.desc())
        .limit(bounded_limit + 1)
    ).all()
    truncated = len(rows) > bounded_limit
    if truncated:
        rows = rows[:bounded_limit]
    rows.reverse()

    bucket_seconds = max(1, bucket_minutes) * 60
    groups: dict[datetime, dict] = {}
    instances_seen: set[str] = set()
    for row in rows:
        bucket_at = bucket_timestamp(row.sampled_at, bucket_seconds)
        group = groups.setdefault(
            bucket_at,
            {
                "instance_request_snapshots": {},
                "sample_count": 0,
                "schema_not_ready_samples": 0,
                "worker_degraded_samples": 0,
            },
        )
        instances_seen.add(row.instance_key)
        group["sample_count"] += 1
        group["schema_not_ready_samples"] += 0 if row.schema_ready else 1
        group["worker_degraded_samples"] += (
            1 if row.worker_health == "degraded" else 0
        )
        # Request values are rolling-window snapshots, not event deltas. Use
        # the last snapshot from each instance in an output bucket so the same
        # requests are not counted again at every sampling interval.
        group["instance_request_snapshots"][row.instance_key] = {
            "window_seconds": row.request_window_seconds,
            "total": row.request_total,
            "server_errors": row.server_errors,
            "average_duration_ms": row.average_duration_ms,
            "p95_duration_ms": row.p95_duration_ms,
        }

    points: list[dict] = []
    for bucket_at in sorted(groups):
        group = groups[bucket_at]
        request_snapshots = list(
            group["instance_request_snapshots"].values()
        )
        request_total = sum(row["total"] for row in request_snapshots)
        server_errors = sum(
            row["server_errors"] for row in request_snapshots
        )
        weighted_duration_total = sum(
            row["average_duration_ms"] * row["total"]
            for row in request_snapshots
        )
        points.append(
            {
                "bucket_at": bucket_at,
                "instances_reporting": len(request_snapshots),
                "sample_count": group["sample_count"],
                "schema_not_ready_samples": group[
                    "schema_not_ready_samples"
                ],
                "worker_degraded_samples": group[
                    "worker_degraded_samples"
                ],
                "request_window_seconds": max(
                    1,
                    *(row["window_seconds"] for row in request_snapshots),
                ),
                "request_total": request_total,
                "server_errors": server_errors,
                "server_error_rate": round(
                    server_errors / request_total, 6
                )
                if request_total
                else 0.0,
                "average_duration_ms": round(
                    weighted_duration_total / request_total, 3
                )
                if request_total
                else 0.0,
                "p95_duration_ms": round(
                    max(
                        (row["p95_duration_ms"] for row in request_snapshots),
                        default=0.0,
                    ),
                    3,
                ),
            }
        )

    expected_buckets = max(
        1,
        math.ceil(
            max(0.0, (to_at - from_at).total_seconds()) / bucket_seconds
        ),
    )
    return {
        "from_at": from_at,
        "to_at": to_at,
        "bucket_minutes": max(1, bucket_minutes),
        "expected_buckets": expected_buckets,
        "buckets_present": len(points),
        "bucket_coverage_rate": round(
            min(1.0, len(points) / expected_buckets), 6
        ),
        "instances_seen": len(instances_seen),
        "sample_count": len(rows),
        "latest_sample_at": rows[-1].sampled_at if rows else None,
        "truncated": truncated,
        "points": points,
    }
