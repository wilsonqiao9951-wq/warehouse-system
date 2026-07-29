# Work-order service intelligence

Phase 5 service intelligence turns governed evidence into field guidance without allowing an automated result to change a work order, inventory, or the knowledge base.

## API

`GET /api/work-orders/{work_order_id}/service-intelligence`

The endpoint is read-only and uses the same shared work-order visibility rule as service context. Administrators, managers, warehouse users, and engineers may read a visible work order in their organization. Field writes remain restricted to the claiming engineer on the bound registered device, or to the existing explicitly audited administrator correction path.

The response contains:

- model-specific fault analysis;
- ranked published machine guidance;
- up to five similar completed work orders;
- a fixed `evidence_scope` value identifying the trusted source boundary.

## Trusted evidence boundary

Historical evidence must:

- belong to the current actor's organization;
- be locked;
- have a server completion timestamp;
- have `completed` status;
- not be the current work order.

Fault analysis additionally requires an exact normalized machine-model match. Knowledge guidance must come from an active exact-model profile and an administrator-published entry. Drafts, archived entries, inactive profiles, unlocked jobs, incomplete jobs, and other organizations are excluded.

## Similar work-order ranking

The deterministic score is:

| Signal | Maximum contribution |
| --- | ---: |
| Exact machine model | 40% |
| Exact work type | 15% |
| Exact fault type | 15% |
| Exact error code | 15% |
| Problem-description token overlap | 15% |

At least one explained signal and a 15 percent score are required. Results are then ordered by score, completion time, and stable work-order ID. Each result states its matched signals and returns only service evidence: problem, repair, outcome, first-time-fix label, rework label, duration, and aggregated used parts.

Financial fields, customer signatures, commercial part fields, and device secrets are not included.

## Fault analysis

For exact-model completed evidence, the API reports:

- completed job count;
- labeled first-time-fix count and rate;
- rework rate;
- average server-recorded repair duration;
- five most frequent fault types;
- five most frequent error codes.

The first-time-fix denominator includes only work orders whose first-time-fix value is explicitly labeled. Rework uses all trusted completed evidence. Fewer than three labeled outcomes produces a limited-confidence warning, and a rework rate of 25 percent or more produces a field-verification warning.

No machine model or no completed evidence produces an explicit no-evidence response instead of a diagnosis.

## Published knowledge ranking

Every candidate begins with a 20 percent exact-model/published-governance score. Ranking can add:

- 35 percent for the same error code;
- up to 25 percent for matching fault terms;
- up to 20 percent for matching symptom terms.

The API returns up to eight entries with their score and matched reason. Each entry includes service-safe related/alternative part summaries, installation location, and authenticated media reference where available. It never returns draft controls, commercial part values, or unpublished content.

## Mobile use

The work-order detail screen displays:

- same-model evidence, first-time-fix, rework, and average repair metrics;
- frequent fault/error evidence and confidence warnings;
- expandable published guidance with protected media access;
- expandable similar jobs with outcomes, durations, and parts used.

These results are advisory. The claiming engineer remains responsible for field verification and the normal authenticated completion workflow.
