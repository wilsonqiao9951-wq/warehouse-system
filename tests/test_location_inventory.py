def test_inventory_can_move_between_locations_in_same_warehouse(client):
    warehouse = client.post("/api/warehouses", json={"code": "MAIN", "name": "Main"}).json()
    source = client.post("/api/storage-locations", json={"warehouse_id": warehouse["id"], "code": "A-01"}).json()
    target = client.post("/api/storage-locations", json={"warehouse_id": warehouse["id"], "code": "B-01"}).json()
    part = client.post("/api/parts", json={"part_number": "LOC-1", "name": "Located item"}).json()
    assert client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 10, "to_warehouse_id": warehouse["id"], "to_location_id": source["id"]}).status_code == 200
    assert client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "transfer", "quantity": 4, "from_warehouse_id": warehouse["id"], "to_warehouse_id": warehouse["id"], "from_location_id": source["id"], "to_location_id": target["id"]}).status_code == 200
    balances = client.get(f"/api/inventory/location-balances?warehouse_id={warehouse['id']}").json()
    quantities = {row["location_code"]: row["quantity"] for row in balances if row["part_id"] == part["id"]}
    assert quantities == {"A-01": 6, "B-01": 4}
    row = next(row for row in client.get("/api/inventory/balances").json() if row["part_id"] == part["id"])
    assert row["quantity"] == 10

def test_location_must_belong_to_selected_warehouse(client):
    first = client.post("/api/warehouses", json={"code": "ONE", "name": "One"}).json()
    second = client.post("/api/warehouses", json={"code": "TWO", "name": "Two"}).json()
    location = client.post("/api/storage-locations", json={"warehouse_id": first["id"], "code": "A"}).json()
    part = client.post("/api/parts", json={"part_number": "LOC-2", "name": "Item"}).json()
    response = client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 1, "to_warehouse_id": second["id"], "to_location_id": location["id"]})
    assert response.status_code == 400
