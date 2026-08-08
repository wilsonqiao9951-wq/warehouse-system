from contextlib import contextmanager

from app.core.config import settings
from app.models import Organization, User, UserRole


@contextmanager
def _enforced_legacy_auth():
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    settings.rbac_enforce = True
    settings.legacy_header_auth = True
    try:
        yield
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def _inventory_fixture(client):
    warehouse = client.post(
        "/api/warehouses",
        json={"code": "RULE-WH", "name": "Rule Warehouse"},
    ).json()
    part = client.post(
        "/api/parts",
        json={
            "part_number": "RULE-PART",
            "name": "Rule part",
            "safety_stock": 1,
            "min_stock": 0,
        },
    ).json()
    inbound = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part["id"],
            "transaction_type": "inbound",
            "quantity": 5,
            "to_warehouse_id": warehouse["id"],
        },
    )
    assert inbound.status_code == 200, inbound.text
    return warehouse, part


def test_override_rule_creates_one_evidenced_alert_and_requires_recovery(client):
    warehouse, part = _inventory_fixture(client)
    rule_url = f"/api/inventory/stock-threshold-rules/{warehouse['id']}/{part['id']}"
    created = client.put(
        rule_url,
        json={
            "threshold_quantity": 5,
            "reorder_quantity": 8,
            "is_active": True,
            "reason": "Critical van service stock",
        },
    )
    assert created.status_code == 200, created.text
    rule = created.json()
    assert rule["version"] == 0
    assert rule["threshold_quantity"] == 5

    conflict = client.put(
        rule_url,
        json={
            "threshold_quantity": 4,
            "reorder_quantity": 7,
            "is_active": True,
            "reason": "Stale editor must not overwrite",
        },
    )
    assert conflict.status_code == 409

    alerts = client.get("/api/inventory/notifications")
    assert alerts.status_code == 200, alerts.text
    assert len(alerts.json()) == 1
    alert = alerts.json()[0]
    assert alert["threshold_source"] == "override"
    assert alert["threshold_rule_id"] == rule["id"]
    assert alert["threshold_quantity"] == 5
    assert alert["effective_threshold_quantity"] == 5
    assert alert["observed_quantity"] == 5
    assert alert["current_quantity"] == 5
    assert alert["reorder_quantity"] == 8

    evaluated = client.post("/api/inventory/low-stock/evaluate")
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["already_active"] >= 1
    assert len(client.get("/api/inventory/notifications").json()) == 1

    acknowledged = client.post(
        f"/api/inventory/notifications/{alert['id']}/actions",
        json={
            "action": "acknowledge",
            "expected_version": alert["version"],
            "note": "Warehouse owner accepted review",
        },
    )
    assert acknowledged.status_code == 200, acknowledged.text
    acknowledged_alert = acknowledged.json()
    assert acknowledged_alert["status"] == "acknowledged"
    assert acknowledged_alert["acknowledgement_note"] == "Warehouse owner accepted review"
    repeated_acknowledgement = client.post(
        f"/api/inventory/notifications/{alert['id']}/actions",
        json={
            "action": "acknowledge",
            "expected_version": alert["version"],
            "note": "Warehouse owner accepted review",
        },
    )
    assert repeated_acknowledgement.status_code == 200
    assert repeated_acknowledgement.json()["version"] == acknowledged_alert["version"]

    blocked = client.post(
        f"/api/inventory/notifications/{alert['id']}/actions",
        json={
            "action": "resolve",
            "expected_version": acknowledged_alert["version"],
            "reason": "Attempted close without stock evidence",
        },
    )
    assert blocked.status_code == 409

    recovered = client.post(
        "/api/inventory/transactions",
        json={
            "part_id": part["id"],
            "transaction_type": "inbound",
            "quantity": 1,
            "to_warehouse_id": warehouse["id"],
        },
    )
    assert recovered.status_code == 200, recovered.text
    resolved = client.post(
        f"/api/inventory/notifications/{alert['id']}/actions",
        json={
            "action": "resolve",
            "expected_version": acknowledged_alert["version"],
            "reason": "Count verified above configured threshold",
        },
    )
    assert resolved.status_code == 200, resolved.text
    assert resolved.json()["status"] == "resolved"
    assert resolved.json()["recovered"] is True
    assert resolved.json()["resolution_reason"] == "Count verified above configured threshold"
    repeated_resolution = client.post(
        f"/api/inventory/notifications/{alert['id']}/actions",
        json={
            "action": "resolve",
            "expected_version": acknowledged_alert["version"],
            "reason": "Count verified above configured threshold",
        },
    )
    assert repeated_resolution.status_code == 200
    assert repeated_resolution.json()["version"] == resolved.json()["version"]
    assert client.get("/api/inventory/notifications").json() == []
    assert len(client.get("/api/inventory/notifications?status=resolved").json()) == 1


def test_low_stock_rule_roles_and_tenants_are_enforced(client):
    warehouse, part = _inventory_fixture(client)
    sessions = client.app.state.testing_session_local
    with sessions() as db:
        manager = User(
            organization_id=1,
            name="Rule Manager",
            email="rule-manager@example.test",
            role=UserRole.MANAGER,
        )
        warehouse_user = User(
            organization_id=1,
            name="Rule Warehouse User",
            email="rule-warehouse@example.test",
            role=UserRole.WAREHOUSE,
        )
        engineer = User(
            organization_id=1,
            name="Rule Engineer",
            email="rule-engineer@example.test",
            role=UserRole.ENGINEER,
        )
        other_org = Organization(name="Other rule tenant", slug="other-rule-tenant")
        db.add_all([manager, warehouse_user, engineer, other_org])
        db.flush()
        other_admin = User(
            organization_id=other_org.id,
            name="Other Rule Admin",
            email="other-rule-admin@example.test",
            role=UserRole.ADMIN,
        )
        db.add(other_admin)
        db.commit()
        ids = {
            "manager": manager.id,
            "warehouse": warehouse_user.id,
            "engineer": engineer.id,
            "other_admin": other_admin.id,
        }

    rule_url = f"/api/inventory/stock-threshold-rules/{warehouse['id']}/{part['id']}"
    with _enforced_legacy_auth():
        manager_save = client.put(
            rule_url,
            headers={"X-User-Id": str(ids["manager"])},
            json={
                "threshold_quantity": 6,
                "reorder_quantity": 9,
                "reason": "Manager governed threshold",
            },
        )
        warehouse_read = client.get(
            "/api/inventory/stock-threshold-rules",
            headers={"X-User-Id": str(ids["warehouse"])},
        )
        active_alert = client.get(
            "/api/inventory/notifications",
            headers={"X-User-Id": str(ids["warehouse"])},
        ).json()[0]
        warehouse_ack = client.post(
            f"/api/inventory/notifications/{active_alert['id']}/actions",
            headers={"X-User-Id": str(ids["warehouse"])},
            json={
                "action": "acknowledge",
                "expected_version": active_alert["version"],
                "note": "Warehouse operator accepted ownership",
            },
        )
        warehouse_write = client.put(
            rule_url,
            headers={"X-User-Id": str(ids["warehouse"])},
            json={
                "threshold_quantity": 2,
                "reorder_quantity": 3,
                "reason": "Warehouse cannot govern rules",
                "expected_version": 0,
            },
        )
        engineer_read = client.get(
            "/api/inventory/stock-threshold-rules",
            headers={"X-User-Id": str(ids["engineer"])},
        )
        hidden = client.get(
            "/api/inventory/stock-threshold-rules",
            headers={"X-User-Id": str(ids["other_admin"])},
        )

    assert manager_save.status_code == 200, manager_save.text
    assert len(warehouse_read.json()) == 1
    assert warehouse_ack.status_code == 200, warehouse_ack.text
    assert warehouse_ack.json()["acknowledged_by"] == ids["warehouse"]
    assert warehouse_ack.json()["acknowledged_by_name"] == "Rule Warehouse User"
    assert warehouse_write.status_code == 403
    assert engineer_read.status_code == 403
    assert hidden.status_code == 200
    assert hidden.json() == []


def test_rule_update_uses_optimistic_version_and_low_stock_projection(client):
    warehouse, part = _inventory_fixture(client)
    rule_url = f"/api/inventory/stock-threshold-rules/{warehouse['id']}/{part['id']}"
    created = client.put(
        rule_url,
        json={
            "threshold_quantity": 5,
            "reorder_quantity": 8,
            "reason": "Initial governed threshold",
        },
    ).json()
    updated = client.put(
        rule_url,
        json={
            "threshold_quantity": 6,
            "reorder_quantity": 10,
            "reason": "Seasonal demand increased",
            "expected_version": created["version"],
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 1
    stale = client.put(
        rule_url,
        json={
            "threshold_quantity": 4,
            "reorder_quantity": 5,
            "reason": "Stale mobile submission",
            "expected_version": 0,
        },
    )
    assert stale.status_code == 409
    projection = client.get("/api/inventory/low-stock-alerts")
    assert projection.status_code == 200, projection.text
    row = projection.json()[0]
    assert row["min_stock"] == 6
    assert row["reorder_quantity"] == 10
    assert row["threshold_source"] == "override"
