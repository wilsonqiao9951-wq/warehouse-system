def test_create_and_filter_storage_locations(client):
    warehouse = client.post("/api/warehouses", json={"code": "MAIN", "name": "Main Warehouse"})
    assert warehouse.status_code == 200
    warehouse_id = warehouse.json()["id"]
    assert warehouse.json()["code"] == "MAIN"

    created = client.post(
        "/api/storage-locations",
        json={"warehouse_id": warehouse_id, "code": "A-01-02", "name": "Fast-moving parts", "zone": "A"},
    )
    assert created.status_code == 200
    assert created.json()["zone"] == "A"

    rows = client.get(f"/api/storage-locations?warehouse_id={warehouse_id}")
    assert rows.status_code == 200
    assert [row["code"] for row in rows.json()] == ["A-01-02"]


def test_storage_location_rejects_unknown_warehouse(client):
    response = client.post("/api/storage-locations", json={"warehouse_id": 999, "code": "UNKNOWN"})
    assert response.status_code == 404
