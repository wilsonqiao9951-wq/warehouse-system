"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";

function localDateKey(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function TodayPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .listWorkOrders({ limit: 100 })
      .then((rows) => {
        setJobs(rows);
        setError("");
      })
      .catch((e: Error) => setError(e.message || "Failed to load jobs."))
      .finally(() => setLoading(false));
  }, []);

  const todayKey = useMemo(() => localDateKey(new Date()), []);

  const todayJobs = useMemo(() => {
    const onDay = jobs.filter((j) => j.schedule_date && j.schedule_date.slice(0, 10) === todayKey);
    if (onDay.length > 0) return onDay;
    return jobs.filter((j) => j.status !== "completed" && j.status !== "COMPLETED");
  }, [jobs, todayKey]);

  const activeJobs = useMemo(() => jobs.filter((j) => j.status !== "completed" && j.status !== "COMPLETED"), [jobs]);

  const runStart = async (id: number) => {
    try {
      await api.startJob(id);
      const refreshed = await api.listWorkOrders({ limit: 100 });
      setJobs(refreshed);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Start failed.");
    }
  };

  return (
    <section className="card">
      <h3>Today</h3>
      <p className="muted">Assigned jobs for {todayKey}. If no schedule date is set, open jobs are shown.</p>
      {error && <p className="notice notice-error">{error}</p>}
      <div className="two-col" style={{ marginBottom: 12 }}>
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="muted">Jobs today / focus list</div>
          <div className="metric">{todayJobs.length}</div>
        </div>
        <div className="card" style={{ marginBottom: 0 }}>
          <div className="muted">All active</div>
          <div className="metric">{activeJobs.length}</div>
        </div>
      </div>
      {loading ? (
        <div style={{ display: "grid", gap: 8 }}>
          <div className="skeleton" style={{ width: "60%" }} />
          <div className="skeleton" style={{ width: "85%" }} />
        </div>
      ) : todayJobs.length === 0 ? (
        <div className="empty-state">No jobs for today. Check My Jobs for the full list.</div>
      ) : (
        <div style={{ display: "grid", gap: 10 }}>
          {todayJobs.map((job) => (
            <div className={`job-card${job.is_locked ? " job-card--locked" : ""}`} key={job.id}>
              <div>
                <b>{job.wo_number || job.ticket_number}</b> <span className="muted">({job.status})</span>
              </div>
              <div className="muted">
                {job.outlet_name || job.store_name || "Outlet"} · {job.city || "—"}
              </div>
              {job.schedule_date && (
                <div className="muted" style={{ fontSize: 13 }}>
                  Scheduled {job.schedule_date}
                </div>
              )}
              {job.is_locked && <span className="job-card__lock">Locked</span>}
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
                {!job.is_locked && <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}#completion`}>
                  Review &amp; complete
                </Link>}
                <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}`}>
                  Open
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
