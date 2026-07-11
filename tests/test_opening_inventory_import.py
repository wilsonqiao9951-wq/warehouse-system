from io import BytesIO

from openpyxl import Workbook


def _inventory_workbook(rows: list[list]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(["warehouse", "part_number", "quantity", "unit_cost", "notes"])
    for row in rows:
        worksheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _preview(client, content: bytes):
    return client.post(
        "/api/imports/opening-inventory/preview",
        files={
            "file": (
                "opening-inventory.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )


def test_opening_inventory_preview_commit_and_reconcile(client):
    part = client.post("/api/parts", json={"part_number": "OPEN-1", "name": "Opening Part"}).json()
    warehouse = client.post("/api/warehouses", json={"name": "Opening Warehouse"}).json()
    content = _inventory_workbook([["Opening Warehouse", "OPEN-1", 12, 7.5, "initial count"]])

    preview = _preview(client, content)
    assert preview.status_code == 200
    batch = preview.json()
    assert batch["status"] == "ready"
    row = batch["preview_rows"][0]
    assert row["part_id"] == part["id"]
    assert row["warehouse_id"] == warehouse["id"]
    assert row["current_quantity"] == 0
    assert row["projected_quantity"] == 12

    committed = client.post(f"/api/imports/opening-inventory/{batch['id']}/commit")
    assert committed.status_code == 200
    assert committed.json()["status"] == "committed"
    recommitted = client.post(f"/api/imports/opening-inventory/{batch['id']}/commit")
    assert recommitted.status_code == 200

    balances = client.get("/api/inventory/balances").json()
    matching = next(
        item for item in balances
        if item["part_id"] == part["id"] and item["warehouse_id"] == warehouse["id"]
    )
    assert matching["quantity"] == 12
    history = client.get("/api/imports/opening-inventory")
    assert history.status_code == 200
    assert history.json()[0]["id"] == batch["id"]


def test_opening_inventory_rejects_unknown_and_duplicate_rows(client):
    client.post("/api/parts", json={"part_number": "OPEN-2", "name": "Opening Part Two"})
    client.post("/api/warehouses", json={"name": "Known Warehouse"})
    content = _inventory_workbook(
        [
            ["Missing Warehouse", "OPEN-2", 4, 1, ""],
            ["Known Warehouse", "MISSING-PART", 4, 1, ""],
            ["Known Warehouse", "OPEN-2", 4, 1, ""],
            ["Known Warehouse", "OPEN-2", 5, 1, "duplicate"],
        ]
    )
    preview = _preview(client, content)
    assert preview.status_code == 200
    batch = preview.json()
    assert batch["status"] == "invalid"
    assert batch["error_rows"] == 3
    blocked = client.post(f"/api/imports/opening-inventory/{batch['id']}/commit")
    assert blocked.status_code == 409
