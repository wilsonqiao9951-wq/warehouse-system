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

Each entry may link a part, a completed work order from the same machine model, a fault/error code, an installation location, and an external HTTP(S) reference.

Related parts can be classified as:

- `recommended`
- `alternative` with the primary part it replaces
- `consumable`
- `reference`

The application also accepts protected photo/video uploads. These files are stored outside the public upload mount and served only through an authenticated knowledge-media endpoint.

## Governance lifecycle

```text
Manager or administrator creates draft
→ Or generate idempotent drafts from a completed same-model work order
→ Or upload a protected field photo/video draft
→ Curator edits draft
→ Administrator publishes
→ Engineers and warehouse users can read it
→ Administrator archives outdated guidance
→ Administrator may reopen it as a draft
```

Published or archived content cannot be edited in place. This prevents already-distributed repair guidance from changing without an explicit audit event. A replacement can be prepared as a new draft and published after review.

Completed-work-order capture creates up to three kinds of draft:

- fault/error/problem context
- the verified repair result
- one used-part note per distinct part

Only a completed work order labeled as a successful first-time repair can produce a `recommended` part draft. Rework and incomplete outcome labeling produce `reference` evidence instead. Origin keys make repeated extraction safe and idempotent.

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

Capture:

- `POST /api/machine-knowledge/{profile_id}/drafts/from-work-order`
- `POST /api/machine-knowledge/{profile_id}/media`
- `GET /api/machine-knowledge/media/{entry_id}`

Every mutation uses server-enforced role checks. Profile and entry changes use `expected_version` where an existing record can be overwritten or transitioned.

## Mobile workflow

The `/knowledge-base` workspace is available to engineers, managers, administrators, and warehouse users. A work-order detail page links directly to its exact machine model and ranks published exact-model guidance against the current fault, error code, and symptoms. Managers and administrators can generate drafts, upload protected media, and classify recommended/alternative parts and installation locations. Engineers and warehouse users see only published entries on active profiles.

The read-only work-order intelligence contract is documented in [`SERVICE_INTELLIGENCE.md`](SERVICE_INTELLIGENCE.md). It never promotes a draft or writes learned output back to a work order automatically.
