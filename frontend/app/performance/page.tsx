"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { PerformanceDashboard, PerformanceScorecard } from "@/types";

function isoDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function percent(value?: number | null) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function money(value?: number | null) {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
}

function minutes(value?: number | null) {
  return value === null || value === undefined ? "—" : `${Math.round(value)} min`;
}

function QualityWarnings({ row }: { row: PerformanceScorecard }) {
  if (!row.completed_in_period) return null;
  const warnings = [];
  if (row.first_time_fix_coverage < 0.8) warnings.push(`First-time-fix coverage is ${percent(row.first_time_fix_coverage)}.`);
  if (row.repair_duration_coverage < 0.8) warnings.push(`Repair-duration coverage is ${percent(row.repair_duration_coverage)}.`);
  if (warnings.length === 0) return null;
  return <div className="muted" style={{ fontSize: 12 }}>{warnings.join(" ")} Compare quality only after coverage improves.</div>;
}

export default function PerformancePage() {
  const today = useMemo(() => new Date(), []);
  const initialFrom = useMemo(() => {
    const value = new Date(today);
    value.setUTCDate(value.getUTCDate() - 89);
    return isoDate(value);
  }, [today]);
  const [fromDate, setFromDate] = useState(initialFrom);
  const [toDate, setToDate] = useState(isoDate(today));
  const [engineerId, setEngineerId] = useState("");
  const [data, setData] = useState<PerformanceDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (from: string, to: string, selected: string) => {
    try {
      setLoading(true);
      setError("");
      setData(await api.getPerformanceScorecards({
        from_date: from,
        to_date: to,
        ...(selected ? { engineer_id: Number(selected) } : {})
      }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load performance scorecards.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(initialFrom, isoDate(today), ""); }, [initialFrom, load, today]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    void load(fromDate, toDate, engineerId);
  };

  return (
    <ManagerShell
      title={data?.viewer_scope === "self" ? "My performance" : "Employee performance"}
      subtitle="Transparent throughput, created-cohort completion, service quality, and parts-use evidence. Metrics remain separate so job complexity is not hidden inside a composite score."
      showDefaultControls={false}
      metrics={[
        { label: "Completed", value: data?.team.completed_in_period ?? "—" },
        { label: "Cohort completion", value: data ? percent(data.team.completion_rate) : "—" },
        { label: "First-time fix", value: data ? percent(data.team.first_time_fix_rate) : "—" },
        { label: "Parts units / job", value: data?.team.parts_quantity_per_completed ?? "—" }
      ]}
    >
      <form className="card" onSubmit={submit}>
        <div className="grid">
          <label>From date (UTC)<input type="date" required value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
          <label>To date (UTC)<input type="date" required value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
          {data?.can_view_team && <label>Engineer<select value={engineerId} onChange={(event) => setEngineerId(event.target.value)}><option value="">All engineers</option>{data.engineer_options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>}
        </div>
        <button type="submit" style={{ marginTop: 12 }} disabled={loading}>{loading ? "Loading..." : "Apply period"}</button>
        {error && <p className="notice notice-error" role="alert">{error}</p>}
      </form>

      {data && !data.can_view_financials && (
        <p className="notice">Your dashboard contains only your own operational evidence. Team identities, parts cost, revenue, labor cost, and contribution remain manager-only.</p>
      )}

      {data && <section className="card">
        <h3>Metric definitions</h3>
        <div className="two-col">
          {Object.entries(data.definitions).map(([code, definition]) => <div key={code}><strong>{code.replaceAll("_", " ")}</strong><p className="muted" style={{ marginTop: 4 }}>{definition}</p></div>)}
        </div>
      </section>}

      {data?.can_view_team ? (
        <section className="card">
          <div className="section-heading-row"><div><h3 style={{ margin: 0 }}>Team scorecards</h3><p className="muted" style={{ margin: "4px 0 0" }}>{data.team.active_engineers} active engineers; quality coverage appears beneath each name.</p></div><span className="status-count">{data.scorecards.length} rows</span></div>
          <div className="table-wrap" style={{ marginTop: 16 }}><table><thead><tr><th>Engineer</th><th>Received cohort</th><th>Completion</th><th>Completed</th><th>30-day throughput</th><th>FTF</th><th>Rework</th><th>Avg repair</th><th>Parts / job</th><th>Parts cost / job</th><th>Contribution</th></tr></thead>
            <tbody>{data.scorecards.map((row) => <tr key={row.engineer_id ?? "unattributed"}>
              <td><strong>{row.engineer_name}</strong>{!row.is_active && row.engineer_id && <div className="muted">Inactive</div>}<QualityWarnings row={row} /></td>
              <td>{row.cohort_completed}/{row.cohort_received}</td><td>{percent(row.completion_rate)}</td><td>{row.completed_in_period}</td><td>{row.throughput_per_30_days}</td>
              <td>{percent(row.first_time_fix_rate)}</td><td>{percent(row.rework_rate)}</td><td>{minutes(row.average_repair_minutes)}</td><td>{row.parts_quantity_per_completed}</td><td>{money(row.parts_cost_per_completed)}</td><td>{money(row.contribution)}</td>
            </tr>)}</tbody>
          </table></div>
        </section>
      ) : data && data.scorecards[0] ? (
        <section className="grid">
          {(() => {
            const row = data.scorecards[0];
            return <>
              <article className="card"><div className="muted">Created cohort completed</div><div className="metric">{row.cohort_completed}/{row.cohort_received}</div><p>{percent(row.completion_rate)} completed by the selected period end.</p></article>
              <article className="card"><div className="muted">30-day normalized throughput</div><div className="metric">{row.throughput_per_30_days}</div><p>{row.completed_in_period} actual completions in {data.days} days.</p></article>
              <article className="card"><div className="muted">First-time fix</div><div className="metric">{percent(row.first_time_fix_rate)}</div><p>{row.first_time_fix_labeled}/{row.completed_in_period} completed jobs labeled.</p></article>
              <article className="card"><div className="muted">Rework</div><div className="metric">{percent(row.rework_rate)}</div><p>Average repair duration: {minutes(row.average_repair_minutes)}.</p></article>
              <article className="card"><div className="muted">Parts quantity / completed job</div><div className="metric">{row.parts_quantity_per_completed}</div><p>{row.parts_quantity} units across {row.parts_usage_work_orders} jobs with recorded usage.</p></article>
              <article className="card"><div className="muted">Evidence coverage</div><div className="metric">{percent(Math.min(row.first_time_fix_coverage, row.repair_duration_coverage))}</div><QualityWarnings row={row} /></article>
            </>;
          })()}
        </section>
      ) : null}
    </ManagerShell>
  );
}
