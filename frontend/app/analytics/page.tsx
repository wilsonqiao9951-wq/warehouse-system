"use client";

import { FormEvent, useEffect, useState } from "react";
import AnalyticsTrendChart from "@/components/analytics-trend-chart";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { AnalyticsKpi, EnterpriseAnalytics } from "@/types";

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function defaultDates() {
  const to = new Date();
  const from = new Date(to);
  from.setUTCDate(from.getUTCDate() - 89);
  return { from_date: isoDate(from), to_date: isoDate(to) };
}

function formatMetric(metric: AnalyticsKpi): string {
  if (metric.value == null) return "—";
  if (metric.unit === "percent") return `${metric.value.toFixed(1)}%`;
  if (metric.unit === "currency") return metric.value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (metric.unit === "hours") return `${metric.value.toFixed(1)}h`;
  return metric.value.toLocaleString();
}

function percent(value?: number | null): string {
  return value == null ? "—" : `${(value * 100).toFixed(1)}%`;
}

function minutes(value?: number | null): string {
  return value == null ? "—" : `${Math.round(value)} min`;
}

function money(value: number): string {
  return value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

export default function AnalyticsPage() {
  const [filters, setFilters] = useState(() => ({ ...defaultDates(), engineer_id: "", job_type: "" }));
  const [data, setData] = useState<EnterpriseAnalytics | null>(null);
  const [canExport, setCanExport] = useState(false);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const load = async (next = filters) => {
    try {
      setBusy(true);
      setError("");
      const result = await api.getEnterpriseAnalytics({
        from_date: next.from_date,
        to_date: next.to_date,
        engineer_id: next.engineer_id ? Number(next.engineer_id) : undefined,
        job_type: next.job_type || undefined
      });
      setData(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load enterprise analytics.");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void load(filters);
    api.getMyPermissions().then((matrix) => setCanExport(matrix.effective_permissions.includes("reports.export"))).catch(() => setCanExport(false));
    // Initial filters are intentionally fixed for this mount.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    setNotice("");
    void load();
  };

  const setRange = (days: number) => {
    const to = new Date();
    const from = new Date(to);
    from.setUTCDate(from.getUTCDate() - days + 1);
    const next = { ...filters, from_date: isoDate(from), to_date: isoDate(to) };
    setFilters(next);
    void load(next);
  };

  const exportCsv = async () => {
    try {
      setExporting(true);
      setError("");
      const receipt = await api.downloadEnterpriseAnalytics({
        from_date: filters.from_date,
        to_date: filters.to_date,
        engineer_id: filters.engineer_id ? Number(filters.engineer_id) : undefined,
        job_type: filters.job_type || undefined
      }, password);
      setPassword("");
      setNotice(`Exported ${receipt.recordCount ?? "filtered"} completed work orders. SHA-256 ${receipt.sha256 || "returned in response headers"}.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to export analytics.");
    } finally {
      setExporting(false);
    }
  };

  const latestSource = data ? [
    data.source_freshness.work_orders_updated_at,
    data.source_freshness.work_order_parts_updated_at,
    data.source_freshness.inventory_transactions_updated_at
  ].filter(Boolean).sort().at(-1) : null;

  return (
    <ManagerShell
      title="Enterprise analytics"
      subtitle="Operational outcomes, service quality, financial contribution, and regional inventory from tenant-owned source records."
      metrics={[
        { label: "Period", value: data ? `${data.period.days} days` : "—" },
        { label: "Grain", value: data?.period.grain || "—" },
        { label: "Generated", value: data ? new Date(data.generated_at).toLocaleTimeString() : "—" }
      ]}
    >
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <form className="card" onSubmit={applyFilters}>
        <h3>Operating review filters</h3>
        <div className="grid">
          <label>From (UTC)<input type="date" required value={filters.from_date} onChange={(event) => setFilters((value) => ({ ...value, from_date: event.target.value }))} /></label>
          <label>To (UTC)<input type="date" required value={filters.to_date} onChange={(event) => setFilters((value) => ({ ...value, to_date: event.target.value }))} /></label>
          <label>Engineer<select value={filters.engineer_id} onChange={(event) => setFilters((value) => ({ ...value, engineer_id: event.target.value }))}><option value="">All engineers</option>{data?.filters.engineers.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label>Job type<select value={filters.job_type} onChange={(event) => setFilters((value) => ({ ...value, job_type: event.target.value }))}><option value="">All job types</option>{data?.filters.job_types.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          <button type="submit" disabled={busy}>{busy ? "Refreshing…" : "Apply filters"}</button>
          <button type="button" className="secondary" onClick={() => setRange(30)}>30 days</button>
          <button type="button" className="secondary" onClick={() => setRange(90)}>90 days</button>
          <button type="button" className="secondary" onClick={() => setRange(365)}>365 days</button>
        </div>
      </form>

      {data && <>
        <section className="grid">
          {data.kpis.map((metric) => <article className="card" key={metric.code} title={metric.definition}>
            <div className="muted">{metric.label}</div>
            <div className="metric">{formatMetric(metric)}</div>
            <div className="muted" style={{ fontSize: 12 }}>
              Previous: {metric.previous_value == null ? "—" : formatMetric({ ...metric, value: metric.previous_value })}
              {metric.delta_percent != null ? ` · ${metric.delta_percent >= 0 ? "+" : ""}${metric.delta_percent.toFixed(1)}%` : ""}
            </div>
          </article>)}
        </section>

        <section className="card">
          <h3>Created vs completed</h3>
          <p className="muted">UTC {data.period.grain} buckets. Hover KPI cards for exact definitions.</p>
          <AnalyticsTrendChart data={data.trend} />
        </section>

        <section className="two-col">
          <div className="card">
            <h3>Service quality coverage</h3>
            <div className="grid">
              <div><div className="muted">First-time fix</div><div className="metric">{percent(data.data_quality.first_time_fix_coverage)}</div><small>{data.data_quality.first_time_fix_labeled}/{data.data_quality.completed_work_orders} completed jobs labeled</small></div>
              <div><div className="muted">Repair duration</div><div className="metric">{percent(data.data_quality.repair_duration_coverage)}</div><small>{data.data_quality.repair_duration_labeled}/{data.data_quality.completed_work_orders} completed jobs labeled</small></div>
              <div><div className="muted">Engineer attribution</div><div className="metric">{percent(data.data_quality.engineer_attribution_coverage)}</div><small>{data.data_quality.engineer_attributed}/{data.data_quality.completed_work_orders} completed jobs attributed</small></div>
            </div>
            {data.data_quality.warnings.map((warning) => <p key={warning} className="notice notice-error">{warning}</p>)}
          </div>
          <div className="card">
            <h3>Source freshness</h3>
            <p><strong>Latest source update:</strong> {latestSource ? new Date(latestSource).toLocaleString() : "No source rows"}</p>
            <p className="muted">Work orders, recorded work-order parts, and inventory ledger. Dashboard responses are live, tenant scoped, and not cached.</p>
            <p className="muted">First-time-fix rates exclude unlabeled completed work orders; coverage is shown beside the result.</p>
          </div>
        </section>

        <section className="card">
          <h3>Engineer outcomes</h3>
          <div className="table-wrap"><table><thead><tr><th>Engineer</th><th>Completed</th><th>FTF rate</th><th>FTF coverage</th><th>Rework</th><th>Avg duration</th><th>Revenue</th><th>Parts</th><th>Contribution</th></tr></thead>
            <tbody>{data.engineers.map((row) => <tr key={row.engineer_id ?? "unattributed"}><td>{row.engineer_name}</td><td>{row.completed_count}</td><td>{percent(row.first_time_fix_rate)}</td><td>{percent(row.first_time_fix_coverage)}</td><td>{percent(row.rework_rate)}</td><td>{minutes(row.average_repair_minutes)}</td><td>{money(row.revenue)}</td><td>{money(row.parts_cost)}</td><td>{money(row.contribution)}</td></tr>)}</tbody>
          </table></div>
        </section>

        <section className="two-col">
          <div className="card">
            <h3>Job type performance</h3>
            <div className="table-wrap"><table><thead><tr><th>Job type</th><th>Completed</th><th>FTF</th><th>Rework</th><th>Avg duration</th><th>Contribution</th></tr></thead>
              <tbody>{data.job_types.map((row) => <tr key={row.job_type}><td>{row.job_type}</td><td>{row.completed_count}</td><td>{percent(row.first_time_fix_rate)}</td><td>{percent(row.rework_rate)}</td><td>{minutes(row.average_repair_minutes)}</td><td>{money(row.contribution)}</td></tr>)}</tbody>
            </table></div>
          </div>
          <div className="card">
            <h3>Regional inventory and consumption</h3>
            <p className="muted">Inventory is current ledger stock. Consumption uses parts on work orders completed in the selected period.</p>
            <div className="table-wrap"><table><thead><tr><th>Region</th><th>Stock qty</th><th>Stock value</th><th>Low stock</th><th>Consumed qty</th><th>Consumed cost</th></tr></thead>
              <tbody>{data.regions.map((row) => <tr key={row.region_id}><td><strong>{row.region_code}</strong><div className="muted">{row.region_name} · {row.warehouse_count} warehouses</div></td><td>{row.stock_quantity}</td><td>{money(row.stock_value)}</td><td className={row.low_stock_sku_count ? "danger" : ""}>{row.low_stock_sku_count}</td><td>{row.consumed_quantity}</td><td>{money(row.consumed_parts_cost)}</td></tr>)}</tbody>
            </table></div>
          </div>
        </section>

        {canExport && <section className="card">
          <h3>Audited completed-work-order export</h3>
          <p className="muted">Exports the filtered completed-work-order grain behind this dashboard. The response includes row-count and SHA-256 evidence.</p>
          <div className="two-col" style={{ alignItems: "end" }}><label>Confirm account password<input type="password" minLength={10} maxLength={128} autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label><button type="button" disabled={exporting || password.length < 10} onClick={() => void exportCsv()}>{exporting ? "Exporting…" : "Export audited CSV"}</button></div>
        </section>}
      </>}
    </ManagerShell>
  );
}
