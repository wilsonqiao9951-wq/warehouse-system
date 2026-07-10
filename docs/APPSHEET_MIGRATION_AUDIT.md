# OpenPartsFlow AppSheet Migration Audit

## Scope and Objective

This document defines the migration audit baseline for moving from Google AppSheet to OpenPartsFlow.

Primary rule:
- Phase 1 must fully preserve current company operations and all critical AppSheet workflows before any optimization rollout.

---

## 1) Existing AppSheet Feature Checklist

Status legend:
- `Implemented`: Exists in current OpenPartsFlow backend/frontend
- `Partial`: Exists but not yet end-to-end complete or needs validation
- `Missing`: Not implemented yet
- `Unknown`: Depends on current AppSheet behavior not yet captured

### Master Data
- `Implemented` User directory (name, contact, role)
- `Implemented` Warehouse master
- `Implemented` Parts master (part number, unit, default cost, safety stock)
- `Unknown` Supplier master and supplier-part pricing history
- `Unknown` Store/customer master and service contract linkage

### Work Order Operations
- `Implemented` Create work order
- `Implemented` Assign engineer
- `Implemented` Update status
- `Implemented` Input revenue
- `Partial` Work order details parity (address/problem fields exist; AppSheet field parity pending)
- `Partial` Work order photo evidence (photo upload exists for part usage; full work-order-level media workflow pending)
- `Unknown` AppSheet automation rules (auto status transitions, reminders, escalations)

### Parts Usage and Inventory
- `Implemented` Use part on work order
- `Implemented` Auto inventory deduction on part usage
- `Implemented` Inventory transaction table and API
- `Implemented` Inventory balance API
- `Implemented` Van inventory view per employee
- `Partial` Full transaction ledger UI (backend available, dedicated frontend ledger page pending)
- `Unknown` Physical inventory count cycle workflows and approval process

### Analytics and Controls
- `Implemented` Work order profit calculation API
- `Implemented` Employee performance baseline (open/completed workload)
- `Implemented` Low stock signal in stock balance
- `Missing` Abnormal parts usage detection
- `Unknown` Existing AppSheet KPI formulas and dashboard definitions

### Export / Integration
- `Implemented` Inventory Excel export
- `Unknown` Any AppSheet external integrations (Google Sheets, Gmail, webhook, ERP sync)
- `Unknown` Existing reporting schedule/distribution requirements

---

## 2) Required Data Tables

Minimum required to preserve current operations:

1. `users`
2. `warehouses`
3. `parts`
4. `work_orders`
5. `work_order_parts`
6. `inventory_transactions`

Recommended additional tables for enterprise migration safety:

7. `attachments` (generic file metadata, links to entities)
8. `audit_logs` (who changed what and when)
9. `alerts` (low stock, abnormal usage, SLA)
10. `kpi_snapshots` (pre-aggregated daily metrics)
11. `roles_permissions` (if role model grows beyond enum)
12. `appsheet_id_mapping` (source-to-target row ID mapping for traceability)

---

## 3) Suggested Database Schema

Current schema is a strong base. Suggested migration-ready shape:

### Core Entities
- `users(id, name, email, phone, role, created_at, updated_at)`
- `warehouses(id, name, location, assigned_user_id, created_at, updated_at)`
- `parts(id, part_number, name, english_name, machine_type, unit, default_cost, safety_stock, supplier, image_url, notes, created_at, updated_at)`
- `work_orders(id, ticket_number, store_name, address, machine_type, problem_description, assigned_user_id, engineer_id, assistant_id, revenue, labor_cost, status, created_at, updated_at)`
- `work_order_parts(id, work_order_id, part_id, warehouse_id, user_id, quantity, unit_cost, installed, old_part_returned, notes, created_at, updated_at)`
- `inventory_transactions(id, part_id, transaction_type, quantity, from_warehouse_id, to_warehouse_id, work_order_id, user_id, unit_cost, notes, created_at, updated_at)`

### Recommended Additions
- `attachments(id, entity_type, entity_id, file_url, file_name, content_type, uploaded_by, created_at)`
  - Supports photos for work orders, part usage, inventory incidents.
- `alerts(id, alert_type, severity, entity_type, entity_id, payload_json, status, created_at, resolved_at, resolved_by)`
  - For low stock and abnormal usage.
- `audit_logs(id, actor_user_id, action, entity_type, entity_id, before_json, after_json, created_at)`
  - Essential for AppSheet parity in traceability.

### Suggested Indexes
- `parts(part_number)` unique
- `work_orders(ticket_number)` unique
- `work_orders(status, assigned_user_id, created_at)`
- `work_order_parts(work_order_id, part_id, created_at)`
- `inventory_transactions(part_id, created_at)`
- `inventory_transactions(work_order_id, created_at)`
- `inventory_transactions(from_warehouse_id, to_warehouse_id, created_at)`

---

## 4) Feature Mapping

AppSheet feature -> OpenPartsFlow module -> API endpoint -> frontend page

1. Work order create/dispatch
- AppSheet feature: Create and assign service jobs
- OpenPartsFlow module: Work Orders
- API endpoint:
  - `POST /api/work-orders`
  - `PATCH /api/work-orders/{work_order_id}`
  - `GET /api/work-orders`
- Frontend page: `frontend/app/work-orders/page.tsx`

2. Parts consumption on service ticket
- AppSheet feature: Record used part and quantity
- OpenPartsFlow module: Parts Usage
- API endpoint:
  - `POST /api/work-orders/{work_order_id}/use-part`
  - `GET /api/work-order-parts`
- Frontend page: `frontend/app/parts-usage/page.tsx`

3. Photo evidence for parts usage
- AppSheet feature: Capture photo in field
- OpenPartsFlow module: Uploads + Parts Usage
- API endpoint:
  - `POST /api/uploads/work-order-parts`
- Frontend page: `frontend/app/parts-usage/page.tsx`

4. Inventory stock visibility
- AppSheet feature: Check current stock
- OpenPartsFlow module: Inventory
- API endpoint:
  - `GET /api/inventory/balances`
- Frontend page: `frontend/app/inventory/page.tsx`

5. Van inventory check
- AppSheet feature: Engineer vehicle stock lookup
- OpenPartsFlow module: Inventory / Employee van stock
- API endpoint:
  - `GET /api/employees/{user_id}/van-inventory`
- Frontend page: `frontend/app/inventory/page.tsx`

6. Staff and role view
- AppSheet feature: Employee role and workload
- OpenPartsFlow module: Employees
- API endpoint:
  - `GET /api/users`
  - `GET /api/dashboard/engineers/{user_id}`
- Frontend page: `frontend/app/employees/page.tsx`

7. Profit and KPI dashboard
- AppSheet feature: Basic management metrics
- OpenPartsFlow module: Dashboard
- API endpoint:
  - `GET /api/work-orders`
  - `GET /api/work-orders/{work_order_id}/profit`
- Frontend page: `frontend/app/page.tsx`

8. Inventory export
- AppSheet feature: Export stock report
- OpenPartsFlow module: Export
- API endpoint:
  - `GET /api/export/inventory.xlsx`
- Frontend page: Not yet linked in current UI (backend ready)

9. Inventory ledger transactions
- AppSheet feature: Inbound/outbound/transfer logs
- OpenPartsFlow module: Inventory Transactions
- API endpoint:
  - `POST /api/inventory/transactions`
  - `GET /api/inventory/transactions`
- Frontend page: Not yet linked in current UI (backend ready)

---

## 5) Missing Information We Need from AppSheet

Critical migration inputs not yet available:

1. Full AppSheet table list and column dictionary
2. Enum values and validation rules per field
3. Key formulas (virtual columns, computed expressions)
4. Automation bots/workflows (triggers, emails, reminders)
5. Security filters and role-based row visibility
6. Current app navigation and user-role UX differences
7. Attachment storage behavior (where files live, retention policy)
8. Historical data volume (row counts per table, attachment size)
9. Data quality issues currently known by operations team
10. Existing KPI definitions used by management
11. Required audit/compliance fields for every transaction
12. Integration dependencies (Google Sheets, external systems)

Without these, parity verification is incomplete.

---

## 6) MVP Migration Plan

### Step A: Discovery and Freeze
- Export AppSheet metadata and data dictionary.
- Freeze critical process definitions with operations leads.
- Define parity acceptance criteria per feature.

### Step B: Data and Schema Alignment
- Map AppSheet tables/columns to OpenPartsFlow schema.
- Add missing tables/columns needed for parity.
- Build `appsheet_id_mapping` for traceable migration.

### Step C: API Parity Completion
- Confirm all AppSheet create/update/read workflows have API coverage.
- Add missing endpoints for any uncovered operational path.

### Step D: UI Parity Completion
- Ensure each role can complete existing AppSheet tasks in OpenPartsFlow.
- Add any missing forms, filters, and export actions.

### Step E: Parallel Run
- Run AppSheet and OpenPartsFlow in parallel for 1-2 cycles.
- Compare key output: stock balances, used-part logs, daily work orders.

### Step F: Cutover
- Freeze AppSheet writes.
- Run final migration sync.
- Go-live OpenPartsFlow with rollback plan documented.

---

## 7) Phase 1 Requirement: Preserve Existing Company Operations

Phase 1 is strictly "parity-first":

- No operational flow may be removed before replacement is validated.
- Every current AppSheet critical user journey must be executable in OpenPartsFlow.
- Data output consistency required:
  - Work orders
  - Parts usage
  - Inventory balances
  - Core operational reporting
- Parallel run sign-off must come from operations owner and warehouse owner.
- Rollback path must exist during initial production period.

Phase 1 acceptance gate:
- "Can operate business without AppSheet" confirmed by real users for all core roles.

---

## 8) Phase 2 Improvements

After Phase 1 sign-off, release improvements in controlled increments:

1. Inventory transaction ledger
- Dedicated ledger UI with filters (part, warehouse, date, type, user)
- Reconciliation report and discrepancy drill-down

2. Van inventory
- Van transfer workflows and rebalance recommendations
- Engineer-level consumption trends

3. Work order profit calculation
- Persisted daily profit snapshots
- Profit ranking by region, engineer, machine type

4. Employee performance
- Multi-metric scorecard (throughput, completion, parts efficiency)
- Role-specific dashboards (manager vs engineer)

5. Low stock alert
- Rule engine with threshold overrides per warehouse/part
- Alert acknowledgment and closure workflow

6. Abnormal parts usage detection
- Baseline model by ticket type/machine/store
- Flag anomalies (quantity spikes, unusual part combinations, off-hour usage)
- Add review queue for manager validation

---

## 9) Role-Based Pages and Permissions

The new system must enforce role-based page visibility and data access separation for technicians, managers, warehouse users, and admins.

### 9.1 Technician

Technician should only see:
- Today's assigned work orders
- Calendar of own assigned jobs
- Road map for own route
- Work order detail
- Add job status update
- Add parts used
- Add QC pictures
- Add returned equipment
- View own van inventory

Technician should NOT see:
- Company-wide profit
- All employee performance
- Inventory cost
- Other technicians' jobs unless assigned
- Admin settings
- Payroll/labor cost
- Full warehouse inventory

### 9.2 Manager

Manager should see:
- All work orders
- All technicians' schedules
- All road map routes
- All inventory warehouses
- Main warehouse and van inventories
- Parts usage by work order
- QC pictures
- Returned equipment
- Job status history
- Revenue
- Labor cost
- Work order profit
- Employee performance
- Low stock alerts
- Abnormal parts usage alerts
- Export reports

### 9.3 Warehouse User

Warehouse user should see:
- Parts list
- Inventory balance
- Inbound inventory
- Outbound inventory
- Transfer inventory
- Low stock alerts
- Inventory transaction ledger

Warehouse user should NOT see:
- Company profit
- Employee payroll/labor cost
- Business analytics unless manager permission is granted

### 9.4 Admin

Admin can see and manage everything:
- Users
- Roles
- Permissions
- Company settings
- All work orders
- All inventory
- All analytics
- Billing/SaaS settings in future

### 9.5 Permission Matrix

`Y` = allowed, `N` = not allowed, `Scoped` = allowed but only within own scope/assignments.

| Feature | Technician | Manager | Warehouse | Admin |
|---|---|---|---|---|
| View own work orders | Y | Y | N | Y |
| View all work orders | N | Y | N | Y |
| Create work order | N | Y | N | Y |
| Edit work order | Scoped | Y | N | Y |
| Update job status | Scoped | Y | N | Y |
| Add parts used | Scoped | Y | Scoped | Y |
| View part cost | N | Y | Y | Y |
| View own van inventory | Y | Y | N | Y |
| View all warehouse inventory | N | Y | Y | Y |
| Transfer parts | N | Y | Y | Y |
| Add QC pictures | Scoped | Y | N | Y |
| View QC pictures | Scoped | Y | Scoped | Y |
| Add returned equipment | Scoped | Y | N | Y |
| View profit | N | Y | N | Y |
| View employee performance | N | Y | N | Y |
| Export reports | N | Y | Scoped | Y |
| Manage users | N | N | N | Y |
| Manage system settings | N | N | N | Y |

Implementation notes for Phase 1:
- UI route guards and backend authorization must both enforce this matrix.
- "Scoped" permissions must always filter by `assigned_user_id` or relevant ownership relation.
- Any cross-role exception requires explicit admin-granted permission and audit logging.

---

## 10) Mobile App UX Design

The new OpenPartsFlow app must feel like a real mobile app, not a desktop website.

Design principle:
- Mobile-first, role-focused flows with fast field operations and minimal typing.

### 10.1 Technician Mobile App

Bottom navigation tabs:
- Today
- Map
- Calendar
- Jobs
- Inventory

#### Technician Today Page
- Show today's assigned jobs
- Job card includes:
  - WO number
  - Outlet name
  - Job type
  - City
  - Scheduled time
  - Priority
- Quick buttons on each card:
  - Navigate
  - Call
  - Start Job
  - Complete Job

#### Technician Work Order Detail Page

Sections:
- Job Summary
- Customer Contact
- Address with map button
- Job Description
- Status Timeline
- Parts Used
- QC Pictures
- Returned Equipment
- Notes

#### Technician Job Flow
- Open assigned job
- Tap Start Job
- Add status update
- Add parts used
- Upload QC pictures
- Add returned equipment if needed
- Tap Complete Job

#### Technician Inventory Page
- Show only own van inventory
- Search parts
- Low stock warning
- Request parts from warehouse

---

### 10.2 Manager Mobile App

Bottom navigation tabs:
- Dashboard
- Jobs
- Map
- Inventory
- Reports

#### Manager Dashboard
- Today's jobs
- Completed jobs
- Pending jobs
- Revenue
- Profit
- Low stock alerts
- Abnormal usage alerts

#### Manager Jobs Page
- View all jobs
- Filter by technician, status, date, city
- Assign technician
- Edit revenue and labor cost
- View profit

#### Manager Inventory Page
- View main warehouse
- View all van inventories
- Transfer parts between warehouse and vans
- See inventory transaction ledger

#### Manager Reports Page
- Employee performance
- Parts usage
- Job profit
- Export CSV

---

### 10.3 UI Requirements

- Mobile-first layout
- Large buttons for field use
- Card-based job list
- Sticky bottom navigation
- Quick actions on job cards
- Minimal typing
- Use dropdowns, scan/search, and photo upload
- Support dark mode later
- Should work well on iPhone screen size

---

### 10.4 Screen-by-Screen Feature Mapping

| Screen | User Role | Purpose | Data Tables | Required APIs |
|---|---|---|---|---|
| Technician: Today | Technician | See today's assigned jobs and take quick actions | `work_orders`, `users` | `GET /api/work-orders` (scoped), `PATCH /api/work-orders/{id}` |
| Technician: Map | Technician | Navigate daily route for assigned jobs | `work_orders` | `GET /api/work-orders` (scoped) |
| Technician: Calendar | Technician | View personal schedule by date/time | `work_orders`, `job_status` | `GET /api/work-orders` (scoped), `GET /api/job-status?work_order_id=` |
| Technician: Jobs | Technician | Browse own assigned jobs list and open details | `work_orders` | `GET /api/work-orders` (scoped) |
| Technician: Inventory | Technician | View own van stock and request replenishment | `inventory_transactions`, `parts`, `warehouses` | `GET /api/employees/{user_id}/van-inventory`, `GET /api/parts` |
| Technician: Work Order Detail | Technician | Execute full field workflow from start to complete | `work_orders`, `job_status`, `work_order_parts`, `qc_pictures`, `return_equipments` | `GET /api/work-orders`, `POST /api/job-status`, `GET /api/job-status`, `POST /api/work-orders/{id}/use-part`, `GET /api/work-order-parts`, `POST /api/qc-pictures`, `GET /api/qc-pictures`, `POST /api/return-equipments`, `GET /api/return-equipments` |
| Manager: Dashboard | Manager | Monitor operations KPIs and risk alerts | `work_orders`, `work_order_parts`, `inventory_transactions`, `parts` | `GET /api/work-orders`, `GET /api/work-orders/{id}/profit`, `GET /api/inventory/balances` |
| Manager: Jobs | Manager | Manage all work orders and assignment/profit inputs | `work_orders`, `users` | `GET /api/work-orders`, `PATCH /api/work-orders/{id}`, `GET /api/users` |
| Manager: Map | Manager | View all active routes and dispatch status | `work_orders`, `users` | `GET /api/work-orders`, `GET /api/users` |
| Manager: Inventory | Manager | Cross-warehouse and van inventory control | `warehouses`, `parts`, `inventory_transactions` | `GET /api/inventory/balances`, `GET /api/inventory/transactions`, `POST /api/inventory/transactions`, `GET /api/warehouses` |
| Manager: Reports | Manager | Analyze performance and export operational reports | `work_orders`, `work_order_parts`, `inventory_transactions`, `users` | `GET /api/export/work-orders.xlsx`, `GET /api/export/inventory.xlsx`, `GET /api/work-orders/{id}/profit`, `GET /api/dashboard/engineers/{user_id}` |

Implementation note:
- Role-based API scoping must match screen visibility to prevent data leakage from mobile clients.

---

## Immediate Next Actions (Non-coding)

1. Conduct AppSheet discovery workshop and export metadata.
2. Build final AppSheet-to-OpenPartsFlow field mapping matrix.
3. Classify all current workflows into:
- Must-have for Phase 1 parity
- Candidate for Phase 2 enhancement
4. Draft UAT scripts for each role before cutover.
