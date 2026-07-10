from fastapi import APIRouter
from fastapi.responses import HTMLResponse

pages_router = APIRouter()


@pages_router.get("/engineer/{user_id}", response_class=HTMLResponse)
def engineer_page(user_id: int):
    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Engineer Dashboard</title>
  <style>
    body {{ font-family: Arial, sans-serif; background: #f6f8fa; margin: 0; padding: 16px; }}
    .card {{ background: #fff; border-radius: 12px; padding: 14px; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }}
    h1 {{ font-size: 20px; margin: 0 0 12px; }}
    h2 {{ font-size: 16px; margin: 0 0 8px; }}
    .muted {{ color: #666; font-size: 13px; }}
    .bad {{ color: #c62828; font-weight: bold; }}
    .ok {{ color: #2e7d32; font-weight: bold; }}
    ul {{ margin: 0; padding-left: 18px; }}
  </style>
</head>
<body>
  <h1>Engineer Dashboard</h1>
  <div id="app" class="muted">Loading...</div>
  <script>
    async function load() {{
      const root = document.getElementById("app");
      const res = await fetch("/api/dashboard/engineers/{user_id}");
      if (!res.ok) {{
        root.innerHTML = "<div class='card bad'>Failed to load engineer dashboard.</div>";
        return;
      }}
      const data = await res.json();
      const items = data.van_inventory.map(item => `
        <li>
          <b>${{item.part_number}}</b> - ${{item.part_name}}
          <span class="${{item.is_low_stock ? "bad" : "ok"}}">Qty: ${{item.quantity}}</span>
        </li>
      `).join("");

      root.innerHTML = `
        <div class="card">
          <h2>${{data.user_name}}</h2>
          <div>Open Work Orders: <b>${{data.open_work_orders}}</b></div>
          <div>Completed Work Orders: <b>${{data.completed_work_orders}}</b></div>
          <div>Van Low Stock Items: <b class="${{data.van_low_stock_items > 0 ? "bad" : "ok"}}">${{data.van_low_stock_items}}</b></div>
        </div>
        <div class="card">
          <h2>Van Inventory</h2>
          <ul>${{items}}</ul>
        </div>
      `;
    }}
    load();
  </script>
</body>
</html>
"""


@pages_router.get("/admin/warehouses", response_class=HTMLResponse)
def admin_warehouse_page():
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Admin Warehouse Dashboard</title>
  <style>
    body { font-family: Arial, sans-serif; background: #f6f8fa; margin: 0; padding: 16px; }
    .card { background: #fff; border-radius: 12px; padding: 14px; margin-bottom: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
    h1 { font-size: 20px; margin: 0 0 12px; }
    h2 { font-size: 16px; margin: 0 0 8px; }
    table { width: 100%; border-collapse: collapse; }
    th, td { border-bottom: 1px solid #e5e7eb; text-align: left; padding: 8px 6px; font-size: 14px; }
    .bad { color: #c62828; font-weight: bold; }
  </style>
</head>
<body>
  <h1>Admin Warehouse Dashboard</h1>
  <div id="app">Loading...</div>
  <script>
    async function load() {
      const root = document.getElementById("app");
      const res = await fetch("/api/dashboard/admin/warehouses");
      if (!res.ok) {
        root.innerHTML = "<div class='card bad'>Failed to load warehouse dashboard.</div>";
        return;
      }
      const data = await res.json();
      const rows = data.warehouses.map(w => `
        <tr>
          <td>${w.warehouse_name}</td>
          <td>${w.assigned_user_name || "-"}</td>
          <td>${w.total_sku}</td>
          <td>${w.total_quantity}</td>
          <td class="${w.low_stock_items > 0 ? "bad" : ""}">${w.low_stock_items}</td>
        </tr>
      `).join("");

      root.innerHTML = `
        <div class="card">
          <h2>Overview</h2>
          <div>Total Warehouses: <b>${data.total_warehouses}</b></div>
          <div>Total Parts: <b>${data.total_parts}</b></div>
          <div>Total Low Stock Items: <b class="${data.total_low_stock_items > 0 ? "bad" : ""}">${data.total_low_stock_items}</b></div>
        </div>
        <div class="card">
          <h2>Warehouse Details</h2>
          <table>
            <thead>
              <tr><th>Warehouse</th><th>Assigned Engineer</th><th>SKU In Stock</th><th>Total Qty</th><th>Low Stock</th></tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      `;
    }
    load();
  </script>
</body>
</html>
"""
