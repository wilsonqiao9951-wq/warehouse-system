"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function DashboardPage() {
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [profit, setProfit] = useState<number>(0);
  const [loading, setLoading] = useState(true);
  const [lowStockCount, setLowStockCount] = useState(0);
  const [role, setRole] = useState<AppRole>("admin");

  useEffect(() => {
    setRole(getCurrentRole());
  }, []);

  useEffect(() => {
    async function load() {
      setLoading(true);
      const workOrders = await api.listWorkOrders();
      setOrders(workOrders);
      const lowStock = await api.getLowStockAlerts().catch(() => []);
      setLowStockCount(lowStock.length);
      const profits = await Promise.all(workOrders.map((w) => api.getWorkOrderProfit(w.id).catch(() => null)));
      const totalProfit = profits.reduce((sum, p) => sum + (p?.profit || 0), 0);
      setProfit(totalProfit);
      setLoading(false);
    }
    load().catch(() => setLoading(false));
  }, []);

  const totalRevenue = useMemo(() => orders.reduce((sum, item) => sum + item.revenue, 0), [orders]);

  if (role !== "manager" && role !== "admin") {
    return <div className="card">Dashboard metrics are limited to manager/admin role.</div>;
  }

  if (loading) {
    return (
      <div className="card">
        <p>Loading dashboard…</p>
        <div style={{ display: "grid", gap: 8, maxWidth: 360 }}>
          <div className="skeleton" style={{ width: "55%" }} />
          <div className="skeleton" style={{ width: "90%" }} />
        </div>
      </div>
    );
  }

  return (
    <ManagerShell
      title="Dashboard"
      subtitle="Company overview and key KPIs."
      metrics={[
        { label: "Total Jobs", value: orders.length },
        { label: "Total Revenue", value: `$${totalRevenue.toFixed(2)}` },
        { label: "Total Profit", value: `$${profit.toFixed(2)}` },
        { label: "Low Stock Alerts", value: lowStockCount }
      ]}
    >
      <></>
    </ManagerShell>
  );
}
