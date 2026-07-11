from io import BytesIO

from openpyxl import Workbook

from app.core.config import settings
from app.models import Organization, User, UserRole


def _parts_workbook(rows: list[list]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["name", "part_number", "default_cost", "unit", "min_stock", "supplier"])
    for row in rows:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _preview(client, content: bytes, headers: dict[str, str] | None = None):
    return client.post(
        "/api/imports/parts/preview",
        headers=headers or {},
        files={
            "file": (
                "customer-parts.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_parts_preview_commit_history_and_idempotency(client):
    content = _parts_workbook(
        [
            ["Water Filter", "SHARED-SKU-1", 12.5, "pcs", 2, "Vendor A"],
            ["Pump", "SHARED-SKU-2", 95, "pcs", 1, "Vendor B"],
        ]
    )
    preview = _preview(client, content)
    assert preview.status_code == 200
    batch = preview.json()
    assert batch["status"] == "ready"
    assert batch["total_rows"] == 2
    assert batch["valid_rows"] == 2
    assert batch["error_rows"] == 0
    assert batch["created_count"] == 2
    assert batch["preview_rows"][0]["part_number"] == "SHARED-SKU-1"

    duplicate_preview = _preview(client, content)
    assert duplicate_preview.status_code == 200
    assert duplicate_preview.json()["id"] == batch["id"]

    committed = client.post(f"/api/imports/parts/{batch['id']}/commit")
    assert committed.status_code == 200
    assert committed.json()["status"] == "committed"
    assert committed.json()["created_count"] == 2
    recommitted = client.post(f"/api/imports/parts/{batch['id']}/commit")
    assert recommitted.status_code == 200
    assert recommitted.json()["created_count"] == 2

    history = client.get("/api/imports/parts")
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [batch["id"]]


def test_parts_preview_rejects_invalid_rows(client):
    content = _parts_workbook(
        [
            ["", "BROKEN-1", 10, "pcs", 0, "Vendor"],
            ["Duplicate A", "DUP-1", 10, "pcs", 0, "Vendor"],
            ["Duplicate B", "DUP-1", -2, "pcs", 0, "Vendor"],
        ]
    )
    preview = _preview(client, content)
    assert preview.status_code == 200
    batch = preview.json()
    assert batch["status"] == "invalid"
    assert batch["error_rows"] == 2
    assert len(batch["errors"]) == 2
    blocked = client.post(f"/api/imports/parts/{batch['id']}/commit")
    assert blocked.status_code == 409


def test_same_part_number_isolated_between_customers(client):
    original_rbac = settings.rbac_enforce
    original_legacy = settings.legacy_header_auth
    try:
        content = _parts_workbook([["Shared Part", "SAME-SKU", 10, "pcs", 0, "Vendor"]])
        first = _preview(client, content).json()
        assert client.post(f"/api/imports/parts/{first['id']}/commit").status_code == 200

        with client.app.state.testing_session_local() as db:
            second_org = Organization(id=2, name="Second Customer", slug="second-customer")
            second_manager = User(
                organization_id=2,
                name="Second Manager",
                email="second-import@example.com",
                role=UserRole.MANAGER,
            )
            db.add_all([second_org, second_manager])
            db.commit()
            second_manager_id = second_manager.id

        settings.rbac_enforce = True
        settings.legacy_header_auth = True
        headers = {"X-User-Id": str(second_manager_id)}
        second = _preview(client, content, headers=headers)
        assert second.status_code == 200
        assert second.json()["created_count"] == 1
        assert second.json()["organization_id"] == 2
        assert client.post(
            f"/api/imports/parts/{second.json()['id']}/commit",
            headers=headers,
        ).status_code == 200
        second_history = client.get("/api/imports/parts", headers=headers)
        assert [item["id"] for item in second_history.json()] == [second.json()["id"]]
    finally:
        settings.rbac_enforce = original_rbac
        settings.legacy_header_auth = original_legacy


def test_item_master_preserves_barcode_tracking_and_custom_columns(client):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append([
        "part_number", "name", "category", "barcode", "item_type", "tracking_mode",
        "custom_color", "custom_customer_code",
    ])
    worksheet.append(["GEN-1", "Generic Item", "Filters", "123456789", "stock", "batch", "blue", "C-99"])
    output = BytesIO()
    workbook.save(output)
    preview = _preview(client, output.getvalue())
    assert preview.status_code == 200
    row = preview.json()["preview_rows"][0]
    assert row["barcode"] == "123456789"
    assert row["tracking_mode"] == "batch"
    assert row["custom_fields"] == {"color": "blue", "customer_code": "C-99"}
    committed = client.post(f"/api/imports/parts/{preview.json()['id']}/commit")
    assert committed.status_code == 200
    item = next(part for part in client.get("/api/parts").json() if part["part_number"] == "GEN-1")
    assert item["category"] == "Filters"
    assert item["barcode"] == "123456789"
    assert item["custom_fields"]["customer_code"] == "C-99"
