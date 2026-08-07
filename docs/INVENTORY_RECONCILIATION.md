# Inventory Reconciliation Exceptions

## Purpose

The reconciliation workbench gives warehouse users, managers, and
administrators one read-only queue for inventory records that need attention.
It does not create a second ledger and cannot post or repair stock.

Frontend route: `/inventory-reconciliation`

API: `GET /api/inventory/reconciliation-exceptions`

## Exception classes

| Class | Severity | Meaning |
| --- | --- | --- |
| Historical reconciliation | Warning or critical | A migrated replenishment is explicitly marked as lacking trustworthy custody evidence. A linked movement raises it to critical because automatic historical reconciliation is intentionally blocked. |
| Custody ledger mismatch | Critical | A replenishment or vehicle return status requires a shipment/receipt that is missing, unexpected, or disagrees on workflow, stage, movement type, part, quantity, or warehouse. |
| Pending count variance | Warning | A submitted physical count differs from its immutable submission snapshot and awaits administrator review. Approval recalculates against live stock before posting. |
| Count ledger mismatch | Critical | Approved count evidence, stored variance, or its uniquely linked adjustment is missing or inconsistent. |

Healthy custody records and approved count adjustments are excluded.

## Response and filters

Optional filters are `source` (`replenishment`, `vehicle_return`, or
`inventory_count`), `severity` (`critical` or `warning`), and `limit` (1–200).
Critical records sort before warnings, then by most recent workflow update.

Each workflow scan is capped at 500 candidates. `truncated=true` means the
operator should narrow a filter; the API never implies that a truncated result
is a complete count. Responses use `Cache-Control: no-store`.

Every item contains its source record, part, warehouse route, quantity or
variance, linked movement IDs, reason, and a drill-down route. Direct reads for
the target replenishment, vehicle return, or count have explicit tenant checks
so an older exception remains reachable even when absent from the normal
100-row history page.

## Authorization and correction boundary

Warehouse users, managers, and administrators may read the queue. Engineers
and assistants receive `403`. Engineers retain the narrower existing ability to
read only replenishments or returns assigned to their own account.

The queue never mutates data. Operators must use the existing inventory-count,
replenishment, or vehicle-return workflow. Those actions continue to enforce
role, current version, registered device, password reauthentication, ledger
linkage, and audit evidence.

## Migration

Revision `20260807_0059` adds
`ix_replenishment_org_reconcile_updated` over organization,
`requires_reconciliation`, and update time. Downgrade removes only the index;
no inventory or custody record is altered.
