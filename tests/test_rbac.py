from app.core.config import settings
from pathlib import Path


def _create_user(client, name: str, role: str, headers: dict[str, str] | None = None) -> int:
    resp = client.post("/api/users", headers=headers or {}, json={"name": name, "email": f"{name}@ex.com", "role": role})
    assert resp.status_code == 200
    return resp.json()["id"]


def _admin_headers() -> dict[str, str]:
    return {"X-User-Id": "1"}


def test_rbac_enforced_role_access(client):
    settings.rbac_enforce = False
    try:
        admin_id = _create_user(client, "admin-rbac", "admin")
        assert admin_id == 1
        settings.rbac_enforce = True

        tech_id = _create_user(client, "tech-rbac", "engineer", headers=_admin_headers())
        manager_id = _create_user(client, "manager-rbac", "manager", headers=_admin_headers())
        wh_id = _create_user(client, "warehouse-rbac", "warehouse", headers=_admin_headers())

        # Technician should not create work order
        denied = client.post(
            "/api/work-orders",
            headers={"X-User-Id": str(tech_id)},
            json={"ticket_number": "RBAC-WO-1", "status": "open"},
        )
        assert denied.status_code == 403

        # Manager can create work order
        created = client.post(
            "/api/work-orders",
            headers={"X-User-Id": str(manager_id)},
            json={
                "ticket_number": "RBAC-WO-2",
                "assigned_user_id": tech_id,
                "engineer_id": tech_id,
                "status": "open",
            },
        )
        assert created.status_code == 200
        work_order_id = created.json()["id"]

        # Technician can only see own assigned work order
        listed = client.get("/api/work-orders", headers={"X-User-Id": str(tech_id)})
        assert listed.status_code == 200
        assert len(listed.json()) == 1
        assert listed.json()[0]["id"] == work_order_id

        # Warehouse cannot view profit
        no_profit = client.get(f"/api/work-orders/{work_order_id}/profit", headers={"X-User-Id": str(wh_id)})
        assert no_profit.status_code == 403

        # Manager can view profit
        yes_profit = client.get(f"/api/work-orders/{work_order_id}/profit", headers={"X-User-Id": str(manager_id)})
        assert yes_profit.status_code == 200
    finally:
        settings.rbac_enforce = False


def test_rbac_requires_header_when_enforced(client):
    settings.rbac_enforce = False
    try:
        _create_user(client, "admin-rbac-2", "admin")
        settings.rbac_enforce = True
        missing = client.get("/api/work-orders")
        assert missing.status_code == 401
    finally:
        settings.rbac_enforce = False


def test_dashboard_scope_and_upload_security(client):
    settings.rbac_enforce = False
    try:
        admin_id = _create_user(client, "admin-security", "admin")
        assert admin_id == 1
        settings.rbac_enforce = True
        tech_id = _create_user(client, "tech-security", "engineer", headers=_admin_headers())
        other_tech_id = _create_user(client, "other-tech-security", "engineer", headers=_admin_headers())
        manager_id = _create_user(client, "manager-security", "manager", headers=_admin_headers())
        warehouse_id = _create_user(client, "warehouse-security", "warehouse", headers=_admin_headers())

        created = client.post(
            "/api/work-orders",
            headers={"X-User-Id": str(manager_id)},
            json={
                "ticket_number": "SECURITY-WO-1",
                "assigned_user_id": tech_id,
                "engineer_id": tech_id,
                "status": "open",
            },
        )
        assert created.status_code == 200
        work_order_id = created.json()["id"]

        own_dashboard = client.get(
            f"/api/dashboard/engineers/{tech_id}",
            headers={"X-User-Id": str(tech_id)},
        )
        assert own_dashboard.status_code == 200
        other_dashboard = client.get(
            f"/api/dashboard/engineers/{tech_id}",
            headers={"X-User-Id": str(other_tech_id)},
        )
        assert other_dashboard.status_code == 403
        warehouse_dashboard = client.get(
            "/api/dashboard/admin/warehouses",
            headers={"X-User-Id": str(warehouse_id)},
        )
        assert warehouse_dashboard.status_code == 403

        png = b"\x89PNG\r\n\x1a\n" + b"test-image-content"
        denied_upload = client.post(
            "/api/uploads/work-order-parts",
            headers={"X-User-Id": str(other_tech_id)},
            data={"work_order_id": str(work_order_id)},
            files={"file": ("photo.png", png, "image/png")},
        )
        assert denied_upload.status_code == 403

        invalid_upload = client.post(
            "/api/uploads/work-order-parts",
            headers={"X-User-Id": str(tech_id)},
            data={"work_order_id": str(work_order_id)},
            files={"file": ("photo.png", b"not-an-image", "image/png")},
        )
        assert invalid_upload.status_code == 400

        uploaded = client.post(
            "/api/uploads/work-order-parts",
            headers={"X-User-Id": str(tech_id)},
            data={"work_order_id": str(work_order_id)},
            files={"file": ("photo.png", png, "image/png")},
        )
        assert uploaded.status_code == 200
        relative_path = uploaded.json()["url"].lstrip("/")
        stored = Path(relative_path)
        assert stored.read_bytes() == png
        stored.unlink()
    finally:
        settings.rbac_enforce = False
