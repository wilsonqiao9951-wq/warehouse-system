# Governed Low-stock Rules and Alert Evidence

OpenPartsFlow evaluates low stock per organization, warehouse, and part. An
active warehouse/part override takes precedence over the part master default;
otherwise the effective threshold is `max(safety_stock, min_stock)`.

## Rule contract

Managers and administrators can create or update one rule per warehouse/part:

```http
PUT /api/inventory/stock-threshold-rules/{warehouse_id}/{part_id}
```

```json
{
  "threshold_quantity": 5,
  "reorder_quantity": 8,
  "is_active": true,
  "reason": "Critical service stock for this vehicle",
  "expected_version": 2
}
```

`expected_version` is omitted only when creating a new rule. Every update must
match the current version or returns `409`. Warehouse users may read rules but
cannot govern them. Engineers and assistants are denied.

`GET /api/inventory/stock-threshold-rules` is tenant-scoped, no-store, and can
filter by warehouse, part, or active state. Each row includes the responsible
creator/updater, business reason, version, and server timestamps.

## Evaluation

Part usage evaluates the affected inventory position inside the same serialized
inventory transaction. An operator can also run a bounded organization scan:

```http
POST /api/inventory/low-stock/evaluate
```

The result reports positions scanned, positions below threshold, alerts
created, already-active alerts, and recovered alerts awaiting closure. A run is
bounded to 50,000 part/warehouse positions. The active-alert partial unique
index permits only one `open` or `acknowledged` row for an organization,
warehouse, and part; concurrent evaluations therefore cannot create duplicate
active work.

## Immutable trigger evidence

Every alert retains:

- triggering rule ID, when an override applied;
- triggering threshold and observed quantity;
- source work order, when usage caused the alert;
- current effective threshold and quantity as a live projection;
- optimistic version;
- acknowledgement account, time, and note;
- resolution account, time, and reason;
- linked replenishment ID and status.

The original trigger threshold is not rewritten when a rule changes. This
preserves why the alert existed while still showing whether stock has recovered
under the current rule.

## State and authorization

```text
open → acknowledged → resolved
```

Warehouse, manager, and administrator users can call:

```http
POST /api/inventory/notifications/{notification_id}/actions
```

Acknowledgement requires the current version and may carry an operator note.
Resolution requires a reason and is allowed only after acknowledgement plus
one of these server-verified conditions:

- physical stock is above the current effective threshold; or
- the linked replenishment request is completed.

Exact retries by the same account and evidence are idempotent. Stale or skipped
transitions return `409`. The previous arbitrary status PATCH returns `410` so
clients cannot bypass the state machine.

Creating a replenishment from an open alert records the requesting account as
the acknowledger. Completion resolves the source alert with custody evidence.
Rejection or cancellation resolves that request's source alert, then immediately
re-evaluates physical stock; if it is still low, a fresh actionable alert is
created instead of hiding the shortage or reusing a terminal request.

## UI

`/low-stock-rules` provides manager rule governance, warehouse read access,
bounded evaluation, active/history filters, complete trigger/current evidence,
versioned acknowledgement, and recovery-gated resolution. `/warehouse-tasks`
uses the same versioned action contract and defaults replenishment quantity to
the effective rule recommendation.

All actions are online-only, tenant-scoped, and written to the immutable audit
log. Frontend capability flags improve usability but never replace API checks.
