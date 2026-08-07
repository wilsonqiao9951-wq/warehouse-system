# Employee Performance Scorecards

The `/performance` workbench separates throughput, created-cohort completion,
service quality, repair duration, and parts-use evidence. OpenPartsFlow does not
collapse these signals into an opaque composite score because repair complexity
and job mix can make a single ranking misleading.

## Definitions

- **Completed throughput** counts work orders completed by the accountable
  engineer inside the selected UTC period and normalizes the count to 30 days.
- **Created-cohort completion** starts with work orders currently assigned to
  the engineer and created inside the period. It counts the share completed by
  the selected period end.
- **First-time fix** excludes unlabeled completed work orders and always exposes
  label coverage.
- **Rework** is the share of completed work orders marked as rework.
- **Repair duration** uses server-measured durations and exposes coverage.
- **Parts efficiency** shows recorded part quantity and cost per completed job,
  plus usage coverage. Lower use is not automatically better; managers must
  consider job type and repair complexity.

Completion attribution uses `completed_by_id`, then the authenticated claim
owner, then the current engineer/assignee. Manager views retain a separate
unattributed row for missing or non-engineer evidence.

## Role separation

`GET /api/performance/scorecards` is tenant-scoped and returns
`Cache-Control: no-store`.

- Engineers receive exactly their own scorecard. A request for another engineer
  is denied, team identities are omitted, and parts cost, revenue, labor cost,
  and contribution are returned as null.
- Managers and administrators require effective `reports.read`; they can view
  the team or one selected engineer and receive financial efficiency evidence.
- Warehouse and assistant roles cannot open this dashboard.

The request range is limited to 366 days. The response includes the precise
metric definitions used by the server so UI labels and exported interpretations
cannot silently diverge.
