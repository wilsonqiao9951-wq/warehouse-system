# OpenPartsFlow development progress

## Baseline

- Starting commit: `c759ea6` (`feat: add offline sync center`)
- Delivery strategy: sellable workflow first, intelligence second, platform capabilities last.
- Required batch gates: migration, backend tests, frontend production build, security review, Git commit, push, CI verification.

## 2026-07-11 — Phase 1 field completion foundation

Status: implemented and locally verified.

Delivered:

- Pause an in-progress work order with status history and audit trail.
- Capture the repair result during completion.
- Capture a structured field checklist during completion.
- Capture customer signature name/data and signing timestamp.
- Store completion evidence on the locked work order.
- Add the mobile field-completion form to work-order details.
- Add Alembic revision `20260711_0014`.
- Extend technician-flow coverage for pause, resume, completion evidence, and audit events.

Verification:

- Backend: 34 tests passed.
- Database: clean SQLite migration from base through `20260711_0014` passed.
- Frontend: Next.js production build passed (27 static pages).
- Dependency review: 8 total findings (4 moderate, 4 high); production-only audit reports 2 findings in Next.js/PostCSS (1 moderate, 1 high). The automated remediation upgrades Next.js 14 to 16, so it requires a separate tested migration batch rather than an unreviewed `--force` update.

Next Phase 1 work:

- Completion-policy configuration per organization/template.

## 2026-07-11 — Phase 1 work-order voice notes

Status: implemented.

Delivered:

- Mobile microphone recording with start/stop/upload controls.
- Work-order audio playback with duration display.
- Tenant- and work-order-scoped audio upload/list APIs.
- Audio file-header validation for WebM, Ogg, WAV, M4A, and MP3.
- Configurable 15 MB audio upload limit.
- Transcription status and transcript fields reserved for the AI transcription batch.
- Audit event for voice-note creation.
- Alembic revision `20260711_0015`.

## 2026-07-11 — Phase 1 drawn customer signature

Status: implemented and locally verified.

Delivered:

- Touch- and pointer-compatible customer signature canvas.
- Clear and re-sign controls before completion.
- Required drawn signature in the mobile completion workflow.
- Server-side PNG data URL and 1.5 MB size validation.
- Read-only signature, checklist, and repair-result display after work-order locking.
- API regression coverage for malformed signature rejection.

Verification:

- Targeted backend flow: 3 tests passed.
- Frontend: Next.js production build passed (27 static pages).

## 2026-07-11 — Phase 1 customer and equipment service context

Status: implemented.

Delivered:

- Tenant-scoped customer and equipment master records.
- Optional customer/equipment links on work orders while preserving legacy snapshot fields.
- Automatic snapshot defaults from linked profiles when a work order is created.
- Engineer-safe service-context API with completed history and aggregated parts used.
- Exact legacy fallback matching by customer/site and machine model.
- Mobile customer, equipment, and expandable repair-history panels.
- Removed unsafe quick-complete actions that bypassed completion evidence.
- Corrected frontend list limits that previously exceeded API validation limits.
- Expanded automatic tenant filtering to all organization-owned models.
- Alembic revision `20260711_0016` with history-query indexes.

Verification:

- Backend: 39 tests passed, including tenant registry, cross-tenant access, relationship mismatch, history scope, and parts aggregation.
- Database: existing migration chain at `0015` upgraded successfully to `0016` without relying on application startup compatibility hooks.
- Frontend: Next.js production build passed (27 static pages).
- Security: no new packages; production audit remains at the recorded Next.js/PostCSS baseline (1 high, 1 moderate) pending the planned framework migration.

## 2026-07-11 — Phase 1 configurable completion policies

Status: implemented and verified.

Delivered:

- Organization default completion policy with normalized job-type overrides.
- Configurable requirements for repair results, customer signatures, field photos, checklist completion, parts usage, and manager approval.
- Server-side evidence enforcement across direct API calls and the mobile UI.
- Engineer completion requests with frozen evidence while approval is pending.
- Manager/admin approval and rejection actions with audit/status history.
- Administrator settings UI for creating and editing policies.
- Blocked completion bypasses through generic create, PATCH, Excel import, and status-timeline APIs.
- Locked and pending-approval work orders reject parts, photos, voice notes, and other evidence mutations.
- Signature payloads now require valid base64 PNG data.
- Secured the deprecated parts-usage endpoint and server-owned photo uploader identity.
- Alembic revision `20260711_0017`.

Verification:

- Backend: 42 tests passed.
- Database: existing schema upgraded through `0016 → 0017` successfully.
- Frontend: Next.js production build passed (27 static pages).
- Security: no new packages; production audit remains at the known Next.js/PostCSS baseline (1 high, 1 moderate).

## 2026-07-11 — Shared engineer pool and device-bound work-order ownership

Status: implemented and locally verified.

Delivered:

- All same-organization engineers can view the shared work-order pool, progress history, parts usage, photos, voice notes, repair information, claimant, and completer.
- Atomic online claim endpoint with a single winner under competing claim attempts.
- Registered phone/browser identity backed by a stable random device ID and a high-entropy device secret stored only as a server-side hash.
- Work-order ownership bound to engineer account, registered device, claim timestamp, and monotonically increasing claim version.
- Owner-only engineer writes across start/pause, field edits, parts, photos, voice, QC, status, returned equipment, completion, and completion requests.
- Administrator correction access with administrator audit attribution; managers retain approval/rejection/release workflows but cannot impersonate the field owner.
- Completion password re-verification and immutable completed engineer/device attribution, kept separate from manager approval attribution.
- Server-owned parts/photo attribution so clients cannot submit another user's identity.
- Sensitive response redaction for non-owner engineers while retaining operational progress visibility.
- Mobile Job Pool, My Claimed Jobs, read-only detail states, claim/release controls, device-aware login, and completion-password UI.
- Offline queue isolation by account, device, work order, and claim version; verified state transitions remain online-only and stale claim generations cannot replay.
- Secure defaults (`RBAC_ENFORCE=true`, `LEGACY_HEADER_AUTH=false`) forced in every runnable environment, plus removal of the frontend legacy identity fallback.
- Safe local startup update: a clean `main` branch fast-forwards from GitHub when available, preserves dirty/offline work, and applies Alembic migrations before launching; containers also migrate before serving.
- Alembic revision `20260711_0018`.

Verification:

- Backend: 49 tests passed, including shared visibility, owner/admin/manager boundaries, competing claims, device mismatch, stale claim version, legacy/warehouse denial, completion authentication, manager approval attribution, and parts identity spoofing.
- Database: full base-to-`0018` migration, `0018 → 0017` downgrade, and `0017 → 0018` re-upgrade passed on SQLite.
- Frontend: Next.js production build passed with type/lint validation and 27 static pages.
- Source hygiene: `git diff --check` passed and no frontend `X-User-Id`/legacy-auth fallback remains.
- Dependency review: production audit reports the existing Next.js/PostCSS baseline (1 high, 1 moderate); the available automatic fix is a breaking Next.js 14 → 16 upgrade and remains isolated to a separate framework-migration batch.

## 2026-07-11 — Phase 2 replenishment custody and vehicle receipt

Status: implemented and verified.

Delivered:

- Replaced free-form replenishment status changes with the strict `requested → picking → shipped → received → completed` custody workflow.
- Restricted picking, shipping, completion, and eligible cancellation to warehouse users and administrators. Managers can create and supervise replenishment requests but cannot perform custody transitions.
- Restricted vehicle receipt to the exact target engineer using their Bearer-authenticated account, active registered device, and current account password.
- Validated that a van destination remains active and assigned to the same engineer before receipt.
- Added `expected_version` optimistic concurrency control; stale actions fail with `409` instead of overwriting newer custody state.
- Reserved picking quantities when calculating available source stock so other inventory writes cannot consume committed pick stock.
- Posted a linked source-warehouse `OUTBOUND` transaction at shipment and a linked destination-vehicle `INBOUND` transaction at receipt.
- Added unique request/stage transaction links so retries cannot create duplicate shipment or receipt inventory movements.
- Limited cancellation to `requested` and `picking`, required a reason, and resolved the originating low-stock notification so a cancelled task does not create a duplicate request loop.
- Resolved the source low-stock notification only after a received request is completed.
- Recorded requester, picker, shipper, receiver, receiving device, completer, canceller, timestamps, transaction IDs, and cancellation reason.
- Added audit events for request, pick, ship, receive, complete, cancel, and historical reconciliation with prior/new state or resolution, prior/new version, warehouses, target engineer, reason, quantity, and inventory transaction attribution.
- Added role-scoped replenishment reads, server-calculated `can_start_picking`, `can_ship`, `can_receive`, `can_complete`, `can_cancel`, and `can_reconcile` flags, plus the authenticated `GET /api/inventory/my-van` endpoint.
- Added idempotent manual first-fill requests for assigned vehicles through `POST /api/inventory/replenishment-requests`, requiring a business reason and organization-scoped `client_request_id`.
- Added administrator-only reconciliation for flagged legacy rows. It requires current password verification, a reason, matching version, a status-compatible `reset_requested` or `accept_historical` resolution, and no linked inventory movements.
- Added warehouse stage-grouped custody UI and an engineer My Van receipt workflow with password confirmation and immediate vehicle-balance refresh.
- Marked alert/manual request creation, custody transitions, and reconciliation as online-only; request payloads, password step-ups, and inventory state changes never enter the offline queue.
- Restricted engineer work-order parts consumption to that engineer's assigned vehicle warehouse.
- Classified any warehouse owned by an engineer as a vehicle, automatically normalized new engineer-owned warehouses to `van`, and rejected inactive/non-engineer vehicle ownership.
- Prevented vehicles from serving as replenishment sources and blocked generic inventory transactions and opening-inventory preview/commit from changing vehicle stock.
- Restricted the generic inventory endpoint to `INBOUND`, `OUTBOUND`, `TRANSFER`, and `DAMAGE`; `RETURN` and `WORK_ORDER_USED` must use their authenticated business workflows.
- Enabled SQLite foreign-key enforcement and busy timeout on every connection, and serialized inventory-affecting custody writes with `BEGIN IMMEDIATE`; PostgreSQL continues to use row locks.
- Added Alembic revision `20260711_0019`; legacy `picking`, `shipped`, `received`, and `completed` rows are flagged `requires_reconciliation`, while the three intermediate labels are also reopened as `requested` because they lacked trustworthy inventory movements or custody evidence.
- Blocked `0019` downgrade whenever linked replenishment inventory movements exist, preventing custody history from being silently orphaned.

Verification:

- Backend: full suite passed, 66 tests.
- Replenishment custody/security: 14 targeted tests passed.
- File-backed SQLite concurrency: 2 targeted contention tests passed.
- Database: fresh base-to-`0019`, empty `0019 → 0018 → 0019`, and legacy compatibility database-to-`0019` paths passed.
- Downgrade safety: a linked replenishment movement blocks `0019 → 0018` before any DDL is applied.
- Frontend: Next.js 16.2.10 production build passed with ESLint 9/type validation and all 26 static routes.
- Dependency security: npm resolved to 0 known vulnerabilities after the Next.js 16 upgrade and the PostCSS security override.
- Source hygiene: frontend and documentation `git diff --check` passed.
