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

    paused = client.post(f"/api/work-orders/{wo}/pause", json={"notes": "Waiting for customer access"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"
    resumed = client.post(f"/api/work-orders/{wo}/start", json={})
    assert resumed.status_code == 200

    used = client.post(f"/api/work-orders/{wo}/use-part", json={"work_order_id": wo, "part_id": part, "warehouse_id": van, "user_id": tech, "quantity": 2, "unit_cost": 20})
    assert used.status_code == 200

    completed = client.post(f"/api/work-orders/{wo}/complete", json={
        "repair_result": "Replaced failed filter and verified operation.",
        "checklist_json": "{\"power_off\":true,\"site_clean\":true}",
        "customer_signature_name": "Alex Customer",
        "customer_signature_data": "data:image/png;base64,iVBORw0KGgo=",
    })
    assert completed.status_code == 200
    assert completed.json()["status"] == "COMPLETED"
    assert completed.json()["is_locked"] is True
    assert completed.json()["repair_result"].startswith("Replaced")
    assert completed.json()["customer_signed_at"] is not None

    blocked = client.post("/api/job-status", json={"work_order_id": wo, "status": "reopen"})
    assert blocked.status_code == 400

    logs = client.get("/api/audit-logs")
    assert logs.status_code == 200
    actions = [row["action"] for row in logs.json()]
    assert "start_job" in actions
    assert "use_part" in actions
    assert "complete_job" in actions
    assert "pause_job" in actions


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


def test_completion_rejects_invalid_signature_data(client):
    tech = _mk_user(client, "tech-signature")
    wo = _mk_wo(client, "WOF-SIGNATURE", tech)
    client.post(f"/api/work-orders/{wo}/start", json={})

    response = client.post(
        f"/api/work-orders/{wo}/complete",
        json={"customer_signature_name": "Customer", "customer_signature_data": "not-an-image"},
    )

    assert response.status_code == 422
    assert "PNG data URL" in response.text


def test_voice_note_upload_and_listing(client):
    tech = _mk_user(client, "tech-voice")
    wo = _mk_wo(client, "WOF-VOICE", tech)
    audio = b"\x1aE\xdf\xa3" + b"voice-note-test" * 10

    uploaded = client.post(
        f"/api/work-orders/{wo}/voice-notes",
        data={"duration_seconds": "4.2"},
        files={"file": ("note.webm", audio, "audio/webm")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["mime_type"] == "audio/webm"
    assert uploaded.json()["transcription_status"] == "not_requested"

    listed = client.get(f"/api/work-orders/{wo}/voice-notes")
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [uploaded.json()["id"]]

    invalid = client.post(
        f"/api/work-orders/{wo}/voice-notes",
        files={"file": ("fake.webm", b"not audio", "audio/webm")},
    )
    assert invalid.status_code == 400


def test_customer_equipment_service_context_and_parts_history(client):
    tech = _mk_user(client, "tech-history")
    customer = client.post("/api/customers", json={
        "name": "Northwind Plant", "account_number": "NW-1", "contact_name": "Sam", "phone": "555-0100"
    }).json()
    equipment = client.post("/api/equipment", json={
        "customer_id": customer["id"], "asset_tag": "NW-CHILLER-1", "manufacturer": "ACME", "model": "ACME-9000", "serial_number": "SN-9"
    }).json()
    other_equipment = client.post("/api/equipment", json={
        "customer_id": customer["id"], "asset_tag": "NW-CHILLER-2", "model": "ACME-9000"
    }).json()
    van = _mk_wh(client, "Van-history", assigned_user_id=tech)
    part = _mk_part(client, "HIST-001")
    client.post("/api/inventory/transactions", json={
        "part_id": part, "transaction_type": "inbound", "quantity": 5, "to_warehouse_id": van
    })

    previous = client.post("/api/work-orders", json={
        "ticket_number": "HISTORY-OLD", "engineer_id": tech, "customer_id": customer["id"], "equipment_id": equipment["id"],
        "job_type": "repair", "problem_description": "Unit would not cool"
    }).json()
    client.post(f"/api/work-orders/{previous['id']}/use-part", json={
        "work_order_id": previous["id"], "part_id": part, "warehouse_id": van, "user_id": tech, "quantity": 2
    })
    client.post(f"/api/work-orders/{previous['id']}/complete", json={"repair_result": "Replaced filter and tested cooling"})

    unrelated = client.post("/api/work-orders", json={
        "ticket_number": "HISTORY-OTHER", "engineer_id": tech, "customer_id": customer["id"], "equipment_id": other_equipment["id"]
    }).json()
    client.post(f"/api/work-orders/{unrelated['id']}/complete", json={"repair_result": "Other asset"})

    current = client.post("/api/work-orders", json={
        "ticket_number": "HISTORY-NOW", "engineer_id": tech, "customer_id": customer["id"], "equipment_id": equipment["id"]
    }).json()
    context = client.get(f"/api/work-orders/{current['id']}/service-context")
    assert context.status_code == 200
    body = context.json()
    assert body["customer"]["account_number"] == "NW-1"
    assert body["equipment"]["asset_tag"] == "NW-CHILLER-1"
    assert [row["ticket_number"] for row in body["history"]] == ["HISTORY-OLD"]
    assert body["history"][0]["parts_used"] == [{"part_number": "HIST-001", "name": "HIST-001", "quantity": 2}]


def test_work_order_rejects_customer_equipment_mismatch(client):
    tech = _mk_user(client, "tech-history-mismatch")
    first = client.post("/api/customers", json={"name": "First customer", "account_number": "FIRST"}).json()
    second = client.post("/api/customers", json={"name": "Second customer", "account_number": "SECOND"}).json()
    equipment = client.post("/api/equipment", json={"customer_id": first["id"], "asset_tag": "FIRST-ASSET", "model": "Model X"}).json()

    response = client.post("/api/work-orders", json={
        "ticket_number": "BAD-LINK", "engineer_id": tech, "customer_id": second["id"], "equipment_id": equipment["id"]
    })
    assert response.status_code == 400
    assert "does not belong" in response.text
