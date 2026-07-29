# Replenishment Custody API

## Purpose

The replenishment API provides an auditable warehouse-to-vehicle chain. Clients do not set arbitrary statuses. They request a named action, and the server validates the actor, current state, target vehicle owner, registered device, password step-up, and workflow version before changing custody or inventory.

## State and inventory model

```text
requested/pending → requested/approved → picking → shipped → received → completed
```

| Transition | Authorized actor | Inventory effect |
| --- | --- | --- |
| Create → `requested/pending` | Manager, admin, warehouse | None |
| Pending → approved/rejected | Manager or admin | Rejection is terminal and requires a reason |
| `requested/approved` → `picking` | Admin or warehouse | Requested quantity becomes reserved in source available-stock calculations |
| `picking` → `shipped` | Admin or warehouse | One linked `OUTBOUND` transaction removes stock from the source |
| `shipped` → `received` for a van | Exact target engineer on registered device, with current password | One linked `INBOUND` transaction adds stock to that engineer's destination van |
| `received` → `completed` | Admin or warehouse | No additional movement; originating alert becomes resolved |

Cancellation is allowed only while `requested` or `picking`, only by an administrator or warehouse user, and requires a reason of at least three characters. A cancelled request resolves its originating inventory notification so it cannot create a duplicate request loop. Shipped stock must use a dedicated return/reconciliation workflow rather than cancellation.

Managers may create requests and read the organization queue but cannot perform custody actions. Engineers receive only rows whose `target_user_id` matches their authenticated account. For non-van destinations with no target engineer, warehouse/admin receipt follows the same action endpoint; this exception never permits them to receive into an engineer-assigned van.

## Authentication

Every endpoint requires a Bearer access token. A target engineer's `receive` action additionally requires:

```text
Authorization: Bearer <access token with registered device id>
X-Device-Token: <registered device secret>
Content-Type: application/json
```

The JSON body includes `account_password`. The password is verified against the current account and immediately discarded. It must never be logged, cached, placed in a URL, or saved to the offline queue.

## Create from an inventory notification

```http
POST /api/inventory/notifications/{notification_id}/create-request?quantity=4&source_warehouse_id=2
```

`source_warehouse_id` is optional at creation and may instead be supplied by `start_picking`. The destination comes from the notification. A van destination must be active and assigned to an active engineer. The endpoint is idempotent per notification and returns the existing request when one already exists.

Allowed roles: manager, admin, warehouse.

## Create a manual vehicle request

Manual requests cover first-fill stock for a new engineer vehicle and other cases where no low-stock notification exists.

```http
POST /api/inventory/replenishment-requests
Content-Type: application/json
```

```json
{
  "part_id": 42,
  "destination_warehouse_id": 7,
  "quantity": 4,
  "source_warehouse_id": 2,
  "reason": "Initial stock allocation for a newly assigned vehicle",
  "client_request_id": "f4a98b5e-0b07-48ef-a4d7-2a6d92d12660"
}
```

`source_warehouse_id` is optional and may be assigned during picking. The destination must be an active vehicle assigned to an active engineer. The optional source must be active, different from the destination, and must not be a vehicle.

`client_request_id` is unique inside the organization. The mobile client generates it with `crypto.randomUUID()` and keeps the same value when retrying one unchanged submission. Repeating the same ID and payload returns the existing request; using that ID with different part, destination, source, quantity, or reason returns `409`.

Allowed roles: manager, admin, warehouse. The endpoint is online-only.

## List requests

```http
GET /api/inventory/replenishment-requests?status=shipped&limit=100
```

`status` accepts `requested`, `picking`, `shipped`, `received`, `completed`, `cancelled`, or `rejected`. Managers, admins, and warehouse users see their organization queue. Engineers see only requests assigned to them as `target_user_id`.

Important response fields include:

- `client_request_id`, `request_reason`, and `requires_reconciliation`;
- part, source warehouse, destination warehouse, work order, and target engineer labels;
- `version`;
- requester, picker, shipper, receiver, receiving device, completer, and canceller labels/timestamps;
- `shipment_transaction_id` and `receipt_transaction_id`;
- `source_available_quantity` and `destination_quantity`;
- `can_approve`, `can_reject`, `can_start_picking`, `can_ship`, `can_receive`, `can_complete`, `can_cancel`, and `can_reconcile`.

Clients must render actions from these capability fields, but must still handle authorization and conflict responses because capabilities can become stale after another user acts.

## Perform an action

```http
POST /api/inventory/replenishment-requests/{request_id}/actions
Content-Type: application/json
```

Every action sends the last `version` returned by the API:

All normal actions are rejected while `requires_reconciliation=true`, regardless of the displayed status.

### Start picking

```json
{
  "action": "start_picking",
  "expected_version": 0,
  "source_warehouse_id": 2
}
```

The server verifies unreserved source stock and records the picker and server time.

### Ship

```json
{
  "action": "ship",
  "expected_version": 1
}
```

The server posts the source `OUTBOUND` transaction and records the shipper and server time in the same database transaction.

### Receive into the engineer's vehicle

```json
{
  "action": "receive",
  "expected_version": 2,
  "account_password": "current account password"
}
```

For a van delivery the server requires the exact target engineer, matching active registered device, current password, and continued destination-van ownership. It posts the destination `INBOUND` transaction and records `received_by`, `received_device_id`, and `received_at` atomically.

### Complete

```json
{
  "action": "complete",
  "expected_version": 3
}
```

Only a request with a successful receipt transaction may complete. Completion does not move inventory again.

### Cancel

```json
{
  "action": "cancel",
  "expected_version": 0,
  "reason": "Destination vehicle is out of service"
}
```

Cancellation is rejected after shipment.

When a request originated from a notification, cancellation marks that notification `resolved`; it does not reopen the alert.

## Reconcile legacy custody

Migration `20260711_0019` flags legacy `picking`, `shipped`, `received`, and `completed` rows because the old labels did not prove physical movements. Intermediate rows are reopened as `requested`; completed rows retain `completed`. Until reconciliation, every ordinary action capability is false.

```http
POST /api/inventory/replenishment-requests/{request_id}/reconcile
Content-Type: application/json
```

Restart a reopened request:

```json
{
  "expected_version": 0,
  "resolution": "reset_requested",
  "reason": "Verified that no stock left the source warehouse",
  "account_password": "current administrator password"
}
```

Accept an older completed record without fabricating ledger entries:

```json
{
  "expected_version": 0,
  "resolution": "accept_historical",
  "reason": "Accepted after review of signed legacy delivery paperwork",
  "account_password": "current administrator password"
}
```

Only an exact administrator can reconcile. The request must still be flagged, the version must match, the reason must contain at least three characters, and the current administrator password must verify. `reset_requested` is valid only for status `requested`; `accept_historical` is valid only for status `completed`.

If any inventory transaction is already linked to the request, reconciliation returns `409` and requires a dedicated stock-correction process. A successful resolution clears `requires_reconciliation`, increments `version`, and records `replenishment_reconciled`. Resetting a notification-backed request reopens its notification; accepting a historical completed request resolves it.

## Authenticated vehicle inventory

```http
GET /api/inventory/my-van?limit=500
```

This endpoint accepts only an engineer and derives the user from the Bearer token. The client does not submit a user ID. After a successful receipt, the mobile My Van page refreshes this endpoint so the new vehicle balance is visible immediately.

## Concurrency, retries, and errors

- Each successful action increments `version`.
- Manual request retries are idempotent by organization and `client_request_id`.
- An `expected_version` mismatch or invalid transition returns `409` and makes no change.
- Repeating an already-applied action returns the current request without posting another inventory movement.
- Database uniqueness on `(replenishment_request_id, movement_stage)` and on the request's shipment/receipt transaction links prevents duplicate movement records.
- Invalid or missing action data returns `422`.
- Insufficient role or target ownership returns `403`; invalid registered-device authentication or password verification returns an authentication error.
- The deprecated `PATCH /api/inventory/replenishment-requests/{id}` returns `410`.
- A reconciliation attempt with linked inventory movements returns `409` without clearing the flag.

Clients should refresh the request list after `409`, then use the returned version and capability flags. They must not automatically retry a custody action using an old version.

## Audit trail

The API records:

- `replenishment_requested`;
- `replenishment_start_picking`;
- `replenishment_ship`;
- `replenishment_receive`;
- `replenishment_complete`;
- `replenishment_cancel`;
- `replenishment_reconciled`.

Transition metadata contains the prior/new state or reconciliation resolution, reason where required, prior/new version, part, quantity, source/destination warehouses, target engineer, and inventory transaction ID. Standard audit context supplies actor, role, authentication method, device record, and server timestamp. Passwords and raw device secrets are excluded.

## Offline behavior

Notification/manual request creation, picking, shipping, receipt, completion, cancellation, and reconciliation are verified online-only operations. The PWA rejects them while offline and never appends them to the JSON offline queue. Read-only cached UI may remain visible, but it is not proof that a capability or version is still current.

## Vehicle inventory boundary

A warehouse is a vehicle when its normalized `warehouse_type` is `van` or its owner is an engineer. Creating an engineer-owned warehouse automatically normalizes it to `van`; a van must be assigned to an active engineer.

- A vehicle cannot be used as a replenishment source.
- `POST /api/inventory/transactions` rejects every vehicle source or destination.
- Opening-inventory preview reports a row error for a vehicle, and commit rechecks the warehouse before posting.
- The generic transaction endpoint accepts only `INBOUND`, `OUTBOUND`, `TRANSFER`, and `DAMAGE`. `RETURN` and `WORK_ORDER_USED` must use authenticated business workflows instead.
- Engineers may consume work-order parts only from their own assigned vehicle.

This boundary ensures that vehicle stock increases only through verified engineer receipt and decreases only through an authenticated field or return workflow.

## Database concurrency and integrity

- Every SQLite connection enables `PRAGMA foreign_keys=ON` and `PRAGMA busy_timeout=5000`.
- SQLite inventory-affecting custody writes acquire `BEGIN IMMEDIATE` before reading stock or mutating state, serializing competing writers.
- PostgreSQL uses row locks for the same critical records.
- Quantity, version, status, movement-stage, paired-link, idempotency, notification, and transaction-link constraints provide database-level backstops.

## Migration

Alembic revision `20260711_0019` formalizes `warehouse_type`; adds manual request ID/reason, reconciliation flag, custody actors/timestamps, target engineer, receiving device, workflow version, cancellation data, transaction links, indexes, checks, and uniqueness constraints; and adds `replenishment_request_id` and `movement_stage` to inventory transactions.

Legacy intermediate rows are reset to `requested` and flagged; legacy completed rows remain completed and are flagged. The migration does not fabricate historical responsibility or inventory records.

Downgrade from `0019` stops with an explicit error while any inventory movement remains linked to a replenishment request. Operators must export and reconcile custody history before removing the schema links; downgrade never silently orphans ledger history.
