"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import {
  InventoryReconciliationPage,
  InventoryReconciliationSeverity,
  InventoryReconciliationSource
} from "@/types";

const SOURCE_LABELS: Record<InventoryReconciliationSource, string> = {
  replenishment: "Replenishment",
  vehicle_return: "Vehicle return",
  inventory_count: "Inventory count"
};

function formatTimestamp(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(normalized));
}

export default function InventoryReconciliationPageView() {
  const [source, setSource] = useState<"" | InventoryReconciliationSource>("");
  const [severity, setSeverity] = useState<"" | InventoryReconciliationSeverity>("");
  const [data, setData] = useState<InventoryReconciliationPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (
    nextSource: "" | InventoryReconciliationSource,
    nextSeverity: "" | InventoryReconciliationSeverity
  ) => {
    try {
      setLoading(true);
      setError("");
      setData(await api.getInventoryReconciliationExceptions({
        ...(nextSource ? { source: nextSource } : {}),
        ...(nextSeverity ? { severity: nextSeverity } : {}),
        limit: 200
      }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load inventory exceptions.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load("", "");
  }, [load]);

  const applyFilters = () => void load(source, severity);
  const resetFilters = () => {
    setSource("");
    setSeverity("");
    void load("", "");
  };

  return (
    <ManagerShell
      title="Inventory Reconciliation"
      subtitle="Find pending physical-count differences and custody records whose status no longer agrees with their immutable inventory movements."
      showDefaultControls={false}
      metrics={[
        { label: "Open Exceptions", value: data?.total ?? "-" },
        { label: "Critical", value: data?.critical ?? "-" },
        { label: "Pending Variances", value: data?.warning ?? "-" },
        { label: "Inventory Counts", value: data?.inventory_count ?? "-" }
      ]}
    >
      <section className="card">
        <div className="two-col">
          <label>
            Workflow source
            <select value={source} onChange={(event) => setSource(event.target.value as typeof source)}>
              <option value="">All workflow sources</option>
              <option value="replenishment">Replenishment</option>
              <option value="vehicle_return">Vehicle return</option>
              <option value="inventory_count">Inventory count</option>
            </select>
          </label>
          <label>
            Severity
            <select value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)}>
              <option value="">All severities</option>
              <option value="critical">Critical evidence mismatch</option>
              <option value="warning">Pending review</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button type="button" onClick={applyFilters} disabled={loading}>Apply filters</button>
          <button type="button" className="secondary" onClick={resetFilters} disabled={loading}>Reset</button>
          <button type="button" className="secondary" onClick={() => void load(source, severity)} disabled={loading}>
            {loading ? "Refreshing..." : "Refresh evidence"}
          </button>
        </div>
      </section>

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
          <h3>Exception queue</h3>
          <span className="muted">{data?.items.length ?? 0} shown</span>
        </div>
        <p className="muted">
          This queue is read-only. Use the linked authenticated workflow to approve, reconcile, or investigate an exception; the queue never posts stock by itself.
        </p>
        {error && <p className="notice notice-error">{error}</p>}
        {data?.truncated && (
          <p className="notice notice-warn">
            Results are bounded for operational safety. Narrow the source or severity filter to inspect all matching candidates.
          </p>
        )}
        {!loading && data?.items.length === 0 && (
          <div className="empty-state">No reconciliation exceptions match these filters.</div>
        )}
        <div style={{ display: "grid", gap: 12 }}>
          {data?.items.map((item) => (
            <article
              className="job-card"
              key={item.id}
              style={{ borderColor: item.severity === "critical" ? "#fca5a5" : "#fcd34d" }}
            >
              <div className="section-heading-row">
                <div>
                  <strong>{item.title}</strong>
                  <div className="muted">
                    {SOURCE_LABELS[item.source]} · {item.status} · Updated {formatTimestamp(item.updated_at)}
                  </div>
                </div>
                <span className={`status-pill ${item.severity === "critical" ? "status-pill--cancelled" : "status-pill--picking"}`}>
                  {item.severity}
                </span>
              </div>
              <p>{item.detail}</p>
              <div className="two-col">
                <div>
                  <span className="muted">Part</span>
                  <div><strong>{item.part_number}</strong> — {item.part_name}</div>
                </div>
                <div>
                  <span className="muted">Warehouse route</span>
                  <div>{item.warehouse_label || "Not recorded"}</div>
                </div>
                <div>
                  <span className="muted">Quantity / variance</span>
                  <div>
                    {item.quantity ?? "-"}
                    {item.variance_quantity !== null && item.variance_quantity !== undefined
                      ? ` · variance ${item.variance_quantity > 0 ? "+" : ""}${item.variance_quantity}`
                      : ""}
                  </div>
                </div>
                <div>
                  <span className="muted">Ledger evidence</span>
                  <div>
                    {item.shipment_transaction_id ? `Ship #${item.shipment_transaction_id} ` : ""}
                    {item.receipt_transaction_id ? `Receive #${item.receipt_transaction_id} ` : ""}
                    {item.adjustment_transaction_id ? `Adjust #${item.adjustment_transaction_id}` : ""}
                    {!item.shipment_transaction_id && !item.receipt_transaction_id && !item.adjustment_transaction_id ? "Missing" : ""}
                  </div>
                </div>
              </div>
              <div className="one-hand-actions" style={{ marginTop: 12 }}>
                <Link className="nav-item" href={item.action_route}>{item.action_label}</Link>
                <Link className="nav-item" href="/inventory-ledger">Open inventory ledger</Link>
              </div>
            </article>
          ))}
        </div>
      </section>
    </ManagerShell>
  );
}
