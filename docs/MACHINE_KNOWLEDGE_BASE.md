# Machine Service Knowledge Base

Phase 5 begins with a governed knowledge contract: field experience can be organized quickly, but only reviewed content is shown as official service guidance.

## Data structure

Each organization owns independent machine profiles keyed by a normalized model name. A profile includes:

- manufacturer and model
- equipment type
- service summary
- completed-job evidence metrics
- confirmed machine/part associations
- typed service knowledge entries

Knowledge entry types are:

- `fault`
- `repair_step`
- `tool`
- `caution`
- `common_error`
- `photo`
- `video`
- `note`

Each entry may link a part, a completed work order from the same machine model, a fault/error code, and a safe HTTP(S) or `/uploads/` media URL.

## Governance lifecycle

```text
Manager or administrator creates draft
→ Curator edits draft
→ Administrator publishes
→ Engineers and warehouse users can read it
→ Administrator archives outdated guidance
→ Administrator may reopen it as a draft
```

Published or archived content cannot be edited in place. This prevents already-distributed repair guidance from changing without an explicit audit event. A replacement can be prepared as a new draft and published after review.

## Evidence and privacy

The API aggregates only completed, locked work orders whose machine model exactly matches the profile:

- completed work-order count
- count of labeled repair outcomes
- first-time-fix rate
- average server-recorded repair duration
- latest completed repair

Optional source work-order links must satisfy the same completed and same-model rules. All profiles, entries, parts, work orders, and audit events are tenant-scoped.

Engineer and warehouse responses receive only a service-safe part summary:

- part ID
- part number
- part name
- image
- recognition source
- confidence and confirmation count

Cost, supplier, and other commercial part fields are not returned.

## API

Read:

- `GET /api/machine-knowledge`
- `GET /api/machine-knowledge/{profile_id}`

Curate:

- `POST /api/machine-knowledge`
- `PATCH /api/machine-knowledge/{profile_id}`
- `POST /api/machine-knowledge/{profile_id}/entries`
- `PATCH /api/machine-knowledge/entries/{entry_id}`

Administrator review:

- `POST /api/machine-knowledge/entries/{entry_id}/actions`

Every mutation uses server-enforced role checks. Profile and entry changes use `expected_version` where an existing record can be overwritten or transitioned.

## Mobile workflow

The `/knowledge-base` workspace is available to engineers, managers, administrators, and warehouse users. A work-order detail page links directly to its exact machine model. Managers and administrators see draft tools; engineers and warehouse users see only published entries on active profiles.
