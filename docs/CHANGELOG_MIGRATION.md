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
