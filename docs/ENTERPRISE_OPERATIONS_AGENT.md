# Enterprise operations agent

The enterprise operations agent is a read-only, tenant-scoped decision-support
surface at `/agent`. It converts an operating question into a bounded intent,
runs server-owned evidence tools, and returns prioritized findings with the
source and definition for every displayed value.

The current mode is `deterministic_evidence`. No external language model is
called, no generated query is executed, and no returned recommendation can
write business data. This makes the initial enterprise Agent deployable without
sending customer data to another processor while preserving a provider-ready
boundary for a later reviewed model integration.

## Intents and tools

The caller may choose an intent or let the server classify English or Chinese
keywords into one of these allowlisted intents:

| Intent | Evidence tools |
| --- | --- |
| `daily_brief` | Enterprise analytics, work-order backlog, inventory readiness, and outbound integration delivery |
| `backlog_risk` | Selected-period backlog age, schedule exposure, and current claim state |
| `service_quality` | First-time-fix, rework, repair duration, and evidence coverage |
| `inventory_risk` | Current regional ledger stock, low-stock thresholds, notifications, and replenishment state |
| `integration_health` | Current outbound failed, pending, and stale-processing synchronization logs |

Date, engineer, and job-type filters are applied to work-order analytics. Current
inventory and integration health are tenant-wide live snapshots; the response
states this limitation rather than implying they are historical or engineer-
specific.

## API

```text
GET  /api/agent/options
POST /api/agent/operations
GET  /api/agent/runs?limit=20
```

All endpoints require effective `agent.use`. Managers and administrators receive
it by default, and administrators may explicitly allow or deny it for another
active tenant user. Each successful `POST` consumes one request from the
organization’s existing monthly AI allowance. Validation failures, permission
denials, and quota failures do not create a completed run.

Engineer names and engineer-specific filtering additionally require effective
`users.read`. A user delegated only `agent.use` receives no employee-directory
options and cannot probe an engineer ID through the Agent.

## Read-only and privacy guarantees

An Agent request may read only allowlisted organization data. The route has no
claim, edit, completion, inventory, approval, retry, reconciliation, or generic
mutation tool. It returns normal application links so an authorized person can
decide whether to enter an existing guarded workflow.

The server uses the raw question only during the request. Durable
`enterprise_agent_runs` evidence stores:

- the authenticated tenant and actor;
- resolved intent;
- SHA-256 question digest and character count, but not question text;
- selected date/engineer/job-type filters;
- the server-owned tools used;
- finding count, duration, status, and timestamp.

A matching `enterprise_agent_run_completed` audit event retains the same bounded
metadata plus the read-only and external-model flags. It never stores the raw
question, generated summary, customer records, credentials, tokens, or tool
result payloads.

## Evidence interpretation

Every finding includes a severity, a recommended human next step, and typed
evidence with its source table(s) and metric definition. First-time-fix and
repair-duration findings carry coverage warnings. Current inventory valuation
uses ledger quantity and current default cost. Historical cancellation and
claim-state snapshots do not yet exist, so the Agent declares that limitation.

Agent advice is operational decision support, not an authorization grant. The
existing work-order owner/device/password controls and inventory custody state
machines remain the only way to change business records.

## Deployment

Alembic revision `20260807_0045` creates the immutable Agent run-evidence table
and tenant/user/time indexes. Apply `alembic upgrade head` before enabling the
navigation item. Monitor request latency and AI allowance consumption. A future
external-model mode must add a separately configured provider, contractual data
handling, prompt/output safety evaluation, and an explicit test proving that the
model still receives no mutation capability.
