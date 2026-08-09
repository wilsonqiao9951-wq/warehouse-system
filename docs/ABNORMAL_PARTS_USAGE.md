# Governed abnormal parts usage

OpenPartsFlow persists explainable part-usage signals and requires an
accountable manager decision. Detection is advisory: it never edits inventory,
work-order ownership, engineer identity, or billing evidence.

## Trusted evidence and baseline scopes

Only prior work orders that are completed, locked, and in the current tenant
are eligible for a quantity or combination baseline. The current usage is
compared only with work orders completed before that usage was recorded, which
prevents the candidate from diluting its own threshold.

For each part, revision `usage-anomaly-v1` stores a 365-day baseline in this
fallback order:

1. job type + machine type + store/outlet;
2. job type + machine type;
3. machine type;
4. job type;
5. organization.

The first scope with at least three prior work orders is used for quantity
comparison. Each stored baseline retains sample work orders, source rows,
segment population, total/mean/standard deviation/P90 quantity, spike
threshold, part support ratio, source time range, SHA-256 evidence fingerprint,
calculation time, and optimistic version.

The quantity threshold is the maximum of P90, 1.8 times the mean, and mean plus
two population standard deviations. These values are evidence defaults, not a
disciplinary conclusion.

## Signals

- `quantity_spike`: observed quantity is greater than the selected baseline
  threshold.
- `unusual_part_combination`: at least five prior exact-context work orders
  exist and the part appeared in fewer than 20 percent of them.
- `off_hour_usage`: the server-recorded usage time is outside 06:00–22:00 in
  the source warehouse's inventory-region IANA timezone. The tenant default
  region is the fallback; UTC is the final fallback.

Every review snapshots the observed quantity/cost, selected baseline, exact
segment support, local hour/timezone, reason codes, human explanations,
algorithm version, and a SHA-256 source fingerprint. Later baseline refreshes
cannot rewrite that review evidence.

## Review state machine

```text
pending
  -> acknowledged
       -> confirmed
       -> dismissed
```

Acknowledgement requires a manager or organization administrator plus a note.
A final decision requires the same managerial role, an acknowledged item, and
a reason. Every action stores the account, server time, prior/new status,
optimistic version, and audit log. Exact retries are idempotent; stale versions
return `409`.

Engineers continue to see the ordinary work-order and part-usage facts allowed
by the work-order visibility contract. The abnormal-review queue is an
operational management report and requires `reports.read`; mutation additionally
requires the manager or administrator role. Tenant scoping and forced
PostgreSQL RLS apply to both baseline and review tables.

## API and workbench

- `GET /api/reports/abnormal-usage` — active/history queue with status,
  severity, and engineer filters.
- `GET /api/reports/abnormal-usage/baselines` — stored baseline evidence.
- `POST /api/reports/abnormal-usage/evaluate` — bounded historical scan (at
  most 5,000 usage rows per request) with an `after_id` continuation cursor.
- `POST /api/reports/abnormal-usage/{id}/actions` — acknowledge, confirm, or
  dismiss using an expected version.
- `/abnormal-usage` — responsive manager review workbench.

The queue response retains the legacy `work_order_id`, `ticket_number`,
`engineer_id`, `parts_cost`, `revenue`, `severity`, and `reason` fields while
adding the governed review contract, so existing read-only report consumers do
not need an immediate field migration.

New part usage is evaluated inside the existing authenticated inventory
transaction after work-order ownership and vehicle/source-warehouse rules pass.
Historical scans are explicit and audited. The history window is bounded to
10,000 completed work orders per evaluation and no model sends tenant data to
an external AI provider.
