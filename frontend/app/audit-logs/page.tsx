"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { getCurrentRole } from "@/lib/role";
import { AuditLogEntry, AuditLogFilters, AuditLogSummary } from "@/types";

interface FilterForm {
  action: string;
  entityType: string;
  entityId: string;
  userId: string;
  fromAt: string;
  toAt: string;
}

const EMPTY_FILTERS: FilterForm = {
  action: "",
  entityType: "",
  entityId: "",
  userId: "",
  fromAt: "",
  toAt: ""
};

function toApiFilters(values: FilterForm): AuditLogFilters {
  return {
    ...(values.action.trim() ? { action: values.action.trim() } : {}),
    ...(values.entityType.trim() ? { entity_type: values.entityType.trim() } : {}),
    ...(Number(values.entityId) > 0 ? { entity_id: Number(values.entityId) } : {}),
    ...(Number(values.userId) > 0 ? { user_id: Number(values.userId) } : {}),
    ...(values.fromAt ? { from_at: new Date(values.fromAt).toISOString() } : {}),
    ...(values.toAt ? { to_at: new Date(values.toAt).toISOString() } : {})
  };
}

function formatTimestamp(value?: string | null) {
  if (!value) return "Never";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "medium"
  }).format(new Date(value));
}

export default function AuditLogsPage() {
  const [draft, setDraft] = useState<FilterForm>(EMPTY_FILTERS);
  const [activeFilters, setActiveFilters] = useState<AuditLogFilters>({});
  const [rows, setRows] = useState<AuditLogEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [summary, setSummary] = useState<AuditLogSummary | null>(null);
  const [isAdmin, setIsAdmin] = useState(false);
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [exportEvidence, setExportEvidence] = useState<{ sha256: string | null; recordCount: number | null } | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async (
    filters: AuditLogFilters,
    beforeId?: number,
    append = false
  ) => {
    try {
      setLoading(true);
      setError("");
      const page = await api.getAuditLogs(filters, beforeId);
      setRows((current) => append ? [...current, ...page.items] : page.items);
      setTotal(page.total);
      setNextBeforeId(page.next_before_id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load audit logs.");
      if (!append) setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSummary = useCallback(async (filters: AuditLogFilters) => {
    try {
      setSummary(await api.getAuditLogSummary(30, filters));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load audit summary.");
    }
  }, []);

  useEffect(() => {
    setIsAdmin(getCurrentRole() === "admin");
    void Promise.all([load({}), loadSummary({})]);
  }, [load, loadSummary]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    try {
      const filters = toApiFilters(draft);
      if (filters.from_at && filters.to_at && filters.to_at < filters.from_at) {
        setError("End time must be on or after start time.");
        return;
      }
      setActiveFilters(filters);
      setExportEvidence(null);
      void Promise.all([load(filters), loadSummary(filters)]);
    } catch {
      setError("Enter a valid date and time range.");
    }
  };

  const resetFilters = () => {
    setDraft(EMPTY_FILTERS);
    setActiveFilters({});
    setExportEvidence(null);
    void Promise.all([load({}), loadSummary({})]);
  };

  const exportCsv = async () => {
    try {
      setExporting(true);
      setError("");
      const evidence = await api.downloadAuditLogs(activeFilters, password);
      setExportEvidence(evidence);
      setPassword("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to export audit logs.");
    } finally {
      setExporting(false);
    }
  };

  return (
    <ManagerShell
      title="Audit Logs"
      subtitle="Search tenant-scoped operational evidence and export a verified compliance record."
      metrics={[
        { label: "Matching Events", value: total },
        { label: "30-day Events", value: summary?.total_events ?? "-" },
        { label: "30-day Actors", value: summary?.unique_actors ?? "-" },
        { label: "Latest Event", value: summary?.latest_event_at ? formatTimestamp(summary.latest_event_at) : "None" }
      ]}
    >
      <section className="card">
        <form onSubmit={applyFilters}>
          <div className="two-col">
            <label>
              Action
              <input
                value={draft.action}
                maxLength={120}
                placeholder="work_order_completed"
                onChange={(event) => setDraft({ ...draft, action: event.target.value })}
              />
            </label>
            <label>
              Entity type
              <input
                value={draft.entityType}
                maxLength={120}
                placeholder="work_order"
                onChange={(event) => setDraft({ ...draft, entityType: event.target.value })}
              />
            </label>
            <label>
              Entity ID
              <input
                type="number"
                min={1}
                value={draft.entityId}
                onChange={(event) => setDraft({ ...draft, entityId: event.target.value })}
              />
            </label>
            <label>
              Actor user ID
              <input
                type="number"
                min={1}
                value={draft.userId}
                onChange={(event) => setDraft({ ...draft, userId: event.target.value })}
              />
            </label>
            <label>
              From
              <input
                type="datetime-local"
                value={draft.fromAt}
                onChange={(event) => setDraft({ ...draft, fromAt: event.target.value })}
              />
            </label>
            <label>
              To
              <input
                type="datetime-local"
                value={draft.toAt}
                onChange={(event) => setDraft({ ...draft, toAt: event.target.value })}
              />
            </label>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
            <button type="submit" disabled={loading}>Apply filters</button>
            <button type="button" className="secondary" onClick={resetFilters} disabled={loading}>Reset</button>
          </div>
        </form>
      </section>

      {summary && (
        <section className="card">
          <h3>30-day activity</h3>
          <div className="two-col">
            <div>
              <h4>Top actions</h4>
              {summary.by_action.length === 0 ? <p className="muted">No activity.</p> : (
                <ul>
                  {summary.by_action.map((item) => <li key={item.value}><code>{item.value}</code> - {item.count}</li>)}
                </ul>
              )}
            </div>
            <div>
              <h4>Top entity types</h4>
              {summary.by_entity_type.length === 0 ? <p className="muted">No activity.</p> : (
                <ul>
                  {summary.by_entity_type.map((item) => <li key={item.value}><code>{item.value}</code> - {item.count}</li>)}
                </ul>
              )}
            </div>
          </div>
        </section>
      )}

      {isAdmin && (
        <section className="card">
          <h3>Audited CSV export</h3>
          <p className="muted">
            The export uses the active filters, is protected against spreadsheet formulas, and records its row count and SHA-256 digest in this audit log.
          </p>
          <div className="two-col" style={{ alignItems: "end" }}>
            <label>
              Confirm administrator password
              <input
                type="password"
                minLength={10}
                maxLength={128}
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
            <button
              type="button"
              onClick={() => void exportCsv()}
              disabled={exporting || password.length < 10}
            >
              {exporting ? "Exporting..." : "Export verified CSV"}
            </button>
          </div>
          {exportEvidence && (
            <p className="notice" style={{ overflowWrap: "anywhere" }}>
              Exported {exportEvidence.recordCount ?? "unknown"} rows. SHA-256: {exportEvidence.sha256 || "Unavailable to this browser"}
            </p>
          )}
        </section>
      )}

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
          <h3>Event evidence</h3>
          <span className="muted">Showing {rows.length} of {total}</span>
        </div>
        {error && <p className="notice notice-error">{error}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {!loading && rows.length === 0 && (
                <tr><td colSpan={5} className="muted">No audit events match these filters.</td></tr>
              )}
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatTimestamp(row.timestamp)}</td>
                  <td>{row.user_name || (row.user_id ? `User #${row.user_id}` : "System")}</td>
                  <td><code>{row.action}</code></td>
                  <td>{row.entity_type}{row.entity_id ? ` #${row.entity_id}` : ""}</td>
                  <td>
                    <details>
                      <summary>{row.metadata_valid ? "View metadata" : "Legacy metadata warning"}</summary>
                      <pre style={{ whiteSpace: "pre-wrap", maxWidth: 520, overflowWrap: "anywhere" }}>
                        {JSON.stringify(row.metadata, null, 2)}
                      </pre>
                    </details>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {nextBeforeId && (
          <button
            type="button"
            className="secondary"
            style={{ marginTop: 12 }}
            disabled={loading}
            onClick={() => void load(activeFilters, nextBeforeId, true)}
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </section>
    </ManagerShell>
  );
}
