"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReplenishmentTimeline from "@/components/replenishment-timeline";
import { api } from "@/lib/api";
import { ReplenishmentRequest, StockBalance } from "@/types";

function partLabel(item: ReplenishmentRequest): string {
  const number = item.part_number || `Part #${item.part_id}`;
  return item.part_name ? `${number} — ${item.part_name}` : number;
}

export default function MyVanInventoryPage() {
  const [items, setItems] = useState<StockBalance[]>([]);
  const [deliveries, setDeliveries] = useState<ReplenishmentRequest[]>([]);
  const [receiptId, setReceiptId] = useState<number | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [stockRows, requestRows, me] = await Promise.all([
        api.getMyVanInventory(),
        api.listReplenishmentRequests(),
        api.getMe()
      ]);
      setItems(stockRows);
      setDeliveries(requestRows.filter((item) => item.target_user_id === me.id || item.can_receive));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load your van inventory.");
    }
  }, []);

  useEffect(() => {
    void load();
    setOnline(navigator.onLine);
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [load]);

  const activeDeliveries = useMemo(
    () => deliveries.filter((item) => item.requires_reconciliation || !["completed", "cancelled"].includes(item.status)),
    [deliveries]
  );
  const awaitingReceipt = activeDeliveries.filter(
    (item) => !item.requires_reconciliation && item.status === "shipped"
  ).length;

  const receive = async (item: ReplenishmentRequest) => {
    if (item.requires_reconciliation) {
      setError("This historical request is read-only until an administrator reconciles it.");
      return;
    }
    if (!online) {
      setError("Reconnect before signing for this delivery. Receipt and inventory posting are online-only.");
      return;
    }
    if (!password) {
      setError("Enter your current account password to confirm receipt.");
      return;
    }
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const updated = await api.actOnReplenishmentRequest(item.id, {
        action: "receive",
        expected_version: item.version,
        account_password: password
      });
      const transaction = updated.receipt_transaction_id
        ? ` Receipt transaction #${updated.receipt_transaction_id}.`
        : "";
      const newBalance = updated.destination_quantity !== null && updated.destination_quantity !== undefined
        ? ` New vehicle stock: ${updated.destination_quantity}.`
        : "";
      setMessage(`Received ${updated.quantity} × ${partLabel(updated)} into your vehicle.${transaction}${newBalance}`);
      setReceiptId(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to confirm receipt.");
    } finally {
      setPassword("");
      setBusy(false);
    }
  };

  return (
    <section>
      <div className="card" style={{ background: "linear-gradient(135deg, #102a56, #155eef)", color: "white" }}>
        <div style={{ fontSize: 13, opacity: 0.78, letterSpacing: ".08em", textTransform: "uppercase" }}>Vehicle custody</div>
        <h2 style={{ margin: "8px 0 4px" }}>My Van</h2>
        <p style={{ margin: 0, opacity: 0.86 }}>
          {awaitingReceipt} shipment{awaitingReceipt === 1 ? "" : "s"} awaiting your verified receipt.
        </p>
      </div>

      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice notice-success">{message}</div>}

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Incoming replenishment</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Only you can receive stock assigned to your vehicle, using your account on this registered phone.
            </p>
          </div>
          <span className="status-count">{activeDeliveries.length}</span>
        </div>

        {!online && (
          <div className="notice notice-error">
            You are offline. You may review loaded information, but receiving and inventory posting require a live connection.
          </div>
        )}

        {activeDeliveries.length === 0 ? (
          <div className="empty-state">No incoming replenishment tasks.</div>
        ) : (
          <div className="warehouse-task-grid">
            {activeDeliveries.map((item) => (
              <article className="job-card replenishment-card" key={item.id}>
                <div className="section-heading-row">
                  <div>
                    <strong>{partLabel(item)}</strong>
                    <div className="muted">Qty {item.quantity} · Request #{item.id}</div>
                  </div>
                  <span className={`status-pill status-pill--${item.status}`}>{item.status}</span>
                </div>
                <div className="custody-route">
                  <div>
                    <span className="muted">From</span>
                    <strong>{item.source_warehouse_name || `Warehouse #${item.source_warehouse_id || "—"}`}</strong>
                  </div>
                  <span aria-hidden="true">→</span>
                  <div>
                    <span className="muted">To</span>
                    <strong>{item.destination_warehouse_name || `Vehicle #${item.destination_warehouse_id}`}</strong>
                  </div>
                </div>

                {item.request_reason && (
                  <div className="notice" style={{ marginTop: 10 }}>
                    <strong>Request reason</strong>
                    <div>{item.request_reason}</div>
                  </div>
                )}

                <ReplenishmentTimeline item={item} />

                {item.requires_reconciliation && (
                  <div className="notice notice-warn" style={{ marginTop: 10 }}>
                    <strong>Historical record — read only</strong>
                    <div>An administrator must reconcile this legacy status before any verified workflow action is allowed.</div>
                  </div>
                )}

                {!item.requires_reconciliation && item.status === "shipped" && !item.can_receive && (
                  <div className="notice notice-error" style={{ marginTop: 10 }}>
                    Read-only on this account or device. Sign in as the assigned engineer on the registered phone.
                  </div>
                )}

                {!item.requires_reconciliation && item.can_receive && receiptId !== item.id && (
                  <button
                    type="button"
                    style={{ marginTop: 10, width: "100%" }}
                    disabled={!online}
                    onClick={() => {
                      setReceiptId(item.id);
                      setPassword("");
                      setError("");
                    }}
                  >
                    Sign for receipt and add to van
                  </button>
                )}

                {!item.requires_reconciliation && item.can_receive && receiptId === item.id && (
                  <div className="receipt-confirmation">
                    <label htmlFor={`receipt-password-${item.id}`}>Confirm with your account password</label>
                    <input
                      id={`receipt-password-${item.id}`}
                      type="password"
                      autoComplete="current-password"
                      value={password}
                      disabled={busy}
                      onChange={(event) => setPassword(event.target.value)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter") void receive(item);
                      }}
                    />
                    <p className="muted">Your password is sent only for live verification and is never stored offline.</p>
                    <div className="one-hand-actions">
                      <button type="button" disabled={busy || !online || !password} onClick={() => void receive(item)}>
                        {busy ? "Verifying…" : "Confirm receipt"}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={busy}
                        onClick={() => {
                          setReceiptId(null);
                          setPassword("");
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Current vehicle inventory</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>Balances refresh immediately after verified receipt.</p>
          </div>
          <span className="status-count">{items.length}</span>
        </div>
        {items.length === 0 ? (
          <div className="empty-state">No vehicle inventory rows.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Part</th>
                  <th>Warehouse</th>
                  <th>Qty</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={`${item.part_id}-${item.warehouse_id}`}>
                    <td>{item.part_number} — {item.part_name}</td>
                    <td>{item.warehouse_name}</td>
                    <td className={item.is_low_stock ? "danger" : ""}>{item.quantity}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </section>
  );
}
