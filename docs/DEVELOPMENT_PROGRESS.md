# OpenPartsFlow development progress

## Baseline

- Starting commit: `c759ea6` (`feat: add offline sync center`)
- Delivery strategy: sellable workflow first, intelligence second, platform capabilities last.
- Required batch gates: migration, backend tests, frontend production build, security review, Git commit, push, CI verification.

## 2026-08-08 - Abnormal part-usage baselines and manager review queue

Status: implemented; release verification in progress.

Delivered:

- Replaced the transient global-cost report with persisted, tenant-scoped
  baselines for job/machine/store, job/machine, machine, job, and organization
  fallback scopes.
- Limited quantity evidence to prior completed and locked work orders and
  retained sample coverage, P90/deviation thresholds, context support, source
  ranges, fingerprints, calculation versions, and timestamps.
- Added quantity-spike, rare part-combination, and warehouse-region local
  off-hours signals with human explanations. Signals are advisory and cannot
  edit inventory or work-order facts.
- Evaluated new usage inside the authenticated inventory transaction and added
  a bounded, audited historical evaluation endpoint for existing data.
- Added manager/admin `pending -> acknowledged -> confirmed|dismissed`
  decisions with required notes/reasons, responsible accounts, server times,
  exact-retry idempotency, optimistic versions, and audit evidence.
- Added active/history, severity and engineer filters, baseline inspection, and
  the responsive `/abnormal-usage` review workbench while preserving the
  existing report URL.
- Added revision `0063`, forced PostgreSQL RLS for both tables, restore/schema
  compatibility, AppSheet parity records, and dedicated operating docs.

Verification so far:

- Automatic quantity spikes, rare combinations, bounded historical scans,
  baseline evidence, state transitions, stale versions, report permissions,
  role denial, tenant isolation, RLS coverage, and compatibility regressions
  passed (14 targeted tests).
- Fresh SQLite base-to-`0063`, `0063 -> 0062 -> 0063`, and Alembic model
  zero-drift checks passed.
- All 275 backend tests passed. Frontend ESLint, TypeScript, and Next.js
  production build passed for all 47 static routes.
- Python dependency consistency/vulnerability checks and full/production npm
  audits passed with no known vulnerabilities. Production configuration and
  Compose topology passed. Local Docker Desktop was not running, so GitHub's
  private-deployment job is the authoritative PostgreSQL/RLS and image-build
  gate.
- Backed up the local `0062` database as
  `openpartsflow.pre-0063-20260808-201604.db` (1,617,920 bytes; SHA-256
  `4D6BD61826E2751BE37A94B8A493B1003E325C74D7BF368FEF41E65133C93902`)
  before upgrading the configured database to `0063` and confirming zero
  model drift.

## 2026-08-08 - Governed low-stock threshold rules and alert evidence

Status: implemented, published as draft PR #36, and verified by GitHub Actions
run #71. Backend, frontend, private PostgreSQL/RLS, dependency, and production
API/Web image jobs all passed.

Delivered:

- Added tenant warehouse/part threshold and replenishment-quantity overrides
  with business reason, actor attribution, optimistic versioning, inactive
  fallback, controlled restore participation, and forced PostgreSQL RLS.
- Replaced ad-hoc notification writes with a duplicate-safe evaluator used by
  part consumption, manual scans, rule changes, and failed replenishments.
- Retained immutable trigger rule/threshold/quantity evidence plus live current
  threshold, physical quantity, replenishment link, and action capabilities.
- Enforced `open -> acknowledged -> resolved` with responsible account/time/
  note evidence, optimistic versions, exact-retry idempotency, and resolution
  only after stock recovery or completed linked replenishment.
- Deprecated the arbitrary notification status PATCH with `410`; creating a
  replenishment now records acknowledgement, while rejection/cancellation
  re-evaluates continuing shortages into one fresh actionable alert.
- Added `/low-stock-rules` for manager governance and warehouse operations,
  active/history evidence, evaluation, acknowledgement, and verified closure;
  updated `/warehouse-tasks` to use the same versioned contract.
- Added revision `0062`, documentation, AppSheet parity status, restore/RLS
  coverage, and threshold-aware low-stock projections.

Verification so far:

- Threshold fallback/override, duplicate suppression, action idempotency,
  stale versions, recovery gating, actor evidence, role denial, tenant
  isolation, consumption triggering, and threshold projection passed.
- Replenishment cancellation and tenant-isolation regressions were updated to
  the one-active-alert contract and passed; continued shortage after a
  cancellation creates one fresh alert.
- All 271 backend tests passed.
- Frontend ESLint, TypeScript, and Next.js production build passed for all 46
  static routes.
- Fresh SQLite base-to-`0062`, `0062 -> 0061 -> 0062`, and Alembic model
  zero-drift checks passed.
- Python dependency consistency/vulnerability checks and full/production npm
  audits passed with no known vulnerabilities; production configuration and
  Compose topology validation passed. Local Docker Desktop was not running, so
  the GitHub private-deployment job remains the authoritative image build and
  PostgreSQL/RLS gate for this batch.
- Backed up the local `0061` database as
  `openpartsflow.pre-0062-20260808-194533.db` (1,581,056 bytes; SHA-256
  `B416C91F1B56DB8D0463480C956D1688C7ABE214E569D4BE7BE74F5B7B08B403`)
  before upgrading the configured database to `0062` and confirming zero
  model drift.

## 2026-08-07 - Employee performance scorecards and role dashboards

Status: implemented, locally verified, and published as draft PR #35. GitHub
CI run 70 passed all backend, frontend, PostgreSQL/RLS, dependency-audit, and
production-image jobs.

Delivered:

- Added bounded, tenant-scoped employee scorecards that keep completed
  throughput, created-cohort completion, first-time-fix, rework, duration, and
  parts-use evidence as separate, documented metrics.
- Added explicit first-time-fix, duration, and parts-usage coverage so incomplete
  evidence cannot silently become a favorable or unfavorable score.
- Added manager/administrator team and engineer filters with financial parts
  efficiency, revenue, labor, and contribution evidence.
- Added an engineer self dashboard that rejects coworker queries, omits team
  identities, and redacts every financial field while retaining the engineer's
  own operational and parts-quantity evidence.
- Added non-engineer/missing completion attribution disclosure, inactive-user
  preservation, maximum 366-day ranges, live `no-store` responses, and the
  `/performance` responsive workbench.

Verification so far:

- Calculation reconciliation, period-end cohort semantics, post-period
  completion exclusion, quality coverage, parts efficiency, financial
  redaction, self-only access, manager filters, role denial, range bounds, and
  tenant isolation passed (3 tests).
- Enterprise analytics, RBAC, and profit-snapshot regression suite passed (14
  tests including the new scorecard tests).
- Frontend ESLint, TypeScript, and Next.js production build passed for all 45
  static routes.
- All 268 backend tests passed.
- The local `0061` database remains at model zero drift; this read-only feature
  requires no schema revision or data rewrite.
- Python dependency consistency/vulnerability checks and full/production npm
  audits passed with no known vulnerabilities; Compose topology and API/web
  production images built successfully.

## 2026-08-07 - Persisted work-order profit snapshots and rankings

Status: implemented, locally verified, and published as draft PR #34. GitHub
CI run 69 passed all backend, frontend, PostgreSQL/RLS, dependency-audit, and
production-image jobs.

Delivered:

- Captures exactly one tenant-scoped profit snapshot in the same transaction
  that completes and locks a work order.
- Stores historical accountable-engineer, machine-type, revenue, labor,
  installed-parts cost, profit, region-attribution, and SHA-256 source evidence.
- Attributes service region from actual parts usage, then the engineer vehicle,
  then the tenant default, while preserving an explicit unattributed state.
- Added daily coverage and profit series plus engineer, region, and machine-type
  rankings with bounded date ranges and result counts.
- Added manager/administrator password-confirmed, audited, idempotent historical
  backfill that retains conflicting snapshots for investigation.
- Added the `/profit-snapshots` management workbench, tenant export inclusion,
  forced PostgreSQL RLS, revision `0061`, and controlled restore compatibility.

Verification so far:

- Snapshot capture, backfill idempotency/conflicts, ranking reconciliation,
  tenant isolation, role enforcement, range bounds, audit evidence, and the
  real work-order completion path passed (4 tests).
- Completion ownership, device authentication, policy, and inventory-flow
  regression suites passed (15 tests).
- Frontend ESLint, TypeScript, and Next.js production build passed for all 44
  static routes.
- All 265 backend tests passed, including the complete migration-chain RLS
  coverage gate for every tenant model.
- Fresh SQLite base-to-`0061`, zero-drift, four-index presence, and
  `0061 -> 0060 -> 0061` migration cycle passed.
- PostgreSQL 16 fresh base-to-`0061`, zero-drift, forced RLS/policy presence,
  tenant read/write/platform verification, and `0061 -> 0060 -> 0061`
  migration cycle passed.
- Python dependency consistency/vulnerability checks and full/production npm
  audits passed with no known vulnerabilities; Compose topology and API/web
  production images built successfully.
- Backed up the local `0060` database as
  `openpartsflow.pre-0061-20260807-183024.db` (1,540,096 bytes; SHA-256
  `C4608F794F3272B945D5CEAE6F71FEE1C93826AD2C7F7E5A470393FF4CC8FBAE`)
  before upgrading the configured database to `0061` and confirming zero
  model drift.

## 2026-08-07 - Van inventory planning and consumption trends

Status: implemented, locally verified, and published as draft PR #33. GitHub
CI run 68 passed all backend, frontend, PostgreSQL/RLS, dependency-audit, and
production-image jobs.

Delivered:

- Added tenant- and role-scoped vehicle planning for warehouse personnel,
  managers, and administrators while denying engineers and assistants the
  company-wide view.
- Calculates on-hand, pending inbound/outbound custody, threshold, historical
  work-order consumption, forward forecast, target, projected balance, and an
  explainable replenish/return quantity for each assigned vehicle and part.
- Added engineer consumption totals, distinct work-order counts, daily
  averages, and daily trend evidence from canonical `WORK_ORDER_USED` ledger
  movements.
- Selects a preferred same-region/main-warehouse source, subtracts picking
  reservations, and discloses whether the complete refill can be fulfilled.
- Added a dedicated management workbench and safe prefill into the existing
  authenticated replenishment workflow; vehicle returns remain initiated by
  the assigned engineer from **My Van**.
- Added revision `0060` with three tenant-leading planning indexes and extended
  controlled restore compatibility.

Verification so far:

- Calculation, pending-custody projection, forecast, source availability,
  filters, response bounds, tenant isolation, role enforcement, and second-
  tenant scoping passed (3 tests).
- Frontend ESLint, TypeScript, and Next.js production build passed for all 43
  static routes.
- All 261 backend tests passed.
- Fresh SQLite base-to-`0060`, zero-drift, three-index presence, and
  `0060 -> 0059 -> 0060` migration cycle passed.
- PostgreSQL 16 fresh base-to-`0060`, zero-drift, migration cycle, planning-
  index presence, and tenant RLS read/write/platform verification passed.
- Python dependency consistency and vulnerability audit plus full/production
  npm audits passed with no known vulnerabilities; Compose topology and API/web
  production images built successfully.
- Backed up the local `0059` database as
  `openpartsflow.pre-0060-20260807-180706.db` (1,527,808 bytes; SHA-256
  `8CD7CB8B43A343205CCF066DC5AB988FDC012F452B785A264BC01BF604BDA75D`)
  before upgrading the configured database to `0060` and confirming zero model
  drift.

## 2026-08-07 - Inventory reconciliation exception workbench

Status: implemented, locally verified, and published as draft PR #32. GitHub
CI run 67 passed all backend, frontend, PostgreSQL/RLS, dependency-audit, and
production-image jobs.

Delivered:

- Added a bounded, tenant-isolated, read-only exception queue across
  replenishment custody, vehicle returns, physical counts, and their immutable
  inventory movements.
- Separates critical evidence mismatches from pending count variances so an
  operator can distinguish corruption/incomplete custody from normal approval
  work.
- Validates movement type, workflow link, movement stage, part, quantity,
  source/destination warehouse, storage location, and required/forbidden links
  for the current workflow state.
- Added source/severity filters, priority ordering, truncation disclosure,
  workflow evidence IDs, and direct drill-down to the exact replenishment,
  return, or count even when it is older than the normal 100-row page.
- Added revision `0059` for the tenant-leading legacy reconciliation scan and
  extended controlled restore compatibility through the new revision.
- Kept the queue non-mutating: all correction, approval, and historical
  reconciliation remains inside the existing password-, device-, version-,
  role-, and audit-protected workflows.

Verification so far:

- Exception classification, healthy-record exclusion, tenant isolation,
  filters, response bounds, direct drill-down, warehouse/manager access, and
  engineer/assistant denial passed (3 tests).
- Replenishment custody and inventory-count regression suite passed (24 tests).
- Frontend ESLint, TypeScript, and Next.js production build passed for all 42
  static routes.
- All 258 backend tests passed.
- Fresh SQLite base-to-`0059`, zero-drift, and `0059 -> 0058 -> 0059`
  migration cycle passed.
- PostgreSQL 16 fresh base-to-`0059`, index-presence, zero-drift, RLS, and
  `0059 -> 0058 -> 0059` migration rehearsal passed.
- Python dependency consistency/requirement audit and full/production npm
  audits passed with no known vulnerabilities; Compose topology and API/web
  production images built successfully.
- Backed up the local `0058` database as
  `openpartsflow.pre-0059-20260807-174755.db` (SHA-256
  `BEC7B0BD661F8B3746F1F49CE7FE98876D9C7025BB6D47A780DBB1E9A80C0B1C`)
  before upgrading the configured database to `0059` and confirming zero
  model drift.

## 2026-08-07 - AppSheet parity inventory ledger workbench

Status: implemented, locally verified, and published as draft PR #31. GitHub CI
run 66 passed all backend, frontend, PostgreSQL/RLS, dependency-audit, and
production-image jobs.

Delivered:

- Added a read-only tenant-scoped business ledger for warehouse users,
  managers, and administrators, while explicitly denying engineers and
  assistants.
- Added server-side transaction type, part, source-or-destination warehouse,
  accountable user, work-order, date-range, and cursor filters with a bounded
  page size and a maximum 366-day requested range.
- Resolved part, warehouse, storage-location, work-order, actor, custody source,
  movement stage, unit cost, and linked workflow evidence without exposing
  another tenant's labels or filter options.
- Added the `Inventory Ledger` management page with a 30-day default view,
  business filters, work-order drill-down, source/destination traceability,
  value summaries, and progressive pagination.
- Added migration `0058` with six tenant-leading ledger query indexes and
  extended controlled restore compatibility through the new revision.

Verification:

- Ledger data resolution, tenant isolation, all filters, cursor pagination,
  range validation, warehouse access, and engineer denial passed (3 tests);
  the broader inventory, custody, RBAC, and restore suite passed (41 tests).
- Fresh SQLite base-to-`0058`, zero-drift check, and
  `0058 -> 0057 -> 0058` migration cycle passed.
- Frontend ESLint, TypeScript, and Next.js production build passed for all 41
  static routes.
- All 255 backend tests passed.
- PostgreSQL 16 fresh base-to-`0058`, zero-drift, RLS, all-six-index presence,
  and `0058 -> 0057 -> 0058` migration rehearsal passed.
- Updated transitive `nanoid` from `3.3.16` to `3.3.18` after the package audit
  identified GHSA-2v37-7h3g-55p8; production and full npm audits now report no
  known vulnerabilities.
- Python requirement/full-environment audits, dependency consistency, Compose
  topology, and production API/web image builds passed with no known dependency
  vulnerabilities.
- Backed up the local `0057` database as
  `openpartsflow.pre-0058-20260807-172750.db` (SHA-256
  `272BF2203D08C2067CA0873FBC0C52B25355E14637FAA641B32E6885D30D28A2`)
  before upgrading the configured database to `0058` and confirming zero
  model drift.

## 2026-08-07 - Phase 9 durable operations history

Status: implemented and locally verified.

Delivered:

- Added a platform-global, retention-controlled health sample model and
  migration `0057` for request-window, schema, worker, and uptime evidence that
  survives API restarts.
- Added per-replica sampling without scheduler election, idempotent interval
  writes, transactional retention cleanup, and non-reversible SHA-256 storage of
  randomized process identities.
- Added a bounded, platform-administrator-only history endpoint with explicit
  truncation, missing-bucket coverage, replica counts, and no tenant, host,
  request, credential, or exception detail.
- Correctly aggregates only the last rolling request snapshot per instance and
  output bucket, avoiding repeated request counts across minute samples.
- Added 6-hour through 7-day operations views while preserving external
  synthetic probes as the authoritative SLA source.
- Added fail-closed production configuration bounds, controlled-restore schema
  compatibility, RBAC documentation, deployment guidance, and migration notes.

Verification:

- Operations history, live monitoring, authorization, and deployment-setting
  target suite passed (42 tests), including bounded-query truncation and invalid
  time-range rejection.
- Fresh SQLite base-to-`0057`, zero-drift check, and
  `0057 -> 0056 -> 0057` migration cycle passed.
- Frontend ESLint, TypeScript, and Next.js production build passed for all 40
  static routes.
- All 252 backend tests passed.
- PostgreSQL 16 fresh base-to-`0057`, zero-drift, RLS, and
  `0057 -> 0056 -> 0057` rehearsal passed. The operations-history verifier
  passed eight-replica concurrent writes, same-bucket idempotency, retention,
  aggregation, and privacy using both owner and restricted
  `NOSUPERUSER/NOBYPASSRLS` application credentials.
- The repeatable PostgreSQL operations-history verifier is included in GitHub
  CI alongside the RLS and worker-lease verifiers.
- Python dependency consistency, requirement/full-environment vulnerability
  audits, full/production npm audits, production configuration, Compose
  topology, and API/web production image builds passed with no known dependency
  vulnerabilities.
- Backed up the local `0056` database as
  `openpartsflow.pre-0057-20260807-170652.db` (SHA-256
  `6F98273B331D741BC6BDD33787F049F17C148EA0DECCF6ED5C14B493C6C59646`)
  before upgrading the configured database to `0057` and confirming zero
  drift.

## 2026-08-07 - Phase 9 multi-instance worker leases

Status: implemented and locally verified.

Delivered:

- Added a platform-global database lease and shared schedule for integration
  delivery and billing reconciliation.
- Added atomic acquisition, heartbeat renewal, graceful release, expired-owner
  takeover, and monotonically increasing generation fencing so stale processes
  cannot publish late results.
- Preserved delivery compare-and-set/idempotency and billing row locks as
  defense-in-depth behind scheduler election.
- Added safe shutdown behavior for non-cancellable Python worker threads and
  bounded heartbeat callbacks during long delivery/billing cycles.
- Added healthy `standby` monitoring plus platform-only shared generation,
  expiration, current-run, and next-run evidence without host identifiers.
- Added fail-closed production timing validation, migration `0056`, controlled
  restore compatibility, and the operator runbook in `docs/WORKER_LEASES.md`.

Verification:

- Worker competition, renewal, release, schedule preservation, stale-owner
  fencing, expired takeover, error handling, and four-replica SQLite contention
  tests passed.
- Operations, deployment, billing, and external-integration target suite passed
  (48 tests).
- Fresh SQLite base-to-`0056` migration and `alembic check` passed with no model
  drift.
- All 246 backend tests passed; frontend ESLint, TypeScript, and the Next.js
  production build passed for all 40 static routes.
- PostgreSQL 16 base-to-`0056`, `0056 -> 0055 -> 0056`, zero-drift, RLS, eight-way
  election, shared scheduling, expiration takeover, and stale-generation fencing
  passed under both owner and restricted runtime credentials.
- Python dependency consistency, requirement/full-environment vulnerability
  audits, full/production npm audits, production Compose configuration, and
  API/web image builds passed with no known dependency vulnerabilities.
- Backed up the local `0055` database as
  `openpartsflow.pre-0056-20260807-164519.db` (SHA-256
  `B0A929FF03BA7D051DBB5F8E0EDD6213C02C8DEE8C035A6133F00347708A03DC`)
  before upgrading the configured database to `0056` head and confirming zero
  drift.

## 2026-08-07 - Phase 9 Enterprise data residency controls

Status: implemented and locally verified.

Delivered:

- Added normalized deployment-region identity with fail-closed staging and
  production validation.
- Added Enterprise-only organization residency pinning, enforcement timestamps,
  optimistic settings versions, platform-password confirmation, and audit
  evidence without credential content.
- Added runtime denial for login, existing sessions, invitations, API keys, and
  public branding when tenant and deployment regions differ.
- Added a production startup database guard before integration/billing workers,
  so a mismatched database cannot continue processing in the background.
- Added platform create/edit UI, customer read-only status, migration `0055`,
  guarded downgrade, controlled-restore compatibility, and the relocation
  runbook in `docs/DATA_RESIDENCY.md`.

Verification:

- Backend: all 239 tests passed, including residency normalization, Enterprise
  entitlement, password confirmation, audit secrecy, session/API-key denial,
  public metadata hiding, and production startup mismatch refusal.
- SQLite and PostgreSQL 16: fresh base-to-`0055`, `0055 -> 0054 -> 0055`,
  `alembic check`, evidence-protected downgrade, deployment readiness, and RLS
  checks passed.
- Frontend ESLint, TypeScript, and the Next.js production build passed for all
  40 static routes; Python and npm dependency audits found no vulnerabilities.
- Backed up the local `0054` database as
  `openpartsflow.pre-0055-20260807-161848.db` (SHA-256
  `09ED203577A1D9ABDB689D07BDA04B7080DBB49CE46C34B3006C07ABD9661037`)
  before upgrading the configured database to `0055` head.

## 2026-08-07 - Phase 9 private deployment readiness

Status: implemented and locally verified.

Delivered:

- Added a production-only Compose topology for PostgreSQL, a one-shot Alembic
  migration gate, API, and static PWA reverse proxy with only one published
  ingress port.
- Separated migration from API startup so concurrent or restarted API instances
  cannot race schema changes.
- Added non-root API and web images with read-only root filesystems, dropped
  capabilities, no-new-privileges, health gates, immutable release metadata,
  explicit writable data volumes, and runtime-only Python dependencies.
- Added persistent and distinct PostgreSQL, public evidence, protected evidence,
  and restore rollback volumes; application upload paths now honor the configured
  storage roots.
- Added same-origin `/api`, `/uploads`, and `/health` proxying, bounded upload
  size/timeouts, PWA cache controls, and baseline browser security headers.
- Added fail-closed staging/production validation for database driver, secrets,
  debug mode, JWT algorithm, HTTPS origins, CORS wildcards, and storage paths.
- Removed localhost CORS origins from staging/production while retaining them for
  development.
- Added a redacted validation CLI, production environment template, deployment,
  upgrade, health, backup, rollback, and incident-isolation runbook.

Verification:

- Production Compose configuration parses successfully with the supplied
  environment template.
- Production safety validation and topology/security contracts passed 15
  targeted backend tests.
- Both production images built successfully; the frontend image generated all
  38 static routes from a clean `npm ci --include=dev` dependency install.
- A complete disposable production stack migrated a new PostgreSQL 16 database
  from base through `20260807_0045`; the one-shot migrator exited zero and API,
  database, and web services became healthy.
- Container probes reported database/schema/worker readiness; the proxy returned
  401 for unauthenticated business APIs, excluded localhost production CORS,
  allowed the configured HTTPS origin, and returned baseline security headers.
- Runtime inspection confirmed API UID/GID `10001:10001`, web UID/GID `101:101`,
  read-only root filesystems, all capabilities dropped, denied code writes, and
  successful writes only to the intended evidence volumes or `/tmp`.
- Corrected fresh-PostgreSQL boolean literals in historical organization and
  regional migrations while preserving SQLite compatibility.
- Backend: all 176 tests passed, including deployment configuration/contract,
  complete migration history, tenant isolation, RBAC, ownership, custody,
  integrations, billing, analytics, Agent, backup, and restore coverage.
- Fresh SQLite base-to-`0045` plus `0045 -> 0044 -> 0045` rehearsal passed.
- Python compilation and dependency consistency passed; frontend ESLint and the
  production npm audit passed with 0 known vulnerabilities.
- CI now validates fail-closed production settings, migrates a real PostgreSQL
  service to the exact head, parses Compose, and builds both production images.

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

## 2026-08-07 - Phase 9 controlled restore media writeback

Status: implemented and locally verified.

Delivered:

- Added restore rehearsal counts for media creates, overwrites, unchanged
  content, and unsafe/conflicting destinations.
- Added exact archive-reference mapping to configured public/private roots with
  traversal, path mismatch, duplicate target, symbolic-link, and regular-file
  enforcement.
- Added resulting-tenant reference validation and cross-tenant media-path
  collision blocking before any file can enter an approved plan.
- Added protected staging of archive content and overwritten originals with a
  configurable 1 GiB evidence limit and durable SHA-256/size records.
- Added same-directory temporary-file promotion, application compensation,
  live-file drift checks, evidence corruption checks, and file-level rollback.
- Added rollback compensation that reapplies archive content if its database
  commit fails, followed by evidence cleanup only after successful completion.
- Added Alembic revision `20260807_0039`, administrator UI evidence, deployment
  settings, RBAC boundaries, and operator documentation.

Verification:

- Restore validation, record rehydration, public overwrite, private create,
  unsafe target, evidence corruption, live drift, rollback, roles, and audit
  tests: 7 passed; export regressions: 3 passed.
- Backend: all 137 tests passed.
- Fresh base-to-`0039`, empty `0039 -> 0038 -> 0039`, schema/constraint
  inspection, and configured media-evidence downgrade refusal passed on SQLite.
- Frontend: ESLint, TypeScript, and Next.js production build passed for all 33
  static routes.
- Python dependency consistency and full/production npm audits passed with 0
  known vulnerabilities.

## 2026-08-07 - Phase 9 legacy database adoption and schema ownership

Status: implemented, locally adopted, and verified.

Delivered:

- Added Alembic revision `20260807_0040` for the four operational tables and
  eleven compatibility fields that were previously created only by runtime
  SQLAlchemy or ad hoc startup mutations.
- Removed application-import schema creation and alteration; production startup
  now performs a read-only, fail-closed check against the sole Alembic head.
- Added a read-only SQLite adoption rehearsal that rejects unknown tables or
  columns, corrupt databases, foreign-key violations, unsafe missing defaults,
  and already-versioned databases.
- Added exclusive-lock apply with an immutable pre-adoption backup, isolated
  full-history candidate migration, deterministic field derivations, per-table
  counts and value hashes, integrity verification, atomic replacement, failure
  restoration, and a JSON audit report.
- Updated the one-command Windows startup to detect a legacy local SQLite file,
  run the protected adoption automatically, apply normal migrations, and stop
  before launching services on any failed safety check.
- Rehearsed and applied the configured local database, retained its backup and
  report, and confirmed the next startup preparation was idempotent.

Verification:

- Legacy rehearsal, non-empty apply, unknown-data refusal, lock refusal, schema
  guard, migration backfill, downgrade, and integrity tests: 5 passed.
- Backend: all 142 tests passed; the live application root returned `200` after
  the startup schema check.
- Python compilation and dependency consistency passed.
- Frontend: ESLint, TypeScript, and Next.js 16.2.12 production build passed for
  all 33 static routes.
- Full and production npm audits passed with 0 known vulnerabilities.
- GitHub PR #7 backend and frontend CI jobs passed.

## 2026-08-07 - Phase 9 enterprise audit console

Status: implemented, locally migrated, and verified.

Delivered:

- Replaced the raw audit-only experience with a structured tenant-scoped
  search API while retaining the legacy list response for existing clients.
- Added exact action, entity, actor, and UTC time filters, descending cursor
  pagination, parsed metadata with explicit malformed-legacy evidence, and
  no-store response controls.
- Added bounded activity summaries for event totals, unique authenticated
  actors, latest activity, top actions, and top entity types.
- Added administrator-only CSV export with Bearer/current-password
  reauthentication, spreadsheet-formula hardening, a configurable 100,000-row
  cap, SHA-256 and row-count headers, and a secret-free export audit event.
- Added a manager/administrator Audit Logs workspace with summary cards,
  filtering, metadata inspection, load-more pagination, and administrator-only
  export controls that display the returned digest evidence.
- Added Alembic revision `20260807_0041` with tenant-first time, action, and
  entity lookup indexes plus API/RBAC/operator documentation.
- Upgraded the configured local database from `0040` to `0041` and inspected
  all three composite indexes in SQLite.

Verification:

- Audit tenant isolation, filters, cursor pagination, malformed metadata,
  compatibility response, role enforcement, password rejection, formula-safe
  CSV, SHA-256 evidence, no-store behavior, and export audit tests passed.
- Backend: all 144 tests passed, including full Alembic history and legacy
  adoption coverage.
- Python compilation passed.
- Frontend: ESLint, TypeScript, and the Next.js 16.2.12 production build passed
  for all 34 static routes.

## 2026-08-07 - Phase 9 operations monitoring and SLA readiness

Status: implemented and locally verified.

Delivered:

- Replaced the pilot checklist's hard-coded health value with runtime worker
  state.
- Added minimal unauthenticated `/health/live` and database/schema-backed
  `/health/ready` probes with no-store responses and no sensitive details.
- Added a bounded, thread-safe five-minute request window for 5xx rate,
  average latency, and p95 latency while excluding probe traffic.
- Added integration-delivery and billing-reconciliation worker start, success,
  result-count, error-class, recovery, and staleness evidence; delivery-loop
  exceptions no longer silently terminate the worker task.
- Added a platform-admin-only cross-customer operational summary for outbound
  queues, critical billing notices, backup policy gaps, restore conflicts,
  database latency, schema state, request thresholds, and worker alerts.
- Added a 30-second-refreshing Platform Operations page and platform-only
  navigation while fixing the nested platform-route active state.
- Documented probe semantics, threshold configuration, privacy boundaries,
  external time-series retention requirements, and deployment checks.

Verification:

- Monitor state, request metrics, worker error/stale/recovery, health-probe,
  schema failure, cross-tenant aggregate, sensitive-detail exclusion, and
  platform-role tests passed.
- Existing platform onboarding, external delivery, and billing lifecycle
  regressions passed.
- Backend: all 147 tests passed.
- Frontend ESLint and TypeScript passed; Next.js production build passed for
  all 35 static routes.

## 2026-08-07 - Phase 9 enterprise access policies

Status: implemented, locally migrated, and verified.

Delivered:

- Added an allowlisted permission catalog for employee-directory, audit,
  reporting, and external-integration capabilities.
- Added compatible role defaults plus per-user `allow`, `deny`, and `inherit`
  resolution; explicit deny wins while administrator access remains immutable.
- Added tenant-scoped permission read and administrator management APIs with a
  mandatory reason and `change_user_permission` audit evidence.
- Applied effective permissions to employee reads, tenant audit reads/exports,
  operational reports, work-order profit/export, and integration read/manage
  endpoints without changing work-order ownership or custody controls.
- Added an administrator permission matrix to Employees and effective-policy
  navigation for Employees, Reports, Audit Logs, and Integrations.
- Added Alembic revision `20260807_0042`, upgraded the configured local
  database from `0041`, and documented resolution, endpoints, isolation, and
  deployment rules.

Verification:

- Role defaults, explicit allow, deny priority, inherit reset, audit evidence,
  delegated read/manage boundaries, immutable administrators, unknown codes,
  and cross-tenant isolation passed in 3 new tests.
- Related RBAC, enterprise audit, and external integration regressions passed;
  12 targeted backend tests passed.
- Backend: all 150 tests passed, including full migration history, legacy
  adoption, backup/restore, concurrency, RBAC, and custody coverage.
- Fresh base-to-`0042` plus `0042 -> 0041 -> 0042` downgrade/upgrade rehearsal
  passed on SQLite.
- Frontend ESLint and TypeScript checks passed; the Next.js 16.2.12 production
  build passed for all 35 static routes.
- Python compilation and dependency consistency passed; full and production
  npm audits reported 0 known vulnerabilities.

## 2026-08-07 - Phase 9 multi-region inventory

Status: implemented, locally migrated, and verified.

Delivered:

- Added tenant-scoped, versioned operating regions with unique code/name,
  validated IANA timezone, active/default invariants, and deterministic default
  creation for existing and newly used organizations.
- Added warehouse regional ownership and migrated all current warehouses to the
  organization's default region without changing ledger balances or vehicle
  custody.
- Added manager/administrator region creation, versioned updates, and audited
  warehouse assignment with an optimistic prior-region check and mandatory
  business reason.
- Added regional stock/low-stock/warehouse/vehicle summaries plus recent
  cross-region transfer history.
- Restricted cross-region main-warehouse transfers to managers and
  administrators, retained ordinary warehouse-role transfers inside a region,
  and preserved the generic vehicle-transfer prohibition.
- Added `from_region_id`, `to_region_id`, and `cross_region` transfer audit
  metadata while retaining standard actor and device evidence.
- Added a Regions workspace for summaries, configuration, warehouse placement,
  and transfer history, with read-only warehouse access.
- Added controlled export/restore ordering and safe older-archive compatibility;
  legacy adoption now generates regional defaults only after source row/hash
  validation succeeds.
- Added Alembic revision `20260807_0043` and upgraded the configured local
  database from `0042` to `0043`.

Verification:

- Four new tests cover default assignment, validation/version/default rules,
  warehouse audit evidence, cross-region authorization, regional balances and
  history, tenant isolation, and vehicle custody protection.
- Backend: all 154 tests passed, including full Alembic history, legacy
  adoption, backup/restore, concurrency, RBAC, and custody coverage.
- Fresh base-to-`0043` plus `0043 -> 0042 -> 0043` downgrade/upgrade rehearsal
  passed on SQLite; the configured local database reports `0043` head.
- Frontend ESLint and TypeScript checks passed; the Next.js 16.2.12 production
  build passed for all 36 static routes.

## 2026-08-07 - Phase 9 enterprise operations analytics

Status: implemented, locally migrated, and verified.

Delivered:

- Added one tenant-scoped operations endpoint with inclusive UTC date,
  engineer, and job-type filters plus an equal-length prior-period comparison.
- Defined created, completed, period-end backlog, first-time-fix, rework,
  duration, and gross-contribution KPIs directly from durable source records.
- Added automatic day/week/month trend grain and engineer/job-type breakdowns.
- Added current regional stock/value/low-stock summaries and completed-job part
  consumption without misrepresenting current inventory as a historical
  snapshot.
- Added first-time-fix, repair-duration, and engineer-attribution coverage,
  interpretation warnings, and source-freshness timestamps.
- Added a password-confirmed completed-work-order CSV with formula hardening,
  a configured fail-closed row limit, SHA-256 and row-count evidence, and an
  `enterprise_analytics_exported` audit event.
- Added a chart-led Analytics workspace with reusable filters and permission-
  aware export controls.
- Added Alembic revision `20260807_0044` for the bounded reporting query paths.

Verification:

- KPI and regional results reconcile to exact seeded source records.
- Equal-period comparisons, date validation, engineer/job-type filters,
  tenant isolation, permission grants/denies, reauthentication, CSV injection
  protection, digest evidence, audit metadata, and export row limits passed.
- Frontend ESLint and TypeScript checks passed.
- Backend: all 158 tests passed, including the complete migration history,
  legacy adoption, backup/restore, tenant isolation, RBAC, inventory custody,
  integrations, billing, monitoring, and analytics reconciliation coverage.
- Fresh base-to-`0044` plus `0044 -> 0043 -> 0044` downgrade/upgrade rehearsal
  passed on SQLite; the configured local database reports `0044` head.
- The Next.js 16.2.12 production build passed for all 37 static routes.
- Python compilation and dependency consistency passed; full and production
  npm audits reported 0 known vulnerabilities.
- Alembic model comparison reported only the documented pre-existing drift and
  no missing analytics index or other new `0044` operation.

## 2026-08-07 - Phase 9 enterprise operations Agent

Status: implemented, locally migrated, and verified.

Delivered:

- Added a bounded English/Chinese intent resolver for daily brief, backlog,
  service quality, inventory readiness, and integration delivery health.
- Reused the reconciled analytics model and added server-owned backlog,
  inventory, replenishment, and outbound-delivery evidence tools.
- Added prioritized findings with metric values, units, source tables,
  definitions, human next steps, confidence, and explicit interpretation
  limitations.
- Enforced a hard read-only Agent contract: no work-order, inventory,
  integration, retry, approval, or custody mutation tool is exposed.
- Added effective `agent.use`, AI monthly allowance charging, tenant isolation,
  no-store responses, and a non-metered filter-options endpoint.
- Added immutable run evidence and matching audit evidence that retain the
  question SHA-256 digest and length but never raw question or response text.
- Added a management workspace with presets, shared filters, guardrails,
  evidence tables, existing-workflow links, and digest-only recent run history.
- Added Alembic revision `20260807_0045` and protected backup/restore and legacy-
  adoption head compatibility.

Verification completed so far:

- Three new tests prove evidence reconciliation, read-only business state,
  tenant isolation, raw-question non-retention, audit/tool trace, AI quota,
  validation-before-charge, intent classification, role defaults, delegation,
  and explicit deny behavior.
- Agent, analytics, and enterprise access-policy regression suites passed (10
  tests); frontend TypeScript passed and ESLint has no errors.
- Backend: all 161 tests passed, including complete migration history, legacy
  adoption, backup/restore, RBAC, tenant isolation, billing/AI quotas, work-
  order ownership, device authentication, inventory custody, analytics, and
  Agent guardrails.
- Fresh base-to-`0045` plus `0045 -> 0044 -> 0045` downgrade/upgrade rehearsal
  passed on SQLite; the configured local database reports `0045` head.
- Frontend ESLint and TypeScript passed; the Next.js 16.2.12 production build
  passed for all 38 static routes.
- Python compilation and dependency consistency passed; full and production
  npm audits reported 0 known vulnerabilities.
- Alembic model comparison reported only the documented pre-existing drift and
  no missing Agent table, Agent index, or other new `0045` operation.
## 2026-08-07 - Stripe commercial billing adapter

- Added server-controlled Stripe Checkout and customer portal sessions with
  administrator password confirmation and tenant-scoped request idempotency.
- Added platform-only refunds with PaymentIntent customer ownership validation.
- Added raw-body webhook signatures, bounded payloads, durable replay/collision
  evidence, out-of-order tenant binding, and provider-neutral lifecycle mapping.
- Added Stripe controls to organization settings, Stripe provider binding to
  platform billing operations, production validation, migration `0046`, and an
  operator runbook in `docs/STRIPE_BILLING.md`.
- Upgraded FastAPI, Starlette, python-multipart, and pytest to remove all known
  dependency advisories; 181 backend tests, the reversible migration rehearsal,
  frontend lint/build, and Python/npm security scans passed.

## 2026-08-07 - Phase 4 real AI visual recognition

Status: implemented, locally migrated, and verified.

Delivered:

- Replaced the photo-byte placeholder with an opt-in OpenAI Responses vision
  adapter using original-detail image input and strict structured output.
- Kept configuration fail-closed, keys server-only, the external host fixed to
  official HTTPS, redirects disabled, payload/output/catalog bounds enforced,
  and every response request set to `store: false`.
- Added tenant-scoped, versioned recognition attempts with client idempotency,
  provider/model/prompt evidence, image/request/output hashes, safe failure
  codes, validated normalized results, candidate count, and timestamps.
- Matched only existing tenant catalog rows, rejected mismatched model IDs/part
  numbers, preserved the complete human and work-order usage confirmation chain,
  and kept all recognition operations outside inventory mutation services.
- Enforced creator ownership for standalone analysis and the claiming engineer's
  registered phone plus current claim version for work-order-linked analysis.
- Added automatic mobile photo analysis, visible provider/attempt/status/output,
  safe error display, explicit retry, and graceful context-ranking fallback when
  AI is disabled.
- Moved new recognition photos out of public static storage and added
  authenticated tenant-wide photo delivery with private caching, sandboxing,
  and MIME-sniffing protection.
- Added Alembic revision `20260807_0047`, portable export participation,
  controlled-restore compatibility, configuration, API/RBAC, and operator docs.

Verification:

- Nine recognition/provider contract, success, failure, retry, idempotency,
  quota, audit, inventory-isolation, and human-lock tests passed.
- Fresh base-to-`0047` plus `0047 -> 0046 -> 0047` passed on SQLite.
- Frontend ESLint and TypeScript passed; the Next.js 16.2.12 production build
  generated all 38 static routes.
- All 186 backend tests passed after the private-media hardening; Python
  compilation and dependency consistency passed, and Python plus both npm
  audits reported 0 known vulnerabilities.
- Alembic model comparison reported only the documented pre-existing drift and
  no missing `0047` table, column, constraint, or index operation.
## 2026-08-07 - Phase 9 authentication hardening

Status: implemented and locally verified.

Delivered:

- Added durable dual-scope login throttling by keyed account and direct-peer fingerprints with bounded production configuration and `Retry-After` responses.
- Added tenant-scoped authentication security evidence without retaining raw email, IP, password, token, or device-secret values.
- Added versioned JWT sessions so administrator password changes and password-confirmed user revocation immediately invalidate all older access tokens.
- Added a Profile security workspace for every role and a safe recent-event view for tenant administrators.
- Added Alembic revision `20260807_0048`, portable export redaction, controlled-restore compatibility, and dynamic legacy-adoption head assertions.

Verification:

- Rate-limit threshold, source/account isolation, tenant isolation, sensitive-field exclusion, password-change invalidation, explicit revocation, and relogin tests passed.
- Fresh base-to-`0048` plus `0048 -> 0047 -> 0048` migration rehearsal passed on SQLite.
- Frontend ESLint and TypeScript passed; the Next.js 16.2.12 production build generated all 38 static routes.
- All 191 backend tests passed; requirements, production image tooling, and full/production npm security scans reported 0 known vulnerabilities after pinning pip 26.1.2 in the API image.

## 2026-08-07 - Phase 9 single-use password reset

Status: implemented and locally verified.

Delivered:

- Added generic, rate-limited reset requests that do not reveal whether an account exists and do not create unbounded work after a limit is reached.
- Added 32-byte tokens stored only as keyed hashes, 30-minute default expiry, prior-token invalidation, atomic single-use consumption, and replay rejection.
- Added TLS SMTP delivery after response completion, safe delivery evidence, production configuration validation, and fail-closed availability.
- Rotated the account authentication version on completion so every old browser and phone bearer token is immediately rejected.
- Added Forgot Password and Reset Password pages plus password-reset outcomes in the administrator security-event view.
- Added Alembic revision `20260807_0049`, portable export redaction, and controlled-restore/legacy-adoption compatibility.

Verification:

- Existing/unknown response equivalence, rate limiting, token secrecy, supersession, expiry, replay, SMTP success/failure, disabled-production behavior, password replacement, and session invalidation passed.
- All 200 backend tests passed.
- Fresh base-to-`0049` plus `0049 -> 0048 -> 0049` migration rehearsal passed on SQLite.
- Frontend ESLint and TypeScript passed; the Next.js 16.2.12 production build generated all 40 static routes.

## 2026-08-07 - Phase 9 administrator MFA

Status: implemented and locally verified.

Delivered:

- Added administrator/platform-administrator TOTP enrollment with password confirmation, expiring setup, confirmation before activation, and standards-compatible provisioning data.
- Encrypted TOTP secrets with a dedicated AES-256-GCM key ring and bound associated data, required valid key configuration in staging/production, and documented ordered key rotation.
- Added short-lived MFA login challenges that cannot authenticate as Bearer tokens, direct-peer/account rate limiting, conditional used-step advancement, and replay rejection.
- Added ten display-once recovery codes stored only as SHA-256 digests, atomic one-time consumption, password-and-factor regeneration, and safe disable.
- Revoked older sessions after enrollment, recovery-code regeneration, and disable; retained only safe tenant-scoped MFA outcomes.
- Added the mobile-ready login verification step and Profile MFA workspace, migration `0050`, export redaction, and restore/current-head compatibility.

Verification:

- Administrator enrollment, role denial, encrypted storage, export redaction, challenge isolation, invalid code, TOTP success/replay, recovery use, disable, session revocation, rate limiting, key rotation, ciphertext tamper rejection, and RFC vector tests passed.
- Fresh base-to-`0050` plus `0050 -> 0049 -> 0050` migration rehearsal passed on SQLite.
- Frontend ESLint, TypeScript, and the Next.js production build passed for all 40 static routes.
- All 209 backend tests passed, including authenticated-encryption tamper/key-rotation coverage and the complete authentication, tenant, backup/restore, inventory custody, billing, AI, and work-order authorization regression suites.
- Alembic model comparison reports only the previously documented drift and no missing `0050` column or constraint operation.
- Python requirement/full-environment and both npm audits reported 0 known vulnerabilities; production configuration, Compose contract/configuration, and API/web image builds passed.
- Backed up the local `0049` database as `openpartsflow.pre-0050-20260807-142601.db` (SHA-256 `7973597B3643A68B2B8B41948BCBD44AC47AC17EEE8B3B707C9E241E4898EBF2`) before upgrading the configured database to `0050` head.

## 2026-08-07 - Phase 9 secure browser sessions

Status: implemented and locally verified.

Delivered:

- Added explicit Cookie and Bearer login modes while preserving existing standalone-client compatibility and Authorization-header precedence.
- Kept the browser JWT in a production `__Host-` Cookie with `Secure`, `HttpOnly`, `SameSite=Strict`, no Domain, and root Path attributes; Cookie responses never expose the JWT to JavaScript.
- Bound a high-entropy CSRF proof digest into each Cookie JWT and enforced the matching header on every unsafe Cookie-authenticated method.
- Migrated the same-origin HTTPS frontend automatically, including JSON operations, offline replay, uploads, exports, private recognition images, and knowledge media.
- Preserved registered-device proof and claim-generation enforcement for engineer Cookie sessions.
- Added CSRF-protected logout and Cookie expiry after logout, password-confirmed session revocation, and MFA authentication-version rotation.
- Removed residual Bearer-only checks from password-confirmed commercial operations, engineer form editability, and governed visual-recognition actions so the production Cookie session works across the complete application.
- Updated private-deployment build controls, production configuration examples, authentication/RBAC/custody documentation, and commercial hardening status.

Verification:

- Cookie flags/body secrecy, safe reads, missing/wrong/cross-session CSRF rejection, Bearer precedence, logout, revocation, engineer device binding, invalid mode, production host prefix, and MFA Cookie completion tests passed.
- All 218 backend tests passed across authentication, tenant isolation, work-order ownership, inventory custody, billing, backup/restore, AI, and offline workflows.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes.
- Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose contract/configuration, and API/web image builds passed with no known dependency vulnerabilities.

## 2026-08-07 - Phase 9 verified employee invitations

Status: implemented and locally verified.

Delivered:

- Required a validated TLS SMTP path for every production/staging invitation and failed before mutation when delivery is disabled or invalid.
- Sent the single-use sign-up URL only to the invited mailbox; production administrator responses, database rows, audit metadata, logs, and customer exports do not retain or reveal the raw token.
- Added durable `manual`, `pending`, `sent`, and `failed` delivery evidence with attempt count, safe failure code, and timestamps.
- Corrected invitation replacement to include the organization boundary so equal emails across tenants remain isolated.
- Added recipient-safe employee UI messaging, shared relay validation, Alembic revision `0051`, controlled-restore compatibility, onboarding guidance, and production configuration examples.

Verification:

- Recipient-only delivery, header injection rejection, TLS relay behavior, safe failure evidence, disabled-production behavior, manual development acceptance, token replay prevention, and cross-tenant replacement isolation passed.
- All 225 backend tests passed across authentication, tenant isolation, work-order ownership, inventory custody, billing, backup/restore, AI, and offline workflows.
- Fresh base-to-`0051` plus `0051 -> 0050 -> 0051` passed on SQLite.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes.
- Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.
- Backed up the local `0050` database as `openpartsflow.pre-0051-20260807-150000.db` (SHA-256 `6CB9399D906BDF61F2B5C3182D1902124C9D30660A596BF503C2B3B35AAE5567`) before upgrading the configured database to `0051` head.

## 2026-08-07 - Phase 9 interrupted outbound delivery recovery

Status: implemented and locally verified.

Delivered:

- Added a platform-administrator-only recovery endpoint and operations-console control for outbound Webhooks stranded in `processing` after a worker or host interruption.
- Required current-password confirmation and a normalized operational reason; customer administrators remain denied.
- Restricted recovery to a bounded batch older than the configured stale cutoff, with row locking and a state recheck to preserve concurrent worker completion.
- Returned eligible rows to the normal delivery queue without sending inline, resetting attempt counters, or changing their stable business idempotency keys.
- Added tenant-scoped audit evidence for every affected organization while excluding payloads, response bodies, callback URLs, credentials, and signatures.
- Added idempotent no-op behavior, cross-tenant/fresh/inbound boundaries, operator guidance, and external-integration documentation.

Verification:

- Targeted operations and external-delivery tests passed (10 tests); all 227 backend tests passed.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes.
- Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.
- No schema change is required; Alembic head remains `20260807_0051`.

## 2026-08-07 - Phase 9 governed disaster-recovery evidence retention

Status: implemented and locally verified.

Delivered:

- Added per-organization retention periods for portable-export integrity metadata, terminal/abandoned restore rehearsals, and applied restore rollback packages.
- Required administrator role, current-password confirmation, normalized operational reason, and optimistic organization settings version for policy changes and cleanup.
- Added fixed UTC previews with candidate counts and database/file byte totals; cleanup is bounded to 500 records and prioritizes sensitive expired rollback packages.
- Preserved approved restores, unexpired rollback windows, referenced exports, all customer business records, and immutable audit history.
- Added fixed rollback expiry on new restore applications and explicit refusal after the governed window.
- Added atomic protected file-evidence quarantine with compensation before commit and automatic recovery/completion after interrupted cleanup.
- Cleared expired database rollback content while retaining application hashes, purge time/operator attribution, safe per-run audit evidence, and idempotent no-op behavior.
- Added the Backups management controls, cross-tenant/role/password/version tests, old-archive compatibility, migration `0052`, and an operator runbook.

Verification:

- Retention, customer export, and controlled restore target suite passed (13 tests).
- Fresh base-to-`0052` and empty `0052 -> 0051 -> 0052` migration rehearsals passed on SQLite.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed for all 40 static routes.
- All 230 backend tests passed across authentication, tenant isolation, engineer ownership, inventory custody, billing, integrations, backups/restores, AI, and offline workflows.
- Python dependency consistency, requirement/full-environment vulnerability audits, full/production npm audits, production configuration, Compose configuration, and API/web image builds passed with no known dependency vulnerabilities.
- Backed up the local `0051` database as `openpartsflow.pre-0052-20260807-153430.db` (SHA-256 `484140685A362D342A7B6942E2A587697A11EEB5423D096F78890D868B33B87F`) before upgrading the configured database to `0052` head.

## 2026-08-07 - Phase 9 PostgreSQL tenant row-level security

Status: implemented and locally verified.

Delivered:

- Added database-enforced tenant read/write isolation to all 51 current tenant
  tables with PostgreSQL `ENABLE/FORCE ROW LEVEL SECURITY` and a shared policy.
- Added transaction-local organization/platform context so pooled connections
  automatically lose their prior scope on commit or rollback.
- Narrowed authenticated user and external API-key sessions immediately after
  server-owned tenant identity resolution; retained explicit reviewed platform
  scope for platform administrators, Stripe callbacks, billing reconciliation,
  delivery scanning, and operations recovery.
- Replaced all direct tenant-scope `Session.info` mutations in application code
  with tested tenant/platform database scope helpers.
- Split production database credentials between a one-shot migration owner and
  a restricted API role that cannot be superuser, inherit owner capability, or
  bypass RLS.
- Added an idempotent fresh/existing-volume role bootstrap, Compose contract
  coverage, a real PostgreSQL verification command, CI integration, migration
  `0053`, controlled-restore compatibility, and an operator runbook.

Verification:

- All 234 backend tests passed across authentication, tenant isolation,
  engineer ownership, inventory custody, billing, integrations,
  backups/restores, AI, and offline workflows.
- PostgreSQL 16 base-to-`0053`, repeat role bootstrap,
  `0053 -> 0052 -> 0053`, empty-scope denial, single-tenant visibility,
  cross-tenant write rejection, platform access, 51-policy coverage, and
  restricted-role capability checks passed.
- SQLite base-to-`0053` and `0053 -> 0052 -> 0053` passed.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed
  for all 40 static routes.
- Python dependency consistency, requirement/full-environment vulnerability
  audits, full/production npm audits, production configuration, Compose
  configuration, and API/web image builds passed with no known dependency
  vulnerabilities.
- Backed up the local `0052` database as
  `openpartsflow.pre-0053-20260807-155052.db` (SHA-256
  `ACB810C4719C364698F373CDC92DE3479C3C879DD204290B2D04C0FFEEEC43D2`)
  before upgrading the configured database to `0053` head.

## 2026-08-07 - Phase 9 database schema contract reconciliation

Status: implemented and locally verified.

Delivered:

- Audited fresh SQLite and PostgreSQL databases with Alembic autogeneration
  instead of assuming migration and model metadata were aligned.
- Removed five false redundant primary-key index declarations and registered
  the existing knowledge, recovery, history, and claim indexes in model
  metadata.
- Added migration `0054` to backfill and enforce eight required
  knowledge/recognition timestamps.
- Replaced global warehouse-name uniqueness with organization-scoped
  uniqueness; validated that two customers can use the same warehouse name and
  code while tenant reads remain isolated.
- Added a downgrade guard that preserves `0054` unchanged when real
  cross-organization names cannot fit the legacy global constraint.
- Added mandatory SQLite and PostgreSQL `alembic check` CI gates, restore
  compatibility, and the durable schema change procedure.

Verification:

- Fresh SQLite and PostgreSQL base-to-`0054` migrations both report
  `No new upgrade operations detected`.
- SQLite `0054 -> 0053 -> 0054`, duplicate-name downgrade refusal, cleanup,
  and successful retry passed.
- PostgreSQL `0054 -> 0053 -> 0054`, post-cycle schema check, and retained RLS
  read/write/platform verification passed.
- Tenant/API, RLS coverage, and private-deployment targeted tests passed.
- All 234 backend tests passed across authentication, tenant isolation,
  engineer ownership, inventory custody, billing, integrations,
  backups/restores, AI, and offline workflows.
- Frontend ESLint, TypeScript, and the Next.js 16.2.12 production build passed
  for all 40 static routes.
- Python dependency consistency, requirement/full-environment vulnerability
  audits, full/production npm audits, production configuration, Compose
  configuration, and API/web image builds passed with no known dependency
  vulnerabilities.
- Backed up the local `0053` database as
  `openpartsflow.pre-0054-20260807-160102.db` (SHA-256
  `CDA4B75A7F2A14261F3E9E2173BEF316C7C9F2A475BEB960BB31A018CF115AFE`)
  before upgrading the configured database to `0054` head and confirming zero
  drift.
