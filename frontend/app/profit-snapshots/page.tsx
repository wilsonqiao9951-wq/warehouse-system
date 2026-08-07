"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { ProfitSnapshotDashboard, ProfitSnapshotRanking } from "@/types";

function isoDate(value: Date) {
  return value.toISOString().slice(0, 10);
}

function money(value: number) {
  return new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(value);
}

function percent(value?: number | null) {
  return value === null || value === undefined ? "—" : `${(value * 100).toFixed(1)}%`;
}

function RankingTable({ title, rows }: { title: string; rows: ProfitSnapshotRanking[] }) {
  return (
    <div className="card" style={{ marginBottom: 0 }}>
      <h3>{title}</h3>
      {rows.length === 0 ? <div className="empty-state">No captured profit evidence.</div> : (
        <div className="table-wrap"><table><thead><tr><th>Rank</th><th>Name</th><th>Jobs</th><th>Revenue</th><th>Profit</th><th>Margin</th></tr></thead>
          <tbody>{rows.map((row, index) => (
            <tr key={`${row.dimension}-${row.key}-${row.label}`}>
              <td>#{index + 1}</td><td><strong>{row.label}</strong></td><td>{row.completed_count}</td>
              <td>{money(row.revenue)}</td><td className={row.profit < 0 ? "danger" : ""}>{money(row.profit)}</td><td>{percent(row.margin_rate)}</td>
            </tr>
          ))}</tbody>
        </table></div>
      )}
    </div>
  );
}

export default function ProfitSnapshotsPage() {
  const today = useMemo(() => new Date(), []);
  const initialFrom = useMemo(() => {
    const value = new Date(today);
    value.setUTCDate(value.getUTCDate() - 89);
    return isoDate(value);
  }, [today]);
  const [fromDate, setFromDate] = useState(initialFrom);
  const [toDate, setToDate] = useState(isoDate(today));
  const [data, setData] = useState<ProfitSnapshotDashboard | null>(null);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [backfilling, setBackfilling] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async (from: string, to: string) => {
    try {
      setLoading(true);
      setError("");
      setData(await api.getProfitSnapshots({ from_date: from, to_date: to, ranking_limit: 50 }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load profit snapshots.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(initialFrom, isoDate(today)); }, [initialFrom, load, today]);

  const backfill = async () => {
    if (!password) {
      setError("Enter your current account password before creating historical financial snapshots.");
      return;
    }
    try {
      setBackfilling(true);
      setError("");
      setMessage("");
      let after: number | undefined;
      let created = 0;
      let existing = 0;
      let conflicts = 0;
      do {
        const result = await api.backfillProfitSnapshots({
          from_date: fromDate,
          to_date: toDate,
          ...(after ? { after_work_order_id: after } : {}),
          limit: 1000,
          account_password: password
        });
        created += result.created;
        existing += result.existing;
        conflicts += result.conflicts;
        after = result.next_after_work_order_id || undefined;
      } while (after);
      setPassword("");
      setMessage(`Snapshot refresh finished: ${created} created, ${existing} already current, ${conflicts} source conflicts retained for review.`);
      await load(fromDate, toDate);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to backfill profit snapshots.");
    } finally {
      setBackfilling(false);
    }
  };

  const maxProfit = Math.max(1, ...(data?.daily.map((row) => Math.abs(row.profit)) || [1]));
  return (
    <ManagerShell
      title="Profit Snapshots"
      subtitle="Daily financial evidence captured when a work order becomes locked, with explicit historical coverage and attribution."
      showDefaultControls={false}
      metrics={[
        { label: "Captured Jobs", value: data?.summary.snapshot_count ?? "-" },
        { label: "Coverage", value: data ? percent(data.summary.coverage_rate) : "-" },
        { label: "Revenue", value: data ? money(data.summary.revenue) : "-" },
        { label: "Profit", value: data ? money(data.summary.profit) : "-" }
      ]}
    >
      <section className="card">
        <div className="two-col">
          <label>From date<input type="date" value={fromDate} onChange={(event) => setFromDate(event.target.value)} /></label>
          <label>To date<input type="date" value={toDate} onChange={(event) => setToDate(event.target.value)} /></label>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button type="button" disabled={loading} onClick={() => void load(fromDate, toDate)}>{loading ? "Loading..." : "Apply period"}</button>
          <button type="button" className="secondary" disabled={loading} onClick={() => void load(fromDate, toDate)}>Refresh evidence</button>
        </div>
        {error && <p className="notice notice-error">{error}</p>}
        {message && <p className="notice notice-success">{message}</p>}
      </section>

      {data && data.summary.missing_snapshot_count > 0 && (
        <section className="card">
          <h3>Historical coverage required</h3>
          <p className="notice notice-warn">
            {data.summary.missing_snapshot_count} of {data.summary.completed_work_orders} completed work orders in this period have no persisted snapshot. Rankings below use only captured evidence.
          </p>
          <label>Current account password<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
          <button type="button" style={{ marginTop: 12 }} disabled={backfilling} onClick={() => void backfill()}>
            {backfilling ? "Creating snapshots..." : "Create missing snapshots"}
          </button>
        </section>
      )}

      <section className="card">
        <div className="section-heading-row"><div><h3 style={{ margin: 0 }}>Daily persisted profit</h3><p className="muted" style={{ margin: "4px 0 0" }}>Zero-height days are retained so gaps are visible.</p></div><span className="status-count">{data?.daily.length ?? 0} days</span></div>
        <div style={{ display: "flex", alignItems: "center", gap: 3, minHeight: 150, overflowX: "auto", marginTop: 16 }}>
          {data?.daily.map((row) => (
            <div key={row.snapshot_date} title={`${row.snapshot_date}: ${money(row.profit)} from ${row.completed_count} jobs`} style={{ display: "flex", alignItems: row.profit >= 0 ? "flex-end" : "flex-start", height: 120, minWidth: 6, flex: 1, maxWidth: 24, borderBottom: "1px solid var(--border)" }}>
              <div style={{ width: "100%", height: `${Math.max(row.profit === 0 ? 1 : 6, Math.round(Math.abs(row.profit) / maxProfit * 110))}px`, background: row.profit < 0 ? "#ef4444" : "linear-gradient(180deg, #34d399, #059669)", borderRadius: 3 }} />
            </div>
          ))}
        </div>
      </section>

      <section className="grid">
        <RankingTable title="Engineer profit ranking" rows={data?.engineers || []} />
        <RankingTable title="Service region profit ranking" rows={data?.regions || []} />
        <RankingTable title="Machine type profit ranking" rows={data?.machine_types || []} />
      </section>
    </ManagerShell>
  );
}
