"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { AbnormalUsageRow } from "@/types";

export default function ReportsPage() {
  const [rows, setRows] = useState<AbnormalUsageRow[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getAbnormalUsage()
      .then((r) => {
        setRows(r);
        setError("");
      })
      .catch((e: Error) => {
        setRows([]);
        setError(e.message || "Failed to load abnormal usage.");
      });
  }, []);

  return (
    <ManagerShell
      title="Reports"
      subtitle="Manager report center and exports."
      metrics={[
        { label: "Available Exports", value: 2 },
        { label: "Abnormal Usage Alerts", value: rows.length }
      ]}
    >
      <section className="card">
        <div className="two-col">
          <a className="nav-item" href="http://127.0.0.1:8000/api/export/work-orders.xlsx" target="_blank" rel="noreferrer">
            Export Work Orders
          </a>
          <a className="nav-item" href="http://127.0.0.1:8000/api/export/inventory.xlsx" target="_blank" rel="noreferrer">
            Export Inventory
          </a>
        </div>
        <h4>Abnormal usage</h4>
        {error && <p className="notice notice-error">{error}</p>}
        <p className="muted" style={{ fontSize: 14 }}>
          Rows below flag jobs where parts cost is high relative to revenue — review before billing close.
        </p>
        <div className="abnormal-mobile-cards">
          {rows.length === 0 && !error ? <div className="empty-state">No abnormal usage rows.</div> : null}
          {rows.map((r) => (
            <div key={r.work_order_id} className="abnormal-card">
              <div>
                <strong>{r.ticket_number}</strong>{" "}
                <span className="muted" style={{ fontSize: 13 }}>
                  severity {r.severity}
                </span>
              </div>
              <div style={{ marginTop: 6 }}>
                <span className="danger" style={{ fontWeight: 700 }}>
                  Parts ${r.parts_cost.toFixed(2)}
                </span>
                <span className="muted"> vs revenue ${r.revenue.toFixed(2)}</span>
              </div>
              <div className="abnormal-card__reason">{r.reason}</div>
            </div>
          ))}
        </div>
        <div className="table-wrap abnormal-table-desktop">
          <table>
            <thead>
              <tr>
                <th>WO</th>
                <th>Parts Cost</th>
                <th>Revenue</th>
                <th>Reason</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.work_order_id}>
                  <td>{r.ticket_number}</td>
                  <td className="danger">${r.parts_cost.toFixed(2)}</td>
                  <td>${r.revenue.toFixed(2)}</td>
                  <td>{r.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </ManagerShell>
  );
}
