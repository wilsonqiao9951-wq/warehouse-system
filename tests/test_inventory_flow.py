def create_user(client, name: str, role: str = "engineer") -> int:
    response = client.post("/api/users", json={"name": name, "email": f"{name}@example.com", "role": role})
    assert response.status_code == 200
    return response.json()["id"]


def create_warehouse(client, name: str, assigned_user_id: int | None = None) -> int:
    payload = {"name": name, "location": name}
    if assigned_user_id is not None:
        payload["assigned_user_id"] = assigned_user_id
    response = client.post("/api/warehouses", json=payload)
    assert response.status_code == 200
    return response.json()["id"]


def create_part(client, part_number: str, default_cost: float = 10.0) -> int:
    response = client.post(
        "/api/parts",
        json={
            "part_number": part_number,
            "name": part_number,
            "default_cost": default_cost,
            "safety_stock": 1,
        },
    )
    assert response.status_code == 200
    return response.json()["id"]


def create_work_order(client, ticket: str, assigned_user_id: int, revenue: float) -> int:
    response = client.post(
        "/api/work-orders",
        json={"ticket_number": ticket, "assigned_user_id": assigned_user_id, "engineer_id": assigned_user_id, "revenue": revenue, "labor_cost": 20.0},
    )
    assert response.status_code == 200
    return response.json()["id"]


def test_work_order_usage_deducts_inventory_and_calculates_profit(client, seed_inventory_ledger):
    tech_id = create_user(client, "tech-1")
    main_wh = create_warehouse(client, "Main")
    van_wh = create_warehouse(client, "Tech Van", assigned_user_id=tech_id)
    part_id = create_part(client, "P-001", default_cost=30.0)
    work_order_id = create_work_order(client, "WO-1", tech_id, revenue=200.0)

    inbound = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "inbound",
            "quantity": 10,
            "to_warehouse_id": main_wh,
            "unit_cost": 30.0,
        },
    )
    assert inbound.status_code == 200

    transfer = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "transfer",
            "quantity": 4,
            "from_warehouse_id": main_wh,
            "to_warehouse_id": van_wh,
            "user_id": tech_id,
            "unit_cost": 30.0,
        },
    )
    assert transfer.status_code == 409
    seed_inventory_ledger(
        part_id=part_id,
        transaction_type="transfer",
        quantity=4,
        from_warehouse_id=main_wh,
        to_warehouse_id=van_wh,
        user_id=tech_id,
        unit_cost=30.0,
    )

    usage = client.post(
        f"/api/work-orders/{work_order_id}/use-part",
        json={
            "work_order_id": work_order_id,
            "part_id": part_id,
            "warehouse_id": van_wh,
            "user_id": tech_id,
            "quantity": 2,
            "unit_cost": 30.0,
        },
    )
    assert usage.status_code == 200

    balances = client.get("/api/inventory/balances")
    assert balances.status_code == 200
    van_balance = next(
        row for row in balances.json() if row["warehouse_id"] == van_wh and row["part_id"] == part_id
    )
    assert van_balance["quantity"] == 2

    transactions = client.get("/api/inventory/transactions")
    assert transactions.status_code == 200
    assert any(tx["transaction_type"] == "work_order_used" and tx["work_order_id"] == work_order_id for tx in transactions.json())

    profit = client.get(f"/api/work-orders/{work_order_id}/profit")
    assert profit.status_code == 200
    payload = profit.json()
    assert payload["revenue"] == 200.0
    assert payload["labor_cost"] == 20.0
    assert payload["parts_cost"] == 60.0
    assert payload["profit"] == 120.0


def test_stock_validation_rejects_insufficient_inventory(client):
    tech_id = create_user(client, "tech-2")
    van_wh = create_warehouse(client, "Tech2 Van", assigned_user_id=tech_id)
    part_id = create_part(client, "P-002")
    work_order_id = create_work_order(client, "WO-2", tech_id, revenue=100.0)

    usage = client.post(
        "/api/work-order-parts",
        json={
            "work_order_id": work_order_id,
            "part_id": part_id,
            "warehouse_id": van_wh,
            "user_id": tech_id,
            "quantity": 1,
            "unit_cost": 20.0,
        },
    )
    assert usage.status_code == 400
    assert "Insufficient stock" in usage.json()["detail"]


def test_manual_inventory_adjustment_is_blocked(client):
    tech_id = create_user(client, "tech-3")
    main_wh = create_warehouse(client, "Main-3")
    part_id = create_part(client, "P-003")

    response = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "adjustment",
            "quantity": 5,
            "to_warehouse_id": main_wh,
            "user_id": tech_id,
            "unit_cost": 10.0,
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Manual inventory adjustment is not allowed"


def test_employee_van_inventory_endpoint(client, seed_inventory_ledger):
    tech_id = create_user(client, "tech-4")
    main_wh = create_warehouse(client, "Main-4")
    van_wh = create_warehouse(client, "Tech4 Van", assigned_user_id=tech_id)
    part_id = create_part(client, "P-004")

    inbound = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "inbound",
            "quantity": 6,
            "to_warehouse_id": main_wh,
            "unit_cost": 12.0,
        },
    )
    assert inbound.status_code == 200
    blocked_transfer = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part_id,
            "transaction_type": "transfer",
            "quantity": 3,
            "from_warehouse_id": main_wh,
            "to_warehouse_id": van_wh,
            "user_id": tech_id,
            "unit_cost": 12.0,
        },
    )
    assert blocked_transfer.status_code == 409
    seed_inventory_ledger(
        part_id=part_id,
        transaction_type="transfer",
        quantity=3,
        from_warehouse_id=main_wh,
        to_warehouse_id=van_wh,
        user_id=tech_id,
        unit_cost=12.0,
    )

    response = client.get(f"/api/employees/{tech_id}/van-inventory")
    assert response.status_code == 200
    data = response.json()
    matched = [row for row in data if row["warehouse_id"] == van_wh and row["part_id"] == part_id]
    assert len(matched) == 1
    assert matched[0]["quantity"] == 3


def test_use_part_endpoint_rejects_negative_inventory(client):
    tech_id = create_user(client, "tech-5")
    van_wh = create_warehouse(client, "Tech5 Van", assigned_user_id=tech_id)
    part_id = create_part(client, "P-005")
    work_order_id = create_work_order(client, "WO-5", tech_id, revenue=100.0)

    response = client.post(
        f"/api/work-orders/{work_order_id}/use-part",
        json={
            "work_order_id": work_order_id,
            "part_id": part_id,
            "warehouse_id": van_wh,
            "user_id": tech_id,
            "quantity": 2,
            "unit_cost": 11.0,
        },
    )
    assert response.status_code == 400
    assert "Insufficient stock" in response.json()["detail"]
