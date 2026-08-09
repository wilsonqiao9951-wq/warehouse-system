# AppSheet parallel-run reconciliation evidence

OpenPartsFlow can compare a bounded canonical AppSheet or Google Sheets export
with the tenant's current OpenPartsFlow records. Each completed comparison is
append-only evidence for an internal pilot decision; it is not customer
acceptance, a legal sign-off, or proof that undiscovered AppSheet formulas and
Bots are equivalent.

## Preconditions and access

- The integration provider must be `appsheet` or `google_sheets`, and the API
  key must be active.
- A persisted parity contract must be `ready` and the submitted
  `source_revision` must match it exactly.
- `integrations.read` can list and inspect evidence. `integrations.manage` plus
  current-account password verification is required to run a comparison.
- Every integration, contract, source link, operational query, evidence row,
  list, and detail lookup has an explicit organization condition. The evidence
  table also participates in ORM tenant enforcement and forced PostgreSQL RLS.

## Canonical input contract

`POST /api/integrations/{integration_id}/parallel-reconciliations` accepts:

```json
{
  "source_revision": "AppSheet pilot export 2026-08-08",
  "observed_from": "2026-08-07T12:00:00Z",
  "observed_to": "2026-08-08T12:00:00Z",
  "work_orders": [
    {"external_id": "row-1001", "status": "completed"}
  ],
  "part_usage": [
    {
      "external_work_order_id": "row-1001",
      "part_number": "FILTER-1",
      "quantity": 2
    }
  ],
  "inventory": [
    {"warehouse_code": "MAIN", "part_number": "FILTER-1", "quantity": 18}
  ],
  "reason": "End-of-day controlled parallel run",
  "account_password": "current account password"
}
```

The observation window is inclusive and cannot exceed 366 days. Work orders
use `work_orders.updated_at`; part usage uses `work_order_parts.updated_at`.
Inventory is the current ledger-derived, non-zero point-in-time balance, so
zero balances must be omitted. Each collection must represent a complete
canonical snapshot for its scope. Duplicate keys are rejected rather than
silently merged.

Limits are 5,000 work orders, 10,000 aggregated part-usage rows, and 10,000
inventory balances per request. External table names and customer-specific
columns must first be mapped outside this endpoint according to the saved
parity contract.

## Comparison semantics

- Work-order key: exact external row ID; value: normalized status.
- Part-usage key: exact external work-order ID plus case-insensitive part
  number; value: summed quantity in the observation window.
- Inventory key: case-insensitive warehouse code plus part number; value:
  current ledger balance.

Each union key is classified as matched, missing from the external snapshot,
missing from OpenPartsFlow, or value mismatch. The response returns complete
aggregate counts and at most 500 discrepancy details. `truncated=true` means
the detail list was bounded while `discrepancy_count` remains complete.

## Retained evidence and privacy boundary

OpenPartsFlow does not retain the submitted snapshot, customer/store names,
addresses, descriptions, notes, media, formulas, passwords, or external
credentials. It retains:

- contract, source-snapshot, and combined-evidence SHA-256 fingerprints;
- source revision and observation window;
- per-object external/internal/matched/difference counts;
- the first 500 canonical discrepancy keys and values;
- responsible actor, server creation time, and business reason.

An exact retry against unchanged OpenPartsFlow state returns the existing
evidence row and does not duplicate the audit event. There are no update or
delete APIs for reconciliation evidence.

## APIs and workbench

- `POST /api/integrations/{integration_id}/parallel-reconciliations`
- `GET /api/integrations/{integration_id}/parallel-reconciliations`
- `GET /api/integrations/{integration_id}/parallel-reconciliations/{id}`
- `/integration-reconciliation` provides JSON/file intake, contract readiness,
  append-only history, aggregate counts, and bounded discrepancy inspection.
- `/pilot-checklist` shows active integrations, ready contracts, latest
  reconciliation evidence, and explicit tenant-scoped operating counts.

## Cutover boundary

A `matched` result proves only that the submitted canonical snapshot matched at
one recorded time. Cutover still requires review of customer-specific formulas,
security filters, attachments, Bots, scheduled reports, failure recovery,
volume, real-device operation, support ownership, rollback readiness, and
authorized business sign-off.
