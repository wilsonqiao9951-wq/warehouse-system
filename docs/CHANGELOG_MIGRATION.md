# OpenPartsFlow Migration Changelog

## 20260807_0059 - Inventory reconciliation queue index

- Added a tenant-leading replenishment reconciliation/updated-time index for
  bounded exception-queue scans.
- Added read-only cross-workflow reconciliation for historical replenishment,
  custody movement mismatches, pending physical-count variances, and count
  adjustment integrity.
- Added direct, tenant-scoped reads for queue drill-down into replenishments,
  vehicle returns, and inventory counts.
- Extends controlled tenant restore compatibility through revision `0059`.
- Downgrade removes only the new query index and does not modify custody or
  ledger evidence.

## 20260807_0058 - Inventory ledger query indexes

- Added tenant-leading indexes for transaction type, part, source warehouse,
  destination warehouse, accountable user, and work order with creation time.
- Added the read-only business inventory ledger API, tenant-referenced filter
  options, cursor pagination, workflow evidence, and the management workbench.
- Extends controlled tenant restore compatibility through revision `0058`.
- Downgrade removes only the six query indexes and does not modify ledger data.

## 20260807_0057 - Durable operations health history

- Added the platform-global `operations_health_samples` table with one
  idempotent time-bucket sample per randomized API-process identity.
- Hashes the process identity before storage and excludes all instance
  identifiers, tenant data, request content, and exception text from the API.
- Retains schema readiness, worker state, uptime, and bounded rolling request
  metrics with configurable cadence, retention, and query limits.
- Added platform-administrator-only history aggregation and the retained-history
  panel in Platform Operations.
- Request aggregation uses only the last rolling snapshot per instance in each
  output bucket, preventing repeated counting across adjacent samples.
- Downgrade removes only the new global history table and index; controlled
  tenant restore compatibility is extended through revision `0057`.

## Purpose

This changelog summarizes migration-related backend upgrades made to align OpenPartsFlow with AppSheet structure while preserving existing logic.

---

## 1) AppSheet-Compatible Data Model Expansion

### WorkOrders (`work_orders`)

Added compatibility fields:
- `wo_number`
- `schedule_date`
- `outlet_name`
- `job_type`
- `description`
- `city`
- `state`
- `zip`
- `contact_phone`
- `revenue` (already present)
- `labor_cost` (already present)

Compatibility behavior:
- `wo_number` and `ticket_number` are auto-mapped both ways.
- `outlet_name` and `store_name` are auto-mapped both ways.
- `description` and `problem_description` are auto-mapped both ways.

Impact:
- Existing clients using `ticket_number/store_name/problem_description` continue to work.
- AppSheet-style payloads can be accepted without breaking legacy flows.

---

### PartListsWOs (`work_order_parts`)

Added:
- `total_cost`

Behavior:
- Auto-calculated as `quantity * unit_cost` during part usage write flow.

Impact:
- Existing use-part logic remains intact.
- Cost reporting is easier and AppSheet-compatible.

---

### QCPictures (`qc_pictures`) - New Table

Fields:
- `id`
- `work_order_id`
- `image_url`
- `uploaded_by`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/qc-pictures`
- `GET /api/qc-pictures`

---

### JobStatus (`job_status`) - New Table

Fields:
- `id`
- `work_order_id`
- `status`
- `timestamp`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/job-status`
- `GET /api/job-status`

---

### ReturnEquipments (`return_equipments`) - New Table

Fields:
- `id`
- `work_order_id`
- `equipment_type`
- `quantity`
- `created_at`
- `updated_at`

Endpoints:
- `POST /api/return-equipments`
- `GET /api/return-equipments`

---

## 2) Core Inventory Upgrade

Existing inventory system retained and validated:
- `parts`
- `inventory_transactions`
- `warehouses`

Enhancement:
- Added `warehouses.warehouse_type` (`main` / `van`) for clearer location semantics.

Existing behavior preserved:
- Stock validation before usage
- Auto inventory deduction on part usage
- Van inventory by employee

Key endpoints:
- `POST /api/inventory/transactions`
- `GET /api/inventory/transactions`
- `GET /api/inventory/balances`
- `GET /api/employees/{user_id}/van-inventory`
- `POST /api/work-orders/{id}/use-part`

---

## 3) Profit Calculation

Formula preserved:
- `profit = revenue - labor_cost - sum(parts)`

Endpoint:
- `GET /api/work-orders/{id}/profit`

Enhancement:
- Profit payload now also includes `wo_number` for AppSheet compatibility context.

---

## 4) Backward Compatibility and Safety

### Existing Logic Preserved
- Legacy work-order creation with `ticket_number` still supported.
- Existing inventory tests continue to pass.
- Existing use-part and profit endpoints unchanged in path and core behavior.

### Runtime Schema Compatibility
- `ensure_schema_compatibility()` now auto-adds newly required columns/tables for existing DB files.
- Avoids breaking old SQLite/PostgreSQL databases during startup.

---

## 5) API Additions and Compatibility Map

### Existing required APIs (kept)
- `POST /api/work-orders`
- `POST /api/work-orders/{id}/use-part`
- `GET /api/work-orders/{id}/profit`

### New APIs added
- `POST /api/qc-pictures`
- `GET /api/qc-pictures`
- `POST /api/job-status`
- `GET /api/job-status`
- `POST /api/return-equipments`
- `GET /api/return-equipments`

### Compatibility behavior in `POST /api/work-orders`
- Accepts either `ticket_number` or `wo_number`.
- Auto-populates missing paired alias field.

---

## 6) Verification Status

Validation completed:
- Backend tests: pass (`pytest`)
- Lint diagnostics: no new issues

Conclusion:
- Migration upgrade is applied with AppSheet-compatible schema extensions and without breaking existing core logic.

---

## 7) Authenticated Engineer Claims (`20260711_0018`)

Added `user_devices` with tenant/user ownership, a stable device ID, hashed device secret, revocation state, device name, and first/last seen timestamps.

Added to `work_orders`:

- `claimed_by_id`
- `claimed_at`
- `claimed_device_id`
- `claim_version`
- `completed_by_id`
- `completed_device_id`

The revision also adds foreign keys and indexes for claimant/completer lookup and organization claim/status filtering. All new work-order columns are nullable except the zero-default claim version, so existing work orders upgrade without forced assignment or false completion attribution.

New APIs:

- `POST /api/work-orders/{id}/claim`
- `POST /api/work-orders/{id}/release`
- `GET /api/work-orders?scope=all|mine|available`

Validation completed on SQLite with a full base-to-head upgrade, `0018 -> 0017` downgrade, and `0017 -> 0018` re-upgrade.

---

## 8) Replenishment Custody and Inventory Movements (`20260711_0019`)

Added to `replenishment_requests`:

- source notification and target engineer links;
- organization-scoped `client_request_id` and `request_reason` for idempotent manual vehicle requests;
- a monotonically increasing workflow `version`;
- `requires_reconciliation` for legacy rows without trustworthy custody evidence;
- picker, shipper, receiver, receiving device, completer, and canceller attribution;
- server timestamps for every custody transition;
- cancellation reason;
- shipment and receipt inventory transaction IDs.

Added to `inventory_transactions`:

- `replenishment_request_id`;
- `movement_stage` (`ship` or `receive`);
- a unique request/stage constraint that prevents duplicate movement posting during retries.

The migration also formalizes `warehouses.warehouse_type`, converts existing engineer-owned warehouses to `van`, adds organization/status and organization/target/status indexes, enforces one request per notification and one manual `client_request_id` per organization, and adds quantity/version/status checks plus unique shipment/receipt transaction links.

Legacy rows labelled `picking`, `shipped`, `received`, or `completed` are marked `requires_reconciliation`. The three intermediate labels are reopened as `requested`; `completed` remains completed for an administrator to explicitly accept as historical or leave blocked for further investigation. Normal custody actions are blocked while the flag remains set.

Workflow behavior:

```text
requested → picking → shipped → received → completed
```

- `picking` reserves the requested source quantity when available stock is calculated.
- `shipped` posts a linked `OUTBOUND` transaction from the source warehouse.
- `received` posts a linked `INBOUND` transaction to the destination vehicle and records the engineer and registered device.
- `completed` closes the task and resolves its originating low-stock notification.
- Cancellation is limited to `requested` or `picking`, requires a reason, and resolves the source notification to avoid recreating a cancelled request loop.

New APIs:

- `POST /api/inventory/replenishment-requests` for an idempotent manual assigned-vehicle request with `client_request_id` and reason
- `GET /api/inventory/replenishment-requests`
- `POST /api/inventory/replenishment-requests/{id}/actions`
- `POST /api/inventory/replenishment-requests/{id}/reconcile`
- `GET /api/inventory/my-van`

The former generic replenishment status PATCH now returns `410`. Action requests send `expected_version`; a stale version or invalid transition returns `409` without changing custody or inventory state.

Reconciliation is administrator-only and requires a matching version, a reason, and current-password verification. `reset_requested` is valid for a reopened requested row; `accept_historical` is valid for a legacy completed row. Rows with linked inventory movements cannot use historical reconciliation. Downgrade from `0019` is also blocked while any linked replenishment movement exists, preventing the migration from discarding ledger-to-custody references.

Runtime inventory safeguards added with this revision:

- SQLite connections enable `PRAGMA foreign_keys=ON` and a five-second busy timeout.
- SQLite inventory-affecting custody writes acquire `BEGIN IMMEDIATE` before reading available stock or changing state; PostgreSQL uses row locks.
- An engineer-owned warehouse is treated as a vehicle even if legacy metadata is stale, and new engineer-owned warehouses are normalized to `van`.
- A vehicle cannot be a replenishment source.
- Generic inventory transactions reject every vehicle source/destination; opening-inventory preview and commit also reject vehicles.
- The generic transaction API accepts only `INBOUND`, `OUTBOUND`, `TRANSFER`, and `DAMAGE`. `RETURN` and `WORK_ORDER_USED` require their authenticated business workflows.

Verification:

- Full backend suite: 66 passed.
- Replenishment custody/security: 14 targeted tests passed.
- File-backed SQLite contention: 2 targeted tests passed.
- Fresh base-to-`0019`, empty `0019 → 0018 → 0019`, and legacy compatibility database-to-`0019` migration paths passed.
- Linked-movement downgrade was rejected before any downgrade DDL executed.
- Frontend upgraded to Next.js 16.2.10 and ESLint 9; lint and the production build passed for all 26 static routes.
- npm dependency installation/audit resolved to 0 known vulnerabilities; PostCSS is pinned to the patched 8.5.17 release.

## 20260712_0020 - Authenticated vehicle return custody

Added `vehicle_return_requests` and the strict reverse logistics chain `requested -> approved -> shipped -> received`.

- Engineers create returns only from their own assigned vehicle and registered device.
- Warehouse/admin approval reserves the vehicle quantity.
- Only the same engineer can confirm handover, using the bound device and current password; this posts `return_ship` vehicle `OUTBOUND`.
- Warehouse/admin receipt validates the linked shipment and posts `return_receive` warehouse `INBOUND` with the same cost.
- Cancellation is allowed only before handover and releases approved reservations.
- Unique client request IDs, workflow versions, transaction stages, tenant indexes, and audit events make retries and concurrent requests safe.
- Generic `RETURN` remains disabled; all return mutations are online-only.
- Downgrade is blocked while linked vehicle-return movements exist.

Verification: full backend suite 70 passed, vehicle custody target suite 18 passed, migration base-to-`0020` and empty `0020 -> 0019 -> 0020` passed, ESLint passed, and the Next.js production build generated all 26 static routes.

## 20260712_0021 - Auditable inventory counts

- Adds tenant-scoped count sessions and lines with actor timestamps and optimistic versions.
- Submission records book snapshots; administrator approval recalculates current book stock and posts one uniquely linked adjustment per non-zero variance.
- Administrator password reauthentication is required before ledger changes. Managers remain read-only and vehicle warehouses are excluded.
- Downgrade is blocked while approved count adjustment movements exist.

## 20260712_0022 - Replenishment approvals

- Adds pending/approved/rejected decision state plus approver/rejector identities, timestamps, and rejection reason.
- Managers and administrators decide requests; warehouse users cannot self-approve and cannot pick pending requests.
- Existing in-progress/completed custody rows are migrated as approved. Rejected rows downgrade safely to cancelled with their reason preserved.

## 20260712_0023 - Work-order learning data

- Adds indexed fault type, error code, and final outcome plus environment information, first-time-fix, rework, and repair duration.
- Duration is non-negative and server-calculated from field start through the engineer's completion submission, so manager approval delay does not inflate it.
- Learning evidence is returned in work-order and equipment service-history APIs and is frozen with the existing completion evidence.

## 20260728_0024 - Controlled visual part candidates

- Adds tenant-scoped photo observations and ranked part candidates.
- Adds the strict `ai_candidate -> employee_confirmed -> admin_confirmed -> usage_verified -> trusted` lifecycle plus reason-required rejection.
- Records every actor and timestamp, uses optimistic versions, and requires a real linked work-order part usage before trust promotion.
- Trusted promotion updates verified machine/part knowledge only; the recognition workflow never writes inventory transactions.

## 20260728_0025 - Governed machine service knowledge

- Adds tenant-scoped machine profiles with normalized per-organization model uniqueness and optimistic versions.
- Adds typed fault, repair-step, tool, caution, common-error, photo, video, and service-note entries.
- Keeps new knowledge in `draft` until an administrator publishes it; published guidance is immutable and can only be archived or reopened as a new draft workflow.
- Links optional tenant-validated parts and completed same-model work orders without exposing cost or supplier data to field readers.
- Aggregates completed-job count, first-time-fix rate, average repair duration, latest completion, and confirmed machine/part associations.
- Records profile, draft, publish, archive, and reopen actions in the organization audit log.

Verification: target workflow tests 3 passed, full backend suite 86 passed, fresh base-to-`0025` plus `0025 -> 0024 -> 0025` passed on SQLite, the Next.js 16.2.12 production build generated all 28 static routes, and the production dependency audit reported 0 vulnerabilities.

## 20260728_0026 - Governed knowledge capture

- Adds idempotent per-profile origin keys so repeated completed-work-order extraction cannot duplicate knowledge drafts.
- Adds recommended, alternative, consumable, and reference part roles plus primary-part substitution and installation-location fields.
- Adds protected media storage metadata, MIME type, byte size, and non-negative/relationship database constraints.
- Generates curator-only drafts from completed same-model work orders: fault context, repair result, and used parts.
- Marks parts as recommended only when the source work order records a successful first-time repair; rework or unlabeled evidence remains reference-only.
- Adds validated JPEG, PNG, GIF, WebP, HEIC, MP4, MOV, and WebM upload with configurable size limits and random private storage keys.
- Serves uploaded media only through an authenticated tenant- and publication-scoped API; it is not mounted under public `/uploads`.

Verification: knowledge capture/governance target suite 6 passed, full backend suite 89 passed, fresh base-to-`0026` plus `0026 -> 0025 -> 0026` passed on SQLite, and the Next.js 16.2.12 production build generated all 28 static routes.
- Work-order-linked evidence is restricted to the claiming engineer's registered device and claim generation or an administrator.

## Phase 5 explainable service intelligence (no schema migration)

- Adds `GET /api/work-orders/{id}/service-intelligence` using the existing work-order learning and governed-knowledge schema.
- Ranks locked completed history by machine, work type, fault, error code, and symptoms and returns an explanation for every match.
- Calculates exact-model first-time-fix, rework, duration, fault, and error-code evidence with low-confidence warnings.
- Ranks only published entries on the active exact-model profile; drafts, archived entries, unlocked jobs, and other tenants are excluded.
- Adds the read-only mobile intelligence panel without broadening work-order mutation permissions.

Verification: service-intelligence target suite 3 passed, full backend suite 92 passed, ESLint passed, and the Next.js 16.2.12 production build generated all 28 static routes. Schema head remains `20260728_0026`.

## 20260728_0027 - External integration foundation

- Adds tenant-scoped external integrations with provider label, field mapping, active state, optimistic version, actors, and last-used time.
- Stores only a globally unique API key prefix and SHA-256 hash; raw keys are shown once on create or rotation.
- Adds stable per-integration external-row-to-work-order links.
- Adds inbound/outbound-ready sync logs with idempotency key, request hash, status, attempts, changed fields, safe error, linked work order, and processing timestamps.
- Adds database constraints for supported providers, integration versions, sync direction/status/attempts, and per-integration source/idempotency uniqueness.
- Adds the idempotent AppSheet/REST inbound work-order endpoint and blocks external updates after claim or evidence freeze.

Verification: external integration target suite 4 passed, full backend suite 96 passed, fresh base-to-`0027` plus `0027 -> 0026 -> 0027` passed on SQLite, and the Next.js 16.2.12 production build generated all 29 static routes.

## 20260729_0028 - External delivery runtime

- Adds HTTPS Webhook destinations and subscribed work-order events to tenant integrations.
- Extends synchronization logs with a durable outbound payload, pending state, response status, next retry, and last-attempt evidence.
- Queues status, completion, and part-usage callbacks in the same transaction as the authoritative business change.
- Signs exact callback bytes with HMAC-SHA256 derived from the integration API key hash.
- Adds concurrency-safe delivery claiming, no-redirect requests, five-attempt exponential retry, terminal failure, and administrator requeue.
- Adds external inventory, linked work-order status, and explainable part-recommendation read APIs without cost or supplier disclosure.
- Rejects non-HTTPS and local/private/reserved Webhook targets.

Verification: external delivery target suite 5 passed, full backend suite 101 passed, fresh base-to-`0028` plus `0028 -> 0027 -> 0028` passed on SQLite, and the Next.js 16.2.12 production build generated all 29 static routes.

## 20260729_0029 - Configurable work-order forms

- Adds tenant-scoped work-order form templates and ordered text, textarea, number, boolean, date, select, photo, and signature fields.
- Adds typed defaults, applicability filters, completion requirements, approval, notification, inventory-declaration, and AI-learning flags.
- Snapshots the exact template version, schema, rules, and defaults onto every assigned work order so later template changes cannot rewrite history.
- Adds optimistic template and form value versions, bounded payloads, typed validation, and immutable evidence after approval submission or completion.
- Keeps forms visible to all same-organization engineers while restricting updates to an administrator or the exact claiming engineer account, registered device, and claim generation.
- Merges configured approval fields into the existing completion policy and blocks completion while configured required evidence is missing.
- Treats inventory-impact flags as governed metadata; dynamic form submissions never mutate physical inventory.

Verification: configurable-form target suite 5 passed, full backend suite 106 passed, fresh base-to-`0029` plus `0029 -> 0028 -> 0029` passed on SQLite, and the Next.js 16.2.12 production build generated all 30 static routes.

## 20260729_0030 - Configured-form action workflow

- Adds tenant-scoped durable notification and inventory-review tasks created only when a flagged configured field actually changes.
- Keys every task to the work order, field, action type, and exact form revision so retries and identical-value submissions cannot duplicate follow-up work.
- Stores field identity and workflow evidence without copying submitted form values into the action queue.
- Adds strict `pending -> acknowledged -> resolved` handling with optimistic versions, actor/timestamp attribution, and audit records.
- Allows managers to process notifications, warehouse staff to process inventory reviews, and administrators to process either; inventory resolution requires notes.
- Gives engineers read-only action progress on shared work orders without global queue or mutation access.
- Keeps inventory changes in the dedicated replenishment, transfer, return, and count workflows; resolving a form action never posts a stock transaction.
- Blocks downgrade while any action evidence exists.

Verification: form-action target suite 3 passed, all 109 backend tests passed in two bounded modules, fresh base-to-`0030` plus `0030 -> 0029 -> 0030` passed on SQLite, and the Next.js 16.2.12 production build generated all 31 static routes.

## 20260729_0031 - Audited offline configured-form conflicts

- Adds tenant-scoped server conflict records linked to the work order, originating engineer, registered device, claim generation, offline base version, and server version.
- Stores bounded local and server form snapshots plus a canonical payload hash under administrator-only full-value access.
- Enforces per-organization client queue idempotency and rejects changed-data reuse.
- Adds pending, kept-server, applied-local, and merged states with optimistic versions, mandatory notes, resolver attribution, and timestamps.
- Lets only the originating account and registered device create a conflict or poll its status receipt.
- Lets only administrators compare full values and resolve by keeping server data, applying the offline copy, or selecting a field merge.
- Requires the latest server form version at resolution and repeats immutable-schema validation; frozen evidence can only keep server data.
- Generates normal notification/inventory-review tasks for real values applied through conflict resolution.
- Adds exact work-order reads so offline replay refreshes every queued claim generation without a 100-record pagination gap.
- Blocks downgrade while any conflict evidence exists.

Verification: conflict, idempotency, account/device ownership, administrator role, cross-tenant, merge, server-revision, form-action, and claim regression suite 17 passed; all 111 backend tests passed in two bounded groups (45 plus 66); fresh base-to-`0031` plus `0031 -> 0030 -> 0031` passed on SQLite; the Next.js 16.2.12 production build generated all 32 static routes.

## 20260730_0032 - Tenant branding and commercial plan controls

- Adds HTTPS logo, primary color, and login headline configuration to each
  organization.
- Adds Starter, Professional, and Enterprise plan codes.
- Adds trialing, active, past-due, suspended, and cancelled subscription states
  plus optional trial end.
- Adds user, main warehouse, vehicle inventory, AI monthly, and external API
  monthly limits.
- Adds optimistic organization settings versions.
- Adds database constraints for supported plan/state values, non-negative
  settings versions, positive resource limits, and non-negative metered
  allowances.
- Migrates existing organizations to active Professional defaults.
- Blocks downgrade after any branding, subscription, plan, limit, trial, or
  settings-version customization to prevent silent configuration loss.

Verification: commercial target suite and file-backed SQLite seat-race coverage
passed; all 115 backend tests passed;
fresh `0031 -> 0032`, schema/default/constraint inspection,
`0032 -> 0031 -> 0032` passed on SQLite; ESLint and the Next.js 16.2.12
production build passed for all 32 static routes; real browser branding/plan
regression passed with zero console errors; production dependency audit reported
0 vulnerabilities.

## 20260806_0033 - Durable monthly AI/API usage metering

- Adds one tenant-isolated commercial usage ledger row per UTC calendar month.
- Stores non-negative AI and external API request counters plus last-used
  timestamps without retaining request or response content.
- Enforces `0` allowances as unavailable (`403`), positive allowance boundaries
  as exhausted (`429`), and continues to count contract/unlimited usage.
- Meters internal recommendations, service intelligence, visual part candidate
  generation, and every external API operation; external recommendations consume
  both an AI and API unit.
- Commits inbound work-order usage with the processed business transaction and
  does not double-charge exact idempotent replays.
- Serializes competing final-unit requests with the organization commercial lock.
- Blocks downgrade after usage evidence exists.

Verification: usage boundary/idempotency/rollover/isolation/race tests passed;
all 119 backend tests passed; fresh base-to-`0033`, schema/index/constraint
inspection, empty `0033 -> 0032 -> 0033`, and guarded evidence downgrade passed
on SQLite; ESLint and the Next.js 16.2.12 production build passed for all 32
static routes; production dependency audit reported 0 vulnerabilities.

## 20260806_0034 - Verified domains and sender identities

- Adds one globally unique, tenant-owned custom hostname per organization.
- Adds pending/verified ownership states, high-entropy DNS TXT challenges,
  verification checks, safe errors, timestamps, and optimistic versions.
- Restricts the capability to Professional and Enterprise administrators.
- Requires current-password reauthentication before hostname, challenge,
  sender-identity, or removal mutations.
- Adds customer sender display/local-part configuration that cannot be enabled
  until domain ownership is verified.
- Adds public safe branding lookup by verified host and automatic login-page host
  discovery without exposing challenges or commercial data.
- Adds platform domain/status/sender visibility, audit evidence, and guarded
  downgrade.

Verification: domain lifecycle and affected commercial suite passed; all 122
backend tests passed; fresh base-to-`0034`, schema/index/constraint inspection,
empty `0034 -> 0033 -> 0034`, and guarded configured-domain downgrade passed on
SQLite; ESLint and the Next.js 16.2.12 production build passed for all 32 static
routes; production dependency audit reported 0 vulnerabilities.

## 20260806_0035 - Billing lifecycle and subscription notices

- Adds one provider-neutral billing account per organization with manual or
  signed-generic binding, unique external references, periods, cancellation,
  grace, ordering cursor, and optimistic version.
- Adds immutable normalized lifecycle event evidence with global provider event
  idempotency, SHA-256 body evidence, applied/stale outcome, and before/after
  subscription and plan state.
- Adds tenant-owned trial, renewal, cancellation, past-due, suspension, and
  cancellation notices with acknowledgement, automatic resolution, and
  optimistic versions.
- Adds HMAC-SHA256 and timestamp-verified Webhook processing with payload size,
  schema, reference, event collision, ordering, and future-clock safeguards.
- Adds platform binding/event/notice/reconciliation operations, organization
  administrator notice visibility, background reconciliation, UI, and audits.
- Requires current-password reauthentication for platform billing bindings and
  refuses downgrade while any billing configuration or evidence remains.

Verification: billing lifecycle tests passed; all 125 backend tests passed;
fresh base-to-`0035`, table/index/check inspection, empty
`0035 -> 0034 -> 0035`, invalid-provider rejection, and configured-evidence
downgrade refusal passed on SQLite; ESLint and the Next.js 16.2.12 production
build passed for all 32 static routes; production dependency audit reported 0
vulnerabilities.

## 2026-08-06 - Commercial usage reports (no schema revision)

- Adds continuous 1–36 month tenant reports backed by the existing `0033` UTC
  usage ledger and current capacity/limit projections.
- Adds a selected-month platform comparison that retains zero-usage customers.
- Adds password-confirmed organization/platform CSV exports, export audit
  evidence, fixed filenames, UTF-8 spreadsheet compatibility, and formula-cell
  hardening.
- Adds organization Reports and platform control-plane reporting UI.

Verification: commercial report and affected billing suites passed; all 127
backend tests passed; ESLint and the Next.js 16.2.12 production build passed for
all 32 static routes; Python dependency consistency passed; production npm
audit reported 0 vulnerabilities.

## 20260806_0036 - Customer data export integrity evidence

- Adds tenant-owned evidence for each generated portable backup, including the
  format version, archive SHA-256, size, record/file/missing counts, per-table
  counts, requester, and generation time.
- Adds administrator-only, current-password-confirmed ZIP generation with
  tenant JSONL data, checksum manifest, and optional referenced local media.
- Excludes password, device, external API key, invitation, and DNS challenge
  authentication material from every archive.
- Streams the archive to the requester without retaining a second plaintext
  server copy and records a secret-free audit event.
- Refuses downgrade while export integrity evidence exists.

Verification: targeted export/isolation/reauthentication tests passed; fresh
base-to-`0036` and empty `0036 -> 0035 -> 0036` migration paths passed on SQLite;
all 130 backend tests passed; configured-evidence downgrade refusal passed;
ESLint, TypeScript, and the Next.js 16.2.12
production build passed for all 33 static routes; Python dependency consistency
and full/production npm audits reported 0 known vulnerabilities.

## 20260806_0037 - Controlled customer data restores

- Adds tenant-owned restore rehearsal evidence with archive/plan SHA-256,
  source metadata, table summaries, conflicts, protected rows, state actors,
  optimistic version, and rollback integrity fields.
- Adds bounded ZIP validation for organization/schema identity, safe paths,
  entry inventory, secret/cross-tenant exclusions, table/file checksums, and
  compressed/uncompressed/rollback limits.
- Adds an administrator-only `validated -> approved -> applied -> rolled_back`
  workflow plus terminal rejection, current-password reauthentication, exact
  archive resubmission, live-plan drift detection, and audit evidence.
- Applies only existing allowlisted master/configuration/knowledge rows and
  protects authentication, billing, audit, work-order custody, inventory
  ledgers, synchronization, and other control-plane data.
- Stores a checksum-protected before/after field snapshot so rollback refuses
  to overwrite changes made after application.
- Refuses downgrade while any restore evidence exists.

Verification: five restore workflow/security tests and three export regression
tests passed; all 135 backend tests passed; fresh base-to-`0037`, empty
`0037 -> 0036 -> 0037`, schema/index/constraint inspection, and guarded
configured-evidence downgrade passed on SQLite; ESLint and the Next.js 16.2.12
production build passed for all 33 static routes; Python dependency consistency
and full/production npm audits reported 0 known vulnerabilities.

## 20260807_0038 - Restore record rehydration evidence

- Adds a non-negative `create_count` to every controlled restore rehearsal so
  administrators can distinguish safe rehydrations from field updates.
- Extends the eligible restore plan to recreate missing allowlisted
  master/configuration/knowledge rows only after global id, unique-key, tenant,
  complete-payload, and foreign-key validation.
- Applies creates in parent-to-child order and removes them in child-to-parent
  rollback order while retaining exact archive, plan, version, and drift checks.
- Propagates unresolved parent conflicts to dependent rows and leaves protected
  transactional/control-plane records and archive media validation-only.
- Refuses downgrade while rehydration evidence exists.

Verification: six restore workflow/security tests and three export regression
tests passed; all 136 backend tests passed; fresh base-to-`0038`, empty
`0038 -> 0037 -> 0038`, schema/constraint inspection, and guarded rehydration-
evidence downgrade passed on SQLite; ESLint and the Next.js production build
passed for all 33 static routes; Python dependency consistency and
full/production npm audits reported 0 known vulnerabilities.

## 20260807_0039 - Controlled restore media evidence

- Adds per-restore media create, overwrite, unchanged, and conflict counts plus
  durable file rollback SHA-256 and byte-size evidence.
- Maps archive files only to exact configured public/private roots and rejects
  unsafe references, mismatched paths, duplicate targets, symbolic links, and
  non-regular destinations.
- Requires every target to remain referenced by the resulting tenant data and
  blocks paths referenced by any other organization.
- Stages verified archive bytes outside served storage, preserves overwritten
  originals, and atomically promotes each target through a same-directory file.
- Compensates file writes when database application fails and reapplies archive
  files when a rollback database commit fails.
- Blocks file rollback on live-file drift or evidence corruption, then removes
  protected evidence after a successful rollback.
- Refuses downgrade while media writeback or rollback evidence exists.

Verification: seven restore workflow/security/media tests and three export
regression tests passed; all 137 backend tests passed; fresh base-to-`0039`,
empty `0039 -> 0038 -> 0039`, schema/constraint inspection, and guarded media-
evidence downgrade passed on SQLite; ESLint and the Next.js production build
passed for all 33 static routes; Python dependency consistency and
full/production npm audits reported 0 known vulnerabilities.

## 20260807_0040 - Formal schema ownership and legacy database adoption

- Adds the formerly runtime-created audit, job-status, QC-picture, and returned-
  equipment tables to the authoritative Alembic history.
- Formalizes legacy compatibility fields for work orders, parts, and work-order
  parts, including safe backfills and guarded downgrade behavior.
- Replaces startup-time `create_all()` and ad hoc `ALTER TABLE` mutation with a
  read-only fail-closed Alembic head check.
- Adds read-only legacy rehearsal plus exclusive-lock apply, permanent backup,
  isolated candidate migration, explicit legacy derivations, row/value hashes,
  integrity checks, atomic replacement, failure restoration, and a JSON audit
  report.
- Updates local startup to detect and safely adopt an unversioned SQLite file
  before applying normal migrations; unknown data or an active database refuses
  startup instead of being silently discarded.

Verification: five legacy-adoption/schema-guard/migration tests passed; all 142
backend tests passed; compile and Python dependency consistency passed; the
configured local legacy database completed backed-up adoption and a second
preparation run was idempotent; ESLint and the Next.js production build passed
for all 33 static routes; full and production npm audits reported 0 known
vulnerabilities.

## 20260807_0041 - Enterprise audit console query indexes

- Adds tenant/time, tenant/action/time, and tenant/entity composite indexes for
  bounded audit search, summaries, and compliance exports.
- Adds cursor-paginated, tenant-scoped audit search with exact action, entity,
  actor, and UTC time-range filters while preserving the legacy list response.
- Adds 30-day activity summaries for managers and administrators.
- Adds administrator-only, current-password-confirmed CSV export with formula
  hardening, configured row limits, SHA-256 response evidence, and an
  `audit_log_exported` event that never retains the password.
- Adds the manager audit workspace with filtering, metadata inspection,
  pagination, activity summaries, and administrator export controls.

Verification: audit search, tenant isolation, cursor behavior, metadata safety,
role boundaries, password verification, CSV hardening, and digest evidence
tests passed; fresh migration through `0041` and legacy-adoption regression
tests passed; all 144 backend tests passed; ESLint, TypeScript, and the Next.js
production build passed for all 34 static routes.

## 20260807_0042 - Enterprise user access policies

- Adds tenant-scoped `user_permission_grants` with one `allow` or `deny`
  override per user and permission code.
- Adds tenant/user lookup indexes, an effect constraint, administrator actor
  attribution, mandatory business reason, and timestamps.
- Keeps role defaults compatible while adding explicit-deny priority and
  `inherit` reset by deleting the override.
- Adds an administrator permission matrix, effective-policy navigation, and
  enforced employee, audit, report, and integration permission boundaries.
- Updates the protected legacy-adoption head verification through `0042`.

## 20260807_0043 - Multi-region inventory ownership

- Adds tenant-scoped inventory regions with unique code/name, validated IANA
  timezone, one active default, optimistic versioning, and audit timestamps.
- Adds indexed warehouse region ownership, seeds a `PRIMARY` region for every
  existing organization, and backfills every existing warehouse.
- Adds regional stock summaries and cross-region transfer history, with
  administrator/manager-only cross-region writes and read access for warehouse
  personnel.
- Preserves the separate authenticated vehicle replenishment, use, and return
  workflows; generic vehicle transfers remain blocked.
- Adds portable export/controlled restore ordering and legacy-adoption default
  generation after source checksum validation.

Verification: four region lifecycle, authorization, tenant-isolation, summary,
audit, and vehicle-protection tests passed; all 154 backend tests passed; fresh
base-to-`0043` and `0043 -> 0042 -> 0043` migration rehearsals passed on SQLite;
ESLint, TypeScript, and the Next.js production build passed for all 36 static
routes.

## 20260807_0044 - Enterprise operations analytics indexes

- Adds tenant/created, tenant/completed, tenant/completer/completed, and
  tenant/job-type/completed work-order indexes for bounded operating reviews.
- Adds tenant/work-order part and tenant/time inventory-transaction indexes for
  contribution, regional consumption, and source-freshness queries.
- Adds tenant-scoped KPI, prior-period, trend, engineer, job-type, regional
  inventory, data-quality, and source-freshness reporting.
- Adds effective `reports.export`, password-confirmed formula-safe CSV export,
  configured row limits, SHA-256/row-count response evidence, and durable export
  audit evidence.
- Adds the chart-led `/analytics` workspace with shared UTC date, engineer, and
  job-type filters.

Verification: four analytics reconciliation, filter, tenant, permission,
reauthentication, export-safety, digest, audit, and size-limit tests passed; all
158 backend tests passed; fresh base-to-`0044` and `0044 -> 0043 -> 0044`
migration rehearsals passed on SQLite; ESLint, TypeScript, and the Next.js
production build passed for all 37 static routes; dependency checks and both npm
audits passed with 0 known vulnerabilities.

## 20260807_0045 - Enterprise operations Agent run evidence

- Adds immutable, tenant-scoped Agent run evidence with actor, resolved intent,
  question digest/length, bounded filters, tool trace, finding count, duration,
  status, and timestamp; raw questions and generated narratives are not stored.
- Adds effective `agent.use`, manager/administrator defaults, and explicit
  enterprise permission overrides.
- Adds allowlisted daily brief, backlog, service-quality, inventory-readiness,
  and integration-health intents over server-owned query tools.
- Adds one-request AI allowance metering per successful run, source definitions,
  data-quality confidence, declared limitations, and hard read-only guardrails.
- Adds the `/agent` workspace with preset questions, UTC/engineer/job-type
  filters, prioritized evidence, protected workflow links, and digest-only run
  history.

Verification: three Agent grounding, tenant, privacy, read-only, audit, quota,
classification, validation, and permission tests passed; all 161 backend tests
passed; fresh base-to-`0045` and `0045 -> 0044 -> 0045` migration rehearsals
passed on SQLite; ESLint, TypeScript, and the Next.js production build passed
for all 38 static routes; dependency checks and both npm audits passed with 0
known vulnerabilities.

## 20260807_0046 - Stripe commercial billing

- Adds server-owned Stripe Checkout plan prices and redirect URLs, short-lived
  customer portal sessions, administrator reauthentication, and platform-only
  refunds that verify the PaymentIntent belongs to the selected tenant.
- Adds raw-request-body Stripe signature verification, timestamp tolerance,
  bounded payloads, ordered subscription lifecycle mapping, and tenant binding
  from protected Checkout/subscription metadata.
- Adds durable request digests, Stripe idempotency keys, safe operation results,
  event receipts, lifecycle evidence, and audit records without storing secrets,
  card data, redirect capabilities, raw provider responses, or business notes.
- Adds the organization subscription controls and platform Stripe binding mode,
  with provider-neutral manual and generic billing compatibility retained.
- Keeps the new payment and webhook evidence protected from controlled customer
  restore while extending portable-schema compatibility through `0046`.

Verification: four Stripe contract, signature, tenant, refund, idempotency,
collision, redirect, audit, and evidence tests passed; all 181 backend tests
passed after dependency security upgrades; fresh base-to-`0046` and
`0046 -> 0045 -> 0046` migration rehearsals passed on SQLite; ESLint,
TypeScript, and the Next.js production build passed for all 38 static routes;
Python and both npm dependency audits reported 0 known vulnerabilities.

## 20260807_0047 - Auditable AI visual recognition

- Adds versioned recognition status to photographed observations and immutable,
  tenant-scoped provider attempts with idempotency, actor, provider/model/prompt,
  request hashes, safe failure codes, structured result, and completion evidence.
- Adds real server-side OpenAI Responses image analysis with base64 image input,
  original-detail OCR, strict JSON Schema output, `store: false`, official-host
  enforcement, bounded catalog context, timeouts, and no redirect following.
- Restricts model output to advisory matching against existing tenant parts;
  hallucinated catalog references are discarded and all human/usage verification
  stages remain mandatory before trusted knowledge changes.
- Adds automatic mobile analysis, visible attempt state, safe retry, photo-only
  upload, and configuration-aware fallback to deterministic context ranking.
- Moves new recognition photos to private random storage and serves them only
  through a tenant-authenticated, sandboxed, MIME-protected media endpoint.
- Extends portable export and controlled-restore schema compatibility through
  `0047`; downgrade is refused while provider-attempt evidence exists.

Verification: nine recognition/provider contract, success,
failure, retry, idempotency, quota, audit, inventory-isolation, and human-lock
tests passed; fresh base-to-`0047` and `0047 -> 0046 -> 0047` migration rehearsal
passed on SQLite; frontend ESLint, TypeScript, and the production build passed
for all 38 static routes; all 186 backend tests, Python dependency consistency,
Python vulnerability audit, and both npm audits passed with 0 known
vulnerabilities.
## 20260807_0048 - Authentication security evidence and revocable sessions

- Added a non-negative user authentication version and embedded it in every new JWT so password changes and explicit session revocation invalidate older tokens immediately.
- Added password-confirmed `POST /api/auth/sessions/revoke-all` for every signed-in role and safe tenant-administrator security event reads at `GET /api/auth/security-events`.
- Added durable account/source login throttling with configurable production-validated bounds and `429 Retry-After` responses.
- Added immutable login/session outcomes with keyed account and source fingerprints; raw identifiers, IP addresses, submitted credentials, bearer tokens, and device secrets are not retained or exposed.
- Added a Profile security workspace, tenant-safe authentication history, export redaction, controlled-restore compatibility, and legacy-adoption current-head validation.

## 20260807_0049 - Single-use password reset

- Added hashed, tenant-scoped reset tokens with expiry, single-use conditional consumption, prior-token invalidation, delivery status, and safe failure evidence.
- Added generic account-enumeration-resistant reset requests with keyed account/source rate limits and fail-closed production availability.
- Added TLS-protected SMTP delivery after the HTTP response; production never stores or returns the raw token and validates relay settings before startup.
- Added password completion that rotates the Argon2 hash and authentication version so all older bearer sessions are revoked immediately.
- Added Forgot Password and Reset Password pages, administrator security-event visibility, export redaction, restore compatibility, and migration `0049`.

## 20260807_0050 - Administrator multi-factor authentication

- Added optional administrator/platform-administrator RFC 6238 TOTP enrollment with current-password confirmation and an expiring provisioning window.
- Added versioned AES-256-GCM authenticated-encryption protection for TOTP secrets, ordered multi-key decryption for key rotation, and fail-closed staging/production key validation.
- Added short-lived password-proven login challenges that cannot be accepted as Bearer tokens, dual-scope attempt throttling, one-step clock-drift tolerance, and conditional TOTP replay prevention.
- Added ten one-time recovery codes whose values are displayed once and retained only as digests; conditional consumption rejects concurrent replay.
- Added password-and-MFA protected recovery-code replacement and MFA disable operations. Enrollment, replacement, and disable revoke all older sessions.
- Added safe MFA security outcomes, Profile enrollment/recovery controls, login challenge UI, export redaction, controlled-restore compatibility, and migration `0050`.

Verification: all 209 backend tests passed, including encryption tamper and key-rotation coverage; fresh base-to-`0050` and `0050 -> 0049 -> 0050` migration rehearsals passed on SQLite; frontend ESLint, TypeScript, and the Next.js production build passed for all 40 static routes; Python and npm audits reported 0 known vulnerabilities; production API/web images built successfully; Alembic comparison contains no missing `0050` operation.

## 20260807 - Secure browser sessions

- Added an explicit Cookie login mode that keeps the signed access credential in a production `Secure`, `HttpOnly`, `SameSite=Strict`, host-only Cookie and never returns it to browser JavaScript.
- Added a high-entropy CSRF proof whose digest is signed into each Cookie session; all unsafe Cookie-authenticated methods reject missing, mismatched, and cross-session proofs.
- Preserved explicit Bearer login and Authorization-header precedence for standalone clients, automation, local cross-origin development, and existing API integrations.
- Migrated same-origin HTTPS web deployments to Cookie mode automatically, including credentials and CSRF handling for JSON, uploads, downloads, offline replay, private images, and knowledge media.
- Preserved engineer registered-device and work-order claim binding in both Cookie and Bearer modes, and added server-side Cookie expiry for logout, session revocation, and MFA credential rotation.
- Enabled Cookie sessions for password-confirmed exports, restores, billing operations, form editing, and governed visual-recognition actions instead of retaining Bearer-only business checks.

Verification: all 218 backend tests passed, including Cookie attributes, CSRF absence/mismatch/cross-session rejection, Bearer precedence, engineer-device binding, password-confirmed audit export, logout/revocation, and MFA Cookie issuance; frontend ESLint, TypeScript, and the production build passed for all 40 static routes; Python requirement/full-environment and full/production npm audits reported 0 known vulnerabilities; production configuration, Compose contract/configuration, and API/web image builds passed.

## 20260807_0051 - Verified invitation email delivery

- Added fail-closed production/staging employee invitations over the validated TLS SMTP transport shared with password reset.
- Removed raw sign-up URLs from production administrator responses; only the invited mailbox receives the random single-use capability.
- Added tenant-scoped delivery status, attempt count, safe failure code, and delivery timestamps without retaining raw tokens.
- Fixed same-email invitation supersession to include the organization boundary, preventing one tenant from invalidating another tenant's invitation.
- Added safe invitation-creation audit evidence, local-development manual links, frontend delivery messaging, production configuration validation, portable-restore compatibility, and migration `0051`.
- Refuses downgrade while non-manual invitation delivery evidence exists.

Verification: all 225 backend tests passed, including recipient-only token delivery, relay failure evidence, fail-closed production behavior, single-use acceptance, and cross-tenant reissue isolation; fresh base-to-`0051` and `0051 -> 0050 -> 0051` migration rehearsals passed on SQLite; frontend ESLint, TypeScript, and the Next.js production build passed for all 40 static routes; Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.

## 20260807 - Interrupted outbound delivery recovery

- Added a platform-administrator-only, password-confirmed operation to requeue a bounded batch of stale outbound Webhook processing leases.
- Locks and rechecks eligible rows, excludes inbound/fresh/completed work, preserves attempt counters and stable idempotency keys, and leaves actual delivery to the worker.
- Added per-organization audit evidence without customer payloads or credentials, an idempotent no-op outcome, operations-console controls, and a recovery runbook.
- No schema change is required; Alembic head remains `20260807_0051`.

Verification: all 227 backend tests passed; frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes; Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.

## 20260807_0052 - Governed disaster-recovery evidence retention

- Added organization-specific export-evidence, terminal-rehearsal, and applied-rollback retention periods with bounded ranges, optimistic versioning, password confirmation, and reasoned audit evidence.
- Added a fixed rollback expiry to new restore applications and refusal of rollback after the governed window.
- Added fixed-cutoff preview counts and byte totals plus a bounded cleanup that preserves active approvals, unexpired rollback packages, referenced exports, customer business data, and audit logs.
- Added atomic file-evidence quarantine, pre-commit compensation, and next-run reconciliation for interruptions on either side of the database commit.
- Added purge time/operator attribution, Backups workspace controls, tenant/role/password boundaries, migration `0052`, and the operator runbook.

Verification: all 230 backend tests passed, including cross-tenant selection, active approval preservation, password/version enforcement, fixed rollback expiry, repeat cleanup, and interrupted file reconciliation; fresh base-to-`0052` and `0052 -> 0051 -> 0052` migration rehearsals passed on SQLite; frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes; Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.

## 20260807_0053 - PostgreSQL tenant row-level security

- Enabled and forced one tenant read/write RLS policy on all 51 current tenant
  tables; the migration coverage set is contract-tested against the ORM tenant
  model registry.
- Added transaction-local PostgreSQL organization/platform settings, immediate
  scope narrowing after user or API-key resolution, and explicit reviewed
  platform scope for platform administrators and cross-tenant workers.
- Replaced ad-hoc ORM session scope mutation with shared database helpers while
  preserving API authorization, work-order ownership, device, claim-version,
  inventory-custody, and field-disclosure controls.
- Split production schema-owner migration and restricted API database
  credentials. The idempotent role bootstrap enforces
  `NOSUPERUSER NOBYPASSRLS NOINHERIT` and repairs existing/default grants.
- Added a real PostgreSQL 16 verifier for empty-scope reads, tenant reads,
  cross-tenant write denial, platform access, role capability, policy coverage,
  and downgrade/re-upgrade behavior.
- Extended controlled-restore schema compatibility through `0053` and added the
  production adoption, verification, and rollback runbook.

Verification: all 234 backend tests passed; real PostgreSQL 16 base-to-`0053`,
role-bootstrap repetition, `0053 -> 0052 -> 0053`, and RLS read/write/platform
checks passed; the SQLite migration cycle passed; frontend ESLint, TypeScript,
and the Next.js 16.2.12 production build passed for all 40 static routes;
Python and npm dependency audits reported 0 known vulnerabilities; production
configuration, Compose configuration, and API/web image builds passed.

## 20260807_0054 - Reconciled database/model schema contract

- Cleared every PostgreSQL and SQLite Alembic autogeneration difference by
  aligning model index declarations with the deployed query indexes and
  removing five redundant primary-key index declarations.
- Backfilled null knowledge/recognition creation and update timestamps before
  enforcing the existing non-null application contract.
- Replaced the legacy global warehouse-name constraint with tenant-scoped
  `(organization_id, name)` uniqueness, allowing separate organizations to use
  equal warehouse names and codes without weakening in-tenant uniqueness.
- Added a pre-mutation downgrade refusal when cross-organization equal names
  can no longer fit the older global constraint.
- Added SQLite and PostgreSQL `alembic check` CI gates, controlled-restore
  compatibility through `0054`, tenant behavior coverage, and the schema
  contract runbook.

Verification: all 234 backend tests passed; fresh SQLite and PostgreSQL
base-to-`0054`, `0054 -> 0053 -> 0054`, zero-drift checks, duplicate-name
downgrade refusal, and post-cycle RLS verification passed; frontend ESLint,
TypeScript, and the Next.js 16.2.12 production build passed for all 40 static
routes; Python and npm dependency audits reported 0 known vulnerabilities;
production configuration, Compose configuration, and API/web image builds
passed.

## 20260807_0055 - Enterprise data residency controls

- Added a required normalized `DEPLOYMENT_REGION` for staging and production,
  plus a pre-worker database guard that refuses startup when any pinned
  organization belongs to another region.
- Added Enterprise-only organization residency assignment with optimistic
  versioning, current-password confirmation, enforcement timestamp, platform
  status projection, and dedicated tenant-scoped audit evidence.
- Blocked mismatched password/MFA login, existing Cookie/Bearer sessions,
  invitations, external API keys, and public branding without weakening the
  platform recovery boundary.
- Added platform create/edit controls, customer read-only status, deployment
  documentation, controlled-restore compatibility through `0055`, and a guarded
  downgrade that refuses to erase active residency evidence.

Verification: all 239 backend tests passed; fresh SQLite and PostgreSQL 16
base-to-`0055`, `0055 -> 0054 -> 0055`, zero-drift checks, downgrade refusal,
production readiness, and post-cycle RLS checks passed; frontend ESLint,
TypeScript, and the Next.js 16.2.12 production build passed for all 40 static
routes; Python and npm dependency audits reported 0 known vulnerabilities.

## 20260807_0056 - Multi-instance background worker leases

- Added one shared database scheduler row per integration/billing worker with
  atomic election, renewable expiration, durable next-run timing, and safe
  operational evidence.
- Added monotonically increasing generation fencing so expired owners cannot
  renew, finish, release, or overwrite a replacement owner's run.
- Added immediate graceful handoff, automatic abandoned-run recovery after
  expiration, long-cycle heartbeats, and shutdown protection for worker threads
  that Python cannot cancel safely.
- Added healthy replica `standby` state and platform-only lease generation,
  expiration, current-run, and next-run visibility without host identity.
- Added deployable timing validation, configuration templates, controlled
  restore compatibility through `0056`, and a multi-instance operations
  runbook.

Verification: all 246 backend tests passed; fresh SQLite and PostgreSQL 16
base-to-`0056`, `0056 -> 0055 -> 0056`, zero-drift, RLS, eight-way election,
restricted-role access, expiration takeover, and stale-generation fencing
passed; frontend ESLint, TypeScript, and the Next.js production build passed for
all 40 static routes; Python and npm dependency audits found no vulnerabilities;
production Compose configuration and API/web image builds passed.
