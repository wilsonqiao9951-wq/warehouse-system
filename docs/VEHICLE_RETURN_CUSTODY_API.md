# Vehicle Return Custody API

Vehicle stock cannot be moved back through the generic inventory endpoint. Returns use an authenticated chain:

```text
requested -> approved -> shipped -> received
```

- The exact engineer creates the request from an assigned vehicle on a registered device.
- Warehouse/admin approval reserves the requested quantity in the vehicle.
- The same engineer confirms physical handover with the registered device and current account password. This writes the vehicle `OUTBOUND` transaction.
- Warehouse/admin receipt validates the shipment ledger and writes the destination warehouse `INBOUND` transaction.
- Cancellation is allowed only in `requested` or `approved`, requires a reason, and releases any reservation.

## Endpoints

```text
GET  /api/inventory/vehicle-return-destinations
POST /api/inventory/vehicle-returns
GET  /api/inventory/vehicle-returns
POST /api/inventory/vehicle-returns/{request_id}/actions
```

Create request:

```json
{
  "part_id": 42,
  "source_warehouse_id": 8,
  "destination_warehouse_id": 1,
  "quantity": 3,
  "reason": "Unused service stock",
  "client_request_id": "83b8cad7-a459-4d5f-aa48-e89d25595d21"
}
```

The source must be an active vehicle assigned to the authenticated engineer. The destination must be an active non-vehicle warehouse. `client_request_id` is unique inside the organization; an unchanged retry returns the original request and a conflicting reuse returns `409`.

Actions use optimistic concurrency:

```json
{"action": "approve", "expected_version": 0}
```

Engineer handover requires password step-up:

```json
{"action": "ship", "expected_version": 1, "account_password": "current-account-password"}
```

Warehouse receipt:

```json
{"action": "receive", "expected_version": 2}
```

## Inventory and audit guarantees

- Approved returns are deducted from available vehicle stock so work-order usage and competing returns cannot consume the same units.
- `return_ship` is unique per return and records the engineer, device, quantity, cost, and vehicle `OUTBOUND`.
- `return_receive` is unique per return and copies shipment cost into the warehouse `INBOUND`.
- Retries never duplicate either inventory movement.
- A shipped return cannot be cancelled. A missing or inconsistent shipment ledger blocks receipt.
- Audit actions are `vehicle_return_requested`, `vehicle_return_approve`, `vehicle_return_ship`, `vehicle_return_receive`, and `vehicle_return_cancel`.
- All mutations are online-only and never enter the PWA offline queue.

Alembic revision `20260712_0020` adds `vehicle_return_requests`, linked inventory stages, constraints, and tenant/status indexes. Downgrade is blocked while a return has linked inventory movements.
