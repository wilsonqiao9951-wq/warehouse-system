"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import {
  WorkOrderFormConflict,
  WorkOrderFormConflictStatus,
  WorkOrderFormValue
} from "@/types";

type StatusFilter = WorkOrderFormConflictStatus | "all";
type ValueSource = "server" | "local";

function valueSummary(value: WorkOrderFormValue | undefined): string {
  if (value === undefined) return "Not present";
  if (value === null) return "Empty";
  if (typeof value === "string" && value.startsWith("data:image/png;base64,")) {
    return "Captured signature";
  }
  const displayed = typeof value === "string" ? value : JSON.stringify(value);
  return displayed.length > 120 ? `${displayed.slice(0, 117)}…` : displayed;
}

export default function SyncConflictsPage() {
  const [conflicts, setConflicts] = useState<WorkOrderFormConflict[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("pending");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [choices, setChoices] = useState<Record<number, Record<string, ValueSource>>>({});
  const [busyId, setBusyId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const rows = await api.listWorkOrderFormConflicts({
        status: statusFilter === "all" ? undefined : statusFilter
      });
      setConflicts(rows);
    } catch (error) {
      setConflicts([]);
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to load sync conflicts."
      });
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => ({
    pending: conflicts.filter((conflict) => conflict.status === "pending").length,
    resolved: conflicts.filter((conflict) => conflict.status !== "pending").length,
    changedAgain: conflicts.filter(
      (conflict) => conflict.current_server_form_version !== conflict.server_form_version
    ).length
  }), [conflicts]);

  const fieldKeys = (conflict: WorkOrderFormConflict) => Array.from(new Set([
    ...Object.keys(conflict.current_server_values),
    ...Object.keys(conflict.local_values)
  ])).sort();

  const mergeValues = (conflict: WorkOrderFormConflict) => {
    const result: Record<string, WorkOrderFormValue> = {};
    for (const key of fieldKeys(conflict)) {
      const source = choices[conflict.id]?.[key] || "server";
      const value = source === "local"
        ? conflict.local_values[key]
        : conflict.current_server_values[key];
      if (value !== undefined) result[key] = value;
    }
    return result;
  };

  const resolve = async (
    conflict: WorkOrderFormConflict,
    action: "keep_server" | "apply_local" | "merge"
  ) => {
    const resolutionNotes = (notes[conflict.id] || "").trim();
    if (resolutionNotes.length < 3) {
      setNotice({
        type: "error",
        text: "Resolution notes are required so the decision remains auditable."
      });
      return;
    }
    try {
      setBusyId(conflict.id);
      await api.resolveWorkOrderFormConflict(conflict.id, {
        expected_version: conflict.version,
        expected_server_form_version: conflict.current_server_form_version,
        action,
        ...(action === "merge" ? { values: mergeValues(conflict) } : {}),
        resolution_notes: resolutionNotes
      });
      setNotice({
        type: "success",
        text: action === "keep_server"
          ? "Server values kept and the device conflict was closed."
          : action === "apply_local"
            ? "Offline values applied with administrator attribution."
            : "Selected values merged with administrator attribution."
      });
      setNotes((current) => ({ ...current, [conflict.id]: "" }));
      await load();
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to resolve sync conflict."
      });
      await load();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <ManagerShell
      title="Offline Form Conflicts"
      subtitle="Compare the engineer's retained device copy with the authoritative server form, then make an attributed administrator decision."
      metrics={[
        { label: "Shown", value: conflicts.length },
        { label: "Pending shown", value: counts.pending },
        { label: "Resolved shown", value: counts.resolved },
        { label: "Server changed again", value: counts.changedAgain }
      ]}
    >
      <p className="notice">
        Conflict registration never changes a work order. Applying or merging values repeats server-side field validation
        and creates the same notification or inventory-review tasks as a normal verified form save.
      </p>
      {notice && (
        <p className={`notice ${notice.type === "success" ? "notice-success" : "notice-error"}`}>
          {notice.text}
        </p>
      )}
      <section className="card">
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
            <option value="pending">Pending</option>
            <option value="kept_server">Kept server</option>
            <option value="applied_local">Applied offline copy</option>
            <option value="merged">Merged</option>
            <option value="all">All</option>
          </select>
        </label>
      </section>

      {loading ? (
        <section className="card"><div className="skeleton" /></section>
      ) : conflicts.length === 0 ? (
        <section className="card"><div className="empty-state">No conflicts match the selected status.</div></section>
      ) : (
        <section style={{ display: "grid", gap: 12 }}>
          {conflicts.map((conflict) => (
            <article className="card" key={conflict.id}>
              <div className="one-hand-actions" style={{ justifyContent: "space-between" }}>
                <div>
                  <strong>Conflict #{conflict.id}</strong>
                  <span className="muted"> · {conflict.status} · revision {conflict.version}</span>
                </div>
                <Link className="nav-item" href={`/work-order-details?work_order_id=${conflict.work_order_id}`}>
                  {conflict.work_order_ticket_number}
                </Link>
              </div>
              <p className="muted">
                Retained {new Date(conflict.created_at).toLocaleString()}
                {conflict.created_by_name ? ` by ${conflict.created_by_name}` : ""}
                {conflict.created_device_name ? ` on ${conflict.created_device_name}` : ""}
                {` · claim ${conflict.claim_version} · offline base ${conflict.base_form_version} · conflict server ${conflict.server_form_version} · current server ${conflict.current_server_form_version}`}
              </p>
              {conflict.current_server_form_version !== conflict.server_form_version && conflict.status === "pending" && (
                <p className="notice notice-error">
                  The server changed again after this conflict was registered. The comparison below uses the latest server values.
                </p>
              )}
              <div style={{ overflowX: "auto" }}>
                <table>
                  <thead>
                    <tr>
                      <th>Field</th>
                      <th>Current server</th>
                      <th>Offline device copy</th>
                      {conflict.status === "pending" && <th>Merge choice</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {fieldKeys(conflict).map((key) => (
                      <tr key={key}>
                        <td><strong>{key}</strong></td>
                        <td>{valueSummary(conflict.current_server_values[key])}</td>
                        <td>{valueSummary(conflict.local_values[key])}</td>
                        {conflict.status === "pending" && (
                          <td>
                            <select
                              aria-label={`Value source for ${key}`}
                              value={choices[conflict.id]?.[key] || "server"}
                              onChange={(event) => setChoices((current) => ({
                                ...current,
                                [conflict.id]: {
                                  ...(current[conflict.id] || {}),
                                  [key]: event.target.value as ValueSource
                                }
                              }))}
                            >
                              <option value="server">Current server</option>
                              <option value="local">Offline copy</option>
                            </select>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {conflict.status === "pending" ? (
                <>
                  <label>
                    Resolution notes
                    <textarea
                      rows={2}
                      value={notes[conflict.id] || ""}
                      placeholder="Record how ownership and field evidence were verified."
                      onChange={(event) => setNotes((current) => ({
                        ...current,
                        [conflict.id]: event.target.value
                      }))}
                    />
                  </label>
                  <div className="one-hand-actions">
                    <button type="button" disabled={busyId === conflict.id} onClick={() => void resolve(conflict, "keep_server")}>
                      Keep server
                    </button>
                    <button type="button" disabled={busyId === conflict.id} onClick={() => void resolve(conflict, "apply_local")}>
                      Apply offline copy
                    </button>
                    <button type="button" disabled={busyId === conflict.id} onClick={() => void resolve(conflict, "merge")}>
                      Merge selected
                    </button>
                  </div>
                </>
              ) : (
                <p className="notice notice-success">
                  Resolved {conflict.resolved_at ? new Date(conflict.resolved_at).toLocaleString() : ""}
                  {conflict.resolved_by_name ? ` by ${conflict.resolved_by_name}` : ""}
                  {conflict.resolution_notes ? ` · ${conflict.resolution_notes}` : ""}
                </p>
              )}
            </article>
          ))}
        </section>
      )}
    </ManagerShell>
  );
}
