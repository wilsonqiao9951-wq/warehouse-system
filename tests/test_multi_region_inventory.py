from __future__ import annotations

import json

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.models import AuditLog, InventoryRegion, Organization, User, UserRole, Warehouse


PASSWORD = "multi-region-test-password"


def _headers(user_id: int) -> dict[str, str]:
    return {"X-User-Id": str(user_id)}


def _create_user(client, name: str, role: str, headers: dict[str, str] | None = None) -> dict:
    response = client.post(
        "/api/users",
        headers=headers or {},
        json={
            "name": name,
            "email": f"{name}@example.test",
            "role": role,
            "password": PASSWORD,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_warehouse(client, name: str, headers: dict[str, str] | None = None) -> dict:
    response = client.post(
        "/api/warehouses",
        headers=headers or {},
        json={"name": name},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _create_region(
    client,
    code: str,
    name: str,
    headers: dict[str, str] | None = None,
) -> dict:
    response = client.post(
        "/api/inventory/regions",
        headers=headers or {},
        json={"code": code, "name": name, "timezone": "America/New_York"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_default_region_is_created_and_assigned_to_new_warehouses(client):
    warehouse = _create_warehouse(client, "Default Region Warehouse")
    assert warehouse["region_id"] is not None

    regions = client.get("/api/inventory/regions")
    assert regions.status_code == 200
    assert len(regions.json()) == 1
    assert regions.json()[0]["code"] == "PRIMARY"
    assert regions.json()[0]["is_default"] is True
    assert regions.json()[0]["timezone"] == "UTC"
    assert warehouse["region_id"] == regions.json()[0]["id"]

    summary = client.get("/api/inventory/regions/summary")
    assert summary.status_code == 200
    assert summary.json()[0]["warehouse_count"] == 1
    assert summary.json()[0]["main_warehouse_count"] == 1


def test_region_validation_versioning_and_default_invariant(client):
    warehouse = _create_warehouse(client, "Versioned Region Warehouse")
    primary = client.get("/api/inventory/regions").json()[0]

    invalid_timezone = client.post(
        "/api/inventory/regions",
        json={"code": "BAD-TZ", "name": "Bad Timezone", "timezone": "Mars/Olympus"},
    )
    assert invalid_timezone.status_code == 422
    invalid_code = client.post(
        "/api/inventory/regions",
        json={"code": "bad/code", "name": "Bad Code", "timezone": "UTC"},
    )
    assert invalid_code.status_code == 422

    west = _create_region(client, "west", "West region")
    stale = client.patch(
        f"/api/inventory/regions/{west['id']}",
        json={"expected_version": 99, "name": "Stale"},
    )
    assert stale.status_code == 409
    remove_only_default = client.patch(
        f"/api/inventory/regions/{primary['id']}",
        json={"expected_version": primary["version"], "is_default": False},
    )
    assert remove_only_default.status_code == 409

    promoted = client.patch(
        f"/api/inventory/regions/{west['id']}",
        json={"expected_version": west["version"], "is_default": True},
    )
    assert promoted.status_code == 200
    assert promoted.json()["is_default"] is True
    regions = client.get("/api/inventory/regions").json()
    assert sum(1 for region in regions if region["is_default"]) == 1
    assert next(region for region in regions if region["id"] == primary["id"])["is_default"] is False

    assigned = client.put(
        f"/api/warehouses/{warehouse['id']}/region",
        json={
            "region_id": west["id"],
            "expected_region_id": primary["id"],
            "reason": "Move stock ownership to western operations",
        },
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["region_id"] == west["id"]
    deactivate_in_use = client.patch(
        f"/api/inventory/regions/{west['id']}",
        json={"expected_version": promoted.json()["version"], "is_active": False},
    )
    assert deactivate_in_use.status_code == 422

    with client.app.state.testing_session_local() as db:
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "assign_warehouse_region")
        )
        assert audit is not None
        metadata = json.loads(audit.metadata_json)
        assert metadata["previous_region_id"] == primary["id"]
        assert metadata["region_id"] == west["id"]
        assert metadata["reason"] == "Move stock ownership to western operations"


def test_cross_region_transfer_requires_manager_and_is_reported(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "region-admin", "admin")
        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        manager = _create_user(client, "region-manager", "manager", _headers(admin["id"]))
        warehouse_user = _create_user(
            client,
            "region-warehouse",
            "warehouse",
            _headers(admin["id"]),
        )
        denied_region_create = client.post(
            "/api/inventory/regions",
            headers=_headers(warehouse_user["id"]),
            json={"code": "DENIED", "name": "Denied region", "timezone": "UTC"},
        )
        assert denied_region_create.status_code == 403
        source = _create_warehouse(client, "Region Source", _headers(manager["id"]))
        target = _create_warehouse(client, "Region Target", _headers(manager["id"]))
        east = _create_region(client, "EAST", "East region", _headers(manager["id"]))
        denied_assignment = client.put(
            f"/api/warehouses/{target['id']}/region",
            headers=_headers(warehouse_user["id"]),
            json={
                "region_id": east["id"],
                "expected_region_id": target["region_id"],
                "reason": "Warehouse role cannot assign regions",
            },
        )
        assert denied_assignment.status_code == 403
        assigned = client.put(
            f"/api/warehouses/{target['id']}/region",
            headers=_headers(manager["id"]),
            json={
                "region_id": east["id"],
                "expected_region_id": target["region_id"],
                "reason": "Target warehouse belongs to eastern operations",
            },
        )
        assert assigned.status_code == 200, assigned.text
        part = client.post(
            "/api/parts",
            headers=_headers(manager["id"]),
            json={"part_number": "REGION-PART", "name": "Regional part", "safety_stock": 1},
        )
        assert part.status_code == 200, part.text
        inbound = client.post(
            "/api/inventory/transactions",
            headers=_headers(warehouse_user["id"]),
            json={
                "part_id": part.json()["id"],
                "transaction_type": "inbound",
                "quantity": 10,
                "to_warehouse_id": source["id"],
            },
        )
        assert inbound.status_code == 200, inbound.text
        transfer_payload = {
            "part_id": part.json()["id"],
            "transaction_type": "transfer",
            "quantity": 4,
            "from_warehouse_id": source["id"],
            "to_warehouse_id": target["id"],
        }
        denied = client.post(
            "/api/inventory/transactions",
            headers=_headers(warehouse_user["id"]),
            json=transfer_payload,
        )
        assert denied.status_code == 403
        assert "Cross-region" in denied.json()["detail"]
        allowed = client.post(
            "/api/inventory/transactions",
            headers=_headers(manager["id"]),
            json=transfer_payload,
        )
        assert allowed.status_code == 200, allowed.text

        summary = client.get(
            "/api/inventory/regions/summary",
            headers=_headers(warehouse_user["id"]),
        )
        assert summary.status_code == 200
        rows = {row["region_code"]: row for row in summary.json()}
        assert rows["PRIMARY"]["total_quantity"] == 6
        assert rows["EAST"]["total_quantity"] == 4
        assert rows["PRIMARY"]["cross_region_transfer_count"] == 1
        assert rows["EAST"]["cross_region_transfer_count"] == 1

        history = client.get(
            "/api/inventory/regions/cross-region-transfers",
            headers=_headers(warehouse_user["id"]),
        )
        assert history.status_code == 200
        assert history.json()[0]["transaction_id"] == allowed.json()["id"]
        assert history.json()[0]["from_region_name"] == "Primary region"
        assert history.json()[0]["to_region_name"] == "East region"

        with client.app.state.testing_session_local() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "inventory_transfer",
                    AuditLog.entity_id == allowed.json()["id"],
                )
            )
            assert audit is not None
            metadata = json.loads(audit.metadata_json)
            assert metadata["cross_region"] is True
            assert metadata["from_region_id"] == source["region_id"]
            assert metadata["to_region_id"] == east["id"]
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_region_management_is_tenant_scoped_and_vehicle_flow_stays_protected(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        settings.rbac_enforce = False
        admin = _create_user(client, "region-tenant-admin", "admin")
        engineer = _create_user(client, "region-vehicle-engineer", "engineer")
        main = _create_warehouse(client, "Region Vehicle Source")
        vehicle_response = client.post(
            "/api/warehouses",
            json={"name": "Region Engineer Van", "assigned_user_id": engineer["id"]},
        )
        assert vehicle_response.status_code == 200
        vehicle = vehicle_response.json()
        second_region = _create_region(client, "REMOTE", "Remote region")
        assigned = client.put(
            f"/api/warehouses/{vehicle['id']}/region",
            json={
                "region_id": second_region["id"],
                "expected_region_id": vehicle["region_id"],
                "reason": "Vehicle operates from the remote region",
            },
        )
        assert assigned.status_code == 200
        part = client.post(
            "/api/parts",
            json={"part_number": "REGION-VAN", "name": "Vehicle protected part"},
        ).json()
        client.post(
            "/api/inventory/transactions",
            json={
                "part_id": part["id"],
                "transaction_type": "inbound",
                "quantity": 2,
                "to_warehouse_id": main["id"],
            },
        )
        protected = client.post(
            "/api/inventory/transactions",
            json={
                "part_id": part["id"],
                "transaction_type": "transfer",
                "quantity": 1,
                "from_warehouse_id": main["id"],
                "to_warehouse_id": vehicle["id"],
            },
        )
        assert protected.status_code == 409
        assert "Vehicle inventory" in protected.json()["detail"]

        with client.app.state.testing_session_local() as db:
            tenant_two = Organization(name="Region Tenant Two", slug="region-tenant-two")
            db.add(tenant_two)
            db.flush()
            tenant_two_manager = User(
                organization_id=tenant_two.id,
                name="Tenant Two Region Manager",
                email="tenant-two-region@example.test",
                role=UserRole.MANAGER,
                password_hash=hash_password(PASSWORD),
            )
            db.add(tenant_two_manager)
            db.flush()
            db.add(
                InventoryRegion(
                    organization_id=tenant_two.id,
                    code="TENANT-TWO",
                    name="Tenant Two region",
                    timezone="UTC",
                    is_default=True,
                    is_active=True,
                )
            )
            db.commit()
            tenant_two_manager_id = tenant_two_manager.id

        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        tenant_two_regions = client.get(
            "/api/inventory/regions",
            headers=_headers(tenant_two_manager_id),
        )
        assert tenant_two_regions.status_code == 200
        assert [row["code"] for row in tenant_two_regions.json()] == ["TENANT-TWO"]
        cross_tenant_assignment = client.put(
            f"/api/warehouses/{main['id']}/region",
            headers=_headers(tenant_two_manager_id),
            json={
                "region_id": tenant_two_regions.json()[0]["id"],
                "expected_region_id": None,
                "reason": "Attempt cross tenant assignment",
            },
        )
        assert cross_tenant_assignment.status_code == 404
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy
