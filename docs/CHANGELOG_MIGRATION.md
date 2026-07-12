# OpenPartsFlow Migration Changelog

## Purpose

This changelog summarizes migration-related backend upgrades made to align OpenPartsFlow with AppSheet structure while preserving existing logic.

---

## 1) AppSheet-Compatible Data Model Expansion

### WorkOrders (`work_orders`)

Added compatibility fields:
- `wo_number`
- `schedule_date`
- `outlet_name`
- `job_type`
- `description`
- `city`
- `state`
- `zip`
- `contact_phone`
- `revenue` (already present)
- `labor_cost` (already present)

Compatibility behavior:
- `wo_number` and `ticket_number` are auto-mapped both ways.
- `outlet_name` and `store_name` are auto-mapped both ways.
- `description` and `problem_description` are auto-mapped both ways.

Impact:
- Existing clients using `ticket_number/store_name/problem_description` continue to work.
- AppSheet-style payloads can be accepted without breaking legacy flows.

---

### PartListsWOs (`work_order_parts`)

Added:
- `total_cost`

Behavior:
- Auto-calculated as `quantity * unit_cost` during part usage write flow.

Impact:
- Existing use-part logic remains intact.
- Cost reporting is easier and AppSheet-compatible.

---

### QCPictures (`qc_pictures`) - New Table

Fields:
- `id`
- `work_order_id`
- `image_url`
- `uploaded_by`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/qc-pictures`
- `GET /api/qc-pictures`

---

### JobStatus (`job_status`) - New Table

Fields:
- `id`
- `work_order_id`
- `status`
- `timestamp`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/job-status`
- `GET /api/job-status`

---

### ReturnEquipments (`return_equipments`) - New Table

Fields:
- `id`
- `work_order_id`
- `equipment_type`
- `quantity`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/return-equipments`
- `GET /api/return-equipments`

---

## 2) Core Inventory Upgrade

Existing inventory system retained and validated:
- `parts`
- `inventory_transactions`
- `warehouses`

Enhancement:
- Added `warehouses.warehouse_type` (`main` / `van`) for clearer location semantics.

Existing behavior preserved:
- Stock validation before usage
- Auto inventory deduction on part usage
- Van inventory by employee

Key endpoints:
- `POST /api/inventory/transactions`
- `GET /api/inventory/transactions`
- `GET /api/inventory/balances`
- `GET /api/employees/{user_id}/van-inventory`
- `POST /api/work-orders/{id}/use-part`

---

## 3) Profit Calculation

Formula preserved:
- `profit = revenue - labor_cost - sum(parts)`

Endpoint:
- `GET /api/work-orders/{id}/profit`

Enhancement:
- Profit payload now also includes `wo_number` for AppSheet compatibility context.

---

## 4) Backward Compatibility and Safety

### Existing Logic Preserved
- Legacy work-order creation with `ticket_number` still supported.
- Existing inventory tests continue to pass.
- Existing use-part and profit endpoints unchanged in path and core behavior.

### Runtime Schema Compatibility
- `ensure_schema_compatibility()` now auto-adds newly required columns/tables for existing DB files.
- Avoids breaking old SQLite/PostgreSQL databases during startup.

---

## 5) API Additions and Compatibility Map

### Existing required APIs (kept)
- `POST /api/work-orders`
- `POST /api/work-orders/{id}/use-part`
- `GET /api/work-orders/{id}/profit`

### New APIs added
- `POST /api/qc-pictures`
- `GET /api/qc-pictures`
- `POST /api/job-status`
- `GET /api/job-status`
- `POST /api/return-equipments`
- `GET /api/return-equipments`

### Compatibility behavior in `POST /api/work-orders`
- Accepts either `ticket_number` or `wo_number`.
- Auto-populates missing paired alias field.

---

## 6) Verification Status

Validation completed:
- Backend tests: pass (`pytest`)
- Lint diagnostics: no new issues

Conclusion:
- Migration upgrade is applied with AppSheet-compatible schema extensions and without breaking existing core logic.

---

## 7) Authenticated Engineer Claims (`20260711_0018`)

Added `user_devices` with tenant/user ownership, a stable device ID, hashed device secret, revocation state, device name, and first/last seen timestamps.

Added to `work_orders`:

- `claimed_by_id`
- `claimed_at`
- `claimed_device_id`
- `claim_version`
- `completed_by_id`
- `completed_device_id`

The revision also adds foreign keys and indexes for claimant/completer lookup and organization claim/status filtering. All new work-order columns are nullable except the zero-default claim version, so existing work orders upgrade without forced assignment or false completion attribution.

New APIs:

- `POST /api/work-orders/{id}/claim`
- `POST /api/work-orders/{id}/release`
- `GET /api/work-orders?scope=all|mine|available`

Validation completed on SQLite with a full base-to-head upgrade, `0018 -> 0017` downgrade, and `0017 -> 0018` re-upgrade.

---

## 8) Replenishment Custody and Inventory Movements (`20260711_0019`)

Added to `replenishment_requests`:

- source notification and target engineer links;
- organization-scoped `client_request_id` and `request_reason` for idempotent manual vehicle requests;
- a monotonically increasing workflow `version`;
- `requires_reconciliation` for legacy rows without trustworthy custody evidence;
- picker, shipper, receiver, receiving device, completer, and canceller attribution;
- server timestamps for every custody transition;
- cancellation reason;
- shipment and receipt inventory transaction IDs.

Added to `inventory_transactions`:

- `replenishment_request_id`;
- `movement_stage` (`ship` or `receive`);
- a unique request/stage constraint that prevents duplicate movement posting during retries.

The migration also formalizes `warehouses.warehouse_type`, converts existing engineer-owned warehouses to `van`, adds organization/status and organization/target/status indexes, enforces one request per notification and one manual `client_request_id` per organization, and adds quantity/version/status checks plus unique shipment/receipt transaction links.

Legacy rows labelled `picking`, `shipped`, `received`, or `completed` are marked `requires_reconciliation`. The three intermediate labels are reopened as `requested`; `completed` remains completed for an administrator to explicitly accept as historical or leave blocked for further investigation. Normal custody actions are blocked while the flag remains set.

Workflow behavior:

```text
requested → picking → shipped → received → completed
```

- `picking` reserves the requested source quantity when available stock is calculated.
- `shipped` posts a linked `OUTBOUND` transaction from the source warehouse.
- `received` posts a linked `INBOUND` transaction to the destination vehicle and records the engineer and registered device.
- `completed` closes the task and resolves its originating low-stock notification.
- Cancellation is limited to `requested` or `picking`, requires a reason, and resolves the source notification to avoid recreating a cancelled request loop.

New APIs:

- `POST /api/inventory/replenishment-requests` for an idempotent manual assigned-vehicle request with `client_request_id` and reason
- `GET /api/inventory/replenishment-requests`
- `POST /api/inventory/replenishment-requests/{id}/actions`
- `POST /api/inventory/replenishment-requests/{id}/reconcile`
- `GET /api/inventory/my-van`

The former generic replenishment status PATCH now returns `410`. Action requests send `expected_version`; a stale version or invalid transition returns `409` without changing custody or inventory state.

Reconciliation is administrator-only and requires a matching version, a reason, and current-password verification. `reset_requested` is valid for a reopened requested row; `accept_historical` is valid for a legacy completed row. Rows with linked inventory movements cannot use historical reconciliation. Downgrade from `0019` is also blocked while any linked replenishment movement exists, preventing the migration from discarding ledger-to-custody references.

Runtime inventory safeguards added with this revision:

- SQLite connections enable `PRAGMA foreign_keys=ON` and a five-second busy timeout.
- SQLite inventory-affecting custody writes acquire `BEGIN IMMEDIATE` before reading available stock or changing state; PostgreSQL uses row locks.
- An engineer-owned warehouse is treated as a vehicle even if legacy metadata is stale, and new engineer-owned warehouses are normalized to `van`.
- A vehicle cannot be a replenishment source.
- Generic inventory transactions reject every vehicle source/destination; opening-inventory preview and commit also reject vehicles.
- The generic transaction API accepts only `INBOUND`, `OUTBOUND`, `TRANSFER`, and `DAMAGE`. `RETURN` and `WORK_ORDER_USED` require their authenticated business workflows.

Verification:

- Full backend suite: 66 passed.
- Replenishment custody/security: 14 targeted tests passed.
- File-backed SQLite contention: 2 targeted tests passed.
- Fresh base-to-`0019`, empty `0019 → 0018 → 0019`, and legacy compatibility database-to-`0019` migration paths passed.
- Linked-movement downgrade was rejected before any downgrade DDL executed.
- Frontend upgraded to Next.js 16.2.10 and ESLint 9; lint and the production build passed for all 26 static routes.
- npm dependency installation/audit resolved to 0 known vulnerabilities; PostCSS is pinned to the patched 8.5.17 release.

## 20260712_0020 - Authenticated vehicle return custody

Added `vehicle_return_requests` and the strict reverse logistics chain `requested -> approved -> shipped -> received`.

- Engineers create returns only from their own assigned vehicle and registered device.
- Warehouse/admin approval reserves the vehicle quantity.
- Only the same engineer can confirm handover, using the bound device and current password; this posts `return_ship` vehicle `OUTBOUND`.
- Warehouse/admin receipt validates the linked shipment and posts `return_receive` warehouse `INBOUND` with the same cost.
- Cancellation is allowed only before handover and releases approved reservations.
- Unique client request IDs, workflow versions, transaction stages, tenant indexes, and audit events make retries and concurrent requests safe.
- Generic `RETURN` remains disabled; all return mutations are online-only.
- Downgrade is blocked while linked vehicle-return movements exist.

Verification: full backend suite 70 passed, vehicle custody target suite 18 passed, migration base-to-`0020` and empty `0020 -> 0019 -> 0020` passed, ESLint passed, and the Next.js production build generated all 26 static routes.

## 20260712_0021 - Auditable inventory counts

- Adds tenant-scoped count sessions and lines with actor timestamps and optimistic versions.
- Submission records book snapshots; administrator approval recalculates current book stock and posts one uniquely linked adjustment per non-zero variance.
- Administrator password reauthentication is required before ledger changes. Managers remain read-only and vehicle warehouses are excluded.
- Downgrade is blocked while approved count adjustment movements exist.
