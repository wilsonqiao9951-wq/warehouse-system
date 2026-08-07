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

## 2026-07-12 - Phase 2 vehicle return custody

Status: implemented and verified.

Delivered:

- Added engineer-owned vehicle return requests with organization-scoped idempotency keys.
- Added warehouse approval and vehicle-stock reservation so work-order usage and competing returns cannot consume committed units.
- Added exact-engineer, registered-device, current-password handover; administrators and warehouse users cannot impersonate this step.
- Added linked vehicle `OUTBOUND` and warehouse `INBOUND` transactions with unique stages, copied cost, actor/device timestamps, and audit history.
- Added warehouse receipt validation, pre-handover cancellation, optimistic versions, tenant isolation, and retry safety.
- Added My Van request/handover UI and warehouse approval/receipt UI; every mutation is online-only.
- Added Alembic revision `20260712_0020` and downgrade protection for linked return movements.

Verification:

- Backend: full suite passed, 70 tests.
- Vehicle/replenishment custody target suite: 18 tests passed.
- Database: fresh base-to-`0020` and empty `0020 -> 0019 -> 0020` passed on SQLite.
- Frontend: ESLint and Next.js 16.2.10 production build passed for all 26 static routes.
- Source hygiene: `git diff --check` passed.

## 2026-07-12 - Phase 2 inventory count custody

Status: implemented and verified.

Delivered:

- Added `draft -> submitted -> approved` warehouse counts with pre-approval cancellation.
- Added physical entry, submission book snapshots, approval-time recalculation, explicit variances, optimistic versions, tenant isolation, and audit events.
- Warehouse users count and submit; managers are read-only; administrators re-enter their password before uniquely linked adjustment movements change the ledger.
- Added the Inventory Counts workspace and made all count mutations online-only.
- Excluded engineer vehicle warehouses and added Alembic revision `20260712_0021` with downgrade protection.

Verification:

- Inventory count security/workflow tests: 2 passed.
- Backend: full suite passed, 72 tests.
- Database: fresh base-to-`0021` and empty `0021 -> 0020 -> 0021` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.10 production build passed for all 27 static routes.
- Source hygiene: `git diff --check` passed.

## 2026-07-12 - Phase 2 warehouse and location scanning

Status: implemented and verified.

Delivered:

- Added warehouse and shelf/bin label tokens using server IDs plus current codes; stale or altered labels are rejected.
- Added warehouse-first location validation, duplicate-code ambiguity protection, inactive-location checks, and cross-warehouse rejection.
- Added registered label discovery for QR/barcode generation and audit events for warehouse, location, and part scans.
- Rebuilt the mobile scan workspace as a required `warehouse -> shelf/bin -> part` flow with camera and manual scanner input.
- Bound part quantity results to the validated location and prevented engineers from probing inventory outside their assigned vehicle.

Verification:

- Location/scan target suite: 7 passed.
- Backend: full suite passed, 75 tests; migration head remains `20260712_0021` because this batch adds no database tables.
- Frontend: ESLint, TypeScript, and Next.js 16.2.10 production build passed for all 27 static routes.
- Source hygiene: `git diff --check` passed.

## 2026-07-12 - Phase 2 replenishment request approval

Status: implemented and verified.

Delivered:

- Added manager/administrator approval or reason-required rejection before warehouse picking.
- Separated business authorization from physical custody: warehouse users cannot self-approve and pending requests cannot reserve or move stock.
- Added approver/rejector identity, timestamps, rejection evidence, capability-driven UI, timeline display, optimistic checks, and audit events.
- Added Alembic revision `20260712_0022`; historical in-progress custody is marked approved and rejected rows downgrade to cancelled without losing the reason.

Verification:

- Replenishment custody/approval suite: 19 passed.
- Backend: full suite passed, 76 tests.
- Database: fresh base-to-`0022` and empty `0022 -> 0021 -> 0022` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.10 production build passed for all 27 static routes.
- Source hygiene: `git diff --check` passed.

## 2026-07-12 - Phase 3 work-order learning data foundation

Status: implemented and verified.

Delivered:

- Added fault type, error code, environment information, final outcome, first-time-fix, rework, and server-measured repair duration.
- Integrated learning capture into the authenticated engineer completion form and immutable completion evidence lifecycle.
- Added structured learning details to equipment service history and completion audit metadata.
- Preserved legacy compatibility by allowing historical unknown values while new mobile completions explicitly capture the result fields.
- Added indexed lookup fields and Alembic revision `20260712_0023` with a non-negative duration constraint.

Verification:

- Work-order flow, completion policy, and ownership target suites: 17 passed.
- Backend: full suite passed, 77 tests.
- Database: fresh base-to-`0023` and empty `0023 -> 0022 -> 0023` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.10 production build passed for all 27 static routes.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 3 explainable part recommendation ranking

Status: implemented and verified.

Delivered:

- Replaced simple machine/job aggregate ordering with tenant-scoped completed-work-order ranking.
- Added ordered matching for machine plus job type, machine, fault type, error code, similar symptoms, and job type.
- Added historical usage count, average recommended quantity, first-time repair success, average repair duration, current available quantity, best warehouse/bin, reason, and confidence.
- Preferred the assigned engineer's vehicle as the displayed stock location while retaining total organization availability.
- Deducted active inventory reservations and excluded unlabeled legacy outcomes from the success denominator.
- Preserved legacy aggregate fallback with visibly lower capped confidence.
- Added mobile departure-checklist metrics plus ranking, inventory, compatibility, and tenant-isolation tests.
- No database migration is required; this batch computes from the Phase 3 learning fields introduced by `20260712_0023`.

Verification:

- Recommendation ranking, legacy fallback, and tenant isolation target suite: 3 passed.
- Backend: full suite passed, 79 tests.
- Frontend: ESLint, TypeScript, and Next.js 16.2.10 production build passed for all 27 static routes.
- Database: no migration required; schema head remains `20260712_0023`.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 4 controlled visual part candidates

Status: implemented and verified.

Delivered:

- Added tenant-scoped visual observations and ranked candidate records.
- Generated candidates from visible label text, machine compatibility, confirmed photo memory, and completed-job recommendations while clearly separating these signals from future OCR/CV providers.
- Enforced AI candidate, employee confirmation, administrator confirmation, actual work-order usage verification, and trusted-knowledge states.
- Added reason-required rejection, optimistic versions, actor/timestamp evidence, audit events, independent employee/admin accounts, and one-selected-candidate protection.
- Restricted work-order-linked evidence to the claiming engineer's registered device and claim generation or an administrator.
- Ensured recognition review never creates or changes inventory transactions.
- Promoted only fully verified results into high-confidence machine/part knowledge.
- Rebuilt the mobile photo-memory page as a candidate capture and review queue with server-driven actions.
- Added Alembic revision `20260728_0024` and the controlled visual recognition API contract.

Verification:

- Visual candidate workflow, state, inventory-isolation, tenant-isolation, and work-order ownership target suite: 4 passed.
- Fresh base-to-`0024` and empty `0024 -> 0023 -> 0024` passed on SQLite.
- Frontend ESLint, TypeScript, and Next.js production build passed for all 27 static routes.
- Backend: full suite passed, 83 tests.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 5 governed machine service knowledge

Status: implemented and verified.

Delivered:

- Added unique tenant-scoped machine profiles with manufacturer, model, equipment type, summary, active state, and optimistic versioning.
- Added structured common-fault, repair-step, tool, caution, common-error, photo, video, and service-note entries.
- Added a governed `draft -> published -> archived` lifecycle; only administrators publish, archive, or reopen knowledge.
- Made published guidance immutable so a curator cannot silently replace instructions already used by field engineers.
- Allowed managers and administrators to link tenant parts and completed same-model work orders as evidence.
- Added completed-work-order count, labeled first-time-fix rate, average repair duration, latest completion, and confirmed machine-part summaries.
- Kept commercial part fields such as cost and supplier out of engineer and warehouse knowledge responses.
- Added tenant filtering, role enforcement, optimistic concurrency, safe media URL validation, and audit events.
- Added a responsive knowledge workspace, all-role navigation, manager draft editor, administrator review actions, and direct work-order-to-machine-knowledge links.
- Added Alembic revision `20260728_0025` and the machine knowledge governance contract.

Verification:

- Machine knowledge publishing, evidence, immutable-content, version, media validation, and tenant-isolation target suite: 3 passed.
- Backend: full suite passed, 86 tests.
- Database: fresh base-to-`0025` and empty `0025 -> 0024 -> 0025` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 28 static routes.
- Dependency security: upgraded Next.js to 16.2.12 and overrode PostCSS 8.5.24 plus Sharp 0.35.3; the production npm audit reports 0 vulnerabilities. Remaining npm audit findings are development-only ESLint/minimatch advisories whose automatic fix requires a separate breaking ESLint 10 migration.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 5 work-order and media knowledge capture

Status: implemented and verified.

Delivered:

- Added one-click curator extraction from completed same-model work orders into fault, repair-result, and used-part drafts.
- Added unique origin keys and duplicate skipping so retries cannot create duplicate knowledge.
- Classified parts from labeled successful first-time repairs as recommended; rework, failed, or unlabeled usage remains reference-only.
- Added recommended, alternative, consumable, and reference roles, including primary-part substitution and installation location.
- Added safe tenant validation for both the linked part and the primary part an alternative replaces.
- Added validated photo/video uploads for JPEG, PNG, GIF, WebP, HEIC, MP4, MOV, and WebM with image and media size limits.
- Stored knowledge media outside the public upload mount with random private storage keys.
- Added authenticated media delivery: curators can preview drafts, while engineers and warehouse users can open media only after administrator publication.
- Prevented protected media URLs/types from being replaced during ordinary draft editing.
- Marked every knowledge mutation as online-only in the mobile client.
- Extended the mobile workspace with work-order extraction, protected capture/upload, part-role, substitution, installation-location, and secure preview controls.
- Added Alembic revision `20260728_0026`.

Verification:

- Knowledge capture, governance, idempotency, part-role, tenant, protected-media, and publication target suite: 6 passed.
- Backend: full suite passed, 89 tests.
- Database: fresh base-to-`0026` and empty `0026 -> 0025 -> 0026` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 28 static routes.
- Production dependency audit: 0 vulnerabilities.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 5 explainable service intelligence

Status: implemented and verified.

Delivered:

- Added a read-only work-order intelligence API for every same-organization operational role.
- Ranked up to five locked completed work orders by exact machine, work type, fault, error code, and symptom similarity with a visible score and match reason.
- Added exact-model completed-job analysis for labeled first-time-fix rate, rework rate, average repair duration, common fault types, and common error codes.
- Added explicit no-evidence, low-sample, and elevated-rework warnings so historical statistics are not presented as a certain diagnosis.
- Ranked up to eight administrator-published entries from the active exact-model knowledge profile against the current error code, fault terms, and symptoms.
- Kept draft, archived, inactive-profile, unlocked, incomplete, and cross-tenant evidence out of every result.
- Returned service-safe part and historical fields without financial values, customer signatures, supplier/cost data, or device secrets.
- Added mobile work-order metrics, published guidance with authenticated media access, and expandable similar-case outcomes/parts.
- Preserved the ownership boundary: other engineers can read the intelligence for a shared work order but still cannot modify it.
- No database migration is required; this batch computes from the governed Phase 3 and Phase 5 evidence already stored at schema head `20260728_0026`.

Verification:

- Service intelligence ranking, publication, shared visibility, safe-response, and tenant-isolation target suite: 3 passed.
- Backend: full suite passed, 92 tests.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 28 static routes.
- Production dependency audit: 0 vulnerabilities.
- Database: no migration required; schema head remains `20260728_0026`.
- Source hygiene: `git diff --check` passed.

## 2026-07-28 - Phase 6 external integration foundation

Status: implemented and verified.

Delivered:

- Added tenant-scoped external integration records for AppSheet, generic REST, Google Sheets, CRM, ERP, and WMS connection labels.
- Added high-entropy API keys whose raw value is shown only on creation/rotation; only a SHA-256 hash and lookup prefix are stored.
- Added administrator-only creation, editing, activation, and key rotation with optimistic versions and audit events.
- Added manager read access to mappings and synchronization logs without credential mutation rights.
- Added configurable canonical-to-external work-order field mapping with a strict intake-only allowlist.
- Added `POST /api/external/v1/work-orders` for authenticated create/update by stable external row ID.
- Added per-integration work-order links so repeated events update the correct record without mixing external identifiers into the work-order table.
- Added per-integration idempotency keys and request hashes: exact replay returns the original result, changed-body reuse is rejected, and failed events can retry with an incremented attempt count.
- Added processed/failed synchronization logs with changed fields, safe errors, linked work orders, attempts, and timestamps.
- Blocked mappings for engineer/device ownership, completion, signatures, financials, part usage, learning outcomes, and inventory.
- Blocked every external update after claim, evidence freeze, or completion so the authenticated engineer workflow remains authoritative.
- Added tenant isolation for integrations, links, logs, Webhook authentication, work orders, and integration audit events.
- Added a responsive `/integrations` workspace with one-time key reveal, mapping editor, key rotation/deactivation, Webhook example, and sync log.
- Added Alembic revision `20260728_0027`.

Verification:

- External key, mapping, idempotency, retry, ownership-boundary, role, rotation, deactivation, audit, and tenant target suite: 4 passed.
- Backend: full suite passed, 96 tests.
- Database: fresh base-to-`0027` and empty `0027 -> 0026 -> 0027` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 29 static routes.
- Production dependency audit: 0 vulnerabilities.
- Source hygiene: `git diff --check` passed.

## 2026-07-29 - Phase 6 external delivery runtime

Status: implemented and verified.

Delivered:

- Added API-key-authenticated external inventory, linked work-order status, and explainable recommendation queries.
- Kept external responses service-safe by excluding cost, supplier, signature, credential, and device-secret fields.
- Added administrator-configured HTTPS callback URL and subscriptions for work-order status, completion, and part-usage events.
- Rejected credential-bearing, non-HTTPS, loopback, link-local, private, reserved, and local callback targets; production delivery also checks resolved addresses and never follows redirects.
- Queued callbacks in the same database transaction as the authoritative status or part-usage change, so external downtime cannot roll back a field action.
- Added canonical event payloads, stable idempotency keys, HMAC-SHA256 signatures, delivery headers, response evidence, and safe bounded errors.
- Added concurrency-safe event claiming plus automatic 1-minute, 5-minute, 30-minute, 2-hour, and 6-hour retry scheduling.
- Added terminal failure after five attempts and administrator requeue from the integration workspace.
- Added an application-lifecycle delivery worker with configurable enablement and polling interval.
- Extended the integration workspace with callback configuration, event subscriptions, direction/event visibility, and retry controls.
- Preserved organization isolation for inventory, linked work orders, recommendations, event queue records, and delivery administration.
- Added Alembic revision `20260729_0028`.

Verification:

- External read, safe-response, event queue, signature, retry, unsafe-target, and tenant-isolation target suite: 5 passed.
- Backend: full suite passed, 101 tests.
- Database: fresh base-to-`0028` and empty `0028 -> 0027 -> 0028` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 29 static routes.
- Production dependency audit: 0 vulnerabilities; Python dependency consistency check passed.
- Source hygiene: `git diff --check` passed.

## 2026-07-29 - Phase 7 configurable work-order forms

Status: implemented and verified.

Delivered:

- Added organization-owned work-order form templates with administrator editing and manager read-only review.
- Added visual configuration for ordered text, long-text, number, yes/no, date, choice, photo, and signature fields.
- Added typed defaults, exact machine/job applicability, initial work-order status, activation, and optimistic template versions.
- Added completion-required, photo, signature, manager-approval, notification, inventory-declaration, and AI-learning controls.
- Snapshotted the assigned template version, schema, rules, and defaults onto each new work order so template edits cannot rewrite historical jobs.
- Added typed, bounded, optimistic form value updates and unknown-field rejection.
- Preserved shared engineer visibility while limiting mutations to an administrator or the claiming engineer's authenticated account, registered phone, and current claim generation.
- Froze configured evidence during approval and after completion.
- Enforced required configured evidence through every server completion path and merged template approval requirements into the existing manager workflow.
- Added mobile dynamic inputs, protected camera upload, drawn signatures, missing-evidence status, and verified saves.
- Kept declared inventory impact separate from the custody ledger; form values cannot create stock movements.
- Added Alembic revision `20260729_0029` and the configurable-form operator/API guide.

Verification:

- Configurable-form snapshot, validation, approval, ownership, role, and applicability target suite: 5 passed.
- Backend: full suite passed, 106 tests.
- Database: fresh base-to-`0029` and empty `0029 -> 0028 -> 0029` passed on SQLite.
- Frontend: TypeScript and Next.js 16.2.12 production build passed for all 30 static routes.
- Production dependency audit: 0 vulnerabilities; Python dependency consistency check passed.
- Source hygiene: `git diff --check` passed.

## 2026-07-29 - Phase 7 configured-form action automation

Status: implemented and verified.

Delivered:

- Upgraded notification and inventory-impact field flags from audit metadata into durable, tenant-scoped follow-up tasks.
- Generated tasks only for real field changes and keyed them by work order, form revision, field, and action type for retry safety.
- Kept submitted values and signatures out of the task queue while preserving the source field, template, job, actor, and revision.
- Added strict pending, acknowledged, and resolved states with optimistic versions and immutable actor/timestamp evidence.
- Limited notification processing to managers/administrators and inventory-review processing to warehouse staff/administrators.
- Required resolution notes for inventory reviews and kept every actual stock change inside the dedicated custody workflows.
- Added read-only task progress for all engineers viewing a shared work order without granting global queue or mutation access.
- Added the `/form-actions` role-scoped inbox and linked it to mobile work-order details and warehouse workflows.
- Added Alembic revision `20260729_0030`.
- Protected downgrade while any configured-form action evidence exists.

Verification:

- Form-action generation, no-op/idempotency, role, transition, optimistic-version, shared-progress, and tenant-isolation target suite: 3 passed.
- Combined configured-form, action, and tenant regression suite: 12 passed.
- Backend: all 109 tests passed in two bounded modules (37 plus 72) after the desktop shell's aggregate child-process timeout was isolated from test results.
- Database: fresh base-to-`0030` and empty `0030 -> 0029 -> 0030` passed on SQLite.
- Frontend: TypeScript and Next.js 16.2.12 production build passed for all 31 static routes.
- Frontend ESLint passed; production dependency audit reports 0 vulnerabilities.
- Python dependency consistency check and source hygiene passed.

## 2026-07-29 - Phase 8 secure offline configured-form sync

Status: implemented and verified.

Delivered:

- Enabled offline configured-form saves from the engineer mobile workbench while keeping verified workflow and inventory mutations online-only.
- Bound every retained operation to the originating account, registered device, work order, and exact claim generation.
- Added stable queue identifiers, operation classification, pending/failed/conflict/blocked states, attempt evidence, and last-error evidence.
- Merged repeated offline saves only when their account, device, work order, claim generation, endpoint, and expected server form version match.
- Preserved unsynchronized work across sign-out while keeping it invisible and unreplayable to another account or device.
- Refreshed authoritative work-order claim generations before replay and blocked released or reclaimed work without discarding it.
- Retained server form-version conflicts locally and prevented stale offline values from silently overwriting current server data.
- Classified authentication, authorization, and missing-claim failures as blocked while retaining transient network/server failures for retry.
- Added startup and network-restoration sync attempts.
- Expanded `/sync-center` with operation type, work order, timestamps, claim generation, attempt counts, blocked ownership, conflict status, explicit retry for recoverable failures, and locked conflicts for administrator resolution.
- Kept queued field and signature values out of sync-center display and application messages.
- Added the offline-form security and operating rules to the configurable-form guide.

Verification:

- Configured-form ownership, claim generation, versioning, completion, action automation, and role target suite: 8 passed.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 31 static routes.
- Production dependency audit: 0 vulnerabilities.
- Backend schema and API behavior remain on the verified `0030` / 109-test baseline; replay uses the existing server ownership, device, claim-generation, form-version, frozen-evidence, type, and size checks.

## 2026-07-29 - Phase 8 administrator sync-conflict resolution

Status: implemented and verified.

Delivered:

- Added durable tenant-scoped server conflicts for stale offline configured-form saves.
- Bound conflict creation to the exact claiming engineer account, registered device, claim generation, work order, and offline form version.
- Added per-organization queue idempotency plus canonical payload hashes so response-loss retries are safe and changed-data queue reuse is rejected.
- Retained bounded offline/server snapshots for administrator review while exposing only a status receipt to the originating phone.
- Restricted full conflict listing and resolution to administrators; managers, warehouse users, other engineers/devices, and organizations cannot inspect values or decide outcomes.
- Added keep-server, apply-offline, and field-by-field merge outcomes with optimistic conflict and current-server versions, mandatory notes, resolver attribution, and timestamps.
- Forced administrators to refresh if the server changes again after conflict detection.
- Reused immutable form-schema validation and generated normal notification/inventory-review tasks for real values applied by a resolution.
- Prevented application to frozen completion/approval evidence while still allowing an administrator to close the conflict by keeping server values.
- Added origin-device resolution polling so a resolved server record can safely replace and clear the retained local copy.
- Added exact single-work-order reads and changed replay preflight to refresh every queued work order without list pagination gaps.
- Added the administrator-only `/sync-conflicts` comparison and resolution workspace.
- Added Alembic revision `20260729_0031` with downgrade protection for retained conflict evidence.

Verification:

- Conflict, idempotency, account/device, administrator role, cross-tenant, merge, server-revision, form-action, and claim regression suite: 17 passed.
- Backend: all 111 tests passed in two bounded groups (45 plus 66).
- Database: fresh base-to-`0031` and empty `0031 -> 0030 -> 0031` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 32 static routes.

## 2026-07-29 - Phase 8 offline evidence safety and photo retention

Status: implemented and verified.

Delivered:

- Replaced the offline mutation blacklist with a strict reviewed allowlist for configured forms, QC picture records, and return-equipment evidence.
- Kept claims, workflow status, completion/approval, part usage, every inventory custody action, configuration, imports, integrations, and user administration online-only.
- Migrated older queued operations outside the allowlist to a retained blocked state so they cannot replay after an upgrade.
- Added IndexedDB photo retention for configured-form and QC photos when the phone is offline or the upload network fails while the browser still reports online.
- Bound every retained photo to the originating account, registered device, work order, claim generation, and evidence purpose.
- Limited device photo storage to 10 MiB per image, 12 images, and 50 MiB per account/device.
- Kept binary bytes outside JSON/localStorage and replaced them with opaque local markers.
- Added claim preflight, purpose validation, protected upload, marker replacement, normal server evidence validation, and post-upload device cleanup.
- Prevented part-usage photos from entering offline storage because part usage changes the inventory ledger.
- Added retained-photo visibility to `/sync-center`, including work order, claim generation, purpose, size, attachment state, and explicit discard for unattached files only.
- Updated the PWA cache generation to `openpartsflow-static-v3`.
- Added the offline sync security/operator guide and expanded mobile QA coverage.

Verification:

- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 32 static routes.
- Production dependency audit: 0 vulnerabilities.
- Backend remains on the fully verified `0031` / 111-test baseline; all replayed evidence uses the existing server ownership, device, claim-generation, frozen-state, type, size, and file-signature checks.

## 2026-07-29 - Phase 8 account/device-isolated offline reading

Status: implemented and verified.

Delivered:

- Added a separate IndexedDB store for reviewed successful GET responses, keyed by exact request path, authenticated account, and registered device.
- Added offline reads for work-order pools, exact work orders, configured forms, completion policies, service context/intelligence, recommendations, form-action progress, field evidence metadata, parts, warehouses, vehicle inventory, replenishment status, and vehicle-return status.
- Kept profit, administration, imports, integrations, arbitrary endpoints, and all mutation authority outside the read cache.
- Limited each response to 1.5 MB and each account/device store to 120 entries and 12 MB with oldest-snapshot pruning.
- Added fallback both when the browser reports offline and when the API is unreachable while the browser still reports online.
- Treated gateway/Service Worker 502, 503, and 504 responses as upstream unavailability: reviewed reads use retained snapshots, eligible writes queue, and every other mutation stays live-only.
- Preserved the local authenticated shell during genuine network failure instead of deleting the device login state.
- Added retained-data timestamps to the global offline/API-unavailable banner and cleared the warning after a real API response.
- Refreshed relevant form/QC/return read snapshots after a successful queued mutation without replaying the write if the optional refresh fails.
- Added read-snapshot count, paths, sizes, and timestamps to `/sync-center` without expanding or displaying cached payloads.
- Kept API responses out of the Service Worker cache; only the account/device-scoped IndexedDB path can return retained application data.
- Expanded the offline security guide and mobile QA checklist for identity isolation, missing snapshots, API-down fallback, and write denial.

Verification:

- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for all 32 static routes.
- Production dependency audit: 0 vulnerabilities.
- Real in-app browser regression passed with a seeded engineer and work order: 14 scoped snapshots were visible in `/sync-center`; after stopping the API, `/today` and the exact work-order detail reopened from retained data with timestamps, the authenticated mobile shell remained present, and an offline claim attempt failed with no state change.
- Backend remains on the fully verified `0031` / 111-test baseline; offline snapshots never bypass server mutation authorization.

## 2026-08-06 - Phase 9 tenant branding and commercial plan controls

Status: implemented and verified.

Delivered:

- Added Starter, Professional, and Enterprise plan records with standard user,
  main warehouse, vehicle inventory, AI, and external API allowances.
- Distinguished `0` as not included and `null` as unlimited or
  contract-governed for AI/API entitlements.
- Added trialing, active, past-due, suspended, and cancelled subscription states
  plus the existing platform active switch.
- Enforced commercial access at password login, every access-token request,
  invitation validation/acceptance, and external API-key authentication.
- Preserved platform-administrator recovery access when the administrator's home
  organization is commercially blocked.
- Added capacity enforcement for active users plus unexpired invitations, active
  main warehouses, and active vehicle inventories.
- Serialized capacity decisions with PostgreSQL row locks or a SQLite immediate
  write lock and handled invitation reissue/direct-account conversion without
  double-counting a seat.
- Added optimistic organization settings versions for branding and platform
  commercial updates.
- Added administrator-managed HTTPS logo, primary color, login headline, branded
  app shell, and customer-specific login links.
- Added a public safe branding projection that excludes subscription, quota,
  usage, user, credential, and billing data.
- Added platform organization creation/editing UI with plans, trials, states,
  limits, usage, and suspension controls.
- Added organization settings and employee seat-usage UI.
- Added organization and platform audit records without passwords, API keys,
  invitation tokens, or branding content.
- Normalized timezone-aware trial input to UTC database values.
- Added Alembic revision `20260730_0032` with database constraints and guarded
  downgrade.
- Documented commercial defaults, access states, quota semantics, security
  boundaries, and deployment.

Verification:

- Commercial branding, public response, role, optimistic version, capacity,
  invitation conversion, plan override, trial, token, and external API-key
  target suite passed.
- Backend: full suite passed, 115 tests, including a file-backed SQLite race
  proving two simultaneous final-seat requests cannot both succeed.
- Database: fresh migration through `0031 -> 0032`, schema/default/constraint
  inspection, `0032 -> 0031`, and re-upgrade to `0032` passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 32 static routes.
- Production dependency audit: 0 vulnerabilities.
- Real in-app browser regression passed for branded public login, authenticated
  tenant header, settings/capacity display, Starter and Professional default
  limits, persisted plan changes, immediate header refresh, and zero console
  errors.
- AI/API allowance storage is complete; durable monthly usage metering and hard
  allowance enforcement remain the next Phase 9 commercial batch.

## 2026-08-06 - Phase 9 durable AI/API usage metering

Status: implemented and verified.

Delivered:

- Added a tenant-isolated UTC monthly usage ledger with durable AI/API counters
  and last-used timestamps.
- Enforced unavailable plan features with `403` and exhausted positive monthly
  limits with `429`; unlimited contract plans remain metered for reporting.
- Metered work-order recommendations, service intelligence, visual part
  candidate generation, external reads, and external work-order intake.
- Charged external recommendations once for API usage and once for AI usage.
- Kept authentication, validation, missing-resource, rejected mutation, and
  rolled-back server failures outside billable usage.
- Returned exact processed inbound idempotency replays without another charge.
- Serialized concurrent final-unit requests across PostgreSQL and SQLite.
- Added live usage-to-allowance visibility to organization settings and the
  platform customer list.
- Added Alembic revision `20260806_0033` with non-negative count constraints,
  tenant/month uniqueness, cascade cleanup, indexes, and guarded downgrade.
- Added boundary, period rollover, combined-charge, idempotency, and file-backed
  SQLite race coverage.

Verification:

- Usage-metering tests: 4 passed.
- Affected commercial, integration, recognition, intelligence, and
  recommendation regression suite: 27 passed.
- Backend: all 119 tests passed, including file-backed SQLite concurrency.
- Database: fresh base-to-`0033`, table/index/constraint inspection, empty
  downgrade/re-upgrade, negative-counter rejection, and refusal to downgrade
  recorded usage all passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 32 static routes.
- Python dependency consistency passed; production npm audit reported 0
  vulnerabilities.

## 2026-08-06 - Phase 9 commercial usage reports

Status: implemented and verified.

Delivered:

- Added continuous zero-filled 1–36 month organization reports over the exact
  UTC AI/API usage ledger used for quota enforcement.
- Added selected-month platform comparison including customers with zero usage.
- Kept historical request counts separate from clearly labeled current limits
  and capacity because historical contract snapshots do not yet exist.
- Added administrator-password-confirmed CSV exports, export audit evidence,
  fixed filenames, UTF-8 spreadsheet compatibility, and formula-injection
  hardening.
- Added organization Reports and platform control-plane review/export UI.
- Added no database revision; the batch reads existing `0033` usage evidence.

Verification:

- Commercial report timeline, zero-fill, period, tenant/platform scope, CSV,
  formula safety, and audit tests: 2 passed.
- Affected billing and commercial usage suite: 9 passed.
- Backend: all 127 tests passed.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 32 static routes.
- Python dependency consistency passed; production npm audit reported 0
  vulnerabilities.

## 2026-08-06 - Phase 9 billing lifecycle and subscription notices

Status: implemented and verified.

Delivered:

- Added manual and signed-generic provider bindings with globally unique
  external references, current periods, scheduled cancellation, grace dates,
  ordering cursor, and optimistic versions.
- Added HMAC-SHA256/timestamp verification, a bounded strict event schema, exact
  two-reference account matching, future-clock rejection, and current-password
  reauthentication for platform binding changes.
- Added deterministic subscription transitions, plan-change restrictions,
  chronological application, exact replay idempotency, event ID collision
  rejection, and retained stale-event evidence.
- Stored normalized before/after lifecycle evidence and SHA-256 payload digests
  without raw provider payloads, Webhook secrets, payment methods, or card data.
- Added durable trial-ending, trial-expired, renewal-upcoming/overdue,
  cancellation, past-due, suspension, and cancelled notices with unique milestones, acknowledgement,
  recovery resolution, and optimistic versions.
- Added startup/hourly and on-demand reconciliation, organization Settings
  visibility, and platform binding/event/notice operations.
- Added Alembic revision `20260806_0035` with provider/reference, period, status,
  digest, version, uniqueness, tenant, index, foreign-key, and guarded-downgrade
  controls.
- Documented that checkout, invoices, tax, refunds, payment collection,
  customer recovery sessions, and outbound notice delivery remain separate
  provider-specific work.

Verification:

- Billing signature, timestamp, replay, collision, ordering, transition,
  recovery, notice, password, and uniqueness tests: 3 passed.
- Affected billing, commercial-plan, and usage-metering suite: 11 passed.
- Backend: all 125 tests passed.
- Database: fresh base-to-`0035`, lifecycle table/index/check inspection, empty
  downgrade/re-upgrade, invalid-provider rejection, and refusal to downgrade
  configured billing evidence all passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 32 static routes.
- Python dependency consistency passed; production npm audit reported 0
  vulnerabilities.

## 2026-08-06 - Phase 9 verified domains and sender identity foundation

Status: implemented and verified.

Delivered:

- Added one globally unique custom portal hostname per Professional/Enterprise
  customer with canonical IDNA normalization and reserved/local-name rejection.
- Added high-entropy DNS TXT challenges, fixed HTTPS DoH resolution, exact
  comparison, safe resolver errors, verification cooldown, and challenge
  rotation.
- Added tenant filtering, administrator-only management, optimistic versions,
  global collision handling, and challenge-free audit evidence.
- Added current-password reauthentication for domain configuration, challenge
  rotation, sender changes, and removal without persisting password material.
- Added automatic safe login branding by verified browser hostname.
- Added verified-domain-gated customer sender display/local-part configuration
  and automatic disablement after a hostname or challenge change.
- Added domain configuration, DNS instructions, verification, rotation, sender,
  and removal controls to organization settings.
- Added domain/status/sender visibility to the platform customer list.
- Added Alembic revision `20260806_0034` with status/version constraints,
  tenant/global uniqueness, foreign keys, indexes, and guarded downgrade.
- Documented the boundary between ownership proof and separately operated DNS
  routing, TLS, hosting, CORS, SPF/DKIM, and email delivery.

Verification:

- Domain normalization, TXT parsing, lifecycle, cooldown, roles, plans,
  uniqueness, tenant isolation, password reauthentication, public projection,
  sender gating, rotation, removal, and audit target tests: 3 passed.
- Affected commercial/platform/auth/multitenancy suite: 18 passed.
- Backend: all 122 tests passed.
- Database: fresh base-to-`0034`, table/index inspection, status/version
  constraint rejection, empty downgrade/re-upgrade, and refusal to downgrade
  configured domains all passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 32 static routes.
- Python dependency consistency passed; production npm audit reported 0
  vulnerabilities.

## 2026-08-06 - Phase 9 customer data portability and backup evidence

Status: implemented and locally verified.

Delivered:

- Added an administrator-only portable backup workspace and API with mandatory
  Bearer/current-password reauthentication.
- Added tenant-scoped JSON Lines export for the organization and every model in
  the central tenant registry.
- Added optional inclusion of referenced local photos, voice notes, recognition
  evidence, and private machine-knowledge media with normalized storage-root
  enforcement.
- Added a versioned `opf-portable-v1` manifest with schema revision, per-table
  counts and hashes, file hashes, missing-file evidence, and explicit secret
  exclusions.
- Excluded user password hashes, registered-device secrets, external API key
  hashes, invitation tokens, and domain verification secrets.
- Streamed archives without retaining another plaintext server copy and added a
  configurable 512 MB uncompressed-content boundary.
- Added durable archive SHA-256, size, record/file/missing counts, requester,
  generation time, and secret-free audit evidence.
- Added Alembic revision `20260806_0036` with non-negative count, checksum,
  format, tenant, requester, index, foreign-key, and guarded-downgrade controls.
- Documented the format and kept restore as a separate staged validation,
  approval, dry-run, application, and rollback workflow.

Verification:

- Tenant isolation, secret redaction, media inclusion, archive/entry checksums,
  administrator role, password reauthentication, evidence, and audit target
  tests: 3 passed.
- Backend: all 130 tests passed.
- Fresh base-to-`0036` and empty `0036 -> 0035 -> 0036` migration paths passed
  on SQLite; configured export evidence correctly refused downgrade.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 33 static routes.
- Python dependency consistency and full/production npm audits passed with 0
  known vulnerabilities; the lockfile was refreshed for patched
  `brace-expansion` and `js-yaml` development dependencies.

## 2026-08-06 - Phase 9 controlled existing-row data restores

Status: implemented and locally verified.

Delivered:

- Added an administrator-only restore workspace with current-password
  reauthentication for validation, decisions, application, and rollback.
- Added bounded `opf-portable-v1` validation for ZIP path safety, duplicate and
  encrypted entries, tenant/schema identity, table/file inventory, secret and
  cross-tenant columns, checksums, counts, and configured size limits.
- Added durable dry-run evidence with archive and plan hashes, source export
  matching, per-table update/unchanged/conflict/protected counts, actor
  attribution, timestamps, notes, and optimistic versions.
- Added explicit approval/rejection and exact-archive application that
  recomputes the plan against live data and aborts on any post-review drift.
- Added atomic existing-row restoration for allowlisted customer/equipment,
  warehouse/location, part/machine, completion-policy, form-template, and
  reviewed machine-knowledge data.
- Kept authentication, billing, audit, work-order custody, inventory ledger,
  synchronization, and other control-plane rows immutable.
- Added checksum-protected before/after rollback snapshots that refuse to
  overwrite later edits.
- Added Alembic revision `20260806_0037`, operator documentation, API/RBAC
  mapping, limits, tests, and guarded downgrade.
- Kept deleted-row recreation and atomic media writeback as explicit future
  batches instead of silently applying partial or unsafe recovery.

Verification:

- Restore validation, tamper rejection, conflict gating, plan drift,
  application, rollback, roles, reauthentication, and audit target tests:
  5 passed; export regressions: 3 passed.
- Backend: all 135 tests passed.
- Fresh base-to-`0037`, empty `0037 -> 0036 -> 0037`, schema/index/constraint
  inspection, and configured-evidence downgrade refusal passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 33 static routes.
- Python dependency consistency and full/production npm audits passed with 0
  known vulnerabilities.

## 2026-08-07 - Phase 9 safe restore record rehydration

Status: implemented and locally verified.

Delivered:

- Added explicit create counts and per-table create summaries to restore API,
  persistence, audits, operator workspace, and rollback display.
- Added deterministic rehydration of deleted allowlisted customer/equipment,
  warehouse/location, part/machine, completion-policy, configurable-form, and
  reviewed machine-knowledge records.
- Added global primary-key ownership, current unique-key, full archived column,
  tenant, and foreign-key checks before a missing row enters the plan.
- Added dependency-aware conflict propagation plus parent-to-child application
  and child-to-parent rollback ordering.
- Added exact-state rollback protection for rehydrated records, so later edits
  prevent the system from deleting them.
- Added Alembic revision `20260807_0038` and updated restore/export/RBAC/operator
  documentation. Media remains checksum-validation-only for the next batch.

Verification:

- Restore validation, parent/child rehydration, rollback drift, global-id
  collision, plan drift, roles, reauthentication, and audit tests: 6 passed;
  export regressions: 3 passed.
- Backend: all 136 tests passed.
- Fresh base-to-`0038`, empty `0038 -> 0037 -> 0038`, schema/constraint
  inspection, and configured rehydration-evidence downgrade refusal passed on
  SQLite.
- Frontend: ESLint, TypeScript, and Next.js production build passed for all 33
  static routes.
- Python dependency consistency and full/production npm audits passed with 0
  known vulnerabilities.
