# OpenPartsFlow RBAC API Mapping

## Objective

This document converts role requirements into an API-level enforcement matrix for implementation.

Roles:
- `technician`
- `manager`
- `warehouse`
- `admin`

Policy keywords:
- `Allow`
- `Deny`
- `Scoped` (only own assignments/ownership scope)

---

## 1) Work Orders Domain

### `GET /api/work-orders`
- technician: `Scoped` (assigned only)
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

Scope filter:
- `work_orders.assigned_user_id == current_user.id` OR `work_orders.engineer_id == current_user.id`

### `POST /api/work-orders`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `PATCH /api/work-orders/{work_order_id}`
- technician: `Scoped` (limited editable fields)
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

Technician allowed fields:
- `status`
- `description`/`problem_description` updates only if needed by operation policy

Technician denied fields:
- `revenue`
- `labor_cost`
- assignment changes

### `GET /api/work-orders/{work_order_id}/profit`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `POST /api/work-orders/{work_order_id}/use-part`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Scoped` (when tied to approved WO operation flow)
- admin: `Allow`

Scope filter:
- Technician can only use parts on assigned work orders.

### `GET /api/work-order-parts`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Scoped` (operational view)
- admin: `Allow`

---

## 2) Job Status / QC / Return Equipment

### `POST /api/job-status`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `GET /api/job-status`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Scoped`
- admin: `Allow`

### `POST /api/qc-pictures`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `GET /api/qc-pictures`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Scoped`
- admin: `Allow`

### `POST /api/return-equipments`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `GET /api/return-equipments`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Scoped`
- admin: `Allow`

---

## 3) Inventory Domain

### `GET /api/parts`
- technician: `Scoped` (only parts needed for assigned jobs / van operations)
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

### `POST /api/parts`
- technician: `Deny`
- manager: `Allow` (optional by company policy)
- warehouse: `Allow`
- admin: `Allow`

### `GET /api/inventory/balances`
- technician: `Deny` (full warehouses)
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

### `GET /api/employees/{user_id}/van-inventory`
- technician: `Scoped` (own only)
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

Technician scope:
- `user_id == current_user.id`

### `POST /api/inventory/transactions`
- technician: `Deny` (except part usage flow)
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

### `GET /api/inventory/transactions`
- technician: `Deny` (or Scoped if needed by policy)
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

---

## 4) People and Performance

### `GET /api/users`
- technician: `Deny` (or limited directory endpoint in future)
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `POST /api/users`
- technician: `Deny`
- manager: `Deny`
- warehouse: `Deny`
- admin: `Allow`

### `GET /api/dashboard/engineers/{user_id}`
- technician: `Scoped` (self only)
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

---

## 5) Exports and Excel Sync

### `GET /api/export/inventory.xlsx`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

### `GET /api/export/parts.xlsx`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Allow`
- admin: `Allow`

### `GET /api/export/work-orders.xlsx`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

### `POST /api/import/parts.xlsx`
- technician: `Deny`
- manager: `Allow` (optional by policy)
- warehouse: `Allow`
- admin: `Allow`

### `POST /api/import/work-orders.xlsx`
- technician: `Deny`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

---

## 6) Uploads

### `POST /api/uploads/work-order-parts`
- technician: `Scoped`
- manager: `Allow`
- warehouse: `Deny`
- admin: `Allow`

Scope:
- Upload must be attached to allowed work order context when used.

---

## 7) Enforcement Strategy

1. JWT/session carries:
- `user_id`
- `role`
- optional scoped warehouse IDs / team IDs

2. Backend authorization layers:
- Route-level role checks
- Query-level data scoping (critical for technician scope)
- Field-level update restrictions for sensitive attributes

3. Frontend guardrails:
- Hide disallowed menus/pages
- Prevent forbidden actions in UI
- Never rely on frontend-only restriction

4. Audit requirements:
- Log denied access attempts
- Log sensitive updates (`revenue`, `labor_cost`, assignment changes, inventory transactions)

---

## 8) Phase 1 RBAC Acceptance Criteria

- Technician cannot access company-wide data through any API path.
- Manager has complete operations visibility and profit/performance access.
- Warehouse can execute full inventory operations without profit/payroll exposure.
- Admin has full platform control.
- All scoped endpoints validated by automated tests (positive + negative cases).
