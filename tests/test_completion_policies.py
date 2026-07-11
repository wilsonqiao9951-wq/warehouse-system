from app.core.config import settings


PNG_SIGNATURE = "data:image/png;base64,iVBORw0KGgo="


def create_user(client, name: str, role: str = "engineer") -> dict:
    return client.post("/api/users", json={"name": name, "email": f"{name}@completion.test", "role": role}).json()


def create_work_order(client, ticket: str, engineer_id: int, job_type: str = "repair") -> dict:
    response = client.post("/api/work-orders", json={
        "ticket_number": ticket, "engineer_id": engineer_id, "assigned_user_id": engineer_id, "job_type": job_type
    })
    assert response.status_code == 200
    return response.json()


def completion_payload() -> dict:
    return {
        "repair_result": "Repair verified under load.",
        "customer_signature_name": "Customer Name",
        "customer_signature_data": PNG_SIGNATURE,
        "checklist_json": '{"equipment_safe":true,"site_clean":true,"customer_briefed":true}',
    }


def test_job_type_policy_overrides_default_and_blocks_status_bypass(client):
    tech = create_user(client, "policy-tech")
    default = client.post("/api/completion-policies", json={"require_repair_result": True})
    assert default.status_code == 200
    override = client.post("/api/completion-policies", json={
        "job_type": " Repair ", "require_repair_result": True, "require_customer_signature": True
    })
    assert override.status_code == 200
    work_order = create_work_order(client, "POLICY-1", tech["id"], "REPAIR")

    policy = client.get(f"/api/work-orders/{work_order['id']}/completion-policy")
    assert policy.status_code == 200
    assert policy.json()["source"] == "job_type"
    assert policy.json()["require_customer_signature"] is True

    bypass_create = client.post("/api/work-orders", json={"ticket_number": "POLICY-BYPASS", "status": " completed "})
    assert bypass_create.status_code == 400
    bypass_patch = client.patch(f"/api/work-orders/{work_order['id']}", json={"status": "COMPLETED"})
    assert bypass_patch.status_code == 400
    fake_timeline = client.post("/api/job-status", json={"work_order_id": work_order["id"], "status": "COMPLETED"})
    assert fake_timeline.status_code == 400

    missing = client.post(f"/api/work-orders/{work_order['id']}/complete", json={"repair_result": "fixed"})
    assert missing.status_code == 422
    assert "customer_signature" in missing.text
    completed = client.post(f"/api/work-orders/{work_order['id']}/complete", json=completion_payload())
    assert completed.status_code == 200
    assert completed.json()["is_locked"] is True


def test_policy_requires_photo_checklist_and_part_usage(client):
    tech = create_user(client, "evidence-tech")
    warehouse = client.post("/api/warehouses", json={"name": "Evidence Van", "assigned_user_id": tech["id"]}).json()
    part = client.post("/api/parts", json={"part_number": "EVID-1", "name": "Evidence Part"}).json()
    work_order = create_work_order(client, "POLICY-EVIDENCE", tech["id"])
    client.post("/api/completion-policies", json={
        "require_repair_result": True,
        "require_customer_signature": True,
        "require_completion_photo": True,
        "require_all_checklist_items": True,
        "require_parts_usage": True,
    })

    incomplete = client.post(f"/api/work-orders/{work_order['id']}/complete", json=completion_payload())
    assert incomplete.status_code == 422
    assert "completion_photo" in incomplete.text and "parts_usage" in incomplete.text

    client.post("/api/inventory/transactions", json={
        "part_id": part["id"], "transaction_type": "inbound", "quantity": 1, "to_warehouse_id": warehouse["id"]
    })
    used = client.post(f"/api/work-orders/{work_order['id']}/use-part", json={
        "work_order_id": work_order["id"], "part_id": part["id"], "warehouse_id": warehouse["id"],
        "user_id": tech["id"], "quantity": 1
    })
    assert used.status_code == 200
    picture = client.post("/api/qc-pictures", json={"work_order_id": work_order["id"], "image_url": "/uploads/evidence.png"})
    assert picture.status_code == 200
    completed = client.post(f"/api/work-orders/{work_order['id']}/complete", json=completion_payload())
    assert completed.status_code == 200


def test_engineer_completion_waits_for_manager_approval_and_freezes_evidence(client):
    settings.rbac_enforce = False
    try:
        admin = create_user(client, "approval-admin", "admin")
        engineer = create_user(client, "approval-engineer", "engineer")
        work_order = create_work_order(client, "POLICY-APPROVAL", engineer["id"])
        client.post("/api/completion-policies", json={
            "require_repair_result": True, "require_manager_approval": True
        })
        settings.rbac_enforce = True
        engineer_headers = {"X-User-Id": str(engineer["id"])}
        admin_headers = {"X-User-Id": str(admin["id"])}

        requested = client.post(
            f"/api/work-orders/{work_order['id']}/complete",
            headers=engineer_headers,
            json={"repair_result": "Ready for approval"},
        )
        assert requested.status_code == 200
        assert requested.json()["status"] == "PENDING_APPROVAL"
        assert requested.json()["is_locked"] is False
        assert requested.json()["completed_at"] is None

        frozen_patch = client.patch(
            f"/api/work-orders/{work_order['id']}", headers=engineer_headers, json={"problem_description": "changed"}
        )
        assert frozen_patch.status_code == 409
        frozen_status = client.post(
            "/api/job-status", headers=engineer_headers, json={"work_order_id": work_order["id"], "status": "in_progress"}
        )
        assert frozen_status.status_code == 400

        approved = client.post(f"/api/work-orders/{work_order['id']}/approve-completion", headers=admin_headers, json={})
        assert approved.status_code == 200
        assert approved.json()["status"] == "COMPLETED"
        assert approved.json()["is_locked"] is True
        assert approved.json()["completion_approved_by"] == admin["id"]
    finally:
        settings.rbac_enforce = False
