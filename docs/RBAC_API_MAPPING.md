# OpenPartsFlow RBAC API Mapping

## Enterprise permission overrides

Organization roles provide stable defaults for employee-directory, audit,
reporting, and external-integration capabilities. Administrators may add an
explicit `allow`, apply an explicit `deny`, or reset a user to `inherit` through
the tenant-scoped permission matrix. Deny overrides the role default. Admin
permissions are immutable, and permission administration itself is never
delegable. All changes require a reason and append an audit event. See
[`ENTERPRISE_ACCESS_POLICIES.md`](ENTERPRISE_ACCESS_POLICIES.md).

These policy overrides do not weaken work-order ownership, registered-device,
claim-version, completion-password, inventory-custody, or tenant checks.

PostgreSQL deployments additionally force tenant read/write row-level security
on all tenant models. API/ORM authorization remains authoritative for roles,
ownership, devices, and field-level disclosure; RLS is the final organization
boundary. See [`POSTGRES_RLS.md`](POSTGRES_RLS.md).

## Work-order access model

OpenPartsFlow separates visibility, field execution, and management. Frontend capability flags are a usability aid only; every rule is enforced again by the API.

| Operation | Other engineer | Active claimant on bound device | Manager | Admin | Warehouse |
| --- | --- | --- | --- | --- | --- |
| View organization work-order pool and progress | Allow | Allow | Allow | Allow | Deny |
| View service context, service intelligence, parts, evidence, and history | Allow | Allow | Allow | Allow | Existing scoped read only |
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

`POST /api/work-orders/{id}/claim` requires an engineer Cookie or Bearer session plus a verified registered device. It uses one conditional database update, so concurrent claim attempts have a single winner.

`POST /api/work-orders/{id}/release` is restricted to managers/admins, requires a reason, clears the claim, increments `claim_version`, and records an audit event.

`GET /api/work-orders/{id}/service-intelligence` follows the shared read scope. It uses only tenant-scoped locked completions and published active exact-model knowledge. Another engineer may inspect its evidence and progress, but the response creates no write capability and omits financial values, customer signatures, commercial part fields, and device secrets.

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

Structured learning fields (`fault_type`, `error_code`, `environment_info`, `final_outcome`, `first_time_fix`, `is_rework`) are field evidence: only the claimed engineer/device or an explicitly attributed administrator correction may write them before evidence freeze. `repair_duration_minutes` is server-owned.

## Authentication safety

- Secure defaults: `RBAC_ENFORCE=true`, `LEGACY_HEADER_AUTH=false`.
- Every runnable environment forces these secure values, so stale pilot `.env` files cannot disable ownership enforcement.
- A legacy `X-User-Id` request may never claim or execute a work order.
- Claim and completion are not placed in the offline queue.
- Queued writes are scoped to organization/user/device and preserve the claim version so a released or reassigned claim cannot be replayed.

## Audit requirements

Claim, release, execution, approval, rejection, and completion actions record the actor, role, authentication method, device record, claim version, server timestamp, and action-specific metadata. Passwords and device secrets are never included.

The `audit.read` effective permission controls search and summaries; it defaults to managers and administrators. The tenant condition is explicit in each query in addition to the session-wide tenant filter.

The `audit.export` permission defaults to administrators and controls `POST /api/audit-logs/export`. A Bearer-authenticated caller must re-enter the current account password. The CSV uses the active filters, hardens spreadsheet-formula cells, returns a SHA-256 digest and row count, and then appends an `audit_log_exported` event containing the digest and filters. The password is discarded after verification and never enters the CSV, response metadata, or audit event. See [`AUDIT_LOGS.md`](AUDIT_LOGS.md).

## Inventory ledger visibility

`GET /api/inventory/ledger` and `GET /api/inventory/ledger/options` allow the
warehouse, manager, and administrator roles. Engineers and assistants are
denied. Every transaction, joined label, filter, count, and option query has an
explicit organization condition; options contain only parts, warehouses, and
users already referenced by the caller's tenant ledger. Responses are marked
`no-store`. The page is read-only: stock corrections must pass through an
authorized inventory count, replenishment, return, or other custody workflow.
See [`INVENTORY_LEDGER.md`](INVENTORY_LEDGER.md).

## Platform operations monitoring

`GET /health/live` and `GET /health/ready` are intentionally unauthenticated so load balancers and orchestrators can probe the process. They expose only uptime plus high-level database, schema, and worker state; they never expose tenant counts, URLs, errors, credentials, or configuration values.

`GET /api/platform/operations/summary` and
`GET /api/platform/operations/history` require `is_platform_admin=true`, not
merely the customer `admin` role. The endpoints deliberately remove the tenant
session scope only after that platform check. The summary aggregates actionable
counts across integration delivery, billing notices, backups, and restore
conflicts; history returns bounded, identity-free service samples. Customer
administrators, managers, engineers, warehouse users, assistants, API keys, and
unauthenticated callers are denied. Detailed worker exception messages and
instance identifiers are not retained in API responses; only high-level state
and the exception class are exposed to the platform operator. See
[`OPERATIONS_MONITORING.md`](OPERATIONS_MONITORING.md).

Background scheduler ownership is elected through the platform-global database
lease table. The platform summary exposes generation, expiration, current-run,
and next-run evidence but never the opaque host/process owner identifier.
Non-owner API replicas report healthy `standby`; every lease mutation requires
the exact owner plus generation fencing token. See
[`WORKER_LEASES.md`](WORKER_LEASES.md).

## Automated acceptance coverage

- Same-organization engineers all see the pool; cross-tenant data remains isolated.
- Only one engineer wins a claim.
- Another engineer, another device, legacy authentication, warehouse roles, and stale claim versions are rejected.
- Parts usage cannot spoof another `user_id` through either API path.
- Completion fails with an incorrect password and permanently records the correct engineer/device.
- Manager approval preserves engineer attribution.
- Other engineers can read the owner's parts and progress records but cannot mutate them.
- Service-intelligence tests prove published-only knowledge, deterministic ranking, shared engineer read access, and cross-tenant evidence exclusion.
- Administrators can correct unlocked records with their own audit attribution; managers cannot impersonate the field owner.
- Releasing a claim invalidates the prior user's device and queued claim generation.

## Enterprise operations analytics

| Operation | Engineer | Manager | Organization admin | Warehouse |
| --- | ---: | ---: | ---: | ---: |
| View operations analytics | Deny by default | Allow | Allow | Deny by default |
| Export completed-work-order detail | Deny by default | Deny by default | Allow with current password | Deny by default |

`reports.read` and `reports.export` are independently resolved through the
enterprise permission matrix. An administrator can delegate either capability
to a non-administrator, but an explicit deny takes precedence over role
defaults. All dashboard and export queries retain the tenant filter. Export
requires Bearer authentication and account-password reauthentication, rejects
oversized results, returns digest and row-count evidence, and records an audit
event. Metric grain and caveats are documented in
[`ENTERPRISE_ANALYTICS.md`](ENTERPRISE_ANALYTICS.md).

## Enterprise operations Agent

| Operation | Engineer | Manager | Organization admin | Warehouse |
| --- | ---: | ---: | ---: | ---: |
| Load Agent options and run history | Deny by default | Allow | Allow | Deny by default |
| Run a read-only evidence review | Deny by default | Allow | Allow | Deny by default |
| Mutate a work order, inventory, integration, or approval through Agent | Deny | Deny | Deny | Deny |

`agent.use` is independently delegable through the enterprise permission
matrix. Every query retains explicit tenant criteria plus session-wide tenant
scope. Engineer options and engineer-specific filters also require `users.read`,
so delegating Agent use does not implicitly disclose the employee directory. A
successful run consumes one AI request and records digest-only run and
audit evidence. The Agent has no business mutation tool; links lead to existing
role, ownership, device, password, version, and custody-protected workflows.
See [`ENTERPRISE_OPERATIONS_AGENT.md`](ENTERPRISE_OPERATIONS_AGENT.md).

## Commercial reporting access model

| Operation | Engineer | Manager | Organization admin | Platform admin |
| --- | --- | --- | --- | --- |
| View organization commercial report | Deny | Deny | Own organization | Own organization |
| Export organization commercial report | Deny | Deny | Own organization + current password | Own organization + current password |
| View selected-month platform comparison | Deny | Deny | Deny | Allow |
| Export platform comparison | Deny | Deny | Deny | Current password required |

Organization reports are generated while the normal tenant session filter is
active. Cross-customer report endpoints check the separate platform permission
before lifting that filter. CSV exports are online-only and create audit
evidence without retaining the confirming password or exported file contents.
Historical rows contain exact metered request counts but deliberately label
allowances and capacity as current state because contract-history snapshots do
not yet exist.

See [Commercial usage reporting](COMMERCIAL_REPORTING.md) for the response and
export contract.

## External integration role defaults

| Operation | Engineer | Manager | Admin | External API key |
| --- | --- | --- | --- | --- |
| View integrations and sync logs | Deny | Allow | Allow | Deny |
| Create/edit/deactivate integration | Deny | Deny | Allow | Deny |
| Rotate and reveal a new key once | Deny | Deny | Allow | Deny |
| Create an inbound work order | Deny | Deny | Existing user API only | Allow |
| Update linked unclaimed intake data | Deny | Deny | Existing user API only | Allow |
| Update claimed/frozen field evidence | Owner workflow only | Deny | Audited correction routes only | Deny |
| Claim/start/complete/use parts/change inventory | Existing role rules | Existing role rules | Existing role rules | Deny |

External keys establish the owning organization before any source link, log, or work-order query occurs. Only the key hash is stored. The raw key appears once at creation or rotation, and a deactivated or rotated key returns `401`.

`integrations.read` and `integrations.manage` user overrides can intentionally
change the human-user defaults in the table. API keys cannot receive these
permissions, and every integration endpoint continues to apply tenant scope.

`POST /api/external/v1/work-orders` requires a unique `X-Idempotency-Key`. Successful replay is read-only, changed payload reuse returns `409`, and failed events can retry with an incremented attempt count. Allowed field mappings are limited to administrative intake data and `open`/`scheduled` status.

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

## Controlled visual recognition

| Operation | Claim owner engineer | Other engineer | Manager | Admin | Warehouse |
|---|---:|---:|---:|---:|---:|
| Create standalone observation | Allow | Allow | Allow | Allow | Allow |
| Create/confirm work-order-linked observation | Allow, bound device + claim version | Deny | Deny | Allow | Deny |
| Run AI on own standalone observation | Allow | Own only | Own only | Allow | Own only |
| Run AI on work-order-linked observation | Allow, bound device + claim version | Deny | Deny | Allow | Deny |
| View organization recognition queue | Allow | Allow | Allow | Allow | Allow |
| Administrator-confirm candidate | Deny | Deny | Deny | Allow | Deny |
| Verify actual work-order usage | Deny | Deny | Deny | Allow | Deny |
| Promote to trusted knowledge | Deny | Deny | Deny | Allow | Deny |
| Reject with reason | Deny | Deny | Deny | Allow | Deny |

Recognition actions never mutate inventory. AI retries stop after human confirmation, and a candidate can reach trusted knowledge only after server-recorded use of the same part on the linked work order.

## Machine service knowledge

| Operation | Engineer | Manager | Admin | Warehouse |
|---|---:|---:|---:|---:|
| Search/read published active profiles | Allow | Allow | Allow | Allow |
| View drafts, archived entries, inactive profiles | Deny | Allow | Allow | Deny |
| Create/update machine profiles | Deny | Allow | Allow | Deny |
| Create/update draft entries | Deny | Allow | Allow | Deny |
| Generate drafts from a completed same-model work order | Deny | Allow | Allow | Deny |
| Upload protected photo/video draft | Deny | Allow | Allow | Deny |
| Publish, archive, or reopen entries | Deny | Deny | Allow | Deny |
| Modify published content in place | Deny | Deny | Deny | Deny |
| Preview protected draft/archived media | Deny | Allow | Allow | Deny |
| Read protected published media | Allow | Allow | Allow | Allow |

All reads and writes are tenant-scoped. Optional source work orders must already be completed and locked and must match the profile model. Work-order extraction is idempotent and never auto-publishes. Recommended-part drafts require a labeled successful first-time repair; other usage is reference-only. Uploaded media uses file-header validation, private random storage keys, and authenticated delivery. Engineer and warehouse responses use a redacted part summary that excludes cost, supplier, and other commercial fields. Frontend capability flags mirror these rules but do not replace API enforcement.

## Billing lifecycle

| Operation | Engineer | Manager | Org admin | Platform admin | Signed provider |
|---|---:|---:|---:|---:|---:|
| Read organization billing/notices | Deny | Deny | Allow while subscription access is available | Home tenant only | Deny |
| Acknowledge organization notice | Deny | Deny | Allow, matching version | Home tenant only | Deny |
| Bind provider references | Deny | Deny | Deny | Allow, current-password reauthentication | Deny |
| List all billing events/notices | Deny | Deny | Deny | Allow | Deny |
| Reconcile all notices | Deny | Deny | Deny | Allow | Deny |
| Submit lifecycle event | Deny | Deny | Deny | Deny | HMAC + timestamp + exact bound references |

Provider events never authorize user actions and do not bypass tenant filters.
They may update only the documented commercial lifecycle fields and retain no
raw payload or payment-method data.

## Multi-region inventory

| Operation | Engineer | Manager | Admin | Warehouse |
|---|---:|---:|---:|---:|
| Read regions, summaries, and cross-region history | Deny | Allow | Allow | Allow |
| Create/update regions | Deny | Allow | Allow | Deny |
| Assign warehouse region with reason | Deny | Allow | Allow | Deny |
| Same-region generic main-warehouse transfer | Deny | Allow | Allow | Allow |
| Cross-region generic main-warehouse transfer | Deny | Allow | Allow | Deny |
| Generic transfer involving a vehicle | Deny | Deny | Deny | Deny |

Region and warehouse reads/writes remain tenant scoped. Version checks protect
region edits, prior-region checks protect warehouse assignments, and every
cross-region transfer retains region identities in the audit event. Vehicle
inventory continues through replenishment receipt, work-order usage, and vehicle
return custody only.

## Customer data backups

| Operation | Engineer | Manager | Org admin | Platform admin |
|---|---:|---:|---:|---:|
| List organization export evidence | Deny | Deny | Allow | Home tenant only |
| Generate and download portable backup | Deny | Deny | Allow, current-password reauthentication | Home tenant only |
| List restore rehearsals | Deny | Deny | Allow | Home tenant only |
| Validate restore archive | Deny | Deny | Allow, current-password reauthentication | Home tenant only |
| Approve/reject restore plan | Deny | Deny | Allow, password + matching version | Home tenant only |
| Apply exact approved archive | Deny | Deny | Allow, password + archive/plan/version match | Home tenant only |
| Roll back applied fields | Deny | Deny | Allow, password + integrity/drift/version checks | Home tenant only |
| Preview disaster-recovery retention candidates | Deny | Deny | Allow | Home tenant only |
| Change retention policy | Deny | Deny | Allow, password + reason + matching settings version | Home tenant only |
| Clean eligible recovery evidence | Deny | Deny | Allow, password + reason + matching settings version | Home tenant only |

Exports use the same tenant model registry as application reads. Authentication
hashes, API key hashes, invitation tokens, device secrets, and DNS verification
secrets are excluded. The archive contains sensitive business and customer data
and is streamed only to the authenticated requester.

Controlled restores never mutate authentication, billing, audit, ledger, or
custody records. The application boundary updates existing allowlisted
master/configuration/knowledge rows and can rehydrate deleted allowlisted rows
only after global-id, unique-key, tenant, and foreign-key checks; conflicts
block approval. Manifested public/private media is written only through the
same administrator-approved exact-archive workflow, with configured-root path
containment, protected before/after evidence, drift checks, and file rollback.
Retention cleanup never selects active approvals, unexpired rollback windows,
customer business records, or audit logs.
