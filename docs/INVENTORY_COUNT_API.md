# Inventory Count API

Inventory counts are online-only and organization-scoped.

1. Warehouse or administrator creates `POST /api/inventory/counts` with a unique `client_request_id`.
2. Warehouse or administrator records physical quantities through `PUT /api/inventory/counts/{id}/lines` using the current `expected_version`.
3. `submit` snapshots every line's book quantity and locks entry.
4. An administrator sends `approve` with the current version and account password. The server recalculates current book stock and posts a uniquely linked adjustment for every non-zero variance.
5. Managers can inspect counts but cannot change them.

Drafts may be cancelled by warehouse users or administrators with a reason. Submitted counts may only be cancelled by administrators. Approved counts are immutable. Vehicle warehouses use their separate engineer custody workflows.
