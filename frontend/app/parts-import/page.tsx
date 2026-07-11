"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { ImportBatch } from "@/types";

export default function PartsImportPage() {
  const [file, setFile] = useState<File | null>(null);
  const [batch, setBatch] = useState<ImportBatch | null>(null);
  const [history, setHistory] = useState<ImportBatch[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadHistory = () => api.listPartsImports().then(setHistory).catch((err: Error) => setError(err.message));

  useEffect(() => {
    void loadHistory();
  }, []);

  const preview = async (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    try {
      setBusy(true);
      setError("");
      setBatch(await api.previewPartsImport(file));
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to preview file.");
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!batch) return;
    try {
      setBusy(true);
      setError("");
      setBatch(await api.commitPartsImport(batch.id));
      await loadHistory();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to import parts.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section className="card">
        <h1>Parts List import</h1>
        <p className="muted">Upload an XLSX file for validation. Nothing is written to the Parts catalog until you confirm.</p>
        <form onSubmit={preview} style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
          <input type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" onChange={(event) => setFile(event.target.files?.[0] || null)} required />
          <button type="submit" disabled={busy || !file}>{busy ? "Checking…" : "Preview file"}</button>
        </form>
        <p className="muted">Required columns: part_number, name. Optional columns may appear in any order.</p>
        {error && <div className="error">{error}</div>}
      </section>

      {batch && (
        <section className="card">
          <h2>Preview: {batch.filename}</h2>
          <div className="metrics-grid">
            <div><strong>{batch.total_rows}</strong><div className="muted">Rows</div></div>
            <div><strong>{batch.valid_rows}</strong><div className="muted">Valid</div></div>
            <div><strong>{batch.error_rows}</strong><div className="muted">Errors</div></div>
            <div><strong>{batch.created_count}</strong><div className="muted">New</div></div>
            <div><strong>{batch.updated_count}</strong><div className="muted">Updates</div></div>
          </div>
          {batch.errors.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <h3>Validation errors</h3>
              <ul>{batch.errors.map((item) => <li key={`${item.row}-${item.part_number || "blank"}`}>Row {item.row}: {item.messages.join("; ")}</li>)}</ul>
            </div>
          )}
          {batch.preview_rows.length > 0 && (
            <div style={{ overflowX: "auto", marginTop: 16 }}>
              <table>
                <thead><tr><th>Row</th><th>Item number</th><th>Name</th><th>Category</th><th>Barcode</th><th>Tracking</th><th>Unit</th><th>Cost</th></tr></thead>
                <tbody>{batch.preview_rows.map((row) => <tr key={String(row.row_number)}><td>{row.row_number}</td><td>{row.part_number}</td><td>{row.name}</td><td>{row.category}</td><td>{row.barcode}</td><td>{row.tracking_mode}</td><td>{row.unit}</td><td>{row.default_cost}</td></tr>)}</tbody>
              </table>
            </div>
          )}
          {batch.status === "ready" && <button type="button" onClick={() => void commit()} disabled={busy} style={{ marginTop: 16 }}>Confirm import</button>}
          {batch.status === "committed" && <div className="success" style={{ marginTop: 16 }}>Import committed successfully.</div>}
        </section>
      )}

      <section className="card">
        <h2>Import history</h2>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>File</th><th>Status</th><th>Rows</th><th>Created</th><th>Updated</th><th>Date</th></tr></thead>
            <tbody>{history.map((item) => <tr key={item.id}><td>{item.filename}</td><td>{item.status}</td><td>{item.total_rows}</td><td>{item.created_count}</td><td>{item.updated_count}</td><td>{new Date(item.created_at).toLocaleString()}</td></tr>)}</tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
