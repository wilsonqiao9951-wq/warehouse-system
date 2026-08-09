# Work-order field media evidence

OpenPartsFlow stores work-order photos and videos as immutable operational
evidence. This workflow is separate from legacy QC-picture records, part-usage
photos, and curated machine-knowledge media.

## Access contract

- Every authenticated operational user in the same organization may list and
  open the evidence so engineers can see team progress.
- Only the active claimant engineer on the registered phone and current claim
  generation, or an administrator, may upload evidence.
- Managers, warehouse users, and other engineers are read-only.
- Pending-approval and completed/locked work orders reject new evidence.
- Uploads are append-only. There is no update or delete endpoint.
- Every query contains an explicit organization predicate, and PostgreSQL
  deployments force tenant row-level security on `work_order_media`.

## Evidence captured

Each row records the work order, category, optional caption, signature-derived
media type and MIME type, byte count, SHA-256, private storage key, sanitized
original file name, authenticated account, registered device, claim version,
client request ID, and server time. Supported categories are `arrival`,
`before`, `during`, `after`, `damage`, `serial_label`, and `other`.

The uploader's account remains visible for team accountability. Internal device
record IDs and original phone file names are returned only to the uploader,
manager, or administrator; peers and warehouse users receive those fields as
`null`.

JPEG, PNG, GIF, WebP, HEIC, WebM, MOV, and MP4 are recognized from file bytes;
the client name and declared content type are not trusted. The configured
`MAX_KNOWLEDGE_MEDIA_UPLOAD_BYTES` limit applies, and each work order is capped
at 100 media records.

`client_request_id` is unique per tenant. An exact retry returns the existing
row; reuse with different evidence returns `409`. The request fingerprint binds
the work order, category, caption, file digest/size/type, original name, actor,
device, and claim version.

## Private file delivery

Files are stored below the private evidence root under random keys. They are
not exposed by `/uploads`. The content endpoint repeats tenant/work-order read
authorization, validates the storage path, byte count, and SHA-256, and returns
`private, no-store`, `nosniff`, and a sandboxed content security policy.

API routes:

- `GET /api/work-orders/{work_order_id}/media`
- `POST /api/work-orders/{work_order_id}/media`
- `GET /api/work-orders/{work_order_id}/media/{media_id}/content`

The work-order mobile screen provides camera/library capture, photo/video
preview, category/caption input, authenticated viewing, and evidence metadata.
Its completion-photo policy accepts either a legacy QC picture or a new field
photo; video alone does not satisfy that policy.

## Backup, restore, and offline boundaries

Portable organization exports include the tenant rows and referenced private
files. Controlled restore validates archives through schema `0070` but does not
mutate immutable field evidence. Operators must restore this evidence through
the complete platform recovery workflow or a separately governed future
append-only import.

Field media upload is intentionally online-only. Large private binary replay
has not been added to the reviewed offline allowlist. Previously cached work
order details still open offline, and legacy QC-photo queuing remains available.

Field evidence is not automatically published to machine knowledge, used as an
AI label, written to inventory, or sent to AppSheet. Each downstream use needs
its own governed review or integration contract.
