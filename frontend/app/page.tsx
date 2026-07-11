"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { WorkOrder } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";
import Link from "next/link";

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
      <section className="grid" style={{ marginTop: 12 }}>
        <Link href="/inventory-scan" className="card" style={{ borderColor: "#93c5fd" }}>
          <div className="muted">现场操作</div><h3 style={{ margin: "6px 0" }}>扫码 / 核对库存 →</h3>
          <p className="muted" style={{ margin: 0 }}>扫描标签或输入物料号，立即反馈可用数量。</p>
        </Link>
        <Link href="/part-observation" className="card" style={{ borderColor: "#c4b5fd" }}>
          <div className="muted">无二维码零件</div><h3 style={{ margin: "6px 0" }}>拍照建立机型记忆 →</h3>
          <p className="muted" style={{ margin: 0 }}>员工确认一次，系统持续推荐相关零件。</p>
        </Link>
        <Link href="/inventory" className="card" style={{ borderColor: "#86efac" }}>
          <div className="muted">仓库管理</div><h3 style={{ margin: "6px 0" }}>查看库存与库位 →</h3>
          <p className="muted" style={{ margin: 0 }}>按仓库、库位和低库存提醒管理物料。</p>
        </Link>
      </section>
    </ManagerShell>
  );
}
