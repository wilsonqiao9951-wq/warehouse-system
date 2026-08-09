# Governed pilot, UAT, and internal decision evidence

OpenPartsFlow replaces the former paper-only pilot checklist with tenant-owned,
account-attributed evidence. The workflow records an internal technical
expansion decision; it does not create customer commercial or legal acceptance.

## Campaign state

Each organization may have only one live campaign. The versioned state chain is:

```text
draft → active → decision_pending → go | no_go
                    ↓
                  active
```

Managers and administrators create a draft and move it between non-terminal
states. Every transition requires the signed-in account's current password, an
expected version, an operational reason, actor identity, and server time.
Terminal decisions cannot be edited or deleted.

## Role evidence

Administrators, managers, warehouse staff, and engineers submit only their own
`training` and `uat` attestations. The server derives the role from the current
session and applies a fixed checklist for that role; the request cannot supply a
different user or role. A passing result requires every fixed item. Failed or
partial attempts remain append-only, and an exact retry returns the same SHA-256
evidence rather than creating a duplicate.

Managers and administrators can review all tenant attestations. Other roles see
only their own evidence plus aggregate gate status, preventing unnecessary
employee evidence disclosure.

## Issues and decisions

Any authenticated operational participant can report a tenant-scoped `sev1`,
`sev2`, or `sev3` issue while the campaign is live. Managers and administrators
resolve issues with current-password confirmation, an expected version, and a
resolution reason. A `go` decision is rejected unless:

- the latest evidence for every operational role includes passed training and
  UAT;
- no severity-1 issue remains open; and
- a `matched` parallel reconciliation was created after the campaign started
  for an active AppSheet/Google Sheets integration and still matches that
  integration's current `ready` parity-contract revision and fingerprint.

Only an organization administrator can record the final `go` or `no_go`
decision. The decision stores a canonical snapshot of evidence IDs,
fingerprints, aggregate open-issue counts, reconciliation identity/status, and
gate results plus a SHA-256 fingerprint. It does not copy issue text, passwords,
tokens, AppSheet rows, customer records, or media into the decision snapshot.

## API and UI

- `GET/POST /api/pilot/campaigns`
- `GET /api/pilot/campaigns/{id}`
- `POST /api/pilot/campaigns/{id}/transitions`
- `POST /api/pilot/campaigns/{id}/attestations`
- `POST /api/pilot/campaigns/{id}/issues`
- `POST /api/pilot/campaigns/{id}/issues/{issue_id}/resolve`
- `POST /api/pilot/campaigns/{id}/decision`
- `/pilot-checklist` combines the live readiness snapshot with the governed
  campaign workspace.

Campaigns, attestations, and issues are in the shared tenant registry and use
explicit organization predicates plus forced PostgreSQL row-level security.
They are included in portable exports for customer evidence custody but are not
allowlisted for restore mutation. Migration `20260809_0069` creates the three
tables and their constraints/indexes.

## External acceptance boundary

The system cannot infer customer-specific AppSheet formulas, Bots, security
filters, attachment rules, contractual KPIs, or authorized external signers.
Those items require real customer input and separately retained approval. A
technical `go` means only that the organization chose to expand its controlled
OpenPartsFlow pilot under the recorded internal gates.
