# Learned part recommendation ranking

Phase 3 recommendations are calculated from the organization's completed work orders. Open, pending-approval, and current work orders are not trusted as learned evidence.

## Matching order

Each historical work order receives an explainable similarity score:

1. Same machine and same job type
2. Same machine
3. Same fault type
4. Same error code
5. Similar problem-description terms
6. Same job type when stronger equipment evidence is unavailable

The service reads at most the latest 500 completed work orders and returns at most 20 ranked parts. Multiple usage rows for the same part and work order are combined before averages are calculated.

## Part quality and quantity

For each candidate part, the response calculates:

- `recommended_quantity`: rounded average quantity per matching completed work order, with a minimum of one
- `usage_count`: distinct matching completed work orders that used the part
- `total_quantity`: total quantity used across those work orders
- `success_rate`: successful first-time repairs divided by fully labeled outcomes
- `average_repair_minutes`: average server-measured repair duration when available
- `confidence`: a zero-to-one score combining best match, average match, evidence volume, labeled success, and current availability

A successful outcome requires all of:

- a repaired/fixed/resolved outcome
- `first_time_fix = true`
- `is_rework = false`

Unknown legacy outcomes do not count as failures. They return `success_rate: null`.

## Inventory availability

Availability is calculated from the tenant-scoped inventory ledger after deducting active picking and approved vehicle-return reservations. The response includes total available quantity and the best current warehouse or storage location.

When the target work order identifies an engineer, stock in that engineer's assigned vehicle is preferred as the displayed location. Otherwise, the positive location with the largest available warehouse balance is shown.

## Compatibility and isolation

If no completed raw history exists, the endpoint can fall back to the legacy machine/job aggregate. Legacy recommendations have a capped confidence below 70 percent and explicitly state that outcome quality is not labeled.

All work-order, part, usage, warehouse, location, inventory, and legacy-memory reads use the authenticated organization scope. Cross-organization history cannot influence candidates, metrics, reasons, or inventory locations.

## API

`GET /api/work-orders/{work_order_id}/part-recommendations`

Example fields:

```json
{
  "part": {"id": 42, "part_number": "CT-900", "name": "Contactor"},
  "recommended_quantity": 2,
  "usage_count": 6,
  "total_quantity": 11,
  "success_rate": 0.833,
  "average_repair_minutes": 74.5,
  "available_quantity": 9,
  "inventory_location": "Van 12 / FRONT-A1",
  "inventory_warehouse_id": 8,
  "inventory_location_id": 31,
  "confidence": 0.91,
  "reason": "Matched by same machine, same job type, same fault type; ..."
}
```
