"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { getOfflineQueue, syncOfflineQueue } from "@/lib/api";

type VisibleQueueItem = ReturnType<typeof getOfflineQueue>[number];

export default function SyncCenterPage() {
  const [queue, setQueue] = useState<VisibleQueueItem[]>([]);
  const [online, setOnline] = useState(true);
  const [message, setMessage] = useState("");
  const refresh = () => setQueue(getOfflineQueue());

  useEffect(() => {
    refresh();
    setOnline(navigator.onLine);
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    window.addEventListener("opf-offline-queued", refresh);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
      window.removeEventListener("opf-offline-queued", refresh);
    };
  }, []);

  const sync = async () => {
    if (!online) {
      setMessage("You are offline. Reconnect before syncing.");
      return;
    }
    const count = await syncOfflineQueue();
    refresh();
    setMessage(count ? `Synchronized ${count} operation${count === 1 ? "" : "s"}.` : "No eligible operations were synchronized.");
  };

  return (
    <ManagerShell
      title="Sync center"
      subtitle="Offline operations are isolated to the signed-in account, registered device, and current work-order claim."
      metrics={[
        { label: "Pending", value: queue.length },
        { label: "Connection", value: online ? "Online" : "Offline" },
        { label: "Verified actions", value: "Online only" }
      ]}
    >
      <section className="card">
        <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Pending operations</h3>
          <button type="button" onClick={() => void sync()}>Sync now</button>
        </div>
        <p className="muted">Claiming, starting, pausing, status changes, and completion always require a live connection. Other queued records are rejected if the job was released or reclaimed.</p>
        {message && <div className="notice notice-success">{message}</div>}
        {queue.length === 0 ? (
          <div className="empty-state">All eligible operations are synchronized.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {queue.map((item, index) => (
              <div className="job-card" key={`${item.queuedAt}-${index}`}>
                <strong>{item.method}</strong> {item.path}
                <div className="muted">
                  Queued {new Date(item.queuedAt).toLocaleString()}
                  {item.claimVersion !== undefined ? ` · claim version ${item.claimVersion}` : ""}
                </div>
                {item.stale && <div className="notice notice-error" style={{ marginTop: 8 }}>Blocked: this work order was released or reclaimed. The queued change will not be replayed.</div>}
                {!item.stale && item.blockedReason && <div className="notice notice-error" style={{ marginTop: 8 }}>Last sync attempt: {item.blockedReason}</div>}
              </div>
            ))}
          </div>
        )}
      </section>
    </ManagerShell>
  );
}
