# Operations Monitoring and SLA Readiness

OpenPartsFlow exposes minimal orchestration probes and a platform-only
operations console. The goal is to detect service, worker, queue, billing, and
data-protection risks without exposing customer records or secrets.

## Probe contract

### `GET /health/live`

Returns `200` while the application process can serve a response. The payload
contains only:

- `status=alive`;
- UTC check time;
- process uptime in seconds.

This endpoint does not touch the database. It is suitable for a liveness probe;
a database outage should not cause an automatic process restart loop.

### `GET /health/ready`

Runs a lightweight database query and checks the schema-ready state established
by the fail-closed startup migration guard. It returns:

- `200` with `status=ready` when database and schema are ready;
- `503` with `status=not_ready` when either core dependency is unavailable;
- a high-level `workers=ok|degraded` field.

Worker degradation does not change the readiness status. Restarting a healthy
API process because an external webhook or billing provider failed can make an
incident worse; worker alerts belong in the operations console and external
alerting pipeline.

Both probes use `Cache-Control: no-store`, receive an `X-Request-ID`, and omit
database URLs, tenant counts, exception text, credentials, and settings.

## Runtime evidence

The process keeps a thread-safe bounded window of at most 10,000 request
samples. Health-probe traffic is excluded. The configured window reports:

- request count;
- 5xx count and rate;
- average latency;
- p95 latency.

The integration-delivery and billing-reconciliation loops record start,
success, error class, result count, and timestamp. A worker is:

- `starting` before its first successful cycle;
- `ok` after a recent successful cycle;
- `error` when its latest cycle failed;
- `standby` when another live API replica owns the shared database lease;
- `stale` after three configured intervals without success, with a minimum
  60-second grace period;
- `disabled` when its feature is disabled.

Exception messages are logged server-side with the normal request/operation
context but are not stored in runtime state or returned to the UI. The console
shows only the exception class.

Runtime request evidence and local worker status are process-local and reset on
restart. Scheduler generation, expiration, current run, next run, and safe
completion evidence are stored in PostgreSQL and shown to platform
administrators without the owner identifier. For contractual SLA history, an
external monitoring system must still poll every replica and store time-series
results. See [`WORKER_LEASES.md`](WORKER_LEASES.md).

## Platform operations summary

`GET /api/platform/operations/summary` and `/platform/operations` require a
platform administrator. Customer administrators are explicitly denied.

The summary includes:

- database latency and active schema revision;
- process uptime and bounded request metrics;
- both background-worker states;
- shared scheduler generation, expiration, current-run, and next-run evidence;
- pending, due, failed, and stale-processing outbound deliveries;
- open critical subscription notices;
- active organizations without a recent portable backup;
- reviewed restore plans with unresolved record or media conflicts;
- normalized warning/critical alerts.

The endpoint aggregates counts only. It does not return customer names,
webhook payloads, response bodies, billing messages, archive paths, or error
details. The page refreshes every 30 seconds and supports an explicit refresh.

## Interrupted outbound delivery recovery

`POST /api/platform/operations/recover-stale-deliveries` provides a bounded,
platform-administrator-only recovery path for outbound Webhook rows left in
`processing` after a worker or host interruption. The operator must confirm the
current account password and supply a non-blank operational reason.

Recovery selects at most the requested bounded batch (100 by default, 500
maximum) whose processing age is older than
`OPERATIONS_STALE_PROCESSING_MINUTES`. Rows are locked before mutation and are
rechecked after lock acquisition. Fresh attempts, inbound sync rows, deliveries
already completed by another worker, and rows no longer in `processing` are
never changed.

Each recovered row returns to `pending` with an immediate retry time. Its
attempt count and stable business idempotency key are preserved, so the worker
can continue normal retry accounting and receivers can deduplicate the
delivery. Recovery does not send the Webhook inside the administrator request.
One tenant-scoped audit record is written for every affected organization with
the operator, reason, cutoff, time, count, and row IDs; payloads, callback URLs,
response bodies, API keys, and signatures are excluded. A request that finds no
eligible rows is also audited in the platform administrator's home organization.

Operational procedure:

1. Confirm the integration worker is stopped, restarted, or otherwise no longer
   executing the stale attempts.
2. Verify the operations console count remains stale beyond the configured
   cutoff; do not recover a request that may still be running.
3. Confirm the receiving system deduplicates `Idempotency-Key` or
   `X-OpenPartsFlow-Delivery`.
4. Enter the incident or change reference and current account password, then
   requeue the bounded batch.
5. Watch the worker and queue counts until the rows become `processed` or enter
   normal retry/failed handling; retain the audit export with the incident.

## Default thresholds

| Setting | Default | Purpose |
| --- | ---: | --- |
| `OPERATIONS_REQUEST_WINDOW_SECONDS` | 300 | Request error/latency window |
| `OPERATIONS_BACKUP_WARNING_DAYS` | 7 | Age after which an active customer backup is overdue |
| `OPERATIONS_STALE_PROCESSING_MINUTES` | 10 | Outbound delivery processing-age alert |
| `OPERATIONS_SLOW_REQUEST_MS` | 1000 | p95 latency warning threshold |
| `WORKER_LEASE_SECONDS` | 90 | Expired-owner failover boundary |
| `WORKER_LEASE_HEARTBEAT_SECONDS` | 10 | Lease renewal/election cadence |

A request error-rate alert requires at least 20 samples and a 5xx rate of at
least 5%. A latency alert requires at least five samples. Counts above zero
raise alerts for due/failed/stuck delivery, critical billing notices, overdue
backups, and restore conflicts.

## Deployment checks

1. Run `python -m scripts.prepare_database`; startup must confirm the current
   Alembic head before a readiness response can be served.
2. Configure the load balancer to use `/health/ready` and the process supervisor
   to use `/health/live`.
3. Poll both endpoints from outside the application host and retain history.
4. Sign in as the platform administrator and open `/platform/operations`.
5. Confirm one enabled worker moves from `starting` to `ok`; replicated
   non-owner processes should move to healthy `standby`. Stop the owner in a
   rehearsal and verify the lease generation increments after takeover.
6. Create a test outbound delivery, confirm the due count changes, then deliver
   or retry it and confirm recovery. In a non-production rehearsal, interrupt a
   worker attempt, wait beyond the stale cutoff, and exercise the protected
   recovery control.
7. Verify the backup-overdue count falls after each customer backup policy is
   satisfied.
8. Route critical alerts to the on-call system and define response ownership in
   the customer SLA; this application view alone is not an SLA guarantee.
