"use client";

import { useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import {
  discardUnreferencedOfflineMedia,
  getOfflineMediaQueue,
  getOfflineReadCacheSummary,
  getOfflineQueue,
  retryOfflineQueueItem,
  syncOfflineQueue
} from "@/lib/api";

type VisibleQueueItem = ReturnType<typeof getOfflineQueue>[number];
type VisibleMediaItem = Awaited<ReturnType<typeof getOfflineMediaQueue>>[number];
type VisibleReadCacheItem = Awaited<ReturnType<typeof getOfflineReadCacheSummary>>[number];

export default function SyncCenterPage() {
  const [queue, setQueue] = useState<VisibleQueueItem[]>([]);
  const [online, setOnline] = useState(true);
  const [message, setMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [media, setMedia] = useState<VisibleMediaItem[]>([]);
  const [readCache, setReadCache] = useState<VisibleReadCacheItem[]>([]);
  const refresh = () => {
    setQueue(getOfflineQueue());
    void getOfflineMediaQueue().then(setMedia).catch(() => setMedia([]));
    void getOfflineReadCacheSummary().then(setReadCache).catch(() => setReadCache([]));
  };

  useEffect(() => {
    refresh();
    setOnline(navigator.onLine);
    const on = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener("online", on);
    window.addEventListener("offline", off);
    window.addEventListener("opf-offline-queued", refresh);
    window.addEventListener("opf-offline-media", refresh);
    window.addEventListener("opf-offline-read-cache", refresh);
    return () => {
      window.removeEventListener("online", on);
      window.removeEventListener("offline", off);
      window.removeEventListener("opf-offline-queued", refresh);
      window.removeEventListener("opf-offline-media", refresh);
      window.removeEventListener("opf-offline-read-cache", refresh);
    };
  }, []);

  const sync = async () => {
    if (!online) {
      setMessage({ type: "error", text: "You are offline. Reconnect before syncing." });
      return;
    }
    const count = await syncOfflineQueue();
    refresh();
    setMessage({
      type: "success",
      text: count
        ? `Synchronized ${count} operation${count === 1 ? "" : "s"}.`
        : "No eligible operations were synchronized."
    });
  };

  const retry = (id: string) => {
    retryOfflineQueueItem(id);
    refresh();
    setMessage({ type: "success", text: "The retained operation is pending another explicit sync attempt." });
  };

  const discardMedia = async (item: VisibleMediaItem) => {
    try {
      await discardUnreferencedOfflineMedia(
        item.marker,
        item.workOrderId,
        item.claimVersion
      );
      refresh();
      setMessage({ type: "success", text: "Unattached offline photo discarded from this device." });
    } catch (error) {
      setMessage({
        type: "error",
        text: error instanceof Error ? error.message : "Offline photo could not be discarded."
      });
    }
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
        { label: "Retained photos", value: media.length },
        { label: "Read snapshots", value: readCache.length },
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
        {message && (
          <div className={`notice ${message.type === "success" ? "notice-success" : "notice-error"}`}>
            {message.text}
          </div>
        )}
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
                    Conflict retained{item.serverConflictId ? ` as review #${item.serverConflictId}` : ""}: the server form changed after this offline copy was opened. Local data has not overwritten the server; administrator resolution is required.
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
      <section className="card">
        <h3 style={{ marginTop: 0 }}>Retained photos</h3>
        <p className="muted">
          Photo bytes stay inside this browser and are isolated to the originating account, device, work order, and claim generation. Attached photos are uploaded before their JSON operation.
        </p>
        {media.length === 0 ? (
          <div className="empty-state">No photos are retained in offline device storage.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {media.map((item) => (
              <div className="job-card" key={item.marker}>
                <strong>{item.purpose === "configured_form_photo" ? "Configured-form photo" : "QC photo"}</strong>
                <div>Work order #{item.workOrderId}</div>
                <div className="muted">
                  Retained {new Date(item.createdAt).toLocaleString()}
                  {` · ${(item.byteSize / 1024 / 1024).toFixed(1)} MiB · claim version ${item.claimVersion}`}
                </div>
                {item.referenced ? (
                  <div className="notice notice-success" style={{ marginTop: 8 }}>
                    Attached to a queued operation; automatic cleanup follows verified upload.
                  </div>
                ) : (
                  <button type="button" style={{ marginTop: 8 }} onClick={() => void discardMedia(item)}>
                    Discard unattached photo
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
      <section className="card">
        <h3 style={{ marginTop: 0 }}>Offline read snapshots</h3>
        <p className="muted">
          Successful, reviewed GET responses are retained only for this account and registered device. They are read-only and never grant mutation permission.
        </p>
        {readCache.length === 0 ? (
          <div className="empty-state">Open work orders online once to prepare this device for offline viewing.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {readCache.slice(0, 20).map((item) => (
              <div className="job-card" key={item.path}>
                <strong>{item.path.split("?")[0]}</strong>
                <div className="muted">
                  Saved {new Date(item.storedAt).toLocaleString()}
                  {` · ${(item.byteSize / 1024).toFixed(0)} KiB`}
                </div>
              </div>
            ))}
            {readCache.length > 20 && (
              <p className="muted">{readCache.length - 20} additional snapshots are retained.</p>
            )}
          </div>
        )}
      </section>
    </ManagerShell>
  );
}
