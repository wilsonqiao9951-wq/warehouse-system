"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { getOfflineQueue, retryOfflineQueueItem, syncOfflineQueue } from "@/lib/api";

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

  const retry = (id: string) => {
    retryOfflineQueueItem(id);
    refresh();
    setMessage("The retained operation is pending another explicit sync attempt.");
  };

  const conflictCount = queue.filter((item) => item.syncState === "conflict").length;
  const blockedCount = queue.filter((item) => item.syncState === "blocked" || item.stale).length;

  return (
    <ManagerShell
      title="Sync center"
      subtitle="Offline operations are isolated to the signed-in account, registered device, and current work-order claim. Warehouse custody changes always stay online."
      metrics={[
        { label: "Pending", value: queue.length },
        { label: "Connection", value: online ? "Online" : "Offline" },
        { label: "Conflicts", value: conflictCount },
        { label: "Ownership blocked", value: blockedCount }
      ]}
    >
      <section className="card">
        <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
          <h3 style={{ margin: 0 }}>Pending operations</h3>
          <button type="button" onClick={() => void sync()}>Sync now</button>
        </div>
        <p className="muted">Configured form values and eligible evidence can be queued. Claiming, work-order status changes, completion, replenishment custody, vehicle return approval/handover/receipt, vehicle inventory posting, and historical reconciliation always require a live connection.</p>
        <p className="muted">Every queued form is isolated to the signed-in account, this registered device, and its claim generation. Version conflicts retain the local record and never overwrite server data silently.</p>
        {message && <div className="notice notice-success">{message}</div>}
        {queue.length === 0 ? (
          <div className="empty-state">All eligible operations are synchronized.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {queue.map((item) => (
              <div className="job-card" key={item.id}>
                <strong>
                  {item.operationType === "work_order_form"
                    ? "Configured form"
                    : item.operationType === "work_order_evidence"
                      ? "Work-order evidence"
                      : item.method}
                </strong>{" "}
                <span className="muted">· {item.syncState}</span>
                {item.workOrderId && <div>Work order #{item.workOrderId}</div>}
                <div className="muted">
                  Queued {new Date(item.queuedAt).toLocaleString()}
                  {item.updatedAt !== item.queuedAt ? ` · updated ${new Date(item.updatedAt).toLocaleString()}` : ""}
                  {item.claimVersion !== undefined ? ` · claim version ${item.claimVersion}` : ""}
                  {item.attemptCount ? ` · ${item.attemptCount} sync attempt${item.attemptCount === 1 ? "" : "s"}` : ""}
                </div>
                {item.stale && <div className="notice notice-error" style={{ marginTop: 8 }}>Blocked: this work order was released or reclaimed. The queued change will not be replayed.</div>}
                {!item.stale && item.syncState === "conflict" && (
                  <div className="notice notice-error" style={{ marginTop: 8 }}>
                    Conflict retained: the server form changed after this offline copy was opened. Local data has not overwritten the server; administrator resolution is required.
                  </div>
                )}
                {!item.stale && item.blockedReason && <div className="notice notice-error" style={{ marginTop: 8 }}>Last sync attempt: {item.blockedReason}</div>}
                {!item.stale && ["failed", "blocked"].includes(item.syncState) && (
                  <button type="button" style={{ marginTop: 8 }} onClick={() => retry(item.id)}>
                    Retry after review
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </ManagerShell>
  );
}
