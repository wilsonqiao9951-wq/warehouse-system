"use client";

import { useCallback, useMemo, useState, useEffect } from "react";
import ManagerShell from "@/components/manager-shell";
import ReplenishmentTimeline from "@/components/replenishment-timeline";
import { api } from "@/lib/api";
import { InventoryNotification, Part, ReplenishmentRequest, VehicleReturnRequest, Warehouse } from "@/types";

type ReplenishmentAction = "approve" | "reject" | "start_picking" | "ship" | "complete" | "cancel";
type ReconciliationResolution = "reset_requested" | "accept_historical";

interface ManualRequestForm {
  partId: number | "";
  destinationWarehouseId: number | "";
  sourceWarehouseId: number | "";
  quantity: number;
  reason: string;
}

interface ReconciliationDraft {
  resolution: ReconciliationResolution;
  reason: string;
  password: string;
}

const emptyManualRequest: ManualRequestForm = {
  partId: "",
  destinationWarehouseId: "",
  sourceWarehouseId: "",
  quantity: 1,
  reason: ""
};

const workflowGroups: Array<{
  title: string;
  description: string;
  statuses: ReplenishmentRequest["status"][];
}> = [
  {
    title: "Approval and picking queue",
    description: "Managers approve the business request before warehouse custody can begin.",
    statuses: ["requested"]
  },
  {
    title: "Picking",
    description: "Picked stock is reserved for this request until it ships.",
    statuses: ["picking"]
  },
  {
    title: "Waiting for engineer",
    description: "The destination engineer must sign in on their registered phone to receive it.",
    statuses: ["shipped"]
  },
  {
    title: "Received",
    description: "Vehicle stock is updated. Warehouse staff can now close the task.",
    statuses: ["received"]
  },
  {
    title: "History",
    description: "Completed, rejected, and cancelled custody records remain visible for audit.",
    statuses: ["completed", "cancelled", "rejected"]
  }
];

function partLabel(item: ReplenishmentRequest): string {
  const number = item.part_number || `Part #${item.part_id}`;
  return item.part_name ? `${number} — ${item.part_name}` : number;
}

function warehouseLabel(name: string | null | undefined, id: number | null | undefined): string {
  return name || (id ? `Warehouse #${id}` : "Not assigned");
}

export default function WarehouseTasksPage() {
  const [notifications, setNotifications] = useState<InventoryNotification[]>([]);
  const [requests, setRequests] = useState<ReplenishmentRequest[]>([]);
  const [vehicleReturns, setVehicleReturns] = useState<VehicleReturnRequest[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [sourceSelections, setSourceSelections] = useState<Record<number, number | "">>({});
  const [requestQuantities, setRequestQuantities] = useState<Record<number, number>>({});
  const [manualRequest, setManualRequest] = useState<ManualRequestForm>(emptyManualRequest);
  const [manualClientRequestId, setManualClientRequestId] = useState("");
  const [reconciliationDrafts, setReconciliationDrafts] = useState<Record<number, ReconciliationDraft>>({});
  const [online, setOnline] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [rowErrors, setRowErrors] = useState<Record<number, string>>({});
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [notificationRows, requestRows, returnRows, warehouseRows, partRows] = await Promise.all([
        api.listInventoryNotifications(),
        api.listReplenishmentRequests(),
        api.listVehicleReturnRequests(),
        api.listWarehouses(),
        api.listParts()
      ]);
      setNotifications(notificationRows);
      setRequests(requestRows);
      setVehicleReturns(returnRows);
      setWarehouses(warehouseRows);
      setParts(partRows);
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to load warehouse tasks.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    setOnline(navigator.onLine);
    const onOnline = () => setOnline(true);
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    return () => {
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
    };
  }, [refresh]);

  const metrics = useMemo(() => ({
    queue: requests.filter((item) => item.status === "requested" || item.status === "picking").length,
    waiting: requests.filter((item) => item.status === "shipped").length,
    returns: vehicleReturns.filter((item) => !["received", "cancelled"].includes(item.status)).length
  }), [requests, vehicleReturns]);
  const vehicleWarehouses = useMemo(
    () => warehouses.filter((warehouse) =>
      warehouse.is_active !== false
      && warehouse.warehouse_type?.toLowerCase() === "van"
      && Boolean(warehouse.assigned_user_id)),
    [warehouses]
  );
  const sourceWarehouses = useMemo(
    () => warehouses.filter((warehouse) =>
      warehouse.is_active !== false
      && warehouse.warehouse_type?.toLowerCase() !== "van"),
    [warehouses]
  );

  const acknowledge = async (id: number) => {
    setBusy(`notification-${id}`);
    setMessage("");
    try {
      await api.updateInventoryNotification(id, "acknowledged");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to acknowledge alert.");
    } finally {
      setBusy("");
    }
  };

  const createRequest = async (id: number) => {
    setBusy(`notification-${id}`);
    setMessage("");
    try {
      const quantity = Math.max(1, requestQuantities[id] || 1);
      await api.createReplenishmentRequest(id, quantity);
      setMessage(`Replenishment request created for ${quantity} item${quantity === 1 ? "" : "s"}.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create replenishment request.");
    } finally {
      setBusy("");
    }
  };

  const updateManualRequest = (update: Partial<ManualRequestForm>) => {
    setManualRequest((current) => ({ ...current, ...update }));
    setManualClientRequestId("");
  };

  const createManualRequest = async () => {
    const reason = manualRequest.reason.trim();
    if (!online) {
      setError("Reconnect before creating a replenishment request.");
      return;
    }
    if (!manualRequest.partId || !manualRequest.destinationWarehouseId || reason.length < 3) {
      setError("Select a part and destination vehicle, then enter a reason of at least 3 characters.");
      return;
    }
    const clientRequestId = manualClientRequestId || window.crypto.randomUUID();
    if (!manualClientRequestId) setManualClientRequestId(clientRequestId);
    setBusy("manual-request");
    setError("");
    setMessage("");
    try {
      const created = await api.createManualReplenishmentRequest({
        part_id: Number(manualRequest.partId),
        destination_warehouse_id: Number(manualRequest.destinationWarehouseId),
        quantity: Math.max(1, manualRequest.quantity),
        ...(manualRequest.sourceWarehouseId ? { source_warehouse_id: Number(manualRequest.sourceWarehouseId) } : {}),
        reason,
        client_request_id: clientRequestId
      });
      setMessage(`Manual replenishment request #${created.id} created for ${created.target_user_name || "the selected vehicle"}.`);
      setManualRequest(emptyManualRequest);
      setManualClientRequestId("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create manual replenishment request.");
    } finally {
      setBusy("");
    }
  };

  const runAction = async (
    item: ReplenishmentRequest,
    action: ReplenishmentAction,
    extras: { source_warehouse_id?: number; reason?: string } = {}
  ) => {
    setBusy(`request-${item.id}`);
    setMessage("");
    setRowErrors((current) => ({ ...current, [item.id]: "" }));
    try {
      await api.actOnReplenishmentRequest(item.id, {
        action,
        expected_version: item.version,
        ...extras
      });
      setMessage(`Request #${item.id} updated successfully.`);
      await refresh();
    } catch (e) {
      setRowErrors((current) => ({
        ...current,
        [item.id]: e instanceof Error ? e.message : "Unable to update replenishment request."
      }));
    } finally {
      setBusy("");
    }
  };

  const startPicking = (item: ReplenishmentRequest) => {
    const selected = sourceSelections[item.id] || item.source_warehouse_id || "";
    if (!selected) {
      setRowErrors((current) => ({ ...current, [item.id]: "Select the source warehouse before picking." }));
      return;
    }
    void runAction(item, "start_picking", { source_warehouse_id: Number(selected) });
  };

  const cancelRequest = (item: ReplenishmentRequest) => {
    const reason = window.prompt("Reason for cancelling this replenishment request:")?.trim();
    if (!reason) return;
    void runAction(item, "cancel", { reason });
  };

  const rejectRequest = (item: ReplenishmentRequest) => {
    const reason = window.prompt("Reason for rejecting this replenishment request:")?.trim();
    if (!reason) return;
    void runAction(item, "reject", { reason });
  };

  const reconciliationDraft = (item: ReplenishmentRequest): ReconciliationDraft =>
    reconciliationDrafts[item.id] || {
      resolution: item.status === "completed" ? "accept_historical" : "reset_requested",
      reason: "",
      password: ""
    };

  const updateReconciliationDraft = (item: ReplenishmentRequest, update: Partial<ReconciliationDraft>) => {
    setReconciliationDrafts((current) => ({
      ...current,
      [item.id]: {
        ...(current[item.id] || {
          resolution: item.status === "completed" ? "accept_historical" : "reset_requested",
          reason: "",
          password: ""
        }),
        ...update
      }
    }));
  };

  const reconcileRequest = async (item: ReplenishmentRequest) => {
    const draft = reconciliationDraft(item);
    if (!online) {
      setRowErrors((current) => ({ ...current, [item.id]: "Reconnect before reconciling historical custody." }));
      return;
    }
    if (draft.reason.trim().length < 3 || !draft.password) {
      setRowErrors((current) => ({ ...current, [item.id]: "Enter a reconciliation reason and your current password." }));
      return;
    }
    setBusy(`reconcile-${item.id}`);
    setMessage("");
    setRowErrors((current) => ({ ...current, [item.id]: "" }));
    try {
      await api.reconcileReplenishmentRequest(item.id, {
        expected_version: item.version,
        resolution: draft.resolution,
        reason: draft.reason.trim(),
        account_password: draft.password
      });
      setMessage(`Historical request #${item.id} reconciled.`);
      setReconciliationDrafts((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      await refresh();
    } catch (e) {
      setRowErrors((current) => ({
        ...current,
        [item.id]: e instanceof Error ? e.message : "Unable to reconcile historical request."
      }));
    } finally {
      setReconciliationDrafts((current) => current[item.id]
        ? { ...current, [item.id]: { ...current[item.id], password: "" } }
        : current);
      setBusy("");
    }
  };

  const runReturnAction = async (
    item: VehicleReturnRequest,
    action: "approve" | "receive" | "cancel",
    reason?: string
  ) => {
    setBusy(`return-${item.id}`);
    setError("");
    setMessage("");
    try {
      await api.actOnVehicleReturnRequest(item.id, {
        action,
        expected_version: item.version,
        ...(reason ? { reason } : {})
      });
      setMessage(`Vehicle return #${item.id} updated.`);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to update vehicle return.");
    } finally {
      setBusy("");
    }
  };

  const cancelVehicleReturn = (item: VehicleReturnRequest) => {
    const reason = window.prompt("Reason for cancelling this vehicle return:")?.trim();
    if (reason) void runReturnAction(item, "cancel", reason);
  };

  return (
    <ManagerShell
      title="Warehouse tasks"
      subtitle="Move each replenishment through an accountable warehouse-to-vehicle custody chain."
      metrics={[
        { label: "Pick queue", value: metrics.queue },
        { label: "Awaiting receipt", value: metrics.waiting },
        { label: "Vehicle returns", value: metrics.returns }
      ]}
    >
      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice notice-success">{message}</div>}

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>New vehicle replenishment</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Create a first-fill or ad-hoc request when no low-stock alert exists.
            </p>
          </div>
          <span className="status-pill status-pill--requested">online only</span>
        </div>
        {!online && <div className="notice notice-error">Reconnect before creating a replenishment request.</div>}
        <div className="manual-replenishment-form">
          <label>
            <span>Part</span>
            <select
              value={manualRequest.partId}
              disabled={busy === "manual-request"}
              onChange={(event) => updateManualRequest({ partId: event.target.value ? Number(event.target.value) : "" })}
            >
              <option value="">Select part</option>
              {parts.filter((part) => part.is_active).map((part) => (
                <option value={part.id} key={part.id}>{part.part_number} — {part.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Destination vehicle</span>
            <select
              value={manualRequest.destinationWarehouseId}
              disabled={busy === "manual-request"}
              onChange={(event) => updateManualRequest({
                destinationWarehouseId: event.target.value ? Number(event.target.value) : ""
              })}
            >
              <option value="">Select assigned vehicle</option>
              {vehicleWarehouses.map((warehouse) => (
                <option value={warehouse.id} key={warehouse.id}>
                  {warehouse.name} · Engineer #{warehouse.assigned_user_id}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Source warehouse (optional)</span>
            <select
              value={manualRequest.sourceWarehouseId}
              disabled={busy === "manual-request"}
              onChange={(event) => updateManualRequest({
                sourceWarehouseId: event.target.value ? Number(event.target.value) : ""
              })}
            >
              <option value="">Assign during picking</option>
              {sourceWarehouses.map((warehouse) => (
                <option value={warehouse.id} key={warehouse.id}>{warehouse.name}</option>
              ))}
            </select>
          </label>
          <label>
            <span>Quantity</span>
            <input
              type="number"
              min={1}
              value={manualRequest.quantity}
              disabled={busy === "manual-request"}
              onChange={(event) => updateManualRequest({ quantity: Math.max(1, Number(event.target.value) || 1) })}
            />
          </label>
          <label className="manual-replenishment-form__reason">
            <span>Business reason</span>
            <textarea
              rows={3}
              maxLength={500}
              placeholder="Example: first vehicle stock allocation for a new engineer"
              value={manualRequest.reason}
              disabled={busy === "manual-request"}
              onChange={(event) => updateManualRequest({ reason: event.target.value })}
            />
          </label>
        </div>
        <button
          type="button"
          style={{ marginTop: 12 }}
          disabled={
            busy === "manual-request"
            || !online
            || !manualRequest.partId
            || !manualRequest.destinationWarehouseId
            || manualRequest.reason.trim().length < 3
          }
          onClick={() => void createManualRequest()}
        >
          {busy === "manual-request" ? "Creating…" : "Create vehicle replenishment"}
        </button>
        {manualClientRequestId && busy !== "manual-request" && (
          <p className="muted" style={{ marginBottom: 0 }}>
            A safe retry will reuse the same request identity until you change this form.
          </p>
        )}
      </section>

      <section className="card">
        <h3>Low-stock alerts</h3>
        {notifications.length === 0 ? (
          <div className="empty-state">No open warehouse alerts.</div>
        ) : (
          <div className="warehouse-task-grid">
            {notifications.map((item) => {
              const notificationBusy = busy === `notification-${item.id}`;
              return (
                <div className="job-card" key={item.id}>
                  <strong>Part #{item.part_id}</strong>
                  <div className="muted">Warehouse #{item.warehouse_id} · Work order {item.work_order_id || "—"}</div>
                  <p style={{ margin: "8px 0" }}>{item.message}</p>
                  <label className="field-label" htmlFor={`request-quantity-${item.id}`}>Request quantity</label>
                  <input
                    id={`request-quantity-${item.id}`}
                    type="number"
                    min={1}
                    value={requestQuantities[item.id] || 1}
                    onChange={(event) => setRequestQuantities((current) => ({
                      ...current,
                      [item.id]: Math.max(1, Number(event.target.value) || 1)
                    }))}
                  />
                  <div className="one-hand-actions">
                    <button type="button" disabled={notificationBusy} onClick={() => void createRequest(item.id)}>
                      {notificationBusy ? "Working…" : "Create request"}
                    </button>
                    <button type="button" disabled={notificationBusy} onClick={() => void acknowledge(item.id)}>
                      Acknowledge
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Vehicle returns</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Approve requested quantities, wait for the engineer&apos;s authenticated handover, then receive into the warehouse.
            </p>
          </div>
          <span className="status-count">{vehicleReturns.length}</span>
        </div>
        {vehicleReturns.length === 0 ? (
          <div className="empty-state">No vehicle return requests.</div>
        ) : (
          <div className="warehouse-task-grid">
            {vehicleReturns.map((item) => {
              const returnBusy = busy === `return-${item.id}`;
              return (
                <article className="job-card replenishment-card" key={item.id}>
                  <div className="section-heading-row">
                    <div>
                      <strong>{item.part_number || `Part #${item.part_id}`} — {item.part_name}</strong>
                      <div className="muted">Qty {item.quantity} · Return #{item.id} · v{item.version}</div>
                    </div>
                    <span className={`status-pill status-pill--${item.status}`}>{item.status}</span>
                  </div>
                  <div className="custody-route">
                    <div>
                      <span className="muted">Engineer vehicle</span>
                      <strong>{item.source_warehouse_name}</strong>
                      <span className="muted">{item.engineer_name}</span>
                    </div>
                    <span aria-hidden="true">→</span>
                    <div>
                      <span className="muted">Destination</span>
                      <strong>{item.destination_warehouse_name}</strong>
                    </div>
                  </div>
                  <div className="notice" style={{ marginTop: 10 }}>{item.reason}</div>
                  <div className="muted">Vehicle stock: {item.source_quantity} · Warehouse stock: {item.destination_quantity}</div>
                  {item.status === "approved" && (
                    <p className="muted">Reserved. Waiting for {item.engineer_name || "the engineer"} to confirm handover.</p>
                  )}
                  {item.status === "shipped" && (
                    <p className="muted">Engineer handover verified on {item.shipped_device_name || "registered device"}.</p>
                  )}
                  {item.shipment_transaction_id && <div className="muted">Vehicle outbound transaction #{item.shipment_transaction_id}</div>}
                  {item.receipt_transaction_id && <div className="muted">Warehouse inbound transaction #{item.receipt_transaction_id}</div>}
                  <div className="one-hand-actions">
                    {item.can_approve && (
                      <button type="button" disabled={returnBusy || !online} onClick={() => void runReturnAction(item, "approve") }>
                        Approve and reserve
                      </button>
                    )}
                    {item.can_receive && (
                      <button type="button" disabled={returnBusy || !online} onClick={() => void runReturnAction(item, "receive") }>
                        Receive into warehouse
                      </button>
                    )}
                    {item.can_cancel && (
                      <button type="button" className="secondary-button" disabled={returnBusy} onClick={() => cancelVehicleReturn(item)}>
                        Cancel return
                      </button>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>

      {workflowGroups.map((group) => {
        const rows = requests.filter((item) => group.statuses.includes(item.status));
        return (
          <section className="card" key={group.title}>
            <div className="section-heading-row">
              <div>
                <h3 style={{ margin: 0 }}>{group.title}</h3>
                <p className="muted" style={{ margin: "4px 0 0" }}>{group.description}</p>
              </div>
              <span className="status-count">{rows.length}</span>
            </div>
            {rows.length === 0 ? (
              <div className="empty-state">No requests in this stage.</div>
            ) : (
              <div className="warehouse-task-grid">
                {rows.map((item) => {
                  const requestBusy = busy === `request-${item.id}`;
                  const reconciliationBusy = busy === `reconcile-${item.id}`;
                  const draft = reconciliationDraft(item);
                  const selectedSource = sourceSelections[item.id] ?? item.source_warehouse_id ?? "";
                  const hasActions = !item.requires_reconciliation
                    && (item.can_approve || item.can_reject || item.can_start_picking || item.can_ship || item.can_complete || item.can_cancel);
                  return (
                    <article className="job-card replenishment-card" key={item.id}>
                      <div className="section-heading-row">
                        <div>
                          <strong>{partLabel(item)}</strong>
                          <div className="muted">Request #{item.id} · Qty {item.quantity} · v{item.version}</div>
                        </div>
                        <span className={`status-pill status-pill--${item.status}`}>{item.status}</span>
                      </div>

                      <div className="custody-route">
                        <div>
                          <span className="muted">Source</span>
                          <strong>{warehouseLabel(item.source_warehouse_name, item.source_warehouse_id)}</strong>
                        </div>
                        <span aria-hidden="true">→</span>
                        <div>
                          <span className="muted">Destination</span>
                          <strong>{warehouseLabel(item.destination_warehouse_name, item.destination_warehouse_id)}</strong>
                          <span className="muted">{item.target_user_name || "No engineer assigned"}</span>
                        </div>
                      </div>

                      {(item.source_available_quantity !== null && item.source_available_quantity !== undefined) && (
                        <div className="muted" style={{ marginTop: 8 }}>Source available: {item.source_available_quantity}</div>
                      )}
                      {(item.destination_quantity !== null && item.destination_quantity !== undefined) && (
                        <div className="muted">Destination stock: {item.destination_quantity}</div>
                      )}
                      {item.work_order_id && (
                        <div className="muted">Work order: {item.work_order_ticket_number || `#${item.work_order_id}`}</div>
                      )}
                      {item.request_reason && (
                        <div className="notice" style={{ marginTop: 10 }}>
                          <strong>Request reason</strong>
                          <div>{item.request_reason}</div>
                        </div>
                      )}
                      {item.status === "requested" && (
                        <div className={`notice ${item.approval_status === "pending" ? "notice-warn" : ""}`} style={{ marginTop: 10 }}>
                          <strong>Approval: {item.approval_status}</strong>
                          {item.approved_by_name && <div>Approved by {item.approved_by_name}</div>}
                        </div>
                      )}
                      {item.status === "rejected" && (
                        <div className="notice notice-error" style={{ marginTop: 10 }}>
                          <strong>Rejected by {item.rejected_by_name || "authorized approver"}</strong>
                          <div>{item.rejection_reason}</div>
                        </div>
                      )}

                      {!item.requires_reconciliation && item.can_start_picking && (
                        <label className="replenishment-source-select">
                          <span>Source warehouse</span>
                          <select
                            value={selectedSource}
                            onChange={(event) => setSourceSelections((current) => ({
                              ...current,
                              [item.id]: event.target.value ? Number(event.target.value) : ""
                            }))}
                            disabled={requestBusy}
                          >
                            <option value="">Select source warehouse</option>
                            {sourceWarehouses.map((warehouse) => (
                              <option value={warehouse.id} key={warehouse.id}>{warehouse.name}</option>
                            ))}
                          </select>
                        </label>
                      )}

                      <ReplenishmentTimeline item={item} />

                      {item.requires_reconciliation && (
                        <div className="reconciliation-panel">
                          <div className="notice notice-warn" style={{ marginTop: 0 }}>
                            <strong>Historical reconciliation required</strong>
                            <div>
                              This legacy status has no trustworthy linked inventory movements. Normal workflow actions are locked.
                            </div>
                          </div>
                          {item.can_reconcile ? (
                            <>
                              <label>
                                <span>Administrator resolution</span>
                                <select
                                  value={draft.resolution}
                                  disabled={reconciliationBusy}
                                  onChange={(event) => updateReconciliationDraft(item, {
                                    resolution: event.target.value as ReconciliationResolution
                                  })}
                                >
                                  <option value="reset_requested" disabled={item.status !== "requested"}>
                                    Reset to requested — restart verified workflow
                                  </option>
                                  <option value="accept_historical" disabled={item.status !== "completed"}>
                                    Accept historical — retain completed status
                                  </option>
                                </select>
                              </label>
                              <label>
                                <span>Reconciliation reason</span>
                                <textarea
                                  rows={3}
                                  maxLength={500}
                                  value={draft.reason}
                                  disabled={reconciliationBusy}
                                  onChange={(event) => updateReconciliationDraft(item, { reason: event.target.value })}
                                />
                              </label>
                              <label>
                                <span>Current administrator password</span>
                                <input
                                  type="password"
                                  autoComplete="current-password"
                                  value={draft.password}
                                  disabled={reconciliationBusy}
                                  onChange={(event) => updateReconciliationDraft(item, { password: event.target.value })}
                                />
                              </label>
                              <p className="muted">Reconciliation is online-only, audited, and never fabricates inventory movements.</p>
                              <button
                                type="button"
                                disabled={
                                  reconciliationBusy
                                  || !online
                                  || draft.reason.trim().length < 3
                                  || !draft.password
                                }
                                onClick={() => void reconcileRequest(item)}
                              >
                                {reconciliationBusy ? "Reconciling…" : "Confirm reconciliation"}
                              </button>
                            </>
                          ) : (
                            <p className="muted" style={{ marginBottom: 0 }}>
                              Administrator review is required. This record remains read-only for your role.
                            </p>
                          )}
                        </div>
                      )}

                      {!item.requires_reconciliation && item.status === "shipped" && (
                        <div className="notice" style={{ marginTop: 10 }}>
                          Waiting for {item.target_user_name || "the destination engineer"} to confirm receipt on their registered phone.
                        </div>
                      )}
                      {item.shipment_transaction_id && <div className="muted">Shipment transaction #{item.shipment_transaction_id}</div>}
                      {item.receipt_transaction_id && <div className="muted">Receipt transaction #{item.receipt_transaction_id}</div>}
                      {rowErrors[item.id] && <div className="notice notice-error">{rowErrors[item.id]}</div>}

                      {hasActions ? (
                        <div className="one-hand-actions">
                          {item.can_approve && (
                            <button type="button" disabled={requestBusy || !online} onClick={() => void runAction(item, "approve")}>
                              Approve request
                            </button>
                          )}
                          {item.can_reject && (
                            <button type="button" className="secondary-button" disabled={requestBusy || !online} onClick={() => rejectRequest(item)}>
                              Reject request
                            </button>
                          )}
                          {item.can_start_picking && (
                            <button type="button" disabled={requestBusy || !selectedSource} onClick={() => startPicking(item)}>
                              {requestBusy ? "Working…" : "Start picking"}
                            </button>
                          )}
                          {item.can_ship && (
                            <button type="button" disabled={requestBusy} onClick={() => void runAction(item, "ship")}>
                              {requestBusy ? "Working…" : "Mark shipped"}
                            </button>
                          )}
                          {item.can_complete && (
                            <button type="button" disabled={requestBusy} onClick={() => void runAction(item, "complete")}>
                              {requestBusy ? "Working…" : "Complete task"}
                            </button>
                          )}
                          {item.can_cancel && (
                            <button type="button" className="secondary-button" disabled={requestBusy} onClick={() => cancelRequest(item)}>
                              Cancel
                            </button>
                          )}
                        </div>
                      ) : (
                        !item.requires_reconciliation && item.status !== "completed" && item.status !== "cancelled" && (
                          <div className="muted" style={{ marginTop: 10 }}>No action is available for your account at this stage.</div>
                        )
                      )}
                    </article>
                  );
                })}
              </div>
            )}
          </section>
        );
      })}
    </ManagerShell>
  );
}
