from io import BytesIO

from openpyxl import Workbook


def _build_parts_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["part_number", "name", "unit", "default_cost", "safety_stock", "supplier", "notes"])
    ws.append(["PX-001", "Filter", "pcs", 12.5, 2, "VendorA", "demo"])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _build_work_orders_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(
        [
            "wo_number",
            "ticket_number",
            "schedule_date",
            "outlet_name",
            "job_type",
            "description",
            "address",
            "city",
            "state",
            "zip",
            "contact_phone",
            "status",
            "revenue",
            "labor_cost",
            "assigned_user_id",
            "engineer_id",
        ]
    )
    ws.append(["WOX-001", "", "2026-04-30", "Demo Outlet", "repair", "desc", "addr", "NYC", "NY", "10001", "123", "open", 100, 40, "", ""])
    buffer = BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def test_excel_import_and_export(client):
    parts_file = _build_parts_xlsx()
    resp = client.post("/api/import/parts.xlsx", files={"file": ("parts.xlsx", parts_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    wo_file = _build_work_orders_xlsx()
    resp = client.post("/api/import/work-orders.xlsx", files={"file": ("work-orders.xlsx", wo_file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert resp.status_code == 200
    assert resp.json()["created"] == 1

    exp_parts = client.get("/api/export/parts.xlsx")
    assert exp_parts.status_code == 200
    assert exp_parts.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    exp_work_orders = client.get("/api/export/work-orders.xlsx")
    assert exp_work_orders.status_code == 200
    assert exp_work_orders.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
