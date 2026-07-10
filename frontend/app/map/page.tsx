"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";
import { getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function MapPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);
  const [role, setRole] = useState("engineer");
  const [error, setError] = useState("");

  useEffect(() => {
    setRole(getCurrentRole());
    api
      .listWorkOrders({ limit: 200 })
      .then((rows) => {
        setJobs(rows);
        setError("");
      })
      .catch((e: Error) => setError(e.message || "Failed to load jobs."));
  }, []);

  return (
    <ManagerShell
      title="Map"
      subtitle={role === "engineer" ? "Route list for your assigned jobs." : "Route list for all team jobs."}
      metrics={[{ label: "Jobs on list", value: jobs.length }]}
    >
      {error && (
        <p className="notice notice-error" style={{ marginBottom: 12 }}>
          {error}
        </p>
      )}
      <section className="card">
        <div className="map-job-cards">
          {jobs.length === 0 && !error ? <div className="empty-state">No jobs to show.</div> : null}
          {jobs.map((job) => (
            <div key={job.id} className="job-card" style={{ margin: 0 }}>
              <div>
                <strong>{job.wo_number || job.ticket_number}</strong>{" "}
                <span className="muted">({job.status})</span>
              </div>
              <div className="muted" style={{ fontSize: 14 }}>
                {job.address || job.city || "—"}
              </div>
              <div className="one-hand-actions" style={{ marginTop: 8 }}>
                <a
                  className="nav-item"
                  href={`https://maps.google.com/?q=${encodeURIComponent(job.address || job.city || "")}`}
                  target="_blank"
                  rel="noreferrer"
                >
                  Navigate
                </a>
                <Link className="nav-item" href={`/work-order-details?work_order_id=${job.id}`}>
                  Open
                </Link>
              </div>
            </div>
          ))}
        </div>
        <div className="table-wrap map-table-desktop">
          <table>
            <thead>
              <tr>
                <th>WO</th>
                <th>Status</th>
                <th>City / address</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>{job.wo_number || job.ticket_number}</td>
                  <td>{job.status}</td>
                  <td>{job.address || job.city || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </ManagerShell>
  );
}
