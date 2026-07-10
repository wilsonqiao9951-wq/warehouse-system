"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";
import ManagerShell from "@/components/manager-shell";

export default function CalendarPage() {
  const [jobs, setJobs] = useState<WorkOrder[]>([]);

  useEffect(() => {
    api.listWorkOrders().then(setJobs).catch(() => setJobs([]));
  }, []);

  const grouped = useMemo(() => {
    const map = new Map<string, number>();
    jobs.forEach((j) => {
      const key = j.status || "open";
      map.set(key, (map.get(key) || 0) + 1);
    });
    return Array.from(map.entries());
  }, [jobs]);

  return (
    <ManagerShell
      title="Calendar"
      subtitle="Team schedule and job distribution."
      metrics={[
        { label: "Total Jobs", value: jobs.length },
        { label: "Status Groups", value: grouped.length }
      ]}
    >
    <section className="card">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Jobs</th>
          </tr>
        </thead>
        <tbody>
          {grouped.map(([status, count]) => (
            <tr key={status}>
              <td>{status}</td>
              <td>{count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
    </ManagerShell>
  );
}
