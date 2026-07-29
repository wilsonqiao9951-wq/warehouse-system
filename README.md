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

On a clean `main` branch the script first checks GitHub and applies a fast-forward update. Dirty worktrees and offline starts keep the local version. Alembic migrations run automatically before either service is launched.

## API Migration Notes

- `POST /api/work-orders/{id}/use-part` is the recommended endpoint for work-order part usage.
- `GET /api/work-orders/{id}/part-recommendations` ranks tenant-scoped completed-job evidence by machine, job type, fault, error code, symptoms, outcome success, repair time, and current stock location. See [`docs/PART_RECOMMENDATION_RANKING.md`](docs/PART_RECOMMENDATION_RANKING.md).
- `POST /api/parts/recognition/candidates` stores a validated part photo and creates review-only candidates from label, machine, photo-memory, and completed-job signals.
- `POST /api/parts/recognition/candidates/{id}/actions` enforces employee confirmation, administrator confirmation, actual-usage verification, and trusted promotion without changing inventory. See [`docs/VISUAL_RECOGNITION_WORKFLOW.md`](docs/VISUAL_RECOGNITION_WORKFLOW.md).
- `GET /api/machine-knowledge` gives every operational role tenant-scoped published machine guidance; managers curate drafts and administrators publish/archive entries through the governed endpoints documented in [`docs/MACHINE_KNOWLEDGE_BASE.md`](docs/MACHINE_KNOWLEDGE_BASE.md).
- `POST /api/machine-knowledge/{id}/drafts/from-work-order` creates review-only fault, repair, and used-part drafts without duplicating prior captures.
- `POST /api/machine-knowledge/{id}/media` stores validated field photos/videos outside the public upload mount; `GET /api/machine-knowledge/media/{entry_id}` enforces tenant, role, profile, and publication state.
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
```

PostgreSQL example:

```text
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/openpartsflow
```

## Database Migrations (Alembic)

- Current schema head: `20260728_0026` (governed work-order and media knowledge capture).
- New database (recommended):
  - `alembic upgrade head`
- Existing database already created by previous app versions:
  - `alembic stamp head`
  - then use `alembic upgrade head` for future migrations
- Create a new migration:
  - `alembic revision -m "your message"`

## Default Database

The default development database is SQLite:

```text
openpartsflow.db
```

You can switch to PostgreSQL later by editing `app/core/config.py`.
