# Multi-region inventory

OpenPartsFlow groups warehouse and vehicle inventory into tenant-owned operating
regions. Regions are an inventory reporting and authorization boundary; they do
not replace warehouse custody, storage locations, replenishment, vehicle return,
or work-order part-usage workflows.

## Data ownership and defaults

- Every region belongs to exactly one organization.
- Region codes and names are unique inside that organization.
- Exactly one active default region is maintained per organization.
- Existing organizations receive `PRIMARY` / `Primary region` / `UTC` during
  migration, and every existing warehouse is assigned to it.
- New organizations or test fixtures are self-healed when their first warehouse
  or region read is processed.
- `warehouses.region_id` remains nullable for safe legacy/import compatibility;
  API-created warehouses are always assigned to the current default region and
  summaries treat a legacy null as the default.
- Region timezones must be valid IANA names, such as `America/New_York`.

## Authorization

| Operation | Administrator | Manager | Warehouse |
| --- | --- | --- | --- |
| List regions and regional inventory | Yes | Yes | Yes |
| View cross-region transfer history | Yes | Yes | Yes |
| Create or update a region | Yes | Yes | No |
| Assign a warehouse to a region | Yes | Yes | No |
| Transfer between main warehouses in one region | Yes | Yes | Yes |
| Transfer between main warehouses in different regions | Yes | Yes | No |

Every mutation is tenant scoped. Region updates use an optimistic `version`, and
warehouse reassignment requires the caller's current `expected_region_id` plus a
business reason. Default regions cannot be deactivated or cleared without first
promoting another active region. Regions with assigned warehouses cannot be
deactivated.

Vehicle inventory is not opened to generic transfers by this feature. Any
generic transaction involving a vehicle warehouse continues to return a conflict
and must use authenticated replenishment receipt, work-order usage, or vehicle
return custody.

## API

- `GET /api/inventory/regions`
- `POST /api/inventory/regions`
- `PATCH /api/inventory/regions/{region_id}`
- `GET /api/inventory/regions/summary`
- `GET /api/inventory/regions/cross-region-transfers`
- `PUT /api/warehouses/{warehouse_id}/region`

The summary reports main and vehicle warehouse counts, ledger quantity, low-stock
rows, and cross-region transfer counts. Transfer history includes both regions,
both warehouses, the part, quantity, transaction identity, and server timestamp.

## Audit evidence

The audit log records region creation and updates, warehouse reassignment with
the mandatory reason and prior/new region, and inventory transfers with
`from_region_id`, `to_region_id`, and `cross_region`. Standard actor role,
authentication method, device, organization, user, and server timestamp evidence
is retained. Passwords and device secrets are never stored.

## Migration and recovery

Alembic revision `20260807_0043` creates `inventory_regions`, adds the warehouse
foreign key and indexes, seeds one default region per existing organization, and
backfills existing warehouses. Downgrade removes only the regional configuration
and warehouse link; it does not alter the inventory ledger.

Portable customer exports include regions and warehouse assignments. Controlled
restore creates regions before warehouses, while archives from compatible older
revisions may omit `warehouse.region_id`. Legacy database adoption validates all
source rows first, then creates default regions and assigns warehouses so
generated configuration cannot distort source row counts or checksums.

Deployment checks:

1. Stop the backend and back up the database.
2. Run `alembic upgrade head`.
3. Confirm `alembic current` reports `20260807_0043`.
4. Open **Regions**, confirm the default region and warehouse assignments, then
   deliberately assign any additional regional warehouses.
5. Test a same-region warehouse transfer and an administrator/manager
   cross-region transfer before production rollout.
