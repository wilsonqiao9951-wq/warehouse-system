from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import math
from threading import Lock


def utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return aware.isoformat().replace("+00:00", "Z")


@dataclass
class _RequestSample:
    occurred_at: datetime
    status_code: int
    duration_ms: float


@dataclass
class _WorkerState:
    enabled: bool
    interval_seconds: int
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_type: str | None = None
    last_result_count: int | None = None
    last_standby_at: datetime | None = None


class OperationsMonitor:
    """Bounded, process-local evidence for probes and operational dashboards."""

    def __init__(self, *, request_capacity: int = 10_000) -> None:
        self._lock = Lock()
        self._request_capacity = max(100, request_capacity)
        self.reset()

    def reset(
        self,
        *,
        delivery_enabled: bool = False,
        delivery_interval_seconds: int = 30,
        billing_enabled: bool = False,
        billing_interval_seconds: int = 3600,
        started_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._started_at = started_at or utcnow_naive()
            self._requests: deque[_RequestSample] = deque(maxlen=self._request_capacity)
            self._workers = {
                "integration_delivery": _WorkerState(
                    enabled=delivery_enabled,
                    interval_seconds=max(1, delivery_interval_seconds),
                ),
                "billing_reconciliation": _WorkerState(
                    enabled=billing_enabled,
                    interval_seconds=max(1, billing_interval_seconds),
                ),
            }

    def record_request(
        self,
        status_code: int,
        duration_ms: float,
        *,
        occurred_at: datetime | None = None,
    ) -> None:
        with self._lock:
            self._requests.append(
                _RequestSample(
                    occurred_at=occurred_at or utcnow_naive(),
                    status_code=status_code,
                    duration_ms=max(0.0, duration_ms),
                )
            )

    def worker_started(self, name: str, *, at: datetime | None = None) -> None:
        with self._lock:
            worker = self._workers.get(name)
            if worker and worker.enabled:
                worker.last_started_at = at or utcnow_naive()

    def worker_succeeded(
        self,
        name: str,
        *,
        result_count: int | None = None,
        at: datetime | None = None,
    ) -> None:
        with self._lock:
            worker = self._workers.get(name)
            if worker and worker.enabled:
                worker.last_success_at = at or utcnow_naive()
                worker.last_error_type = None
                worker.last_result_count = result_count

    def worker_failed(
        self,
        name: str,
        error: BaseException,
        *,
        at: datetime | None = None,
    ) -> None:
        with self._lock:
            worker = self._workers.get(name)
            if worker and worker.enabled:
                worker.last_error_at = at or utcnow_naive()
                worker.last_error_type = type(error).__name__

    def worker_standby(self, name: str, *, at: datetime | None = None) -> None:
        with self._lock:
            worker = self._workers.get(name)
            if worker and worker.enabled:
                worker.last_standby_at = at or utcnow_naive()

    def snapshot(
        self,
        *,
        window_seconds: int = 300,
        now: datetime | None = None,
    ) -> dict:
        checked_at = now or utcnow_naive()
        window = max(1, window_seconds)
        cutoff = checked_at - timedelta(seconds=window)
        with self._lock:
            samples = [row for row in self._requests if row.occurred_at >= cutoff]
            started_at = self._started_at
            workers = {name: _WorkerState(**asdict(state)) for name, state in self._workers.items()}

        durations = sorted(row.duration_ms for row in samples)
        total = len(samples)
        server_errors = sum(1 for row in samples if row.status_code >= 500)
        p95_index = max(0, math.ceil(total * 0.95) - 1) if total else 0
        request_metrics = {
            "window_seconds": window,
            "total": total,
            "server_errors": server_errors,
            "server_error_rate": round(server_errors / total, 6) if total else 0.0,
            "average_duration_ms": round(sum(durations) / total, 3) if total else 0.0,
            "p95_duration_ms": round(durations[p95_index], 3) if total else 0.0,
        }

        worker_rows = []
        for name, state in workers.items():
            grace_seconds = max(60, state.interval_seconds * 3)
            recent_standby = bool(
                state.last_standby_at
                and (checked_at - state.last_standby_at).total_seconds()
                <= grace_seconds
            )
            if not state.enabled:
                status = "disabled"
            elif recent_standby and (
                state.last_success_at is None
                or state.last_standby_at > state.last_success_at
            ) and (
                state.last_error_at is None
                or state.last_standby_at > state.last_error_at
            ):
                status = "standby"
            elif state.last_success_at is None:
                if (checked_at - started_at).total_seconds() > grace_seconds:
                    status = "stale"
                elif state.last_error_at is not None:
                    status = "error"
                else:
                    status = "starting"
            elif (checked_at - state.last_success_at).total_seconds() > grace_seconds:
                status = "stale"
            elif state.last_error_at and state.last_error_at > state.last_success_at:
                status = "error"
            else:
                status = "ok"
            worker_rows.append(
                {
                    "name": name,
                    "enabled": state.enabled,
                    "status": status,
                    "interval_seconds": state.interval_seconds,
                    "grace_seconds": grace_seconds,
                    "last_started_at": utc_iso(state.last_started_at),
                    "last_success_at": utc_iso(state.last_success_at),
                    "last_error_at": utc_iso(state.last_error_at),
                    "last_error_type": state.last_error_type,
                    "last_result_count": state.last_result_count,
                    "last_standby_at": utc_iso(state.last_standby_at),
                }
            )

        return {
            "checked_at": utc_iso(checked_at),
            "started_at": utc_iso(started_at),
            "uptime_seconds": max(0, int((checked_at - started_at).total_seconds())),
            "requests": request_metrics,
            "workers": worker_rows,
        }


operations_monitor = OperationsMonitor()
