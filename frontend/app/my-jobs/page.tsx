"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { StockBalance, WorkOrder, WorkOrderPartRecommendation } from "@/types";

export default function MyJobsPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [recommendations, setRecommendations] = useState<WorkOrderPartRecommendation[]>([]);
  const [vanStock, setVanStock] = useState<StockBalance[]>([]);
  const [checked, setChecked] = useState<Record<number, boolean>>({});

  useEffect(() => {
    const userId = window.localStorage.getItem("opf_user_id");
    if (userId) api.getVanInventory(Number(userId)).then(setVanStock).catch(() => setVanStock([]));
  }, []);

  useEffect(() => {
    api
      .listWorkOrders({ limit: 200 })
      .then((rows) => {
        setJobs(rows);
        setError("");
      })
      .catch((e: Error) => setError(e.message || "Failed to load jobs."));
  }, []);

  const runStart = async (id: number) => {
    try {
      await api.startJob(id);
      const refreshed = await api.listWorkOrders({ limit: 200 });
      setJobs(refreshed);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed.");
    }
  };

  const showRecommendations = async (id: number) => {
    setSelected(id);
    setChecked({});
    try { setRecommendations(await api.getWorkOrderPartRecommendations(id)); }
    catch (e) { setError(e instanceof Error ? e.message : "Unable to load recommendations."); }
  };

  const runComplete = async (id: number) => {
    try {
      await api.completeJob(id);
      const refreshed = await api.listWorkOrders({ limit: 200 });
      setJobs(refreshed);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Complete failed.");
    }
  };

  return (
    <section>
      <div className="card" style={{ background: "linear-gradient(135deg, #102a56, #155eef)", color: "white" }}>
        <div style={{ fontSize: 13, opacity: .78, letterSpacing: ".08em", textTransform: "uppercase" }}>Field workspace</div>
        <h2 style={{ margin: "8px 0 4px" }}>Today’s service jobs</h2>
        <p style={{ margin: 0, opacity: .86 }}>查看工单、准备零件，并把现场经验沉淀到系统。</p>
      </div>
      <section className="card">
      <h3 style={{ marginTop: 0 }}>My Jobs</h3>
      {error && <p className="notice notice-error">{error}</p>}
      <div style={{ display: "grid", gap: 10 }}>
        {jobs.length === 0 && !error ? <div className="empty-state">No jobs returned for your account.</div> : null}
        {jobs.map((job) => (
          <div className={`job-card${job.is_locked ? " job-card--locked" : ""}`} key={job.id}>
            <div>
              <b>{job.wo_number || job.ticket_number}</b> <span className="muted">({job.status})</span>
            </div>
            <div className="muted">{job.outlet_name || job.store_name || "Outlet"} · {job.city || "-"}</div>
            {job.machine_type && <div className="muted" style={{ marginTop: 4 }}>Equipment: {job.machine_type}</div>}
            {job.is_locked && <span className="job-card__lock">Completed — locked</span>}
            <div className="one-hand-actions">
              <a
                className="nav-item"
                href={`https://maps.google.com/?q=${encodeURIComponent(job.address || "")}`}
                target="_blank"
                rel="noreferrer"
              >
                Navigate
              </a>
              {job.contact_phone ? (
                <a className="nav-item" href={`tel:${job.contact_phone}`}>
                  Call
                </a>
              ) : (
                <span className="nav-item" style={{ opacity: 0.5, cursor: "not-allowed" }}>
                  Call
                </span>
              )}
              <button type="button" onClick={() => runStart(job.id)} disabled={Boolean(job.is_locked)}>
                Start
              </button>
              <button type="button" onClick={() => runComplete(job.id)} disabled={Boolean(job.is_locked)}>
                Complete
              </button>
              <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}`}>
                Open
              </Link>
              <button type="button" onClick={() => void showRecommendations(job.id)}>Parts assist</button>
            </div>
            {selected === job.id && <div className="notice notice-success" style={{ marginTop: 10 }}><strong>AI parts assist · departure checklist</strong>{recommendations.length === 0 ? <div>No learned recommendation yet. Capture the parts used to train this model.</div> : <div style={{ display: "grid", gap: 8, marginTop: 8 }}>{recommendations.slice(0, 5).map((rec) => { const available = vanStock.filter((row) => row.part_id === rec.part.id).reduce((sum, row) => sum + row.quantity, 0); const shortage = Math.max(0, rec.recommended_quantity - available); return <label key={rec.part.id} style={{ display: "flex", gap: 8, alignItems: "flex-start" }}><input type="checkbox" checked={Boolean(checked[rec.part.id])} onChange={(e) => setChecked((prev) => ({ ...prev, [rec.part.id]: e.target.checked }))} style={{ width: 20, minHeight: 20, marginTop: 2 }} /><span><b>{rec.part.part_number}</b> · carry {rec.recommended_quantity} · van stock {available} {shortage > 0 ? <span className="danger">· request {shortage} from warehouse</span> : <span style={{ color: "#15803d" }}>· ready</span>}<br /><span className="muted">{rec.reason}</span></span></label>; })}</div>}</div>}
          </div>
        ))}
      </div>
    </section>
    </section>
  );
}
