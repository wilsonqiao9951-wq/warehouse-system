"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";

export default function MyJobsPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);
  const [error, setError] = useState("");

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
    <section className="card">
      <h3>My Jobs</h3>
      {error && <p className="notice notice-error">{error}</p>}
      <div style={{ display: "grid", gap: 10 }}>
        {jobs.length === 0 && !error ? <div className="empty-state">No jobs returned for your account.</div> : null}
        {jobs.map((job) => (
          <div className={`job-card${job.is_locked ? " job-card--locked" : ""}`} key={job.id}>
            <div>
              <b>{job.wo_number || job.ticket_number}</b> <span className="muted">({job.status})</span>
            </div>
            <div className="muted">{job.outlet_name || job.store_name || "Outlet"} · {job.city || "-"}</div>
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
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
