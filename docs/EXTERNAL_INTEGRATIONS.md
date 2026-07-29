# External integration foundation

Phase 6 starts with a tenant-scoped inbound contract for AppSheet and other external systems. This batch creates governed API credentials, configurable work-order field mapping, stable source links, idempotent processing, and visible synchronization evidence.

## Credential lifecycle

Administrators create integrations from `/integrations` or:

`POST /api/integrations`

Supported provider labels are:

- `appsheet`
- `generic`
- `google_sheets`
- `crm`
- `erp`
- `wms`

The raw API key is returned only on creation or rotation. OpenPartsFlow stores a SHA-256 hash and a short lookup prefix, never the usable key. Rotating a key invalidates the previous key immediately. Deactivating an integration rejects every webhook call.

Managers may view integrations, mappings, and sync logs. Only administrators may create, edit, deactivate, or rotate credentials.

Management endpoints:

- `GET /api/integrations`
- `POST /api/integrations`
- `PATCH /api/integrations/{integration_id}`
- `POST /api/integrations/{integration_id}/rotate-key`
- `GET /api/integrations/{integration_id}/sync-logs`

## Work-order Webhook

Endpoint:

`POST /api/external/v1/work-orders`

Required headers:

```text
X-API-Key: opf_<prefix>_<secret>
X-Idempotency-Key: a unique event or retry identifier
Content-Type: application/json
```

Example:

```json
{
  "external_id": "appsheet-row-key",
  "data": {
    "WO ID": "WO-1001",
    "Site": "Customer site",
    "Issue": "No cooling",
    "Model": "ACME-9000"
  }
}
```

The default AppSheet mapping shown in the administration page is:

```json
{
  "ticket_number": "WO ID",
  "outlet_name": "Site",
  "problem_description": "Issue",
  "machine_type": "Model"
}
```

If no ticket or work-order number is mapped, the server creates a stable generated identifier from the integration and external row ID.

## Allowed mapping fields

External systems may map only administrative intake fields:

- `ticket_number`
- `wo_number`
- `schedule_date`
- `outlet_name`
- `store_name`
- `job_type`
- `description`
- `problem_description`
- `address`
- `city`
- `state`
- `zip`
- `contact_phone`
- `machine_type`
- `status`

External status is limited to `open` or `scheduled`. Assignment, claim ownership, engineer identity, device identity, parts usage, costs, learning outcomes, signatures, completion, approval, and inventory fields cannot be mapped.

## Ownership boundary

An external integration may create a work order or update its linked unclaimed, unfrozen record. Updates stop when any of these is true:

- an engineer has claimed the work order;
- the work order is locked;
- the work order is completed or awaiting completion approval.

The existing authenticated field workflow remains authoritative after dispatch. A Webhook cannot claim, start, complete, approve, consume parts, or alter inventory.

## Idempotency and retry

The combination of integration and `X-Idempotency-Key` is unique.

- Same key and same body after success: returns the original work-order result with `replayed=true`.
- Same key with different data: returns `409` and changes nothing.
- Same key after a failed business validation: retries the event and increments `attempt_count`.
- A separate key for the same `external_id`: updates the existing linked work order, subject to the ownership boundary.

Every event records direction, type, external ID, idempotency key, request hash, status, attempt count, linked work order, changed fields, safe error text, and timestamps. API secrets are never stored in sync logs.

## Tenant isolation

API key authentication establishes the organization before reading links, logs, or work orders. Integrations, source links, sync logs, work orders, and audit entries all use the existing database tenant filter. The same external row ID may be used independently by different organizations.

## Current boundary

This foundation covers inbound work-order create/update. Outbound status/parts callbacks, inventory/recommendation read APIs, delivery retry scheduling, and signed Webhook destinations remain subsequent Phase 6 batches.
