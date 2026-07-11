def test_part_usage_notifies_warehouse_when_stock_reaches_threshold(client):
    user = client.post("/api/users", json={"name": "notify-tech", "email": "notify-tech@example.com", "role": "engineer"}).json()
    warehouse = client.post("/api/warehouses", json={"code": "NOTIFY", "name": "Notify Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "LOW-1", "name": "Low Part", "safety_stock": 2}).json()
    client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 3, "to_warehouse_id": warehouse["id"]})
    work_order = client.post("/api/work-orders", json={"ticket_number": "NOTIFY-1", "assigned_user_id": user["id"], "engineer_id": user["id"]}).json()
    used = client.post(f"/api/work-orders/{work_order['id']}/use-part", json={"work_order_id": work_order["id"], "part_id": part["id"], "warehouse_id": warehouse["id"], "user_id": user["id"], "quantity": 1})
    assert used.status_code == 200
    notices = client.get("/api/inventory/notifications")
    assert notices.status_code == 200
    assert notices.json()[0]["part_id"] == part["id"]
    notification_id = notices.json()[0]["id"]
    acknowledged = client.patch(f"/api/inventory/notifications/{notification_id}?status=acknowledged")
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
