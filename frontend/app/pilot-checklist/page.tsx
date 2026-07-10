"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { PilotChecklist } from "@/types";

export default function PilotChecklistPage() {
  const [data, setData] = useState<PilotChecklist | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .getPilotChecklist()
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message || "Failed to load checklist."));
  }, []);

  return (
    <ManagerShell title="Pilot Checklist" subtitle="Operational readiness snapshot before go-live.">
      <section className="card">
        {error && <p className="notice notice-error">{error}</p>}
        {!data && !error && (
          <div style={{ display: "grid", gap: 8 }}>
            <div className="skeleton" style={{ width: "50%" }} />
            <div className="skeleton" style={{ width: "80%" }} />
          </div>
        )}
        {data && (
          <div className="pilot-metric-grid">
            <div className={`pilot-metric${data.system_health !== "ok" ? " pilot-metric--alert" : ""}`}>
              <div className="muted">System health</div>
              <div className="metric" style={{ fontSize: 22 }}>
                {data.system_health}
              </div>
            </div>
            <div className="pilot-metric">
              <div className="muted">Users</div>
              <div className="metric">{data.total_users}</div>
            </div>
            <div className="pilot-metric">
              <div className="muted">Work orders</div>
              <div className="metric">{data.total_work_orders}</div>
            </div>
            <div className="pilot-metric">
              <div className="muted">Parts</div>
              <div className="metric">{data.total_parts}</div>
            </div>
            <div className="pilot-metric">
              <div className="muted">Inventory txns</div>
              <div className="metric">{data.total_inventory_transactions}</div>
            </div>
            <div className={`pilot-metric${data.low_stock_alert_count > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Low stock alerts</div>
              <div className="metric">{data.low_stock_alert_count}</div>
            </div>
            <div className={`pilot-metric${data.abnormal_usage_alert_count > 0 ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Abnormal usage</div>
              <div className="metric">{data.abnormal_usage_alert_count}</div>
            </div>
          </div>
        )}
      </section>
    </ManagerShell>
  );
}
