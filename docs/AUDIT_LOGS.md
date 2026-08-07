# Enterprise Audit Logs

OpenPartsFlow records tenant-owned operational evidence in `audit_logs`.
`audit.read` defaults to managers and administrators. `audit.export` defaults
to administrators and also requires current-account password verification.
Administrators can explicitly allow or deny these capabilities for a
non-administrator through the enterprise access policy matrix.

## Access boundaries

| Operation | Manager default | Administrator | Other-role default |
| --- | --- | --- | --- |
| Legacy list | Allow | Allow | Deny |
| Search and cursor pagination | Allow | Allow | Deny |
| 30-day summary | Allow | Allow | Deny |
| CSV export | Deny | Password-confirmed authenticated session | Deny |

An explicit user override may change a non-administrator default in this table.
Password verification, tenant scope, row limits, and audit evidence still apply.

Every query includes the actor's `organization_id` explicitly. The normal
SQLAlchemy tenant-session filter remains active as a second boundary. User
names come only from the same tenant-scoped user relation.

## APIs

### Compatibility list

`GET /api/audit-logs?skip=0&limit=100`

This route retains the original list response and raw `metadata` JSON string so
existing integrations continue to work.

### Structured search

`GET /api/audit-logs/search`

Optional exact-match filters:

- `action`
- `entity_type`
- `entity_id`
- `user_id`
- `from_at` and `to_at` as ISO-8601 timestamps (timezone-less values are UTC)
- `before_id` as the descending cursor
- `limit`, from 1 through 200

The response contains `items`, the total count for the active filters, and
`next_before_id`. Metadata is parsed into an object. Malformed historical JSON
is returned as `{"legacy_raw": "..."}` with `metadata_valid=false` rather than
breaking the page or hiding the evidence. Structured response and CSV
timestamps are emitted explicitly as UTC.

### Activity summary

`GET /api/audit-logs/summary?days=30`

The bounded window is 1 through 365 days. The response includes event count,
distinct authenticated actors, latest event time, top actions, and top entity
types. Action, entity-type, entity-id, and actor filters are supported.

### Verified export

`POST /api/audit-logs/export`

The JSON body accepts the same search filters and requires
`account_password`. Export behavior is deliberately stricter:

1. only an administrator role is accepted;
2. an authenticated Cookie or Bearer session and the current account password are required;
3. the server counts matching rows before materializing the CSV;
4. `MAX_AUDIT_EXPORT_ROWS` rejects oversized exports with `413`;
5. cells beginning with spreadsheet formula characters are prefixed safely;
6. the UTF-8 CSV receives a SHA-256 digest;
7. response headers expose `X-Content-SHA256` and `X-Record-Count`;
8. an `audit_log_exported` event records filters, count, digest, actor, and UTC
   generation time after the export snapshot is created.

The current password is used only for verification. It is not written to the
database, logs, response headers, CSV, or export audit metadata. The export's
own audit event is intentionally not part of the snapshot it describes.

## Database indexes

Alembic revision `20260807_0041` adds:

- `(organization_id, timestamp)`
- `(organization_id, action, timestamp)`
- `(organization_id, entity_type, entity_id)`

These indexes serve the tenant boundary first and keep common time, action, and
entity investigations bounded as the evidence table grows.

## Operator checks

After deployment:

1. run `python -m scripts.prepare_database` and confirm the current Alembic head;
2. sign in as a manager and confirm search/summary work but export is absent;
3. sign in as an administrator and verify an incorrect password is rejected;
4. export a narrow time range and compare the file SHA-256 with the response;
5. refresh the page and confirm the `audit_log_exported` event is present;
6. confirm another organization's seeded event never appears in search,
   summary, or export.
