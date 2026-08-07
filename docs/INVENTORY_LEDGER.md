# Inventory Ledger Workbench

## Purpose

The inventory ledger workbench gives warehouse users, managers, and
administrators a read-only, tenant-isolated view of physical stock evidence.
It resolves database IDs into operational names and connects a movement to its
work order or custody workflow without creating an alternate stock ledger.

Frontend route: `/inventory-ledger`

## API

`GET /api/inventory/ledger` accepts:

- `transaction_type`: inbound, outbound, transfer, work_order_used, return,
  adjustment, or damage;
- `part_id`;
- `warehouse_id`, matched against either source or destination;
- `user_id`, the accountable actor recorded on the transaction;
- `work_order_id`;
- `from_at` and `to_at`, with an ordered range no longer than 366 days;
- `before_id` for stable descending cursor pagination; and
- `limit`, from 1 to 200 and defaulting to 50.

The response includes the matching total, current items, and the next cursor.
Each row includes part, warehouse and bin labels, work-order ticket, actor,
unit and total value, movement stage, source workflow, notes, and linked
replenishment, vehicle-return, or inventory-count evidence where applicable.

`GET /api/inventory/ledger/options` returns parts, warehouses, and users that
are already referenced by the organization's ledger. It does not expose the
full employee or inventory master merely to populate a filter.

Both endpoints return `Cache-Control: no-store`.

## Authorization and tenant boundary

Allowed roles are `warehouse`, `manager`, and `admin`. Engineers and assistants
receive `403`. Organization conditions are explicit on transactions and every
joined entity as defense in depth alongside the normal tenant session scope and
PostgreSQL row-level security.

The workbench cannot change inventory. A discrepancy must be corrected through
the inventory-count approval flow or the applicable replenishment/return
custody workflow, preserving authentication, version checks, and audit evidence.

## Migration

Revision `20260807_0058` adds tenant-leading indexes for type, part, source
warehouse, destination warehouse, user, and work order with creation time.
Downgrade removes only these indexes; transaction evidence is untouched.
