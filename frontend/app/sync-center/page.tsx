"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { getOfflineQueue, syncOfflineQueue } from "@/lib/api";

export default function SyncCenterPage() {
  const [queue, setQueue] = useState<Array<{ path: string; method: string; queuedAt: string }>>([]);
  const [online, setOnline] = useState(true);
  const [message, setMessage] = useState("");
  const refresh = () => setQueue(getOfflineQueue());
  useEffect(() => { refresh(); setOnline(navigator.onLine); const on = () => setOnline(true); const off = () => setOnline(false); window.addEventListener("online", on); window.addEventListener("offline", off); window.addEventListener("opf-offline-queued", refresh); return () => { window.removeEventListener("online", on); window.removeEventListener("offline", off); window.removeEventListener("opf-offline-queued", refresh); }; }, []);
  const sync = async () => { if (!online) { setMessage("当前离线，请恢复网络后重试。"); return; } const count = await syncOfflineQueue(); refresh(); setMessage(count ? `已同步 ${count} 条操作。` : "没有可同步的操作。"); };
  return <ManagerShell title="Sync center" subtitle="查看工程师离线记录，并在网络恢复后安全同步。" metrics={[{ label: "Pending", value: queue.length }, { label: "Connection", value: online ? "Online" : "Offline" }, { label: "Photos", value: "Online upload" }]}><section className="card"><div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}><h3 style={{ margin: 0 }}>Pending operations</h3><button type="button" onClick={() => void sync()}>Sync now</button></div><p className="muted">JSON 工单和库存操作可离线排队；照片需要联网上传。</p>{message && <div className="notice notice-success">{message}</div>}{queue.length === 0 ? <div className="empty-state">All operations are synchronized.</div> : <div style={{ display: "grid", gap: 8 }}>{queue.map((item, index) => <div className="job-card" key={`${item.queuedAt}-${index}`}><strong>{item.method}</strong> {item.path}<div className="muted">Queued {new Date(item.queuedAt).toLocaleString()}</div></div>)}</div>}</section></ManagerShell>;
}
