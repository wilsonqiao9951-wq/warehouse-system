# OpenPartsFlow

OpenPartsFlow is an open-source parts inventory and work-order usage tracking system for field service teams.

## Features

- Parts master data
- Warehouse / van inventory locations
- Inventory transactions
- Employee parts assignment
- Work order parts usage
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
- Employee page (roles and performance overview)

Run frontend:

```bash
cd frontend
cp .env.example .env.local
npm install
npm run dev
```

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

## API Migration Notes

- `POST /api/work-orders/{id}/use-part` is the recommended endpoint for work-order part usage.
- `POST /api/work-order-parts` is still available for backward compatibility but marked deprecated.
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

## Environment Configuration

Copy `.env.example` to `.env` and update values:

```text
APP_NAME=OpenPartsFlow
APP_ENV=development
APP_DEBUG=false
LOG_LEVEL=INFO
DATABASE_URL=sqlite:///./openpartsflow.db
```

PostgreSQL example:

```text
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/openpartsflow
```

## Database Migrations (Alembic)

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
