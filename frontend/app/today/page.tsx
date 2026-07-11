"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";

function claimLabel(job: WorkOrder): string {
  if (job.completed_by_name) return `Completed by ${job.completed_by_name}`;
  if (job.can_edit) return "Claimed by you on this device";
  if (job.claimed_by_name) return `Claimed by ${job.claimed_by_name}`;
  return "Available to claim";
}

export default function TodayPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    const rows = await api.listWorkOrders({ scope: "all", limit: 100 });
    setJobs(rows);
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setError(""))
      .catch((e: Error) => setError(e.message || "Failed to load jobs."))
      .finally(() => setLoading(false));
  }, [refresh]);

  const orderedJobs = useMemo(
    () => [...jobs].sort((a, b) => Number(b.can_claim) - Number(a.can_claim) || Number(b.can_edit) - Number(a.can_edit) || a.id - b.id),
    [jobs]
  );
  const availableCount = useMemo(() => jobs.filter((job) => job.can_claim).length, [jobs]);
  const mineCount = useMemo(() => jobs.filter((job) => job.can_edit).length, [jobs]);

  const claim = async (id: number) => {
    try {
      setBusyId(id);
      setError("");
      await api.claimWorkOrder(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Claim failed.");
    } finally {
      setBusyId(null);
    }
  };

  const runStart = async (id: number) => {
    try {
      setBusyId(id);
      setError("");
      await api.startJob(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed.");
    } finally {
      setBusyId(null);
    }
  };

  return (
    <section className="card">
      <h3>Job pool</h3>
      <p className="muted">Every engineer can view the full work-order pool. Claim a job before making field updates; the claim is bound to your signed-in account and this device.</p>
      {error && <p className="notice notice-error">{error}</p>}
      <div className="two-col" style={{ marginBottom: 12 }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="muted">Available to claim</div>
          <div className="metric">{availableCount}</div>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="muted">Mine on this device</div>
          <div className="metric">{mineCount}</div>
        </div>
      </div>
      {loading ? (
        <div style={{ display: "grid", gap: 8 }}>
          <div className="skeleton" style={{ width: "60%" }} />
          <div className="skeleton" style={{ width: "85%" }} />
        </div>
      ) : orderedJobs.length === 0 ? (
        <div className="empty-state">No work orders are available.</div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {orderedJobs.map((job) => (
            <div className={`job-card${job.is_locked ? " job-card--locked" : ""}`} key={job.id}>
              <div>
                <b>{job.wo_number || job.ticket_number}</b> <span className="muted">({job.status})</span>
              </div>
              <div className="muted">
                {job.outlet_name || job.store_name || "Outlet"} · {job.city || "—"}
              </div>
              {job.schedule_date && <div className="muted" style={{ fontSize: 13 }}>Scheduled {job.schedule_date}</div>}
              <div className={job.can_claim || job.can_edit ? "notice notice-success" : "muted"} style={{ marginTop: 8 }}>
                {claimLabel(job)}
                {job.claimed_at && job.claimed_by_name && <span> · {new Date(job.claimed_at).toLocaleString()}</span>}
              </div>
              {job.completed_device_name && <div className="muted" style={{ fontSize: 13 }}>Completion device: {job.completed_device_name}</div>}
              {job.is_locked && <span className="job-card__lock">Completed — locked</span>}
              <div className="one-hand-actions">
                <a className="nav-item" href={`https://maps.google.com/?q=${encodeURIComponent(job.address || "")}`} target="_blank" rel="noreferrer">
                  Navigate
                </a>
                {job.contact_phone ? <a className="nav-item" href={`tel:${job.contact_phone}`}>Call</a> : <span className="nav-item" style={{ opacity: 0.5, cursor: "not-allowed" }}>Call</span>}
                {job.can_claim && <button type="button" onClick={() => void claim(job.id)} disabled={busyId === job.id}>{busyId === job.id ? "Claiming…" : "Claim job"}</button>}
                {job.can_edit && <button type="button" onClick={() => void runStart(job.id)} disabled={busyId === job.id || Boolean(job.is_locked)}>Start</button>}
                {job.can_complete && <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}#completion`}>Review &amp; complete</Link>}
                <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}`}>Open {job.can_edit ? "" : "read-only"}</Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
