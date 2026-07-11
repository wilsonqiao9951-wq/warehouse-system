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
