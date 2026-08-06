"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { getCurrentRole } from "@/lib/role";
import { AbnormalUsageRow, OrganizationCommercialReport } from "@/types";

export default function ReportsPage() {
  const [rows, setRows] = useState<AbnormalUsageRow[]>([]);
  const [commercial, setCommercial] = useState<OrganizationCommercialReport | null>(null);
  const [commercialMonths, setCommercialMonths] = useState(12);
  const [commercialPassword, setCommercialPassword] = useState("");
  const [isAdmin, setIsAdmin] = useState(false);
  const [exporting, setExporting] = useState(false);
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

  useEffect(() => {
    const admin = getCurrentRole() === "admin";
    setIsAdmin(admin);
    if (admin) {
      api.getOrganizationCommercialReport(commercialMonths)
        .then(setCommercial)
        .catch((e: Error) => setError(e.message));
    }
  }, [commercialMonths]);

  const exportCommercial = async () => {
    try {
      setExporting(true);
      setError("");
      await api.downloadOrganizationCommercialReport(commercialMonths, commercialPassword);
      setCommercialPassword("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to export commercial report.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <ManagerShell
      title="Reports"
      subtitle="Manager report center and exports."
      metrics={[
        { label: "Available Exports", value: isAdmin ? 3 : 2 },
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
        {isAdmin && commercial && (
          <section style={{ marginTop: 20 }}>
            <h4>Commercial usage</h4>
            <p className="muted">
              Monthly request evidence is historical. Limits and capacity columns show the current contract at report generation time.
            </p>
            <div className="two-col" style={{ alignItems: "end" }}>
              <label>
                History months
                <input
                  type="number"
                  min={1}
                  max={36}
                  value={commercialMonths}
                  onChange={(event) => setCommercialMonths(Math.min(36, Math.max(1, Number(event.target.value) || 1)))}
                />
              </label>
              <label>
                Confirm administrator password for CSV export
                <input type="password" minLength={10} autoComplete="current-password" value={commercialPassword} onChange={(event) => setCommercialPassword(event.target.value)} />
              </label>
            </div>
            <button type="button" onClick={() => void exportCommercial()} disabled={exporting || commercialPassword.length < 10}>
              {exporting ? "Exporting…" : "Export audited CSV"}
            </button>
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead><tr><th>UTC month</th><th>AI requests</th><th>API requests</th></tr></thead>
                <tbody>
                  {commercial.periods.map((period) => (
                    <tr key={period.period_start}>
                      <td>{period.period_start}</td>
                      <td>{period.ai_requests.toLocaleString()} / {commercial.ai_monthly_limit ?? "Unlimited"}</td>
                      <td>{period.api_requests.toLocaleString()} / {commercial.api_monthly_limit ?? "Unlimited"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
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
