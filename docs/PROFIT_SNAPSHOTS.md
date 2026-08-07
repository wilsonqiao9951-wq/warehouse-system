# Persisted Work-Order Profit Snapshots

OpenPartsFlow records one tenant-scoped financial snapshot when a work order
first reaches `COMPLETED`. The snapshot is written in the same database
transaction as completion, so a locked work order cannot become complete
without its matching financial evidence.

## Evidence captured

- Completion date/time and ticket number
- Accountable engineer ID and historical display name
- Machine type
- Revenue, labor cost, installed-parts cost, profit, and source fingerprint
- Service-region attribution and the warehouse evidence used to choose it

Region attribution is deterministic: the highest-value actual parts-usage
warehouse wins, then the engineer's active vehicle region, then the tenant's
default region. Records with no valid source remain explicitly unattributed.
The fingerprint prevents a changed historical source from silently replacing a
previous snapshot.

## API and access

- `GET /api/analytics/profit-snapshots` requires effective `reports.read`, is
  tenant-scoped, returns `Cache-Control: no-store`, and supports a maximum
  366-day dashboard range.
- `POST /api/analytics/profit-snapshots/backfill` is limited to managers and
  administrators with `reports.read`, requires current-account password
  verification, scans at most 1,000 work orders per request, and records an
  audit event for every batch.

The dashboard reports completed-work-order coverage before presenting daily
profit and region, engineer, and machine-type rankings. Missing evidence is
never treated as zero profit. Backfill is idempotent; if source evidence no
longer matches an existing fingerprint, the old snapshot is retained and a
conflict is disclosed for review.

## Operations

The management workbench is `/profit-snapshots`. For a large historical
period, use its password-confirmed action; it follows the server cursor until
the selected period is complete. The `work_order_profit_snapshots` table is
included in tenant exports and PostgreSQL row-level security.
