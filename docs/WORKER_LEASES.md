# Multi-instance background worker leases

OpenPartsFlow coordinates the integration-delivery and billing-reconciliation
schedulers through the shared database. Every API replica may start both loops,
but only the current lease owner may claim a scheduled run.

## Lease contract

Migration `20260807_0056` creates the platform-global `worker_leases` table.
Each worker name has one row containing:

- an opaque owner identifier that is never returned by the API;
- a monotonically increasing generation used as a fencing token;
- acquisition, heartbeat, and expiration timestamps;
- a shared next-run time and current-run start time;
- safe last-success/error-class/result-count evidence.

Acquisition is one database upsert. A replica may renew its own unexpired lease,
or replace an expired lease; competing live owners receive no row. Every takeover
increments the generation and clears an abandoned run marker. Renewal, run
claim, completion, and release all require the exact owner and generation, so a
late result from an expired process cannot overwrite the new owner's state.

The owner renews while idle and between bounded work items. On graceful shutdown
an idle lease is expired immediately without changing `next_run_at`. If shutdown
interrupts a Python worker thread, the application deliberately does not release
its lease: the thread may finish safely, otherwise another replica takes over
after expiration.

## Scheduling and failure behavior

`next_run_at` is shared rather than process-local. Claiming a due run records
`run_started_at`; successful or failed completion clears it and advances the
shared schedule by the worker's configured interval. If a process disappears
mid-run, lease takeover clears the abandoned marker while retaining the overdue
schedule, allowing immediate recovery.

Outbound delivery retains its row-level compare-and-set claim and downstream
idempotency key. The scheduler lease prevents redundant queue scans; the delivery
claim remains the final duplicate-send boundary. Billing keeps its organization
row locks and idempotent notice rules behind the scheduler lease.

## Configuration

| Setting | Default | Rule |
| --- | ---: | --- |
| `WORKER_LEASE_SECONDS` | 90 | Production/staging: 30 to 3600 seconds |
| `WORKER_LEASE_HEARTBEAT_SECONDS` | 10 | 1 to 300 seconds and no more than one third of the lease |

Deployable environments require PostgreSQL. SQLite remains supported for local
development and tests, but it is not a multi-process production topology.

## Operations

The platform operations console shows the shared generation, lease expiration,
run start, and next-run time without exposing the owner/host identifier. A live
non-owner replica reports `standby`, which is healthy and does not trigger stale
worker alerts.

During an incident:

1. Check `/health/ready` on every replica and the platform operations page.
2. Confirm another replica is reporting `standby` and that lease expiration is
   moving while the owner is healthy.
3. Stop or isolate the failed replica. Do not manually edit the lease row.
4. Verify the generation increments after expiration and a due run completes.
5. For a delivery left in `processing`, use the separately protected stale
   delivery recovery workflow only after its configured cutoff.

The reference Compose file is still a single-host deployment. Multiple API
replicas also require a real load balancer/orchestrator and shared durable media
storage; database worker leases alone do not provide multi-host high availability.

## Migration and rollback

Upgrade before starting any `0056` application process. The table contains only
ephemeral scheduler coordination and safe operational evidence, so downgrade
drops it. Stop all API replicas before downgrade; older code has no cross-instance
scheduler coordination and must not be run with multiple replicas.
