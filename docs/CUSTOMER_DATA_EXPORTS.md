# Customer data exports and backup evidence

## Purpose

Organization administrators can generate a portable, tenant-isolated ZIP from
the **Backups** workspace. The operation requires Bearer authentication and
current-password reauthentication. Managers, warehouse staff, engineers, and
other organizations cannot list or generate the export evidence.

The system streams the finished archive to the authenticated administrator. It
does not retain a second plaintext archive on the application server. The
customer is responsible for moving the downloaded file into its approved,
encrypted backup storage.

## Archive format

Format version: `opf-portable-v1`.

The ZIP contains:

- `manifest.json`, including the organization, schema revision, UTC generation
  time, table/file counts, missing-file references, and SHA-256 values for each
  included data or media file;
- `data/<table>.jsonl`, with one UTF-8 JSON object per tenant-owned database
  record;
- `files/public/...`, for local photos and voice notes referenced by exported
  records when file inclusion is enabled;
- `files/private/...`, for tenant-scoped machine-knowledge media when file
  inclusion is enabled.

Only the selected organization row and records protected by the server tenant
registry are queried. Local files are copied only from normalized configured
storage roots, and path traversal or missing files are listed as missing rather
than followed.

## Secret exclusions

The portable archive intentionally excludes authentication material that must
never be restored or shared as customer business data:

- user password hashes;
- registered-device token hashes;
- external API key hashes;
- invitation token hashes;
- domain verification tokens and values.

The manifest records every excluded table/column. Work-order signatures,
customer contacts, operational notes, costs, and other business records remain
in the archive, so the ZIP must be handled as sensitive customer data.

## Integrity evidence

After the archive is successfully constructed, the server commits an
`organization_data_exports` row and an
`organization_data_export_generated` audit event. The evidence stores:

- archive SHA-256 and byte size;
- format version and UTC generation time;
- total record, included-file, and missing-file counts;
- per-table record counts;
- requesting administrator and whether files were included.

The same archive SHA-256 is returned in the
`X-OpenPartsFlow-SHA256` response header and shown in the Backups workspace.
Customers should calculate SHA-256 from the downloaded ZIP and compare it with
this durable evidence.

## Limits and restore boundary

`MAX_DATA_EXPORT_BYTES` limits the combined uncompressed database and local-file
content. `DATA_EXPORT_PUBLIC_FILES_ROOT` and
`DATA_EXPORT_PRIVATE_FILES_ROOT` define the only local roots eligible for
inclusion.

`opf-portable-v1` is accepted only by the separate controlled restore workflow.
It performs archive validation, an eligible-row dry-run, explicit approval,
exact-archive and live-plan revalidation, atomic updates, guarded rehydration of
missing allowlisted records, staged media writeback, and drift-protected
database/file rollback.
See [`CONTROLLED_DATA_RESTORES.md`](CONTROLLED_DATA_RESTORES.md).

## API

- `GET /api/organization/data-exports` — organization administrator only;
  returns the latest integrity evidence.
- `POST /api/organization/data-exports` — organization administrator only;
  requires `account_password` and accepts `include_files`; streams the ZIP.

Both endpoints are online-only. Export requests are never stored in the offline
queue.
