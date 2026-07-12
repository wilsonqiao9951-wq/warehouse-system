# OpenPartsFlow RBAC API Mapping

## Work-order access model

OpenPartsFlow separates visibility, field execution, and management. Frontend capability flags are a usability aid only; every rule is enforced again by the API.

| Operation | Other engineer | Active claimant on bound device | Manager | Admin | Warehouse |
| --- | --- | --- | --- | --- | --- |
| View organization work-order pool and progress | Allow | Allow | Allow | Allow | Deny |
| View service context, parts, evidence, and history | Allow | Allow | Allow | Allow | Existing scoped read only |
| Claim an available work order | Allow with verified Bearer device | Idempotent on same device | Deny | Deny | Deny |
| Edit field data | Deny | Allow with current claim version | Deny | Allow with audit | Deny |
| Start/pause/add evidence/use parts | Deny | Allow with current claim version | Deny | Allow with audit | Deny |
| Request or directly complete | Deny | Allow with current password verification | Deny | Deny | Deny |
| Approve/reject completion | Deny | Deny | Allow | Allow | Deny |
| Release an active claim | Deny | Deny | Allow with reason | Allow with reason | Deny |

## Work-order pool APIs

`GET /api/work-orders` supports `scope=all|mine|available`.

- Every same-organization engineer can use `all` and see the common job pool.
- `mine` filters by `claimed_by_id`, not legacy assignment fields.
- `available` returns unclaimed, unlocked work orders.
- Cross-organization rows are excluded by the tenant session filter.
- Other engineers can see status history, parts usage, photos, voice notes, repair progress, claimant, and completer. They do not receive customer signature images, financial values, or device-record identifiers.
- Responses include `can_claim`, `can_edit`, and `can_complete`, calculated by the server.

`POST /api/work-orders/{id}/claim` requires an engineer Bearer token plus a verified registered device. It uses one conditional database update, so concurrent claim attempts have a single winner.

`POST /api/work-orders/{id}/release` is restricted to managers/admins, requires a reason, clears the claim, increments `claim_version`, and records an audit event.

## Field execution APIs

The following writes use the owner-or-administrator edit guard, except completion endpoints which always require the actual claim owner:

- `PATCH /api/work-orders/{id}` for engineer-editable fields
- `POST /api/work-orders/{id}/start`
- `POST /api/work-orders/{id}/pause`
- `POST /api/work-orders/{id}/complete`
- `POST /api/work-orders/{id}/request-completion`
- `POST /api/work-orders/{id}/use-part`
- deprecated `POST /api/work-order-parts`
- work-order photo and voice-note uploads
- QC picture, job-status, and return-equipment creation

For an engineer request the guard requires:

1. exact `ENGINEER` role (admin role inheritance cannot bypass it);
2. Bearer authentication;
3. active registered device and matching device secret;
4. `claimed_by_id == actor.user_id`;
5. `claimed_device_id == actor.device_record_id`;
6. `X-Claim-Version == work_order.claim_version`.

Administrators may correct an unlocked work order through these edit routes, and every change is attributed to the administrator in the audit log. Administrators cannot request or directly complete a work order. The API overrides client attribution fields such as parts `user_id` and photo `uploaded_by` with the authenticated actor.

## Completion attribution

Completion requires the engineer's current account password in `account_password`. The server writes:

- `completed_by_id` from `claimed_by_id`;
- `completed_device_id` from `claimed_device_id`;
- `completed_at` from server time;
- `completion_approved_by` separately when manager approval is required.

Completed work orders are locked. Managers and administrators cannot overwrite the recorded engineer through approval or correction workflows.

## Authentication safety

- Secure defaults: `RBAC_ENFORCE=true`, `LEGACY_HEADER_AUTH=false`.
- Every runnable environment forces these secure values, so stale pilot `.env` files cannot disable ownership enforcement.
- A legacy `X-User-Id` request may never claim or execute a work order.
- Claim and completion are not placed in the offline queue.
- Queued writes are scoped to organization/user/device and preserve the claim version so a released or reassigned claim cannot be replayed.

## Audit requirements

Claim, release, execution, approval, rejection, and completion actions record the actor, role, authentication method, device record, claim version, server timestamp, and action-specific metadata. Passwords and device secrets are never included.

## Automated acceptance coverage

- Same-organization engineers all see the pool; cross-tenant data remains isolated.
- Only one engineer wins a claim.
- Another engineer, another device, legacy authentication, warehouse roles, and stale claim versions are rejected.
- Parts usage cannot spoof another `user_id` through either API path.
- Completion fails with an incorrect password and permanently records the correct engineer/device.
- Manager approval preserves engineer attribution.
- Other engineers can read the owner's parts and progress records but cannot mutate them.
- Administrators can correct unlocked records with their own audit attribution; managers cannot impersonate the field owner.
- Releasing a claim invalidates the prior user's device and queued claim generation.

## Replenishment custody access model

The replenishment workflow separates request supervision, physical warehouse custody, and vehicle receipt. Response capability flags drive the UI, but the API independently validates role, current status, workflow version, target vehicle owner, device, and password.

| Operation | Other engineer | Target vehicle engineer | Manager | Admin | Warehouse |
| --- | --- | --- | --- | --- | --- |
| View replenishment queue | Assigned requests only | Assigned requests only | Allow | Allow | Allow |
| Approve / reject pending request | Deny | Deny | Allow with rejection reason | Allow | Deny |
| Create request from an inventory alert | Deny | Deny | Allow | Allow | Allow |
| Start picking / assign source | Deny | Deny | Deny | Allow | Allow |
| Ship from source warehouse | Deny | Deny | Deny | Allow | Allow |
| Receive into an assigned vehicle | Deny | Allow with bound device and current password | Deny | Deny | Deny |
| Complete a received request | Deny | Deny | Deny | Allow | Allow |
| Cancel a requested/picking request | Deny | Deny | Deny | Allow with reason | Allow with reason |
| Reconcile a flagged historical request | Deny | Deny | Deny | Allow with reason and current password | Deny |

Managers may create, approve, or reject requests and inspect progress, but cannot impersonate warehouse custody actors or the receiving engineer. Warehouse users cannot self-approve and can only pick an approved request. Administrators may approve and perform warehouse custody.

Requests may originate from a low-stock notification or from `POST /api/inventory/replenishment-requests`. The manual endpoint is limited to an active assigned vehicle destination and requires a business reason plus an organization-scoped `client_request_id`. Repeating the same ID and payload returns the existing request; reusing the ID for different data returns `409`.

`GET /api/inventory/replenishment-requests` returns all organization requests to managers/admins/warehouse users and only target-assigned requests to engineers. Each row includes:

- custody actor names and server timestamps;
- receiving device name;
- shipment/receipt inventory transaction IDs;
- source available and destination physical quantities;
- `requires_reconciliation` and `can_reconcile`;
- `can_start_picking`, `can_ship`, `can_receive`, `can_complete`, and `can_cancel`.

`POST /api/inventory/replenishment-requests/{id}/actions` accepts `approve`, `reject`, `start_picking`, `ship`, `receive`, `complete`, or `cancel`. Approval is manager/admin-only; rejection is terminal and requires a reason. The server rejects skipped, reversed, stale, or unauthorized transitions.

All normal action capabilities are false while `requires_reconciliation` is set. Only an exact administrator can call `POST /api/inventory/replenishment-requests/{id}/reconcile`, and the call requires a matching version, a reason, and current-password verification. `reset_requested` is valid only for a reopened requested row; `accept_historical` is valid only for a legacy completed row. Any linked inventory movement blocks this historical reconciliation path.

For a vehicle `receive` action the server requires:

1. exact `ENGINEER` role;
2. `target_user_id == actor.user_id`;
3. Bearer authentication and an active registered device with its matching secret;
4. the destination van still assigned to the same engineer;
5. the engineer's current password in `account_password`;
6. current status `shipped` and matching `expected_version`.

The receipt password is discarded after verification and never written to the replenishment record, inventory transaction, or audit log. Warehouse users, managers, administrators, other engineers, legacy identity headers, and another registered device cannot sign for a target engineer's vehicle delivery.

## Replenishment inventory and audit rules

- `requested/pending → requested/approved` records the manager or administrator decision without moving stock.
- `requested/approved → picking` reserves source quantity through the available-stock calculation.
- `picking → shipped` creates one linked source `OUTBOUND` transaction.
- `shipped → received` creates one linked destination `INBOUND` transaction and records the engineer/device.
- `received → completed` closes the custody task and resolves its originating alert without moving stock again.
- Cancellation is allowed only before shipment (`requested` or `picking`) and requires a reason.
- Cancellation resolves its originating notification; it does not reopen the alert and create a duplicate request loop.
- Unique request/stage and transaction-link constraints prevent retries from posting duplicate shipment or receipt movements.

The audit actions include `replenishment_requested`, `replenishment_approve`, `replenishment_reject`, `replenishment_start_picking`, `replenishment_ship`, `replenishment_receive`, `replenishment_complete`, `replenishment_cancel`, and `replenishment_reconciled`.

All notification/manual request creation, custody mutations, and reconciliation are online-only in the mobile client. They are never stored in or replayed from the offline queue.

## Vehicle inventory boundary

An explicit `warehouse_type=van` or assignment to an engineer classifies a warehouse as a vehicle. Creation automatically normalizes an engineer-owned warehouse to `van`, and a van must belong to an active engineer.

- Vehicles cannot be selected as replenishment sources.
- The generic inventory transaction endpoint cannot move stock from or into a vehicle.
- Opening-inventory preview and commit reject vehicle warehouses.
- Engineers can consume work-order parts only from their own assigned vehicle.
- `RETURN` and `WORK_ORDER_USED` cannot be submitted through the generic transaction endpoint; they require the authenticated return and work-order usage workflows.

SQLite enables foreign-key enforcement on every connection and uses `BEGIN IMMEDIATE` to serialize inventory-affecting custody writes before stock is read. PostgreSQL uses row locks. These database controls support, but do not replace, the API role and capability checks above.

## Vehicle return custody

| Operation | Vehicle owner engineer | Other engineer | Manager | Admin | Warehouse |
|---|---:|---:|---:|---:|---:|
| Create request from assigned vehicle | Allow, bound device | Deny | Deny | Deny | Deny |
| View requests | Own only | Own only | Allow | Allow | Allow |
| Approve and reserve | Deny | Deny | Deny | Allow | Allow |
| Confirm physical handover | Allow, bound device + password | Deny | Deny | Deny | Deny |
| Receive into warehouse | Deny | Deny | Deny | Allow | Allow |
| Cancel before handover | Allow own | Deny | Deny | Allow | Allow |

After approval, the return quantity is reserved against vehicle availability. Handover writes `OUTBOUND`; receipt writes `INBOUND`. Shipped returns cannot be cancelled, generic `RETURN` remains disabled, and all return mutations are online-only.

## Inventory count custody

| Operation | Manager | Admin | Warehouse |
|---|---:|---:|---:|
| View counts | Allow | Allow | Allow |
| Create / record / submit | Deny | Allow | Allow |
| Approve and adjust ledger | Deny | Allow, password | Deny |
| Cancel draft | Deny | Allow | Allow |
| Cancel submitted | Deny | Allow | Deny |

Vehicle warehouses are excluded. Every mutation requires the matching optimistic version and remains online-only.

## Warehouse and location scanning

| Endpoint | Manager | Admin | Warehouse | Engineer |
|---|---:|---:|---:|---:|
| `GET /inventory/location-labels` | Allow | Allow | Allow | Deny |
| `POST /inventory/location-scan` | Allow | Allow | Allow | Deny |
| `POST /inventory/scan` | Allow | Allow | Allow | Own vehicle only |

Location labels are validated against both their database ID and current printed code. A location scan can require an expected warehouse, preventing a same-code shelf in another warehouse from becoming the active context.
