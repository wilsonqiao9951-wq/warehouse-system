"use client";

import { useCallback, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { PlatformOperationsSummary } from "@/types";

function formatTimestamp(value?: string | null): string {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(new Date(value));
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86_400);
  const hours = Math.floor((seconds % 86_400) / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  return `${days}d ${hours}h ${minutes}m`;
}

export default function PlatformOperationsPage() {
  const [data, setData] = useState<PlatformOperationsSummary | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      setData(await api.getPlatformOperationsSummary());
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load platform operations.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  return (
    <ManagerShell
      title="Platform Operations"
      subtitle="Live process, queue, billing, and data-protection evidence for SLA operations. Refreshes every 30 seconds."
      metrics={[
        { label: "Overall", value: data?.status ?? "Loading" },
        { label: "Uptime", value: data ? formatUptime(data.uptime_seconds) : "-" },
        { label: "5m p95", value: data ? `${data.requests.p95_duration_ms.toFixed(1)} ms` : "-" },
        { label: "5m 5xx", value: data ? `${(data.requests.server_error_rate * 100).toFixed(1)}%` : "-" }
      ]}
    >
      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <h3>Core readiness</h3>
            <p className="muted">Checked {formatTimestamp(data?.checked_at)}</p>
          </div>
          <button type="button" className="secondary" disabled={loading} onClick={() => void load()}>
            {loading ? "Refreshing..." : "Refresh now"}
          </button>
        </div>
        {error && <p className="notice notice-error">{error}</p>}
        {data && (
          <div className="pilot-metric-grid">
            <div className={`pilot-metric${data.database_status !== "ok" ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Database</div>
              <div className="metric" style={{ fontSize: 20 }}>{data.database_status}</div>
              <small>{data.database_latency_ms.toFixed(2)} ms</small>
            </div>
            <div className={`pilot-metric${data.schema_status !== "ok" ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Schema</div>
              <div className="metric" style={{ fontSize: 20 }}>{data.schema_status}</div>
              <small>{data.schema_revision}</small>
            </div>
            <div className={`pilot-metric${data.integration_queue.outbound_due > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Webhook due</div>
              <div className="metric">{data.integration_queue.outbound_due}</div>
              <small>{data.integration_queue.outbound_pending} pending</small>
            </div>
            <div className={`pilot-metric${data.integration_queue.outbound_failed > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Webhook failed</div>
              <div className="metric">{data.integration_queue.outbound_failed}</div>
              <small>{data.integration_queue.stale_processing} stuck processing</small>
            </div>
            <div className={`pilot-metric${data.open_critical_billing_notices > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Critical billing</div>
              <div className="metric">{data.open_critical_billing_notices}</div>
            </div>
            <div className={`pilot-metric${data.data_protection.organizations_without_recent_backup > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Backup overdue</div>
              <div className="metric">{data.data_protection.organizations_without_recent_backup}</div>
              <small>of {data.data_protection.active_organizations} active customers</small>
            </div>
          </div>
        )}
      </section>

      {data && (
        <>
          <section className="card">
            <h3>Background workers</h3>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Worker</th><th>Status</th><th>Last success</th><th>Last result</th><th>Last error</th></tr></thead>
                <tbody>
                  {data.workers.map((worker) => (
                    <tr key={worker.name}>
                      <td><code>{worker.name}</code></td>
                      <td>{worker.status}</td>
                      <td>{formatTimestamp(worker.last_success_at)}</td>
                      <td>{worker.last_result_count ?? "-"}</td>
                      <td>{worker.last_error_type || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="card">
            <h3>Active operational alerts</h3>
            {data.alerts.length === 0 ? (
              <div className="empty-state">No configured operational threshold is currently breached.</div>
            ) : (
              <div style={{ display: "grid", gap: 10 }}>
                {data.alerts.map((alert) => (
                  <div key={alert.code} className={`notice${alert.severity === "critical" ? " notice-error" : ""}`}>
                    <strong>{alert.severity.toUpperCase()}</strong> - {alert.message} ({alert.count})
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card">
            <h3>Request window</h3>
            <div className="table-wrap">
              <table>
                <tbody>
                  <tr><th>Window</th><td>{data.requests.window_seconds} seconds</td></tr>
                  <tr><th>Requests</th><td>{data.requests.total}</td></tr>
                  <tr><th>Server errors</th><td>{data.requests.server_errors}</td></tr>
                  <tr><th>Average latency</th><td>{data.requests.average_duration_ms.toFixed(2)} ms</td></tr>
                  <tr><th>p95 latency</th><td>{data.requests.p95_duration_ms.toFixed(2)} ms</td></tr>
                  <tr><th>Restore plans with conflicts</th><td>{data.data_protection.restore_plans_with_conflicts}</td></tr>
                </tbody>
              </table>
            </div>
          </section>
        </>
      )}
    </ManagerShell>
  );
}
