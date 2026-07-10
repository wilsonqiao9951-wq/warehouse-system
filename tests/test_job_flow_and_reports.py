def _mk_user(client, name: str, role: str = "engineer") -> int:
    return client.post("/api/users", json={"name": name, "email": f"{name}@x.com", "role": role}).json()["id"]


def _mk_wh(client, name: str, assigned_user_id: int | None = None) -> int:
    payload = {"name": name, "location": name}
    if assigned_user_id:
        payload["assigned_user_id"] = assigned_user_id
    return client.post("/api/warehouses", json=payload).json()["id"]


def _mk_part(client, part_number: str, min_stock: int = 2) -> int:
    return client.post("/api/parts", json={"part_number": part_number, "name": part_number, "default_cost": 20, "safety_stock": 1, "min_stock": min_stock}).json()["id"]


def _mk_wo(client, ticket: str, uid: int, city: str = "NYC", job_type: str = "repair") -> int:
    return client.post(
        "/api/work-orders",
        json={
            "ticket_number": ticket,
            "assigned_user_id": uid,
            "engineer_id": uid,
            "revenue": 300,
            "labor_cost": 50,
            "city": city,
            "job_type": job_type,
        },
    ).json()["id"]


def test_full_technician_job_flow_and_lock(client):
    tech = _mk_user(client, "tech-flow")
    van = _mk_wh(client, "Van-flow", assigned_user_id=tech)
    part = _mk_part(client, "PF-001")
    wo = _mk_wo(client, "WOF-001", tech)

    client.post("/api/inventory/transactions", json={"part_id": part, "transaction_type": "inbound", "quantity": 3, "to_warehouse_id": van, "unit_cost": 20})
    started = client.post(f"/api/work-orders/{wo}/start", json={})
    assert started.status_code == 200
    assert started.json()["status"] == "IN_PROGRESS"

    used = client.post(f"/api/work-orders/{wo}/use-part", json={"work_order_id": wo, "part_id": part, "warehouse_id": van, "user_id": tech, "quantity": 2, "unit_cost": 20})
    assert used.status_code == 200

    completed = client.post(f"/api/work-orders/{wo}/complete", json={})
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["is_locked"] is True

    blocked = client.post("/api/job-status", json={"work_order_id": wo, "status": "reopen"})
    assert blocked.status_code == 400

    logs = client.get("/api/audit-logs")
    assert logs.status_code == 200
    actions = [row["action"] for row in logs.json()]
    assert "start_job" in actions
    assert "use_part" in actions
    assert "complete_job" in actions


def test_work_order_filters_low_stock_and_abnormal_reports(client):
    tech = _mk_user(client, "tech-filter")
    van = _mk_wh(client, "Van-filter", assigned_user_id=tech)
    p1 = _mk_part(client, "PF-100", min_stock=5)
    p2 = _mk_part(client, "PF-200", min_stock=1)
    wo1 = _mk_wo(client, "WOF-100", tech, city="Austin", job_type="install")
    wo2 = _mk_wo(client, "WOF-200", tech, city="Dallas", job_type="repair")

    client.post("/api/inventory/transactions", json={"part_id": p1, "transaction_type": "inbound", "quantity": 5, "to_warehouse_id": van, "unit_cost": 10})
    client.post("/api/inventory/transactions", json={"part_id": p2, "transaction_type": "inbound", "quantity": 5, "to_warehouse_id": van, "unit_cost": 10})
    client.post(f"/api/work-orders/{wo1}/use-part", json={"work_order_id": wo1, "part_id": p1, "warehouse_id": van, "user_id": tech, "quantity": 4, "unit_cost": 10})
    client.post(f"/api/work-orders/{wo2}/use-part", json={"work_order_id": wo2, "part_id": p2, "warehouse_id": van, "user_id": tech, "quantity": 1, "unit_cost": 10})

    filtered = client.get("/api/work-orders?city=Austin&job_type=install&status=open")
    assert filtered.status_code == 200
    assert len(filtered.json()) == 1

    low_stock = client.get("/api/inventory/low-stock-alerts")
    assert low_stock.status_code == 200
    assert any(row["part_id"] == p1 for row in low_stock.json())

    abnormal = client.get("/api/reports/abnormal-usage")
    assert abnormal.status_code == 200
    if abnormal.json():
        assert any("90th percentile" in row["reason"] or "historical average" in row["reason"] for row in abnormal.json())
