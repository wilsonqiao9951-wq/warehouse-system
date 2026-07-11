"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { InventoryNotification, ReplenishmentRequest } from "@/types";

export default function WarehouseTasksPage() {
  const [notifications, setNotifications] = useState<InventoryNotification[]>([]);
  const [requests, setRequests] = useState<ReplenishmentRequest[]>([]);
  const [error, setError] = useState("");
  const refresh = async () => { try { const [n, r] = await Promise.all([api.listInventoryNotifications(), api.listReplenishmentRequests()]); setNotifications(n); setRequests(r); setError(""); } catch (e) { setError(e instanceof Error ? e.message : "Unable to load warehouse tasks."); } };
  useEffect(() => { void refresh(); }, []);
  const acknowledge = async (id: number) => { await api.updateInventoryNotification(id, "acknowledged"); await refresh(); };
  const createRequest = async (id: number) => { await api.createReplenishmentRequest(id, 1); await refresh(); };
  const advance = async (item: ReplenishmentRequest) => { const next: Record<string, string> = { requested: "picking", picking: "shipped", shipped: "received", received: "completed" }; const status = next[item.status]; if (status) { await api.updateReplenishmentRequest(item.id, status); await refresh(); } };
  return <ManagerShell title="Warehouse tasks" subtitle="把工程师消耗转成可执行的补货和调拨任务。" metrics={[{ label: "Open alerts", value: notifications.length }, { label: "Requests", value: requests.length }, { label: "Workflow", value: "Live" }]}>
    {error && <div className="notice notice-error">{error}</div>}
    <section className="card"><h3>Low-stock alerts</h3>{notifications.length === 0 ? <div className="empty-state">No open warehouse alerts.</div> : <div style={{ display: "grid", gap: 10 }}>{notifications.map((item) => <div className="job-card" key={item.id}><strong>Part #{item.part_id}</strong><div className="muted">Warehouse #{item.warehouse_id} · Work order {item.work_order_id || "—"}</div><p style={{ margin: "8px 0" }}>{item.message}</p><div className="one-hand-actions"><button type="button" onClick={() => void createRequest(item.id)}>Create replenishment request</button><button type="button" onClick={() => void acknowledge(item.id)}>Acknowledge</button></div></div>)}</div>}</section>
    <section className="card"><h3>Replenishment requests</h3><p className="muted">Requested → Picking → Shipped → Received → Completed</p>{requests.length === 0 ? <div className="empty-state">Requests created from alerts will appear here.</div> : <div className="table-wrap"><table><thead><tr><th>Part</th><th>Destination</th><th>Source</th><th>Qty</th><th>Status</th><th>Action</th></tr></thead><tbody>{requests.map((item) => <tr key={item.id}><td>#{item.part_id}</td><td>#{item.destination_warehouse_id}</td><td>{item.source_warehouse_id ? `#${item.source_warehouse_id}` : "To assign"}</td><td>{item.quantity}</td><td>{item.status}</td><td>{item.status !== "completed" && item.status !== "cancelled" && <button type="button" onClick={() => void advance(item)}>Advance</button>}</td></tr>)}</tbody></table></div>}</section>
  </ManagerShell>;
}
