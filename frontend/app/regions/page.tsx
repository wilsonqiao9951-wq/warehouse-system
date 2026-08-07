"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { AppRole, getCurrentRole } from "@/lib/role";
import {
  CrossRegionTransfer,
  InventoryRegion,
  InventoryRegionSummary,
  Warehouse
} from "@/types";

const emptyRegion = {
  code: "",
  name: "",
  timezone: "UTC",
  is_default: false,
  is_active: true
};

export default function RegionsPage() {
  const [role, setRole] = useState<AppRole>("warehouse");
  const [regions, setRegions] = useState<InventoryRegion[]>([]);
  const [summary, setSummary] = useState<InventoryRegionSummary[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [transfers, setTransfers] = useState<CrossRegionTransfer[]>([]);
  const [form, setForm] = useState({ ...emptyRegion });
  const [editingId, setEditingId] = useState<number | null>(null);
  const [assignments, setAssignments] = useState<Record<number, number>>({});
  const [assignmentReason, setAssignmentReason] = useState("Operational region assignment");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const canManage = role === "admin" || role === "manager";

  const refresh = async () => {
    const [regionRows, summaryRows, warehouseRows, transferRows] = await Promise.all([
      api.listInventoryRegions(),
      api.listInventoryRegionSummary(),
      api.listWarehouses(),
      api.listCrossRegionTransfers()
    ]);
    setRegions(regionRows);
    setSummary(summaryRows);
    setWarehouses(warehouseRows);
    setTransfers(transferRows);
    setAssignments(Object.fromEntries(
      warehouseRows
        .filter((warehouse) => warehouse.region_id != null)
        .map((warehouse) => [warehouse.id, Number(warehouse.region_id)])
    ));
  };

  useEffect(() => {
    setRole(getCurrentRole());
    void refresh().catch((reason: Error) => setError(reason.message));
  }, []);

  const activeRegions = useMemo(
    () => regions.filter((region) => region.is_active),
    [regions]
  );

  const submitRegion = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      if (editingId != null) {
        const existing = regions.find((region) => region.id === editingId);
        if (!existing) return;
        await api.updateInventoryRegion(editingId, {
          expected_version: existing.version,
          code: form.code,
          name: form.name,
          timezone: form.timezone,
          is_default: form.is_default,
          is_active: form.is_active
        });
        setNotice("Region updated with a new audited version.");
      } else {
        await api.createInventoryRegion(form);
        setNotice("Inventory region created.");
      }
      setEditingId(null);
      setForm({ ...emptyRegion });
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save inventory region.");
    } finally {
      setBusy(false);
    }
  };

  const beginEdit = (region: InventoryRegion) => {
    setEditingId(region.id);
    setForm({
      code: region.code,
      name: region.name,
      timezone: region.timezone,
      is_default: region.is_default,
      is_active: region.is_active
    });
    setNotice("");
    setError("");
  };

  const assignWarehouse = async (warehouse: Warehouse) => {
    const regionId = assignments[warehouse.id];
    if (!regionId) return;
    try {
      setBusy(true);
      setError("");
      await api.assignWarehouseRegion(warehouse.id, {
        region_id: regionId,
        expected_region_id: warehouse.region_id ?? null,
        reason: assignmentReason.trim()
      });
      setNotice(`${warehouse.name} region assignment saved and audited.`);
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to assign warehouse region.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ManagerShell
      title="Regional inventory"
      subtitle="Regional ownership, warehouse placement, stock totals, and controlled cross-region transfers."
      metrics={[
        { label: "Regions", value: regions.length },
        { label: "Warehouses", value: warehouses.length },
        { label: "Cross-region transfers", value: transfers.length }
      ]}
    >
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}

      {canManage && (
        <form className="card" onSubmit={submitRegion}>
          <h3>{editingId == null ? "Create region" : "Edit region"}</h3>
          <div className="grid">
            <label>
              Region code
              <input
                required
                maxLength={50}
                value={form.code}
                onChange={(event) => setForm((value) => ({ ...value, code: event.target.value }))}
                placeholder="NORTHEAST"
              />
            </label>
            <label>
              Region name
              <input
                required
                maxLength={120}
                value={form.name}
                onChange={(event) => setForm((value) => ({ ...value, name: event.target.value }))}
                placeholder="Northeast operations"
              />
            </label>
            <label>
              IANA timezone
              <input
                required
                value={form.timezone}
                onChange={(event) => setForm((value) => ({ ...value, timezone: event.target.value }))}
                placeholder="America/New_York"
              />
            </label>
          </div>
          <div style={{ display: "flex", gap: 16, marginTop: 12, flexWrap: "wrap" }}>
            <label><input type="checkbox" checked={form.is_default} onChange={(event) => setForm((value) => ({ ...value, is_default: event.target.checked }))} /> Default region</label>
            <label><input type="checkbox" checked={form.is_active} onChange={(event) => setForm((value) => ({ ...value, is_active: event.target.checked }))} /> Active</label>
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button disabled={busy} type="submit">{editingId == null ? "Create region" : "Save region"}</button>
            {editingId != null && (
              <button type="button" className="secondary" onClick={() => { setEditingId(null); setForm({ ...emptyRegion }); }}>
                Cancel
              </button>
            )}
          </div>
        </form>
      )}

      <div className="card">
        <h3>Regional stock summary</h3>
        <div className="table-wrap"><table><thead><tr><th>Region</th><th>Timezone</th><th>Warehouses</th><th>Vehicles</th><th>Total qty</th><th>Low stock rows</th><th>Cross-region</th><th>Status</th>{canManage && <th>Action</th>}</tr></thead>
          <tbody>{summary.map((row) => {
            const region = regions.find((item) => item.id === row.region_id);
            return (
              <tr key={row.region_id}>
                <td><strong>{row.region_code}</strong><div className="muted">{row.region_name}{row.is_default ? " · default" : ""}</div></td>
                <td>{row.timezone}</td><td>{row.main_warehouse_count}</td><td>{row.vehicle_warehouse_count}</td><td>{row.total_quantity}</td>
                <td className={row.low_stock_sku_count > 0 ? "danger" : ""}>{row.low_stock_sku_count}</td><td>{row.cross_region_transfer_count}</td><td>{row.is_active ? "Active" : "Inactive"}</td>
                {canManage && <td>{region && <button type="button" className="secondary" onClick={() => beginEdit(region)}>Edit</button>}</td>}
              </tr>
            );
          })}</tbody>
        </table></div>
      </div>

      <div className="card">
        <h3>Warehouse region ownership</h3>
        {canManage && <label>Audit reason<input value={assignmentReason} minLength={3} maxLength={500} onChange={(event) => setAssignmentReason(event.target.value)} /></label>}
        <div className="table-wrap"><table><thead><tr><th>Warehouse</th><th>Type</th><th>Region</th>{canManage && <th>Action</th>}</tr></thead>
          <tbody>{warehouses.map((warehouse) => (
            <tr key={warehouse.id}>
              <td><strong>{warehouse.code || warehouse.name}</strong><div className="muted">{warehouse.name}</div></td>
              <td>{warehouse.warehouse_type || "main"}</td>
              <td>{canManage ? (
                <select value={assignments[warehouse.id] || ""} onChange={(event) => setAssignments((value) => ({ ...value, [warehouse.id]: Number(event.target.value) }))}>
                  <option value="">Select region</option>{activeRegions.map((region) => <option key={region.id} value={region.id}>{region.name}</option>)}
                </select>
              ) : regions.find((region) => region.id === warehouse.region_id)?.name || "Primary region"}</td>
              {canManage && <td><button type="button" disabled={busy || assignments[warehouse.id] === warehouse.region_id || assignmentReason.trim().length < 3} onClick={() => void assignWarehouse(warehouse)}>Assign</button></td>}
            </tr>
          ))}</tbody>
        </table></div>
      </div>

      <div className="card">
        <h3>Recent cross-region transfers</h3>
        {transfers.length === 0 ? <p className="muted">No cross-region transfers recorded.</p> : (
          <div className="table-wrap"><table><thead><tr><th>Time</th><th>Part</th><th>Route</th><th>Qty</th><th>Transaction</th></tr></thead>
            <tbody>{transfers.map((transfer) => <tr key={transfer.transaction_id}>
              <td>{new Date(transfer.created_at).toLocaleString()}</td><td>{transfer.part_number} — {transfer.part_name}</td>
              <td>{transfer.from_region_name} / {transfer.from_warehouse_name} → {transfer.to_region_name} / {transfer.to_warehouse_name}</td>
              <td>{transfer.quantity}</td><td>#{transfer.transaction_id}</td>
            </tr>)}</tbody>
          </table></div>
        )}
      </div>
    </ManagerShell>
  );
}
