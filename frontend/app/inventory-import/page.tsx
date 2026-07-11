"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ImportBatch } from "@/types";

export default function OpeningInventoryImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [history, setHistory] = useState<ImportBatch[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadHistory = () => api.listOpeningInventoryImports().then(setHistory).catch((err: Error) => setError(err.message));

  useEffect(() => {
    void loadHistory();
  }, []);

  const preview = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    try {
      setBusy(true);
      setError("");
      setBatch(await api.previewOpeningInventoryImport(file));
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to preview opening inventory.");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!batch) return;
    try {
      setBusy(true);
      setError("");
      setBatch(await api.commitOpeningInventoryImport(batch.id));
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to commit opening inventory.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section className="card">
        <h1>Opening inventory import</h1>
        <p className="muted">Required columns: part_number, warehouse, quantity. Optional: unit_cost and notes.</p>
        <form onSubmit={preview} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] || null)} required />
          <button type="submit" disabled={busy || !file}>{busy ? "Checking…" : "Preview and reconcile"}</button>
        </form>
        {error && <div className="error">{error}</div>}
      </section>

      {batch && (
        <section className="card">
          <h2>Reconciliation preview</h2>
          <p>{batch.valid_rows} valid rows · {batch.error_rows} error rows</p>
          {batch.errors.length > 0 && <ul>{batch.errors.map((item) => <li key={`${item.row}-${item.part_number || "blank"}`}>Row {item.row}: {item.messages.join("; ")}</li>)}</ul>}
          {batch.preview_rows.length > 0 && (
            <div style={{ overflowX: "auto" }}>
              <table>
                <thead><tr><th>Part</th><th>Warehouse</th><th>Current</th><th>Opening import</th><th>Projected</th><th>Unit cost</th></tr></thead>
                <tbody>{batch.preview_rows.map((row) => <tr key={`${row.part_id}-${row.warehouse_id}`}><td>{row.part_number} — {row.part_name}</td><td>{row.warehouse}</td><td>{row.current_quantity}</td><td>{row.quantity}</td><td>{row.projected_quantity}</td><td>{row.unit_cost}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {batch.status === "ready" && <button type="button" onClick={() => void commit()} disabled={busy} style={{ marginTop: 16 }}>Confirm opening inventory</button>}
          {batch.status === "committed" && <div className="success" style={{ marginTop: 16 }}>Opening inventory committed as inbound transactions.</div>}
        </section>
      )}

      <section className="card">
        <h2>Opening inventory history</h2>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>File</th><th>Status</th><th>Transactions</th><th>Errors</th><th>Date</th></tr></thead>
            <tbody>{history.map((item) => <tr key={item.id}><td>{item.filename}</td><td>{item.status}</td><td>{item.created_count}</td><td>{item.error_rows}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
