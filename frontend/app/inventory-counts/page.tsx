"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { InventoryCount, Part, Warehouse } from "@/types";

export default function InventoryCountsPage() {
  const [counts, setCounts] = useState<InventoryCount[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [warehouseId, setWarehouseId] = useState<number | "">("");
  const [title, setTitle] = useState("");
  const [lineDrafts, setLineDrafts] = useState<Record<number, { partId: number | ""; quantity: number }>>({});
  const [passwords, setPasswords] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [countRows, warehouseRows, partRows] = await Promise.all([
        api.listInventoryCounts(), api.listWarehouses(), api.listParts()
      ]);
      setCounts(countRows);
      setWarehouses(warehouseRows.filter((row) => row.is_active !== false && row.warehouse_type !== "van"));
      setParts(partRows.filter((row) => row.is_active));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load inventory counts");
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);
  const openCount = useMemo(() => counts.filter((row) => row.status === "draft" || row.status === "submitted").length, [counts]);

  async function createCount() {
    if (!warehouseId || title.trim().length < 3) return;
    setBusy("create"); setError(""); setMessage("");
    try {
      await api.createInventoryCount({
        client_request_id: crypto.randomUUID(), warehouse_id: warehouseId, title: title.trim()
      });
      setTitle(""); setMessage("Draft count created."); await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to create count"); }
    finally { setBusy(""); }
  }

  async function saveLine(item: InventoryCount) {
    const draft = lineDrafts[item.id];
    if (!draft?.partId || draft.quantity < 0) return;
    setBusy(`line-${item.id}`); setError("");
    try {
      await api.recordInventoryCountLine(item.id, {
        part_id: draft.partId, counted_quantity: draft.quantity, expected_version: item.version
      });
      await refresh();
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Unable to record count"); }
    finally { setBusy(""); }
  }

  async function act(item: InventoryCount, action: "submit" | "approve" | "cancel") {
    let reason: string | undefined;
    if (action === "cancel") {
      reason = window.prompt("Cancellation reason")?.trim();
      if (!reason) return;
    }
    setBusy(`${action}-${item.id}`); setError("");
    try {
      await api.actOnInventoryCount(item.id, {
        action, expected_version: item.version, reason,
        password: action === "approve" ? passwords[item.id] : undefined
      });
      setPasswords((current) => ({ ...current, [item.id]: "" }));
      setMessage(action === "approve" ? "Count approved and inventory ledger adjusted." : `Count ${action} successful.`);
      await refresh();
    } catch (reasonValue) { setError(reasonValue instanceof Error ? reasonValue.message : "Unable to update count"); }
    finally { setBusy(""); }
  }

  return (
    <ManagerShell title="Inventory Counts" subtitle="Count first; administrator approval is required before the ledger changes."
      metrics={[{ label: "Open counts", value: String(openCount) }, { label: "History", value: String(counts.length) }]}>
      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice">{message}</div>}
      <section className="card">
        <h3>Create count</h3>
        <div className="form-grid">
          <label><span>Warehouse</span><select value={warehouseId} onChange={(event) => setWarehouseId(event.target.value ? Number(event.target.value) : "")}>
            <option value="">Select warehouse</option>{warehouses.map((row) => <option key={row.id} value={row.id}>{row.name}</option>)}
          </select></label>
          <label><span>Count title</span><input value={title} maxLength={160} onChange={(event) => setTitle(event.target.value)} placeholder="Weekly warehouse count" /></label>
        </div>
        <button type="button" disabled={busy === "create" || !warehouseId || title.trim().length < 3} onClick={() => void createCount()}>Create draft</button>
      </section>

      {counts.map((item) => {
        const draft = lineDrafts[item.id] || { partId: "" as const, quantity: 0 };
        return <section className="card" key={item.id}>
          <div className="section-heading-row"><div><h3 style={{ margin: 0 }}>{item.title}</h3><span className="muted">#{item.id} · {item.warehouse_name} · v{item.version}</span></div>
            <span className={`status-pill status-pill--${item.status}`}>{item.status}</span></div>
          {item.can_edit && <div className="form-grid" style={{ marginTop: 12 }}>
            <label><span>Part</span><select value={draft.partId} onChange={(event) => setLineDrafts((current) => ({ ...current, [item.id]: { ...draft, partId: event.target.value ? Number(event.target.value) : "" } }))}>
              <option value="">Select part</option>{parts.map((part) => <option value={part.id} key={part.id}>{part.part_number} — {part.name}</option>)}
            </select></label>
            <label><span>Physical quantity</span><input type="number" min={0} value={draft.quantity} onChange={(event) => setLineDrafts((current) => ({ ...current, [item.id]: { ...draft, quantity: Math.max(0, Number(event.target.value)) } }))} /></label>
            <button type="button" disabled={!draft.partId || busy === `line-${item.id}`} onClick={() => void saveLine(item)}>Record count</button>
          </div>}
          {item.lines.length === 0 ? <div className="empty-state">No parts counted yet.</div> : <div className="table-wrap"><table><thead><tr><th>Part</th><th>Counted</th><th>Book at submit</th><th>Book at approval</th><th>Variance</th><th>Ledger</th></tr></thead><tbody>
            {item.lines.map((line) => <tr key={line.id}><td>{line.part_number} — {line.part_name}</td><td>{line.counted_quantity}</td><td>{line.submitted_book_quantity ?? "—"}</td><td>{line.approved_book_quantity ?? "—"}</td><td>{line.variance_quantity ?? "—"}</td><td>{line.adjustment_transaction_id ? `#${line.adjustment_transaction_id}` : "—"}</td></tr>)}
          </tbody></table></div>}
          <div className="one-hand-actions">
            {item.can_submit && <button type="button" disabled={Boolean(busy)} onClick={() => void act(item, "submit")}>Submit for approval</button>}
            {item.can_approve && <><input type="password" autoComplete="current-password" placeholder="Administrator password" value={passwords[item.id] || ""} onChange={(event) => setPasswords((current) => ({ ...current, [item.id]: event.target.value }))} />
              <button type="button" disabled={Boolean(busy) || !passwords[item.id]} onClick={() => void act(item, "approve")}>Approve and adjust ledger</button></>}
            {item.can_cancel && <button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void act(item, "cancel")}>Cancel</button>}
          </div>
        </section>;
      })}
    </ManagerShell>
  );
}
