"use client";

import { useCallback, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { PlatformOperationsHistory, PlatformOperationsSummary } from "@/types";

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
  const [history, setHistory] = useState<PlatformOperationsHistory | null>(null);
  const [historyHours, setHistoryHours] = useState(24);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [recoveryReason, setRecoveryReason] = useState("");
  const [accountPassword, setAccountPassword] = useState("");
  const [recovering, setRecovering] = useState(false);
  const [recoveryNotice, setRecoveryNotice] = useState("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const bucketMinutes = historyHours <= 24 ? 5 : historyHours <= 72 ? 15 : 60;
      const [summary, historical] = await Promise.all([
        api.getPlatformOperationsSummary(),
        api.getPlatformOperationsHistory(historyHours, bucketMinutes)
      ]);
      setData(summary);
      setHistory(historical);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load platform operations.");
    } finally {
      setLoading(false);
    }
  }, [historyHours]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30_000);
    return () => window.clearInterval(timer);
  }, [load]);

  const recoverStaleDeliveries = async () => {
    if (recoveryReason.trim().length < 3 || !accountPassword) {
      setError("Enter an operational reason and your current account password.");
      return;
    }
    try {
      setRecovering(true);
      setError("");
      setRecoveryNotice("");
      const result = await api.recoverStaleIntegrationDeliveries({
        account_password: accountPassword,
        reason: recoveryReason.trim(),
        max_items: 100
      });
      setRecoveryNotice(
        result.recovered_count > 0
          ? `${result.recovered_count} interrupted deliveries across ${result.organization_count} organizations were safely queued for retry.`
          : "No delivery still met the stale-processing cutoff. No queue state was changed."
      );
      setAccountPassword("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to recover stale deliveries.");
    } finally {
      setRecovering(false);
    }
  };

  return (
    <ManagerShell
      title="Platform Operations"
      subtitle="Live process, queue, billing, and data-protection evidence for SLA operations. Refreshes every 30 seconds."
      metrics={[
        { label: "Overall", value: data?.status ?? "Loading" },
        { label: "Uptime", value: data ? formatUptime(data.uptime_seconds) : "-" },
        { label: "5m p95", value: data ? `${data.requests.p95_duration_ms.toFixed(1)} ms` : "-" },
        { label: "5m 5xx", value: data ? `${(data.requests.server_error_rate * 100).toFixed(1)}%` : "-" },
        { label: "Observed buckets", value: history ? `${(history.bucket_coverage_rate * 100).toFixed(1)}%` : "-" }
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

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "center", flexWrap: "wrap" }}>
          <div>
            <h3>Observed service history</h3>
            <p className="muted">
              Self-reported samples persist across restarts. Missing buckets are visible, but external synthetic probes remain the authoritative SLA source.
            </p>
          </div>
          <select
            aria-label="Operations history period"
            value={historyHours}
            onChange={(event) => setHistoryHours(Number(event.target.value))}
          >
            <option value={6}>Last 6 hours</option>
            <option value={24}>Last 24 hours</option>
            <option value={72}>Last 3 days</option>
            <option value={168}>Last 7 days</option>
          </select>
        </div>
        {history && (
          <>
            <div className="pilot-metric-grid" style={{ marginTop: 12 }}>
              <div className={`pilot-metric${history.bucket_coverage_rate < 0.9 ? " pilot-metric--alert" : ""}`}>
                <div className="muted">Bucket coverage</div>
                <div className="metric">{(history.bucket_coverage_rate * 100).toFixed(1)}%</div>
                <small>{history.buckets_present} of {history.expected_buckets} expected</small>
              </div>
              <div className="pilot-metric">
                <div className="muted">Instances observed</div>
                <div className="metric">{history.instances_seen}</div>
                <small>{history.sample_count} retained samples</small>
              </div>
              <div className="pilot-metric">
                <div className="muted">Latest sample</div>
                <div style={{ fontWeight: 700 }}>{formatTimestamp(history.latest_sample_at)}</div>
                <small>{history.bucket_minutes}-minute buckets</small>
              </div>
            </div>
            {history.truncated && <p className="notice notice-error">The configured query cap truncated older samples in this period.</p>}
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead><tr><th>Bucket</th><th>Instances</th><th>Requests</th><th>5xx</th><th>p95</th><th>Worker/schema risk</th></tr></thead>
                <tbody>
                  {history.points.length === 0 ? (
                    <tr><td colSpan={6}>No retained samples yet. The first sample is written when the API starts.</td></tr>
                  ) : history.points.slice(-12).reverse().map((point) => (
                    <tr key={point.bucket_at}>
                      <td>{formatTimestamp(point.bucket_at)}</td>
                      <td>{point.instances_reporting}</td>
                      <td>{point.request_total}</td>
                      <td>{point.server_errors} ({(point.server_error_rate * 100).toFixed(1)}%)</td>
                      <td>{point.p95_duration_ms.toFixed(1)} ms</td>
                      <td>{point.worker_degraded_samples} / {point.schema_not_ready_samples}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      {data && (
        <>
          <section className="card">
            <h3>Background workers</h3>
            <div className="table-wrap">
              <table>
                <thead><tr><th>Worker</th><th>Status</th><th>Lease</th><th>Next run</th><th>Last success / standby</th><th>Last result</th><th>Last error</th></tr></thead>
                <tbody>
                  {data.workers.map((worker) => (
                    <tr key={worker.name}>
                      <td><code>{worker.name}</code></td>
                      <td>{worker.status}</td>
                      <td>{worker.lease_generation ? `#${worker.lease_generation} until ${formatTimestamp(worker.lease_expires_at)}` : "-"}</td>
                      <td>{worker.run_started_at ? `Running since ${formatTimestamp(worker.run_started_at)}` : formatTimestamp(worker.next_run_at)}</td>
                      <td>{formatTimestamp(worker.status === "standby" ? worker.last_standby_at : worker.last_success_at)}</td>
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
            <h3>Interrupted delivery recovery</h3>
            <p className="muted">
              Requeue only Webhook attempts that have remained in processing beyond the configured stale cutoff.
              Downstream systems must continue deduplicating the stable delivery idempotency key.
            </p>
            <div className="two-col">
              <input
                value={recoveryReason}
                onChange={(event) => setRecoveryReason(event.target.value)}
                placeholder="Operational recovery reason"
                maxLength={500}
              />
              <input
                type="password"
                autoComplete="current-password"
                value={accountPassword}
                onChange={(event) => setAccountPassword(event.target.value)}
                placeholder="Current account password"
                maxLength={128}
              />
            </div>
            <button
              type="button"
              disabled={recovering || data.integration_queue.stale_processing === 0}
              onClick={() => void recoverStaleDeliveries()}
              style={{ marginTop: 12 }}
            >
              {recovering ? "Recovering..." : `Requeue stale deliveries (${data.integration_queue.stale_processing})`}
            </button>
            {recoveryNotice && <p className="notice" style={{ marginTop: 12 }}>{recoveryNotice}</p>}
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
