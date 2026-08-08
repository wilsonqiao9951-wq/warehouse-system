"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { AppRole, getCurrentRole } from "@/lib/role";
import { InventoryNotification, Part, StockThresholdRule, Warehouse } from "@/types";

type AlertStatus = "active" | "open" | "acknowledged" | "resolved" | "all";

interface RuleDraft {
  warehouseId: string;
  partId: string;
  threshold: string;
  reorder: string;
  reason: string;
  isActive: boolean;
  expectedVersion?: number;
}

const emptyDraft: RuleDraft = {
  warehouseId: "",
  partId: "",
  threshold: "0",
  reorder: "1",
  reason: "",
  isActive: true
};

function timeLabel(value?: string | null) {
  return value ? new Date(value).toLocaleString() : "—";
}

export default function LowStockRulesPage() {
  const [role, setRole] = useState<AppRole>("warehouse");
  const [rules, setRules] = useState<StockThresholdRule[]>([]);
  const [alerts, setAlerts] = useState<InventoryNotification[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [alertStatus, setAlertStatus] = useState<AlertStatus>("active");
  const [draft, setDraft] = useState<RuleDraft>(emptyDraft);
  const [actionNotes, setActionNotes] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const canManageRules = role === "admin" || role === "manager";

  const load = useCallback(async (status: AlertStatus) => {
    try {
      const [ruleRows, alertRows, warehouseRows, partRows] = await Promise.all([
        api.listStockThresholdRules(),
        api.listInventoryNotifications(status),
        api.listWarehouses(),
        api.listParts()
      ]);
      setRules(ruleRows);
      setAlerts(alertRows);
      setWarehouses(warehouseRows);
      setParts(partRows);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load low-stock controls.");
    }
  }, []);

  useEffect(() => {
    setRole(getCurrentRole());
  }, []);

  useEffect(() => {
    void load(alertStatus);
  }, [alertStatus, load]);

  const metrics = useMemo(() => ({
    overrides: rules.filter((item) => item.is_active).length,
    open: alerts.filter((item) => item.status === "open").length,
    acknowledged: alerts.filter((item) => item.status === "acknowledged").length,
    recovered: alerts.filter((item) => item.recovered && item.status !== "resolved").length
  }), [alerts, rules]);

  const selectRule = (rule: StockThresholdRule) => {
    setDraft({
      warehouseId: String(rule.warehouse_id),
      partId: String(rule.part_id),
      threshold: String(rule.threshold_quantity),
      reorder: String(rule.reorder_quantity),
      reason: rule.reason,
      isActive: rule.is_active,
      expectedVersion: rule.version
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const saveRule = async (event: FormEvent) => {
    event.preventDefault();
    const warehouseId = Number(draft.warehouseId);
    const partId = Number(draft.partId);
    const threshold = Number(draft.threshold);
    const reorder = Number(draft.reorder);
    if (!warehouseId || !partId || !Number.isInteger(threshold) || threshold < 0 || !Number.isInteger(reorder) || reorder < 1) {
      setError("Select a warehouse and part, then enter valid whole-number quantities.");
      return;
    }
    if (draft.reason.trim().length < 3) {
      setError("Record a business reason of at least three characters.");
      return;
    }
    setBusy("rule");
    setError("");
    setMessage("");
    try {
      const saved = await api.saveStockThresholdRule(warehouseId, partId, {
        threshold_quantity: threshold,
        reorder_quantity: reorder,
        is_active: draft.isActive,
        reason: draft.reason.trim(),
        ...(draft.expectedVersion === undefined ? {} : { expected_version: draft.expectedVersion })
      });
      setMessage(`Saved ${saved.part_number} at ${saved.warehouse_name}; version ${saved.version}.`);
      setDraft(emptyDraft);
      await load(alertStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save threshold rule.");
    } finally {
      setBusy("");
    }
  };

  const evaluate = async () => {
    setBusy("evaluate");
    setError("");
    setMessage("");
    try {
      const result = await api.evaluateLowStock();
      setMessage(
        `Scanned ${result.scanned} positions: ${result.below_threshold} below threshold, ${result.created} new alerts, ${result.recovered_active} recovered alerts awaiting closure.`
      );
      await load(alertStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to evaluate inventory.");
    } finally {
      setBusy("");
    }
  };

  const act = async (item: InventoryNotification, action: "acknowledge" | "resolve") => {
    const evidence = (actionNotes[item.id] || "").trim();
    if (evidence.length < 3) {
      setError(`${action === "acknowledge" ? "Acknowledgement note" : "Resolution reason"} must be at least three characters.`);
      return;
    }
    setBusy(`alert-${item.id}`);
    setError("");
    setMessage("");
    try {
      const updated = await api.actOnInventoryNotification(item.id, {
        action,
        expected_version: item.version,
        ...(action === "acknowledge" ? { note: evidence } : { reason: evidence })
      });
      setMessage(`Alert #${item.id} is now ${updated.status}; action attributed to the signed-in account.`);
      setActionNotes((current) => ({ ...current, [item.id]: "" }));
      await load(alertStatus);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to update low-stock alert.");
    } finally {
      setBusy("");
    }
  };

  return (
    <ManagerShell
      title="Low-stock Rules & Evidence"
      subtitle="Govern warehouse-specific thresholds and close alerts only after accountable review and verified recovery."
      metrics={[
        { label: "Active overrides", value: metrics.overrides },
        { label: "Open shown", value: metrics.open },
        { label: "Acknowledged shown", value: metrics.acknowledged },
        { label: "Recovered to close", value: metrics.recovered }
      ]}
    >
      {error && <div className="notice notice-error">{error}</div>}
      {message && <div className="notice">{message}</div>}

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Inventory evaluation</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>
              Scan every tenant part/warehouse position. Recovered alerts remain visible until an operator records a closure reason.
            </p>
          </div>
          <button type="button" disabled={busy === "evaluate"} onClick={() => void evaluate()}>
            {busy === "evaluate" ? "Scanning…" : "Evaluate now"}
          </button>
        </div>
      </section>

      {canManageRules && (
        <section className="card">
          <div className="section-heading-row">
            <div>
              <h3 style={{ margin: 0 }}>{draft.expectedVersion === undefined ? "New threshold override" : "Edit threshold override"}</h3>
              <p className="muted" style={{ margin: "4px 0 0" }}>Saving a stale version is refused so two managers cannot overwrite each other.</p>
            </div>
            {draft.expectedVersion !== undefined && (
              <button type="button" className="secondary" onClick={() => setDraft(emptyDraft)}>Cancel edit</button>
            )}
          </div>
          <form className="filter-grid" onSubmit={saveRule}>
            <label>
              Warehouse
              <select
                value={draft.warehouseId}
                disabled={draft.expectedVersion !== undefined}
                onChange={(event) => setDraft((current) => ({ ...current, warehouseId: event.target.value }))}
                required
              >
                <option value="">Select warehouse</option>
                {warehouses.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
              </select>
            </label>
            <label>
              Part
              <select
                value={draft.partId}
                disabled={draft.expectedVersion !== undefined}
                onChange={(event) => setDraft((current) => ({ ...current, partId: event.target.value }))}
                required
              >
                <option value="">Select part</option>
                {parts.map((item) => <option key={item.id} value={item.id}>{item.part_number} · {item.name}</option>)}
              </select>
            </label>
            <label>
              Alert at or below
              <input type="number" min={0} step={1} value={draft.threshold} onChange={(event) => setDraft((current) => ({ ...current, threshold: event.target.value }))} required />
            </label>
            <label>
              Suggested replenishment
              <input type="number" min={1} step={1} value={draft.reorder} onChange={(event) => setDraft((current) => ({ ...current, reorder: event.target.value }))} required />
            </label>
            <label style={{ gridColumn: "1 / -1" }}>
              Business reason
              <input maxLength={500} value={draft.reason} onChange={(event) => setDraft((current) => ({ ...current, reason: event.target.value }))} required />
            </label>
            <label className="checkbox-row">
              <input type="checkbox" checked={draft.isActive} onChange={(event) => setDraft((current) => ({ ...current, isActive: event.target.checked }))} />
              Rule active
            </label>
            <button type="submit" disabled={busy === "rule"}>{busy === "rule" ? "Saving…" : "Save version"}</button>
          </form>
        </section>
      )}

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Threshold overrides</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>Inactive rows fall back to the part-level safety/minimum threshold.</p>
          </div>
          <span className="status-count">{rules.length}</span>
        </div>
        {rules.length === 0 ? <div className="empty-state">No warehouse-specific overrides.</div> : (
          <div className="warehouse-task-grid">
            {rules.map((item) => (
              <article className="job-card" key={item.id}>
                <strong>{item.part_number} · {item.part_name}</strong>
                <div className="muted">{item.warehouse_name}</div>
                <p>Alert at ≤ <strong>{item.threshold_quantity}</strong> · replenish <strong>{item.reorder_quantity}</strong></p>
                <div className="muted">{item.is_active ? "Active" : "Inactive"} · version {item.version} · {item.reason}</div>
                <div className="muted">Updated by {item.updated_by_name || "system"} · {timeLabel(item.updated_at)}</div>
                {canManageRules && <button type="button" className="secondary" onClick={() => selectRule(item)}>Edit</button>}
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="card">
        <div className="section-heading-row">
          <div>
            <h3 style={{ margin: 0 }}>Alert evidence</h3>
            <p className="muted" style={{ margin: "4px 0 0" }}>The trigger threshold is immutable; current recovery uses the latest active rule.</p>
          </div>
          <select aria-label="Alert status" value={alertStatus} onChange={(event) => setAlertStatus(event.target.value as AlertStatus)}>
            <option value="active">Active</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="all">All</option>
          </select>
        </div>
        {alerts.length === 0 ? <div className="empty-state">No alerts match this status.</div> : (
          <div className="warehouse-task-grid">
            {alerts.map((item) => (
              <article className="job-card" key={item.id}>
                <div className="section-heading-row">
                  <strong>{item.part_number || `Part #${item.part_id}`}</strong>
                  <span className={`status-pill status-pill--${item.status}`}>{item.status}</span>
                </div>
                <div className="muted">{item.warehouse_name || `Warehouse #${item.warehouse_id}`}</div>
                <p>{item.message}</p>
                <div className="muted">
                  Trigger {item.observed_quantity ?? "—"} at threshold {item.threshold_quantity}; current {item.current_quantity} against effective {item.effective_threshold_quantity}.
                </div>
                <div className="muted">Source: {item.threshold_source === "override" ? "warehouse override" : "part default"} · version {item.version}</div>
                {item.acknowledged_at && <div className="muted">Acknowledged by {item.acknowledged_by_name || "system"} · {timeLabel(item.acknowledged_at)} · {item.acknowledgement_note || "no note"}</div>}
                {item.resolved_at && <div className="muted">Resolved by {item.resolved_by_name || "system"} · {timeLabel(item.resolved_at)} · {item.resolution_reason}</div>}
                {item.linked_replenishment_id && (
                  <div className="muted">Replenishment #{item.linked_replenishment_id} · {item.linked_replenishment_status}</div>
                )}
                {(item.can_acknowledge || item.can_resolve) && (
                  <>
                    <label>
                      {item.can_acknowledge ? "Acknowledgement note" : "Resolution reason"}
                      <input
                        maxLength={500}
                        value={actionNotes[item.id] || ""}
                        onChange={(event) => setActionNotes((current) => ({ ...current, [item.id]: event.target.value }))}
                      />
                    </label>
                    <div className="one-hand-actions">
                      {item.can_acknowledge && <button type="button" disabled={busy === `alert-${item.id}`} onClick={() => void act(item, "acknowledge")}>Acknowledge</button>}
                      {item.can_resolve && <button type="button" disabled={busy === `alert-${item.id}`} onClick={() => void act(item, "resolve")}>Resolve with evidence</button>}
                    </div>
                  </>
                )}
                {item.status === "acknowledged" && !item.can_resolve && (
                  <div className="notice">Keep open: stock has not recovered and linked replenishment is not completed.</div>
                )}
              </article>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginBottom: 0 }}><Link href="/warehouse-tasks">Open replenishment custody workflows</Link></p>
      </section>
    </ManagerShell>
  );
}
