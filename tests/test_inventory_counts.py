from contextlib import contextmanager

from app.core.config import settings
from app.models import AuditLog, InventoryCountLine, InventoryTransaction, TransactionType


PASSWORD = "inventory-count-password"


@contextmanager
def enforced_rbac():
    previous_rbac, previous_legacy = settings.rbac_enforce, settings.legacy_header_auth
    settings.rbac_enforce, settings.legacy_header_auth = True, False
    try:
        yield
    finally:
        settings.rbac_enforce, settings.legacy_header_auth = previous_rbac, previous_legacy


def create_user(client, name: str, role: str):
    response = client.post("/api/users", json={
        "name": name, "email": f"{name}@count.test", "role": role, "password": PASSWORD,
    })
    assert response.status_code == 200, response.text
    return response.json()


def login(client, user):
    response = client.post("/api/auth/login", data={"username": user["email"], "password": PASSWORD})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def setup_count(client):
    admin = create_user(client, "count-admin", "admin")
    warehouse_user = create_user(client, "count-warehouse", "warehouse")
    manager = create_user(client, "count-manager", "manager")
    warehouse = client.post("/api/warehouses", json={"code": "COUNT", "name": "Count Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "COUNT-1", "name": "Count Part", "default_cost": 4}).json()
    client.post("/api/inventory/transactions", json={
        "part_id": part["id"], "transaction_type": "inbound", "quantity": 10,
        "to_warehouse_id": warehouse["id"],
    })
    return admin, warehouse_user, manager, warehouse, part


def test_count_approval_recalculates_variance_and_posts_one_adjustment(client):
    admin, warehouse_user, manager, warehouse, part = setup_count(client)
    with enforced_rbac():
        admin_headers, staff_headers, manager_headers = login(client, admin), login(client, warehouse_user), login(client, manager)
        created = client.post("/api/inventory/counts", headers=staff_headers, json={
            "client_request_id": "count-request-0001", "warehouse_id": warehouse["id"],
            "title": "Weekly count",
        })
        assert created.status_code == 200, created.text
        count = created.json()
        counted = client.put(f"/api/inventory/counts/{count['id']}/lines", headers=staff_headers, json={
            "part_id": part["id"], "counted_quantity": 8, "expected_version": count["version"],
        })
        assert counted.status_code == 200, counted.text
        count = counted.json()
        submitted = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=staff_headers, json={
            "action": "submit", "expected_version": count["version"],
        })
        assert submitted.status_code == 200, submitted.text
        count = submitted.json()
        assert count["lines"][0]["submitted_book_quantity"] == 10

        # Normal inventory remains live while approval is pending.
        inbound = client.post("/api/inventory/transactions", headers=admin_headers, json={
            "part_id": part["id"], "transaction_type": "inbound", "quantity": 2,
            "to_warehouse_id": warehouse["id"],
        })
        assert inbound.status_code == 200, inbound.text
        denied = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=manager_headers, json={
            "action": "approve", "expected_version": count["version"], "password": PASSWORD,
        })
        assert denied.status_code == 403
        approved = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=admin_headers, json={
            "action": "approve", "expected_version": count["version"], "password": PASSWORD,
        })
        assert approved.status_code == 200, approved.text
        result = approved.json()
        assert result["status"] == "approved"
        assert result["lines"][0]["approved_book_quantity"] == 12
        assert result["lines"][0]["variance_quantity"] == -4

        balance = client.get("/api/inventory/balances", headers=admin_headers).json()
        row = next(item for item in balance if item["part_id"] == part["id"] and item["warehouse_id"] == warehouse["id"])
        assert row["quantity"] == 8
        retry = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=admin_headers, json={
            "action": "approve", "expected_version": count["version"], "password": PASSWORD,
        })
        assert retry.status_code == 409

    with client.app.state.testing_session_local() as db:
        line = db.query(InventoryCountLine).one()
        adjustments = db.query(InventoryTransaction).filter(
            InventoryTransaction.inventory_count_line_id == line.id,
            InventoryTransaction.transaction_type == TransactionType.ADJUSTMENT,
        ).all()
        assert len(adjustments) == 1
        assert db.query(AuditLog).filter(AuditLog.action == "inventory_count_approve").count() == 1


def test_count_idempotency_edit_lock_and_cancel_reason(client):
    _admin, warehouse_user, _manager, warehouse, part = setup_count(client)
    with enforced_rbac():
        headers = login(client, warehouse_user)
        payload = {"client_request_id": "count-request-0002", "warehouse_id": warehouse["id"], "title": "Shelf count"}
        first = client.post("/api/inventory/counts", headers=headers, json=payload)
        second = client.post("/api/inventory/counts", headers=headers, json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        count = first.json()
        line = client.put(f"/api/inventory/counts/{count['id']}/lines", headers=headers, json={
            "part_id": part["id"], "counted_quantity": 10, "expected_version": count["version"],
        }).json()
        stale = client.put(f"/api/inventory/counts/{count['id']}/lines", headers=headers, json={
            "part_id": part["id"], "counted_quantity": 9, "expected_version": count["version"],
        })
        assert stale.status_code == 409
        missing_reason = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=headers, json={
            "action": "cancel", "expected_version": line["version"],
        })
        assert missing_reason.status_code == 422
        cancelled = client.post(f"/api/inventory/counts/{count['id']}/actions", headers=headers, json={
            "action": "cancel", "expected_version": line["version"], "reason": "Count scheduled incorrectly",
        })
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
