"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ReplenishmentTimeline from "@/components/replenishment-timeline";
import { api } from "@/lib/api";
import { ReplenishmentRequest, StockBalance, VehicleReturnRequest, Warehouse } from "@/types";

function partLabel(item: ReplenishmentRequest): string {
  const number = item.part_number || `Part #${item.part_id}`;
  return item.part_name ? `${number} — ${item.part_name}` : number;
}

export default function MyVanInventoryPage() {
  const [items, setItems] = useState<StockBalance[]>([]);
  const [deliveries, setDeliveries] = useState<ReplenishmentRequest[]>([]);
  const [returns, setReturns] = useState<VehicleReturnRequest[]>([]);
  const [returnDestinations, setReturnDestinations] = useState<Warehouse[]>([]);
  const [returnStockKey, setReturnStockKey] = useState("");
  const [returnDestinationId, setReturnDestinationId] = useState("");
  const [returnQuantity, setReturnQuantity] = useState(1);
  const [returnReason, setReturnReason] = useState("");
  const [returnClientId, setReturnClientId] = useState("");
  const [shipReturnId, setShipReturnId] = useState<number | null>(null);
  const [returnPassword, setReturnPassword] = useState("");
  const [receiptId, setReceiptId] = useState<number | null>(null);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [online, setOnline] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [stockRows, requestRows, returnRows, destinationRows, me] = await Promise.all([
        api.getMyVanInventory(),
        api.listReplenishmentRequests(),
        api.listVehicleReturnRequests(),
        api.listVehicleReturnDestinations(),
        api.getMe()
      ]);
      setItems(stockRows);
      setDeliveries(requestRows.filter((item) => item.target_user_id === me.id || item.can_receive));
      setReturns(returnRows);
      setReturnDestinations(destinationRows);
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
  const activeReturns = useMemo(
    () => returns.filter((item) => !["received", "cancelled"].includes(item.status)),
    [returns]
  );

  const createReturn = async () => {
    const stock = items.find((item) => `${item.part_id}:${item.warehouse_id}` === returnStockKey);
    const reason = returnReason.trim();
    if (!online) return setError("Reconnect before creating a vehicle return.");
    if (!stock || !returnDestinationId || reason.length < 3) {
      return setError("Select vehicle stock and a destination warehouse, then enter a return reason.");
    }
    if (returnQuantity < 1 || returnQuantity > stock.quantity) {
      return setError(`Return quantity must be between 1 and ${stock.quantity}.`);
    }
    const clientRequestId = returnClientId || window.crypto.randomUUID();
    if (!returnClientId) setReturnClientId(clientRequestId);
    setBusy(true);
    setError("");
    try {
      const created = await api.createVehicleReturnRequest({
        part_id: stock.part_id,
        source_warehouse_id: stock.warehouse_id,
        destination_warehouse_id: Number(returnDestinationId),
        quantity: returnQuantity,
        reason,
        client_request_id: clientRequestId
      });
      setMessage(`Return #${created.id} submitted for warehouse approval.`);
      setReturnStockKey("");
      setReturnDestinationId("");
      setReturnQuantity(1);
      setReturnReason("");
      setReturnClientId("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create vehicle return.");
    } finally {
      setBusy(false);
    }
  };

  const shipReturn = async (item: VehicleReturnRequest) => {
    if (!online) return setError("Reconnect before confirming return handover.");
    if (!returnPassword) return setError("Enter your current account password.");
    setBusy(true);
    setError("");
    try {
      await api.actOnVehicleReturnRequest(item.id, {
        action: "ship",
        expected_version: item.version,
        account_password: returnPassword
      });
      setMessage(`Return #${item.id} handed over. Vehicle inventory has been reduced.`);
      setShipReturnId(null);
      setReturnPassword("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to confirm return handover.");
    } finally {
      setBusy(false);
    }
  };

  const cancelReturn = async (item: VehicleReturnRequest) => {
    const reason = window.prompt("Reason for cancelling this return:")?.trim();
    if (!reason) return;
    setBusy(true);
    try {
      await api.actOnVehicleReturnRequest(item.id, {
        action: "cancel",
        expected_version: item.version,
        reason
      });
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to cancel return.");
    } finally {
      setBusy(false);
    }
  };

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
            <h3 style={{ margin: 0 }}>Return stock to warehouse</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Submit unused vehicle stock. Warehouse approval reserves it; your password confirms physical handover.
            </p>
          </div>
          <span className="status-count">{activeReturns.length}</span>
        </div>

        <div className="manual-request-form">
          <label>
            <span>Vehicle stock</span>
            <select
              value={returnStockKey}
              disabled={busy}
              onChange={(event) => {
                setReturnStockKey(event.target.value);
                setReturnClientId("");
              }}
            >
              <option value="">Select stocked part</option>
              {items.filter((item) => item.quantity > 0).map((item) => (
                <option key={`${item.part_id}:${item.warehouse_id}`} value={`${item.part_id}:${item.warehouse_id}`}>
                  {item.part_number} — {item.part_name} · {item.warehouse_name} · Qty {item.quantity}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Destination warehouse</span>
            <select
              value={returnDestinationId}
              disabled={busy}
              onChange={(event) => {
                setReturnDestinationId(event.target.value);
                setReturnClientId("");
              }}
            >
              <option value="">Select warehouse</option>
              {returnDestinations.map((warehouse) => (
                <option key={warehouse.id} value={warehouse.id}>{warehouse.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Quantity</span>
            <input
              type="number"
              min={1}
              value={returnQuantity}
              disabled={busy}
              onChange={(event) => {
                setReturnQuantity(Math.max(1, Number(event.target.value) || 1));
                setReturnClientId("");
              }}
            />
          </label>
          <label className="manual-request-reason">
            <span>Reason</span>
            <input
              value={returnReason}
              disabled={busy}
              placeholder="Unused job stock, vehicle reassignment…"
              onChange={(event) => {
                setReturnReason(event.target.value);
                setReturnClientId("");
              }}
            />
          </label>
          <button type="button" disabled={busy || !online} onClick={() => void createReturn()}>
            Submit return request
          </button>
        </div>

        {activeReturns.length === 0 ? (
          <div className="empty-state">No active vehicle returns.</div>
        ) : (
          <div className="warehouse-task-grid" style={{ marginTop: 14 }}>
            {activeReturns.map((item) => (
              <article className="job-card replenishment-card" key={item.id}>
                <div className="section-heading-row">
                  <div>
                    <strong>{item.part_number || `Part #${item.part_id}`} — {item.part_name}</strong>
                    <div className="muted">Qty {item.quantity} · Return #{item.id}</div>
                  </div>
                  <span className={`status-pill status-pill--${item.status}`}>{item.status}</span>
                </div>
                <div className="custody-route">
                  <div><span className="muted">Vehicle</span><strong>{item.source_warehouse_name}</strong></div>
                  <span aria-hidden="true">→</span>
                  <div><span className="muted">Warehouse</span><strong>{item.destination_warehouse_name}</strong></div>
                </div>
                <div className="notice" style={{ marginTop: 10 }}>{item.reason}</div>
                {item.status === "requested" && <p className="muted">Waiting for warehouse approval.</p>}
                {item.status === "approved" && <p className="muted">Approved and reserved. Confirm handover on this registered phone.</p>}
                {item.status === "shipped" && <p className="muted">Handed over. Waiting for warehouse receipt.</p>}

                {item.can_ship && shipReturnId !== item.id && (
                  <button type="button" disabled={!online || busy} onClick={() => setShipReturnId(item.id)}>
                    Confirm handover
                  </button>
                )}
                {item.can_ship && shipReturnId === item.id && (
                  <div className="receipt-confirmation">
                    <label htmlFor={`return-password-${item.id}`}>Current account password</label>
                    <input
                      id={`return-password-${item.id}`}
                      type="password"
                      autoComplete="current-password"
                      value={returnPassword}
                      disabled={busy}
                      onChange={(event) => setReturnPassword(event.target.value)}
                    />
                    <div className="one-hand-actions">
                      <button type="button" disabled={busy || !returnPassword} onClick={() => void shipReturn(item)}>
                        Verify and hand over
                      </button>
                      <button type="button" className="secondary-button" onClick={() => setShipReturnId(null)}>Cancel</button>
                    </div>
                  </div>
                )}
                {item.can_cancel && (
                  <button type="button" className="secondary-button" disabled={busy} onClick={() => void cancelReturn(item)}>
                    Cancel return
                  </button>
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
