def test_inventory_scan_matches_barcode_and_reports_stock(client):
    warehouse = client.post("/api/warehouses", json={"code": "SCAN", "name": "Scan Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "SCAN-1", "name": "Scan Part", "barcode": "012345"}).json()
    client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 8, "to_warehouse_id": warehouse["id"]})
    result = client.post("/api/inventory/scan", json={"barcode": "012345", "quantity": 3, "warehouse_id": warehouse["id"]})
    assert result.status_code == 200
    assert result.json()["matched"] is True
    assert result.json()["current_quantity"] == 8
    assert result.json()["projected_quantity"] == 5


def test_inventory_scan_reports_unknown_label(client):
    result = client.post("/api/inventory/scan", json={"barcode": "unknown"})
    assert result.status_code == 200
    assert result.json()["matched"] is False
