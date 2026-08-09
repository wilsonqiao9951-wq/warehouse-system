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

`integrations.read` defaults to managers and administrators;
`integrations.manage` defaults to administrators. A tenant administrator can
explicitly allow or deny either capability for a non-administrator. Tenant
scope, one-time secret display, and audit requirements are unchanged.

Management endpoints:

- `GET /api/integrations`
- `POST /api/integrations`
- `PATCH /api/integrations/{integration_id}`
- `POST /api/integrations/{integration_id}/rotate-key`
- `GET /api/integrations/{integration_id}/sync-logs`
- `POST /api/integrations/{integration_id}/sync-logs/{log_id}/retry`
- `GET /api/integrations/{integration_id}/parity-contract`
- `PUT /api/integrations/{integration_id}/parity-contract`

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

## External read APIs

The same tenant-scoped `X-API-Key` may query:

- `GET /api/external/v1/inventory`
- `GET /api/external/v1/work-orders/{external_id}`
- `GET /api/external/v1/work-orders/{external_id}/recommendations`

Inventory accepts optional exact `part_number` and `warehouse_code` filters plus a bounded `limit`. Responses contain operational quantities and locations, but never supplier or cost fields. Work-order lookup is restricted to the external IDs linked to the calling integration. Recommendation responses expose the recommended quantity, historical evidence, current availability, reason, and confidence without financial data.

## Signed outbound Webhooks

An administrator may configure one HTTPS callback URL and subscribe to:

- `work_order.status_changed`
- `work_order.completed`
- `work_order.part_used`

Private, loopback, link-local, reserved, credential-bearing, fragment-bearing, non-HTTPS, and local host targets are rejected. Redirects are not followed during delivery.

Every business event is committed to the delivery queue in the same transaction as the work-order status or part usage. External downtime therefore does not roll back or delay the engineer's field action.

Every successful `/external/v1` call consumes one external API unit from the
organization's current UTC monthly allowance. The recommendations endpoint also
consumes one AI unit. A processed inbound idempotency key can be replayed without
a second charge. Invalid credentials, validation failures, missing links,
rejected mutations, and failed transactions are not charged. A plan without the
capability returns `403`; an exhausted positive allowance returns `429`.

Outbound requests include:

```text
Content-Type: application/json
X-OpenPartsFlow-Event: work_order.completed
X-OpenPartsFlow-Delivery: <sync log id>
X-OpenPartsFlow-Timestamp: <Unix seconds>
X-OpenPartsFlow-Signature: sha256=<hex HMAC>
Idempotency-Key: <stable business event key>
```

To verify a signature:

1. SHA-256 hash the raw OpenPartsFlow API key and use the 32 resulting bytes as the HMAC key.
2. Concatenate the timestamp, a literal period, and the exact request body bytes.
3. Calculate HMAC-SHA256 and compare its hex digest to `X-OpenPartsFlow-Signature` with a constant-time comparison.
4. Reject stale timestamps and remember the delivery or idempotency key.

API key rotation also rotates the signing key. Update the external receiver before generating new events.

Successful HTTP `2xx` responses mark a delivery processed. Network failures and non-`2xx` responses retry after 1 minute, 5 minutes, 30 minutes, 2 hours, and 6 hours. Five failed attempts move the event to `failed`; an administrator can requeue it from the integration workspace. The application worker polls due deliveries every `INTEGRATION_DELIVERY_POLL_SECONDS` while `INTEGRATION_DELIVERY_ENABLED=true`.

If a worker or host stops after claiming a row, the platform operations console
detects the row after `OPERATIONS_STALE_PROCESSING_MINUTES`. A platform
administrator can password-confirm a bounded requeue after verifying that the
old attempt is no longer running. The recovery preserves the attempt count and
stable idempotency key, excludes inbound rows and fresh attempts, records
tenant-scoped audit evidence, and never performs delivery inside the recovery
request. Receivers must therefore retain their normal idempotency protection.

## Tenant isolation

API key authentication establishes the organization before reading links, logs, or work orders. Integrations, source links, sync logs, work orders, and audit entries all use the existing database tenant filter. The same external row ID may be used independently by different organizations.

## AppSheet and Google Sheets parallel-run contract

The integrations workspace creates a provider-aware field and automation
template, accepts a complete external table dictionary, validates canonical
field directions and live Webhook coverage, and calculates a seven-capability
readiness score. Saved contracts retain versions, actor/time evidence, gaps,
and a SHA-256 fingerprint. External-only columns may be documented with no
canonical mapping; unsupported or protected canonical fields are rejected.

Managers have read-only access and administrators save through optimistic
versions. Integration mapping or subscription changes automatically revalidate
the saved contract. See
[`INTEGRATION_PARITY_CONTRACTS.md`](INTEGRATION_PARITY_CONTRACTS.md).

## Current boundary

The platform covers inbound work-order create/update, external inventory/status/recommendation reads, outbound work-order lifecycle callbacks, and versioned AppSheet/Google Sheets parallel-run contracts. Field mapping remains intake-only; external systems cannot mutate engineer ownership, authenticated device claims, completion evidence, part usage, or inventory through these APIs.
