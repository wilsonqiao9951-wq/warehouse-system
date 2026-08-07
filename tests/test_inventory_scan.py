from contextlib import contextmanager

from app.core.config import settings
from app.models import AuditLog


@contextmanager
def enforced_rbac():
    old_rbac, old_legacy = settings.rbac_enforce, settings.legacy_header_auth
    settings.rbac_enforce, settings.legacy_header_auth = True, False
    try:
        yield
    finally:
        settings.rbac_enforce, settings.legacy_header_auth = old_rbac, old_legacy


def test_inventory_scan_matches_barcode_and_reports_stock(client):
    warehouse = client.post("/api/warehouses", json={"code": "SCAN", "name": "Scan Warehouse"}).json()
    part = client.post("/api/parts", json={"part_number": "SCAN-1", "name": "Scan Part", "barcode": "012345"}).json()
    client.post("/api/inventory/transactions", json={"part_id": part["id"], "transaction_type": "inbound", "quantity": 8, "to_warehouse_id": warehouse["id"]})
    result = client.post("/api/inventory/scan", json={"barcode": "012345", "quantity": 3, "warehouse_id": warehouse["id"]})
    assert result.status_code == 200
    assert result.json()["matched"] is True
    assert result.json()["current_quantity"] == 8
    assert result.json()["projected_quantity"] == 5


def test_inventory_scan_reports_unknown_label(client):
    result = client.post("/api/inventory/scan", json={"barcode": "unknown"})
    assert result.status_code == 200
    assert result.json()["matched"] is False


def test_warehouse_location_labels_create_validated_scan_context(client):
    warehouse = client.post("/api/warehouses", json={"code": "WH-SCAN", "name": "Scan Warehouse"}).json()
    other = client.post("/api/warehouses", json={"code": "WH-OTHER", "name": "Other Warehouse"}).json()
    location = client.post("/api/storage-locations", json={
        "warehouse_id": warehouse["id"], "code": "A-01", "name": "Shelf A1", "zone": "A",
    }).json()
    client.post("/api/storage-locations", json={"warehouse_id": other["id"], "code": "A-01", "name": "Duplicate"})

    labels = client.get(f"/api/inventory/location-labels?warehouse_id={warehouse['id']}")
    assert labels.status_code == 200, labels.text
    warehouse_label = next(row for row in labels.json() if row["location_id"] is None)
    location_label = next(row for row in labels.json() if row["location_id"] == location["id"])
    scanned_warehouse = client.post("/api/inventory/location-scan", json={"label": warehouse_label["label_token"]})
    assert scanned_warehouse.status_code == 200
    assert scanned_warehouse.json()["scan_type"] == "warehouse"
    scanned_location = client.post("/api/inventory/location-scan", json={
        "label": location_label["label_token"], "expected_warehouse_id": warehouse["id"],
    })
    assert scanned_location.status_code == 200
    assert scanned_location.json()["location_code"] == "A-01"
    assert client.post("/api/inventory/location-scan", json={"label": "A-01"}).status_code == 409
    assert client.post("/api/inventory/location-scan", json={
        "label": location_label["label_token"], "expected_warehouse_id": other["id"],
    }).status_code == 409
    with client.app.state.testing_session_local() as db:
        assert db.query(AuditLog).filter(AuditLog.action == "inventory_location_scanned").count() == 1


def test_part_scan_uses_validated_location_balance(client):
    warehouse = client.post("/api/warehouses", json={"code": "LOC-QTY", "name": "Location Quantity"}).json()
    location = client.post("/api/storage-locations", json={"warehouse_id": warehouse["id"], "code": "BIN-1"}).json()
    part = client.post("/api/parts", json={"part_number": "LOC-PART", "name": "Location Part", "barcode": "LOC-0001"}).json()
    inbound = client.post("/api/inventory/transactions", json={
        "part_id": part["id"], "transaction_type": "inbound", "quantity": 6,
        "to_warehouse_id": warehouse["id"], "to_location_id": location["id"],
    })
    assert inbound.status_code == 200, inbound.text
    result = client.post("/api/inventory/scan", json={"barcode": "LOC-0001", "location_id": location["id"]})
    assert result.status_code == 200, result.text
    assert result.json()["warehouse_id"] == warehouse["id"]
    assert result.json()["location_id"] == location["id"]
    assert result.json()["current_quantity"] == 6


def test_engineer_cannot_probe_another_warehouse_stock(client):
    password = "engineer-scan-password"
    engineer = client.post("/api/users", json={
        "name": "scan-engineer", "email": "scan-engineer@example.test", "role": "engineer", "password": password,
    }).json()
    client.post("/api/warehouses", json={
        "code": "SCAN-VAN", "name": "Engineer Van", "warehouse_type": "van", "assigned_user_id": engineer["id"],
    })
    main = client.post("/api/warehouses", json={"code": "PRIVATE-MAIN", "name": "Private Main"}).json()
    part = client.post("/api/parts", json={"part_number": "PRIVATE-PART", "name": "Private", "barcode": "PRIVATE-1"}).json()
    client.post("/api/inventory/transactions", json={
        "part_id": part["id"], "transaction_type": "inbound", "quantity": 20, "to_warehouse_id": main["id"],
    })
    with enforced_rbac():
        login = client.post("/api/auth/login", data={"username": engineer["email"], "password": password})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        denied = client.post("/api/inventory/scan", headers=headers, json={
            "barcode": "PRIVATE-1", "warehouse_id": main["id"],
        })
        assert denied.status_code == 403
