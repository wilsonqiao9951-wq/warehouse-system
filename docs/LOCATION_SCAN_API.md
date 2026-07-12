# Warehouse and Location Scan API

Warehouse staff scan in this order:

1. Fetch registered tokens with `GET /api/inventory/location-labels?warehouse_id={id}` when printing or replacing labels.
2. Scan the warehouse through `POST /api/inventory/location-scan`.
3. Scan a shelf/bin through the same endpoint with `expected_warehouse_id` set to the verified warehouse.
4. Scan the part through `POST /api/inventory/scan` with both verified `warehouse_id` and `location_id`.

Tokens use `OPF:WH:{id}:{code}` and `OPF:LOC:{id}:{code}`. The server resolves the tenant-scoped ID and compares the current code, so stale, altered, inactive, ambiguous, or cross-warehouse labels fail closed. Human-entered codes remain supported, but a duplicate location code requires a verified warehouse context.

Warehouse, location, and part scans create audit events. Scanning never changes inventory. Engineers may identify a part without a warehouse context, but quantity lookup is restricted to their assigned vehicle.
