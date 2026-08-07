# Controlled customer data restores

## Purpose

Organization administrators can validate an `opf-portable-v1` backup, review a
dry-run, approve or reject it, apply the approved database changes, and roll
those changes back. Every mutation requires Bearer authentication, the current
administrator password, an exact optimistic version, and tenant ownership.

The uploaded ZIP is held only for the active request. It is not retained by the
application. Applying an approved restore therefore requires uploading the
exact same archive again; its SHA-256 must match the rehearsal evidence.

## State flow

```text
validated -> approved -> applied -> rolled_back
          \-> rejected
```

- `validated`: archive and entry checksums passed and a dry-run is recorded;
- `approved`: an administrator accepted a conflict-free plan with eligible
  changes and an approval note;
- `rejected`: the rehearsal was explicitly rejected and cannot be reused;
- `applied`: the exact archive and unchanged live plan were applied atomically;
- `rolled_back`: the stored pre-application field snapshot was restored.

Every state transition creates a tenant audit event without storing a password
or archive contents.

## Archive validation

The validator rejects:

- unsupported format or database schema revisions (`0036`, `0037`, and `0038`
  archives are compatible with the `0038` restore workflow);
- an organization id or slug that differs from the signed-in tenant;
- missing, duplicate, absolute, parent-relative, backslash, symbolic-link, or
  encrypted ZIP entries;
- unknown tables or columns, authentication-secret columns, cross-tenant rows,
  unexpected entries, and manifest count mismatches;
- per-table or per-file size/checksum mismatches;
- compressed upload, uncompressed content, entry count, manifest, or rollback
  snapshot limits that exceed server configuration.

Matching `organization_data_exports` evidence is shown when available. A match
helps an operator trace the source export, but disaster recovery remains
possible when the original evidence database is unavailable.

## Controlled application boundary

The workflow updates existing eligible rows and can rehydrate missing eligible
rows. It never deletes current records during application or changes the
identity, tenant, or immutable timestamps of an existing row.

Eligible tables:

- customers and equipment;
- warehouses and storage locations;
- parts and part-machine associations;
- completion policies;
- configurable work-order templates and fields;
- reviewed machine-knowledge profiles and entries.

Authentication, devices, invitations, domains, billing, usage, external
credentials, work-order execution/custody, inventory ledgers, approval
workflows, synchronization logs, imports, export/restore evidence, and audit
history are validation-only.

A missing eligible row is included in the create plan only when:

- its archived id is globally unused, including by another tenant;
- all archived columns needed for deterministic reconstruction are present;
- its tenant id exactly matches the signed-in organization;
- every current unique key remains available; and
- every foreign key points to a current same-tenant row or another valid row in
  the same rehydration plan.

Invalid parent rows propagate conflicts to planned children. Creates run in
parent-to-child dependency order. A uniqueness, ownership, or referential
conflict blocks approval rather than selecting a different id or relationship.

Archive media entries are checksum-verified but are not written to storage in
this stage. Existing database file references may be restored only when their
target files are already present.

## Plan stability and rollback

The rehearsal plan stores a SHA-256 derived from every eligible row id and its
before/after field values. Application reparses the same archive and recomputes
the plan from the live database. Any intervening eligible data change produces
a different plan and returns `409` before writes occur.

After a successful application, the exact action/before/after plan is stored as
the rollback snapshot with its own SHA-256 and byte count. Rollback first
confirms that every updated or rehydrated row still equals the applied value;
later edits stop rollback rather than being overwritten. Updated fields are
restored and rehydrated rows are removed in child-to-parent order. Application
and rollback each use one database transaction.

## API

- `GET /api/organization/data-restores`
- `POST /api/organization/data-restores/rehearsals` — multipart ZIP and
  `account_password`
- `POST /api/organization/data-restores/{id}/decision` — `approve` or `reject`,
  note, password, and `expected_version`
- `POST /api/organization/data-restores/{id}/apply` — exact multipart ZIP,
  password, and `expected_version`
- `POST /api/organization/data-restores/{id}/rollback` — password and
  `expected_version`

All endpoints are administrator-only, tenant-filtered, and online-only.

## Configuration

- `MAX_DATA_RESTORE_ARCHIVE_BYTES` — maximum compressed upload size;
- `MAX_DATA_RESTORE_UNCOMPRESSED_BYTES` — maximum declared uncompressed ZIP
  content;
- `MAX_DATA_RESTORE_ROLLBACK_BYTES` — maximum persisted before/after plan.

## Future expansion boundary

Media writeback requires storage staging, atomic promotion, overwrite evidence,
and file-level rollback. It remains checksum-validation-only until that
capability is added as a separate reviewed batch.
