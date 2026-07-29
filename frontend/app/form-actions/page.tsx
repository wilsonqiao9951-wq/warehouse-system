"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { WorkOrderFormAction } from "@/types";

type StatusFilter = "pending" | "acknowledged" | "resolved" | "all";
type TypeFilter = "notification" | "inventory_review" | "all";

export default function FormActionsPage() {
  const [tasks, setTasks] = useState<WorkOrderFormAction[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [typeFilter, setTypeFilter] = useState<TypeFilter>("all");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.listWorkOrderFormActions({
        status: statusFilter === "all" ? undefined : statusFilter,
        action_type: typeFilter === "all" ? undefined : typeFilter
      });
      setTasks(rows);
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to load form actions."
      });
      setTasks([]);
    } finally {
      setLoading(false);
    }
  }, [statusFilter, typeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => ({
    pending: tasks.filter((task) => task.status === "pending").length,
    inventory: tasks.filter((task) => task.action_type === "inventory_review").length,
    notifications: tasks.filter((task) => task.action_type === "notification").length
  }), [tasks]);

  const updateTask = async (
    task: WorkOrderFormAction,
    action: "acknowledge" | "resolve"
  ) => {
    const resolutionNotes = (notes[task.id] || "").trim();
    if (
      action === "resolve"
      && task.action_type === "inventory_review"
      && resolutionNotes.length < 3
    ) {
      setNotice({
        type: "error",
        text: "Inventory review resolution needs notes describing the separate custody or replenishment action."
      });
      return;
    }
    try {
      setBusyId(task.id);
      await api.updateWorkOrderFormAction(task.id, {
        expected_version: task.version,
        action,
        resolution_notes: resolutionNotes || null
      });
      setNotice({
        type: "success",
        text: action === "acknowledge" ? "Action acknowledged." : "Action resolved with an audit trail."
      });
      setNotes((current) => ({ ...current, [task.id]: "" }));
      await load();
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to update form action."
      });
    } finally {
      setBusyId(null);
    }
  };

  return (
    <ManagerShell
      title="Configured Form Actions"
      subtitle="Review notifications and declared inventory impacts created by verified work-order form changes."
      metrics={[
        { label: "Shown", value: tasks.length },
        { label: "Pending shown", value: counts.pending },
        { label: "Inventory reviews", value: counts.inventory },
        { label: "Notifications", value: counts.notifications }
      ]}
    >
      <p className="notice">
        An inventory-review task never changes stock. Complete any physical movement through the existing replenishment,
        transfer, return, or count workflow, then record the result here.
      </p>
      {notice && (
        <p className={`notice ${notice.type === "success" ? "notice-success" : "notice-error"}`}>
          {notice.text}
        </p>
      )}
      <section className="card">
        <div className="two-col">
          <label>Status
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="pending">Pending</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
              <option value="all">All</option>
            </select>
          </label>
          <label>Action type
            <select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value as TypeFilter)}>
              <option value="all">All action types</option>
              <option value="notification">Notification</option>
              <option value="inventory_review">Inventory review</option>
            </select>
          </label>
        </div>
      </section>

      {loading ? (
        <section className="card"><div className="skeleton" /></section>
      ) : tasks.length === 0 ? (
        <section className="card"><div className="empty-state">No actions match the selected filters.</div></section>
      ) : (
        <section style={{ display: "grid", gap: 12 }}>
          {tasks.map((task) => (
            <article className="card" key={task.id}>
              <div className="one-hand-actions" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>{task.action_type === "inventory_review" ? "Inventory review" : "Operational notification"}</strong>
                  <span className="muted"> · {task.status} · revision {task.version}</span>
                </div>
                <Link className="nav-item" href={`/work-order-details?work_order_id=${task.work_order_id}`}>
                  {task.work_order_ticket_number}
                </Link>
              </div>
              <p>
                <strong>{task.field_label}</strong>
                <span className="muted"> · {task.template_name || "Configured form"} · form revision {task.triggered_form_version}</span>
              </p>
              <p className="muted">
                Triggered {new Date(task.created_at).toLocaleString()}
                {task.created_by_name ? ` by ${task.created_by_name}` : ""}.
              </p>
              {task.acknowledged_at && (
                <p className="muted">
                  Acknowledged {new Date(task.acknowledged_at).toLocaleString()}
                  {task.acknowledged_by_name ? ` by ${task.acknowledged_by_name}` : ""}.
                </p>
              )}
              {task.resolved_at && (
                <p className="notice notice-success">
                  Resolved {new Date(task.resolved_at).toLocaleString()}
                  {task.resolved_by_name ? ` by ${task.resolved_by_name}` : ""}
                  {task.resolution_notes ? ` · ${task.resolution_notes}` : ""}
                </p>
              )}
              {(task.can_acknowledge || task.can_resolve) && task.status !== "resolved" && (
                <>
                  <label>
                    Resolution notes {task.action_type === "inventory_review" && "(required to resolve)"}
                    <textarea
                      rows={2}
                      value={notes[task.id] || ""}
                      placeholder={
                        task.action_type === "inventory_review"
                          ? "Example: replenishment request #123 opened; no direct stock mutation from form."
                          : "Optional response or dispatch note"
                      }
                      onChange={(event) => setNotes((current) => ({
                        ...current,
                        [task.id]: event.target.value
                      }))}
                    />
                  </label>
                  <div className="one-hand-actions">
                    {task.can_acknowledge && (
                      <button type="button" disabled={busyId === task.id} onClick={() => void updateTask(task, "acknowledge")}>
                        Acknowledge
                      </button>
                    )}
                    {task.can_resolve && (
                      <button type="button" disabled={busyId === task.id} onClick={() => void updateTask(task, "resolve")}>
                        Resolve
                      </button>
                    )}
                    {task.action_type === "inventory_review" && (
                      <Link className="nav-item" href="/warehouse-tasks">Open warehouse workflows</Link>
                    )}
                  </div>
                </>
              )}
            </article>
          ))}
        </section>
      )}
    </ManagerShell>
  );
}
