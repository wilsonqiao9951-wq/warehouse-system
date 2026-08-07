"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { VanPlanning, VanPlanningAction } from "@/types";

const ACTION_LABELS: Record<VanPlanningAction, string> = {
  replenish: "Replenish",
  return: "Return excess",
  balanced: "Balanced"
};

function replenishmentRoute(item: VanPlanning["recommendations"][number]) {
  const query = new URLSearchParams({
    part_id: String(item.part_id),
    destination_warehouse_id: String(item.warehouse_id),
    quantity: String(item.recommended_quantity),
    reason: `Van planning recommendation: ${item.reason}`
  });
  if (item.suggested_warehouse_id) {
    query.set("source_warehouse_id", String(item.suggested_warehouse_id));
  }
  return `/warehouse-tasks?${query.toString()}#new-replenishment`;
}

export default function VanInventoryPlanningPage() {
  const [data, setData] = useState<VanPlanning | null>(null);
  const [engineerOptions, setEngineerOptions] = useState<Array<{ id: number; name: string }>>([]);
  const [lookbackDays, setLookbackDays] = useState(30);
  const [coverageDays, setCoverageDays] = useState(14);
  const [engineerId, setEngineerId] = useState<number | "">("");
  const [action, setAction] = useState<"" | VanPlanningAction>("");
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (filters: {
    lookback_days: number;
    coverage_days: number;
    engineer_id?: number;
    action?: VanPlanningAction;
  }) => {
    try {
      setLoading(true);
      setError("");
      const result = await api.getVanInventoryPlanning({ ...filters, limit: 500 });
      setData(result);
      if (!filters.engineer_id) {
        setEngineerOptions(Array.from(
          new Map(result.engineers.map((row) => [row.engineer_id, { id: row.engineer_id, name: row.engineer_name }])).values()
        ));
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load vehicle inventory planning.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load({ lookback_days: 30, coverage_days: 14 });
  }, [load]);

  const applyFilters = () => void load({
    lookback_days: lookbackDays,
    coverage_days: coverageDays,
    ...(engineerId ? { engineer_id: engineerId } : {}),
    ...(action ? { action } : {})
  });

  const resetFilters = () => {
    setLookbackDays(30);
    setCoverageDays(14);
    setEngineerId("");
    setAction("");
    setSearch("");
    void load({ lookback_days: 30, coverage_days: 14 });
  };

  const shownRecommendations = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return data?.recommendations || [];
    return (data?.recommendations || []).filter((item) =>
      [item.part_number, item.part_name, item.engineer_name, item.warehouse_code, item.warehouse_name]
        .some((value) => value.toLowerCase().includes(needle))
    );
  }, [data, search]);

  return (
    <ManagerShell
      title="Van Inventory Planning"
      subtitle="Turn authenticated vehicle usage and in-flight custody records into explainable replenishment and return recommendations."
      showDefaultControls={false}
      metrics={[
        { label: "Active Vehicles", value: data?.summary.vehicle_count ?? "-" },
        { label: `Units Used (${data?.lookback_days ?? lookbackDays}d)`, value: data?.summary.consumed_quantity ?? "-" },
        { label: "Replenish", value: data?.summary.replenish_count ?? "-" },
        { label: "Return Excess", value: data?.summary.return_count ?? "-" }
      ]}
    >
      <section className="card">
        <div className="two-col">
          <label>
            Consumption lookback
            <select value={lookbackDays} onChange={(event) => setLookbackDays(Number(event.target.value))}>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
              <option value={90}>90 days</option>
            </select>
          </label>
          <label>
            Forward coverage
            <select value={coverageDays} onChange={(event) => setCoverageDays(Number(event.target.value))}>
              <option value={7}>7 days</option>
              <option value={14}>14 days</option>
              <option value={30}>30 days</option>
              <option value={60}>60 days</option>
            </select>
          </label>
          <label>
            Engineer
            <select value={engineerId} onChange={(event) => setEngineerId(event.target.value ? Number(event.target.value) : "")}>
              <option value="">All engineers</option>
              {engineerOptions.map((engineer) => (
                <option value={engineer.id} key={engineer.id}>{engineer.name}</option>
              ))}
            </select>
          </label>
          <label>
            Recommendation
            <select value={action} onChange={(event) => setAction(event.target.value as typeof action)}>
              <option value="">Replenish and return</option>
              <option value="replenish">Replenish only</option>
              <option value="return">Return excess only</option>
              <option value="balanced">Balanced rows</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button type="button" onClick={applyFilters} disabled={loading}>{loading ? "Calculating..." : "Apply planning window"}</button>
          <button type="button" className="secondary" onClick={resetFilters} disabled={loading}>Reset</button>
          <button type="button" className="secondary" onClick={applyFilters} disabled={loading}>Refresh evidence</button>
        </div>
        {error && <p className="notice notice-error">{error}</p>}
        {data?.truncated && (
          <p className="notice notice-warn">
            Results reached an operational bound. Select an engineer or recommendation type to narrow the calculation.
          </p>
        )}
      </section>

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Engineer consumption trends</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>Usage is sourced only from work-order ledger movements posted from each assigned vehicle.</p>
          </div>
          <span className="status-count">{data?.engineers.length ?? 0}</span>
        </div>
        {!loading && data?.engineers.length === 0 && <div className="empty-state">No active assigned vehicles match this view.</div>}
        <div className="warehouse-task-grid" style={{ marginTop: 14 }}>
          {data?.engineers.map((engineer) => {
            const maxDaily = Math.max(1, ...engineer.trend.map((point) => point.quantity));
            return (
              <article className="job-card" key={`${engineer.engineer_id}-${engineer.warehouse_id}`}>
                <div className="section-heading-row">
                  <div>
                    <strong>{engineer.engineer_name}</strong>
                    <div className="muted">{engineer.warehouse_code} — {engineer.warehouse_name}</div>
                  </div>
                  <span className="status-pill status-pill--received">{engineer.consumed_quantity} used</span>
                </div>
                <div className="two-col" style={{ marginTop: 12 }}>
                  <div><span className="muted">Work orders</span><div className="metric" style={{ fontSize: 24 }}>{engineer.work_order_count}</div></div>
                  <div><span className="muted">Daily average</span><div className="metric" style={{ fontSize: 24 }}>{engineer.average_daily_usage}</div></div>
                </div>
                <div style={{ display: "flex", alignItems: "end", gap: 4, minHeight: 58, marginTop: 12 }} aria-label="Daily consumption trend">
                  {engineer.trend.length === 0 ? (
                    <span className="muted">No work-order part usage in this window.</span>
                  ) : engineer.trend.map((point) => (
                    <div
                      key={point.date}
                      title={`${point.date}: ${point.quantity} units`}
                      style={{
                        flex: 1,
                        minWidth: 5,
                        maxWidth: 22,
                        height: `${Math.max(8, Math.round((point.quantity / maxDaily) * 54))}px`,
                        borderRadius: "5px 5px 2px 2px",
                        background: "linear-gradient(180deg, #38bdf8, #2563eb)"
                      }}
                    />
                  ))}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Rebalance recommendations</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              The planner is read-only. Stock changes still require the replenishment or vehicle-return custody workflow and its authenticated actors.
            </p>
          </div>
          <span className="status-count">{shownRecommendations.length}</span>
        </div>
        <input
          style={{ marginTop: 14 }}
          placeholder="Search part, engineer, vehicle..."
          value={search}
          onChange={(event) => setSearch(event.target.value)}
        />
        {!loading && shownRecommendations.length === 0 && <div className="empty-state" style={{ marginTop: 14 }}>No recommendations match this view.</div>}
        <div style={{ display: "grid", gap: 12, marginTop: 14 }}>
          {shownRecommendations.map((item) => (
            <article className="job-card" key={`${item.warehouse_id}-${item.part_id}`}>
              <div className="section-heading-row">
                <div>
                  <strong>{item.part_number} — {item.part_name}</strong>
                  <div className="muted">{item.engineer_name} · {item.warehouse_code} — {item.warehouse_name}</div>
                </div>
                <span className={`status-pill ${item.recommended_action === "replenish" ? "status-pill--requested" : item.recommended_action === "return" ? "status-pill--picking" : "status-pill--completed"}`}>
                  {ACTION_LABELS[item.recommended_action]} {item.recommended_quantity || ""}
                </span>
              </div>
              <div className="grid" style={{ marginTop: 12 }}>
                <div><span className="muted">On hand</span><div><strong>{item.current_quantity}</strong></div></div>
                <div><span className="muted">Pending in / out</span><div><strong>+{item.pending_inbound_quantity} / -{item.pending_outbound_quantity}</strong></div></div>
                <div><span className="muted">Projected</span><div><strong>{item.projected_quantity}</strong></div></div>
                <div><span className="muted">Target</span><div><strong>{item.target_quantity}</strong></div></div>
              </div>
              <p>{item.reason}</p>
              <p className="muted">
                {item.consumed_quantity} used in {data?.lookback_days} days · {item.forecast_quantity} forecast for {data?.coverage_days} days · threshold {item.threshold_quantity}
              </p>
              {item.recommended_action === "replenish" && !item.source_can_fulfill && (
                <p className="notice notice-warn">The suggested warehouse cannot fully cover this quantity. Review the ledger or split procurement before approval.</p>
              )}
              <div className="one-hand-actions">
                {item.recommended_action === "replenish" && (
                  <Link className="nav-item" href={replenishmentRoute(item)}>Prepare authenticated replenishment</Link>
                )}
                {item.recommended_action === "return" && (
                  <span className="muted">The assigned engineer submits this quantity from My Van; warehouse staff then approve and receive it.</span>
                )}
                <Link className="nav-item" href="/inventory-ledger">Review ledger evidence</Link>
              </div>
            </article>
          ))}
        </div>
      </section>
    </ManagerShell>
  );
}
