# OpenPartsFlow

OpenPartsFlow is an open-source parts inventory and work-order usage tracking system for field service teams.

## Features

- Parts master data
- Warehouse / van inventory locations
- Inventory transactions
- Employee parts assignment
- Work order parts usage
- Shared engineer work-order pool with atomic claiming
- Account- and registered-device-bound field execution
- Password re-verification and exact engineer/device completion attribution
- Structured work-order learning data for faults, outcomes, first-time fix, rework, and server-measured duration
- Governed machine service knowledge with published faults, repair steps, tools, cautions, media, and verified field evidence
- Idempotent knowledge drafts generated from completed jobs plus tenant-protected field photo/video storage
- Explainable same-model fault analysis, published-guidance ranking, and similar completed-job retrieval on the mobile work-order screen
- Tenant-scoped AppSheet/REST API keys, configurable inbound work-order mapping, idempotent Webhooks, and synchronization logs
- Durable UTC monthly AI/API usage metering with plan limits, atomic concurrency enforcement, and idempotent external charging
- Verified customer domains, automatic host-based login branding, and domain-gated sender identity configuration
- Provider-neutral signed subscription events, ordered idempotent billing evidence, and durable lifecycle notices
- Tenant and platform commercial usage reports with password-confirmed, audited CSV export
- Tenant-scoped enterprise audit search, activity summaries, and password-confirmed hash-evidenced CSV export
- Minimal live/ready probes plus platform-only request, worker, integration, billing, and backup operations monitoring
- Role-compatible enterprise user access policies with explicit allow/deny/inherit overrides and complete audit evidence
- Tenant-scoped enterprise operations analytics with reconciled KPIs, quality coverage, regional stock, and audited CSV export
- Read-only enterprise operations Agent with bounded intents, source-defined evidence, quota control, and privacy-preserving run audit
- Tenant-isolated portable ZIP backups with secret redaction, media manifests, and durable SHA-256 evidence
- Controlled restore rehearsal, safe record/media recovery, exact-plan application, and drift-protected rollback
- Auditable replenishment custody from warehouse picking through engineer vehicle receipt
- Manager/administrator replenishment approval with rejection evidence before warehouse picking
- Reserved picking stock with separate shipment OUTBOUND and receipt INBOUND inventory movements
- Idempotent manual first-fill replenishment for newly assigned engineer vehicles
- Vehicle inventory isolation from generic transactions and opening-stock imports
- Authenticated vehicle-to-warehouse return custody with reservation and engineer handover
- Auditable inventory counts with administrator-approved, ledger-linked adjustments
- Validated warehouse → shelf/bin → part scanning with stale-label and cross-warehouse protection
- Real-time inventory balance
- Excel export

## Quick Start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m scripts.prepare_database
uvicorn app.main:app --reload
```

Open API docs:

```text
http://127.0.0.1:8000/docs
```

## Frontend Admin Dashboard (Next.js)

The project now includes a Next.js admin dashboard at `frontend/` with:

- Dashboard metrics (total jobs, total revenue, total profit)
- Work orders management (create job, assign engineer, revenue, status)
- Parts usage UI (select part, quantity, auto inventory deduction)
- Inventory views (warehouse stock and van inventory)
- Warehouse replenishment queue with server-authorized picking, shipping, and completion actions
- Engineer My Van deliveries with registered-phone and password-verified receipt
- Employee page (roles and performance overview)
- Enterprise analytics page with UTC period, engineer, and job-type filters
- Enterprise operations Agent with preset questions, priority findings, guardrails, and digest-only run history

Run frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

The frontend uses Next.js 16.2.12 and requires Node.js 20.9 or newer.

Default frontend URL:

```text
http://127.0.0.1:3000
```

### One-command local start (Windows PowerShell)

From project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-dev.ps1
```

This opens two terminals:

- Backend: `http://127.0.0.1:8000`
- Frontend: `http://localhost:3000`

On a clean `main` branch the script first checks GitHub and applies a fast-forward update. Dirty worktrees and offline starts keep the local version. Database preparation runs before either service is launched: versioned databases receive Alembic migrations, while an unversioned legacy SQLite database is backed up, rebuilt, verified, and adopted automatically. Any failed safety check stops startup. See [`docs/LEGACY_DATABASE_ADOPTION.md`](docs/LEGACY_DATABASE_ADOPTION.md).

## API Migration Notes

- `POST /api/work-orders/{id}/use-part` is the recommended endpoint for work-order part usage.
- `GET /api/work-orders/{id}/part-recommendations` ranks tenant-scoped completed-job evidence by machine, job type, fault, error code, symptoms, outcome success, repair time, and current stock location. See [`docs/PART_RECOMMENDATION_RANKING.md`](docs/PART_RECOMMENDATION_RANKING.md).
- `POST /api/parts/recognition/candidates` stores a validated part photo and creates review-only candidates from label, machine, photo-memory, and completed-job signals.
- `POST /api/parts/recognition/candidates/{id}/actions` enforces employee confirmation, administrator confirmation, actual-usage verification, and trusted promotion without changing inventory. See [`docs/VISUAL_RECOGNITION_WORKFLOW.md`](docs/VISUAL_RECOGNITION_WORKFLOW.md).
- `GET /api/machine-knowledge` gives every operational role tenant-scoped published machine guidance; managers curate drafts and administrators publish/archive entries through the governed endpoints documented in [`docs/MACHINE_KNOWLEDGE_BASE.md`](docs/MACHINE_KNOWLEDGE_BASE.md).
- `POST /api/machine-knowledge/{id}/drafts/from-work-order` creates review-only fault, repair, and used-part drafts without duplicating prior captures.
- `POST /api/machine-knowledge/{id}/media` stores validated field photos/videos outside the public upload mount; `GET /api/machine-knowledge/media/{entry_id}` enforces tenant, role, profile, and publication state.
- `GET /api/work-orders/{id}/service-intelligence` returns read-only, tenant-scoped fault metrics, ranked published exact-model guidance, and explained similar completed jobs. See [`docs/SERVICE_INTELLIGENCE.md`](docs/SERVICE_INTELLIGENCE.md).
- `POST /api/external/v1/work-orders` accepts API-key-authenticated, idempotent AppSheet/REST work-order intake. Administrators manage credentials and mappings under `/api/integrations`; see [`docs/EXTERNAL_INTEGRATIONS.md`](docs/EXTERNAL_INTEGRATIONS.md).
- `POST /api/organization/data-exports` creates a password-confirmed tenant backup ZIP with JSONL records, referenced local evidence files, secret redaction, and a checksum manifest; see [`docs/CUSTOMER_DATA_EXPORTS.md`](docs/CUSTOMER_DATA_EXPORTS.md).
- `POST /api/organization/data-restores/rehearsals` validates a backup and records a dry-run before separate approval, exact-archive application, and rollback; see [`docs/CONTROLLED_DATA_RESTORES.md`](docs/CONTROLLED_DATA_RESTORES.md).
- `GET /api/audit-logs/search` and `/summary` require effective `audit.read`; password-confirmed `POST /api/audit-logs/export` requires `audit.export` and returns a formula-safe, SHA-256-recorded CSV. See [`docs/AUDIT_LOGS.md`](docs/AUDIT_LOGS.md).
- `GET /health/live` and `/health/ready` provide minimal orchestration probes; platform administrators use `GET /api/platform/operations/summary` and `/platform/operations` for live SLA-operability evidence. See [`docs/OPERATIONS_MONITORING.md`](docs/OPERATIONS_MONITORING.md).
- `GET /api/permissions/me` resolves role defaults and administrator-issued user overrides; the administrator matrix is documented in [`docs/ENTERPRISE_ACCESS_POLICIES.md`](docs/ENTERPRISE_ACCESS_POLICIES.md).
- `GET /api/analytics/operations` returns reconciled work-order, service-quality, contribution, and regional-inventory metrics; password-confirmed `POST /api/analytics/operations/export` creates a formula-safe, digest-evidenced CSV. See [`docs/ENTERPRISE_ANALYTICS.md`](docs/ENTERPRISE_ANALYTICS.md).
- `POST /api/agent/operations` runs a permission-controlled, read-only operating review over allowlisted tenant evidence and retains only digest-level question metadata. See [`docs/ENTERPRISE_OPERATIONS_AGENT.md`](docs/ENTERPRISE_OPERATIONS_AGENT.md).
- `POST /api/work-order-parts` is still available for backward compatibility but marked deprecated.
- `GET /api/inventory/replenishment-requests` returns the role-scoped replenishment queue and server-calculated action capabilities.
- `POST /api/inventory/replenishment-requests` creates a manual vehicle request with a required business reason and client-generated idempotency key.
- `POST /api/inventory/replenishment-requests/{id}/actions` advances the strict replenishment custody workflow using an `expected_version`.
- `POST /api/inventory/replenishment-requests/{id}/reconcile` lets an administrator resolve flagged legacy custody with a reason and password re-verification.
- `GET /api/inventory/my-van` returns only the authenticated engineer's assigned vehicle inventory.
- `POST /api/inventory/vehicle-returns` lets the authenticated engineer request a return from their own vehicle.
- `POST /api/inventory/vehicle-returns/{id}/actions` enforces warehouse approval, engineer password handover, and warehouse receipt.
- The former generic replenishment status PATCH is deprecated and returns `410`; clients must use the authenticated action endpoint.
- `POST /api/inventory/transactions` is limited to non-vehicle `INBOUND`, `OUTBOUND`, `TRANSFER`, and `DAMAGE`; vehicle, `RETURN`, and `WORK_ORDER_USED` changes require their authenticated business workflows.
- Full custody contract: [`docs/REPLENISHMENT_CUSTODY_API.md`](docs/REPLENISHMENT_CUSTODY_API.md).
- Work-order profit response now uses:
  - `revenue`
  - `labor_cost`
  - `parts_cost`
  - `profit` (`revenue - labor_cost - parts_cost`)

## Excel Sync (Database <-> Excel)

Export:

- `GET /api/export/inventory.xlsx`
- `GET /api/export/parts.xlsx`
- `GET /api/export/work-orders.xlsx`

Import (`.xlsx` upload via `file` field):

- `POST /api/import/parts.xlsx`
- `POST /api/import/work-orders.xlsx`

Import behavior:

- Uses upsert strategy (create new, update existing by key).
- Parts key: `part_number`
- Work orders key: `ticket_number` / `wo_number` (AppSheet-compatible)
- Opening inventory accepts only non-vehicle warehouses. Vehicle stock enters through authenticated replenishment receipt, and leaves through authenticated work-order usage or a dedicated return workflow.

## Environment Configuration

Copy `.env.example` to `.env` and update values:

```text
APP_NAME=OpenPartsFlow
APP_ENV=development
APP_DEBUG=false
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///./openpartsflow.db
RBAC_ENFORCE=true
LEGACY_HEADER_AUTH=false
JWT_SECRET_KEY=<at least 32 random characters>
MAX_IMAGE_UPLOAD_BYTES=10485760
MAX_KNOWLEDGE_MEDIA_UPLOAD_BYTES=52428800
OPERATIONS_REQUEST_WINDOW_SECONDS=300
OPERATIONS_BACKUP_WARNING_DAYS=7
MAX_ANALYTICS_EXPORT_ROWS=100000
```

PostgreSQL example:

```text
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/openpartsflow
```

## Database Migrations (Alembic)

- Current schema head: `20260807_0045` (enterprise Agent run evidence).
- New database (recommended):
  - `alembic upgrade head`
- Existing database already created by previous app versions:
  - First run a read-only rehearsal: `python -m scripts.adopt_legacy_database --database ./openpartsflow.db`
  - Stop the backend, then apply: `python -m scripts.adopt_legacy_database --database ./openpartsflow.db --apply`
  - Never use `alembic stamp head` on an unversioned database; it can hide missing schema without creating it.
- Create a new migration:
  - `alembic revision -m "your message"`

## Default Database

The default development database is SQLite:

```text
openpartsflow.db
```

You can switch to PostgreSQL later by editing `app/core/config.py`.
