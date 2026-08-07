# Van Inventory Planning

OpenPartsFlow calculates explainable vehicle replenishment and return guidance
without creating or changing stock. The planner uses the immutable inventory
ledger and the existing authenticated custody workflows as its only evidence
and execution paths.

## Access and isolation

`GET /api/inventory/van-planning` is available to warehouse users, managers,
and administrators. Engineers and assistants are denied. Every vehicle, user,
part, transaction, replenishment, return, and warehouse lookup is constrained
to the authenticated organization.

The response is marked `Cache-Control: no-store`. An organization may have at
most 100 active assigned vehicles and 500 parts evaluated in one request, with
at most 500 recommendations returned. `truncated=true` discloses when a bound
was reached.

## Calculation

The default planning window looks back 30 days and forecasts 14 days. Both are
explicitly bounded (`1..366` and `1..90`). For every assigned vehicle and part:

```text
average_daily_usage = work-order-used ledger quantity / lookback_days
forecast_quantity   = ceil(average_daily_usage * coverage_days)
threshold_quantity  = max(part safety stock, part minimum stock)
target_quantity     = max(forecast_quantity, threshold_quantity)
projected_quantity  = on_hand + pending_replenishment - pending_return
```

- `projected < target` produces a replenishment recommendation.
- `projected > target` produces a return recommendation.
- equality is balanced and is omitted by default.

Pending replenishment includes non-reconciliation records in `requested`,
`picking`, or `shipped`. Pending return includes `requested` or `approved`;
shipped stock is already reflected in the ledger. This prevents the planner
from duplicating work already in custody.

The suggested source prefers a main warehouse in the vehicle's region, then
the largest available balance after picking reservations. The response states
whether that warehouse can fulfill the full recommended quantity.

## Execution rules

The planner is intentionally read-only:

- A replenishment recommendation opens the existing manual replenishment form
  with the part, vehicle, quantity, source, and evidence reason prefilled.
- A return recommendation instructs the assigned engineer to submit the return
  from **My Van**; warehouse personnel then approve and receive it.
- Generic inventory transactions remain unable to post to or from vehicles.
- Device binding, account/password verification, optimistic versions, tenant
  isolation, role checks, and audit evidence remain enforced by the custody
  endpoints.

## Filters

Supported query parameters are `lookback_days`, `coverage_days`,
`engineer_id`, `part_id`, `action`, `include_balanced`, and `limit`. A
cross-tenant or unknown engineer/part filter returns `404` without disclosing
whether that record exists elsewhere.
