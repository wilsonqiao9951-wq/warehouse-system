def test_similar_work_orders_receive_part_recommendations(client):
    user = client.post("/api/users", json={"name": "memory-tech", "email": "memory-tech@example.com", "role": "engineer"}).json()
    warehouse = client.post("/api/warehouses", json={"code": "MEM", "name": "Memory Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "PUMP-SEAL", "name": "Pump Seal"}).json()
    client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 10, "to_warehouse_id": warehouse["id"]})
    work_order = client.post("/api/work-orders", json={"ticket_number": "MEM-1", "assigned_user_id": user["id"], "engineer_id": user["id"], "machine_type": "Pump-X", "job_type": "seal replacement"}).json()
    used = client.post(f"/api/work-orders/{work_order['id']}/use-part", json={"work_order_id": work_order["id"], "part_id": part["id"], "warehouse_id": warehouse["id"], "user_id": user["id"], "quantity": 2})
    assert used.status_code == 200
    recommendations = client.get(f"/api/work-orders/{work_order['id']}/part-recommendations")
    assert recommendations.status_code == 200
    assert recommendations.json()[0]["part"]["part_number"] == "PUMP-SEAL"
    assert recommendations.json()[0]["recommended_quantity"] == 2
