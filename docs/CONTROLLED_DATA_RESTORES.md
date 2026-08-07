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

Rehearsals approved before revision `0039` must be run again because file state
is now part of the signed plan. Rollback snapshots from already-applied `0037`
or `0038` restores remain supported.

## Archive validation

The validator rejects:

- unsupported format or database schema revisions (the explicit compatibility
  map accepts portable revisions `0036` through the current `0045` workflow);
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
history are validation-only. Enterprise Agent run evidence is also validation-
only and cannot be rewritten by a restore.

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

Archive media entries are mapped only from exact `/uploads/...` or
`private:...` manifest references to their configured public/private storage
roots. Absolute, parent-relative, backslash, mismatched, duplicate-target,
symbolic-link, and non-regular-file destinations are rejected or recorded as
approval-blocking conflicts. A target must still be referenced by the current
organization or the approved database plan, and any reference from another
organization blocks writeback.

The rehearsal reports media creates, overwrites, unchanged files, and
conflicts. Application stages every changed archive file under the protected
rollback root, copies every overwritten original, verifies all hashes again,
then uses a same-directory temporary file and atomic replacement for each live
target. If the database commit fails, promoted files are compensated back to
their pre-application state.

## Plan stability and rollback

The rehearsal plan stores a SHA-256 derived from every eligible row id and its
before/after field values. Application reparses the same archive and recomputes
the plan from the live database. Any intervening eligible data change produces
a different plan and returns `409` before writes occur.

After a successful application, the exact database and file action plan is
stored as the rollback snapshot with SHA-256 and byte counts. The durable file
evidence retains archive content plus every overwritten original outside the
served media roots. Rollback first confirms that every affected row and live
file still equals the applied value and that every evidence file still matches
its recorded hash. Later edits or evidence corruption stop rollback.

Application also fixes a governed rollback expiry using the organization's
retention policy. Rollback is refused after that timestamp. Expired rollback
packages can be removed only through the password-confirmed, version-checked,
bounded retention workflow; the restore row keeps its application and purge
attribution after the sensitive database/file package is gone.

Updated fields are restored, rehydrated rows are removed in child-to-parent
order, overwritten files are restored, and files created by the restore are
removed. A failed rollback database commit reapplies the restored archive
files. Successful rollback removes the protected file evidence directory.

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

- `GET /api/organization/data-retention` - fixed-cutoff policy and cleanup
  preview
- `PUT /api/organization/data-retention` - password-confirmed, versioned policy
  update
- `POST /api/organization/data-retention/cleanup` - password-confirmed,
  reasoned, bounded evidence cleanup

All endpoints are administrator-only, tenant-filtered, and online-only.

## Configuration

- `MAX_DATA_RESTORE_ARCHIVE_BYTES` — maximum compressed upload size;
- `MAX_DATA_RESTORE_UNCOMPRESSED_BYTES` — maximum declared uncompressed ZIP
  content;
- `MAX_DATA_RESTORE_ROLLBACK_BYTES` — maximum persisted before/after plan;
- `DATA_RESTORE_ROLLBACK_FILES_ROOT` — protected, non-public directory for
  archive and overwritten-original file evidence;
- `MAX_DATA_RESTORE_FILE_ROLLBACK_BYTES` — maximum combined staged archive and
  overwritten-original bytes for one restore.

## Operational boundary

The rollback root must not be inside either public or private media root. It
must be included in encrypted server backup, excluded from direct web serving,
and monitored for sufficient free space. Database and filesystem operations are
coordinated with compensation; operators should preserve the evidence directory
for every restore that remains in `applied` state.

The retention cleanup adds a protected quarantine/repair boundary around file
evidence deletion so an interruption before commit restores active evidence and
an interruption after commit can finish deletion on the next run. See
[`DATA_RETENTION.md`](DATA_RETENTION.md).
