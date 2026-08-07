# Enterprise operations analytics

OpenPartsFlow provides a tenant-scoped operating review at `/analytics`. The
dashboard reads the work-order, work-order-part, inventory-ledger, warehouse,
and region records that already drive operational workflows; it does not keep
a second reporting ledger.

## Access and filters

`GET /api/analytics/operations` requires effective `reports.read`. Managers and
organization administrators receive that permission by default, and an
administrator may delegate or deny it through the enterprise permission
matrix. Every source query includes the authenticated organization ID.

The report accepts an inclusive UTC `from_date` and `to_date`, an optional
engineer, and an optional job type. A range may contain at most 366 days. The
default is the latest 90 UTC days. The comparison period is the immediately
preceding range of the same length. Trend grain is selected automatically:

- day for 31 days or fewer;
- week for 32 through 180 days;
- month for 181 through 366 days.

Engineer attribution uses the completion actor first, then the assigned or
legacy engineer where completion attribution is unavailable. This preserves
historical compatibility without allowing a client to change completion
ownership.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Created work orders | Work orders whose server `created_at` is inside the selected UTC period. |
| Completed work orders | Work orders whose server `completed_at` is inside the selected UTC period. |
| Period-end backlog | Work orders created on or before the period end and not completed on or before it; currently cancelled rows are excluded. Historical cancellation timestamps are not available. |
| First-time-fix rate | `first_time_fix=true` divided by completed work orders that have a first-time-fix label. Unlabeled jobs are excluded and coverage is reported separately. |
| Rework rate | Completed work orders marked `is_rework=true` divided by all completed work orders. |
| Average repair hours | Mean server-recorded `repair_duration_minutes` among completed work orders with duration evidence. Coverage is reported separately. |
| Gross contribution | Work-order revenue minus labor cost minus the recorded total cost of parts used on completed work orders. This is not recognized revenue or accounting net income. |
| Regional stock | Current inventory-ledger quantity multiplied by each part's current default cost. It is a live balance, not a historical period-end snapshot. |
| Regional consumption | Recorded parts on work orders completed in the selected period, attributed to the region of the source warehouse. |

The response includes source-freshness timestamps and coverage for first-time
fix, repair duration, and engineer attribution. Coverage warnings are emitted
below the dashboard's declared thresholds so incomplete evidence is not hidden
behind an apparently precise rate.

## Export

`POST /api/analytics/operations/export` requires effective `reports.export`,
Bearer authentication, and the current account password. It exports one row per
filtered completed work order. The CSV:

- begins with a UTF-8 byte-order mark;
- hardens text cells that could execute spreadsheet formulas;
- returns `X-Record-Count` and `X-Content-SHA256` evidence;
- uses `Cache-Control: no-store`;
- fails closed above `MAX_ANALYTICS_EXPORT_ROWS`; and
- appends `enterprise_analytics_exported` audit evidence containing the actor,
  filters, row count, digest, and generation time, but never the password or CSV
  contents.

## Deployment

Alembic revision `20260807_0044` adds tenant/date, engineer/date, job-type/date,
work-order-parts, and inventory-ledger indexes used by these bounded queries.
Apply `alembic upgrade head` before enabling the route in production. Validate
dashboard totals against a known operating period after deployment and monitor
query latency at production data volume. Dashboard responses are live and
uncached; durable historical snapshots require a future warehouse or snapshot
pipeline.
