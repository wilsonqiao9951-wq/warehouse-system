"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api, getApiPublicOrigin } from "@/lib/api";
import {
  ExternalIntegration,
  ExternalIntegrationProvider,
  ExternalIntegrationSecret,
  ExternalSyncLog,
  ExternalWebhookEvent,
  IntegrationParityAutomation,
  IntegrationParityCapability,
  IntegrationParityContract,
  IntegrationParityTable
} from "@/types";

const defaultMapping = {
  ticket_number: "WO ID",
  outlet_name: "Site",
  problem_description: "Issue",
  machine_type: "Model"
};

const providers: Array<{ value: ExternalIntegrationProvider; label: string }> = [
  { value: "appsheet", label: "AppSheet" },
  { value: "generic", label: "Generic REST" },
  { value: "google_sheets", label: "Google Sheets" },
  { value: "crm", label: "CRM" },
  { value: "erp", label: "ERP" },
  { value: "wms", label: "WMS" }
];
const webhookEvents: Array<{ value: ExternalWebhookEvent; label: string }> = [
  { value: "work_order.status_changed", label: "Work-order status changes" },
  { value: "work_order.completed", label: "Work-order completion" },
  { value: "work_order.part_used", label: "Part usage" }
];
const capabilityLabels: Record<IntegrationParityCapability, string> = {
  work_order_intake: "Work-order intake",
  work_order_status_read: "Work-order status read",
  inventory_read: "Inventory read",
  recommendations_read: "AI recommendations read",
  status_callback: "Status callback",
  completion_callback: "Completion callback",
  part_usage_callback: "Parts-usage callback"
};

function parseMapping(value: string): Record<string, string> {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Field mapping must be a JSON object.");
  }
  for (const [canonical, external] of Object.entries(parsed)) {
    if (typeof external !== "string") {
      throw new Error(`Mapping value for ${canonical} must be text.`);
    }
  }
  return parsed as Record<string, string>;
}

function parseList<T>(value: string, label: string): T[] {
  const parsed = JSON.parse(value) as unknown;
  if (!Array.isArray(parsed)) throw new Error(`${label} must be a JSON array.`);
  return parsed as T[];
}

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<ExternalIntegration[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [logs, setLogs] = useState<ExternalSyncLog[]>([]);
  const [parity, setParity] = useState<IntegrationParityContract | null>(null);
  const [role, setRole] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<ExternalIntegrationSecret | null>(null);
  const [form, setForm] = useState({
    name: "AppSheet field service",
    provider: "appsheet" as ExternalIntegrationProvider,
    mapping: JSON.stringify(defaultMapping, null, 2),
    webhook_url: "",
    subscribed_events: [] as ExternalWebhookEvent[]
  });
  const [editor, setEditor] = useState({
    name: "",
    mapping: "{}",
    webhook_url: "",
    subscribed_events: [] as ExternalWebhookEvent[],
    is_active: true
  });
  const [parityEditor, setParityEditor] = useState({
    source_revision: "",
    required_capabilities: [] as IntegrationParityCapability[],
    tables: "[]",
    automations: "[]"
  });

  const selected = useMemo(
    () => integrations.find((item) => item.id === selectedId) || null,
    [integrations, selectedId]
  );
  const isAdmin = role === "admin";
  const webhookUrl = `${getApiPublicOrigin()}/api/external/v1/work-orders`;

  const refresh = async (preferId?: number) => {
    const rows = await api.listIntegrations();
    setIntegrations(rows);
    const nextId = preferId ?? selectedId ?? rows[0]?.id ?? null;
    setSelectedId(nextId);
  };

  useEffect(() => {
    setRole(window.localStorage.getItem("opf_role") || "");
    void refresh().catch((reason: Error) => setError(reason.message));
    // The initial request establishes the selected integration.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!selected) {
      setLogs([]);
      setParity(null);
      return;
    }
    setEditor({
      name: selected.name,
      mapping: JSON.stringify(selected.field_mapping, null, 2),
      webhook_url: selected.webhook_url || "",
      subscribed_events: selected.subscribed_events,
      is_active: selected.is_active
    });
    Promise.all([
      api.listIntegrationSyncLogs(selected.id),
      api.getIntegrationParityContract(selected.id)
    ])
      .then(([nextLogs, nextParity]) => {
        setLogs(nextLogs);
        setParity(nextParity);
        setParityEditor({
          source_revision: nextParity.source_revision,
          required_capabilities: nextParity.required_capabilities,
          tables: JSON.stringify(nextParity.tables, null, 2),
          automations: JSON.stringify(nextParity.automations, null, 2)
        });
      })
      .catch((reason: Error) => setError(reason.message));
  }, [selected]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await api.createIntegration({
        name: form.name.trim(),
        provider: form.provider,
        field_mapping: parseMapping(form.mapping),
        webhook_url: form.webhook_url.trim() || null,
        subscribed_events: form.subscribed_events
      });
      setRevealed(result);
      setNotice("Integration created. Copy the API key now; it will not be shown again.");
      setError("");
      await refresh(result.integration.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to create integration.");
    }
  };

  const save = async () => {
    if (!selected) return;
    try {
      const updated = await api.updateIntegration(selected.id, {
        expected_version: selected.version,
        name: editor.name.trim(),
        field_mapping: parseMapping(editor.mapping),
        webhook_url: editor.webhook_url.trim() || null,
        subscribed_events: editor.subscribed_events,
        is_active: editor.is_active
      });
      setNotice("Integration settings saved.");
      setError("");
      await refresh(updated.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save integration.");
    }
  };

  const rotate = async () => {
    if (!selected) return;
    try {
      const result = await api.rotateIntegrationKey(selected.id, selected.version);
      setRevealed(result);
      setNotice("API key rotated. Update the external system now; the previous key is invalid.");
      setError("");
      await refresh(result.integration.id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to rotate API key.");
    }
  };

  const toggleEvent = (
    target: "form" | "editor",
    eventName: ExternalWebhookEvent,
    checked: boolean
  ) => {
    const update = (events: ExternalWebhookEvent[]) => (
      checked
        ? [...new Set([...events, eventName])]
        : events.filter((item) => item !== eventName)
    );
    if (target === "form") {
      setForm((previous) => ({ ...previous, subscribed_events: update(previous.subscribed_events) }));
    } else {
      setEditor((previous) => ({ ...previous, subscribed_events: update(previous.subscribed_events) }));
    }
  };

  const retryDelivery = async (log: ExternalSyncLog) => {
    if (!selected) return;
    try {
      await api.retryIntegrationDelivery(selected.id, log.id);
      setNotice("Delivery queued for an immediate retry.");
      setLogs(await api.listIntegrationSyncLogs(selected.id));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to retry delivery.");
    }
  };

  const saveParityContract = async () => {
    if (!selected || !parity) return;
    try {
      const updated = await api.saveIntegrationParityContract(selected.id, {
        expected_version: parity.version,
        source_revision: parityEditor.source_revision.trim(),
        required_capabilities: parityEditor.required_capabilities,
        tables: parseList<IntegrationParityTable>(parityEditor.tables, "Tables"),
        automations: parseList<IntegrationParityAutomation>(parityEditor.automations, "Automations")
      });
      setParity(updated);
      setParityEditor({
        source_revision: updated.source_revision,
        required_capabilities: updated.required_capabilities,
        tables: JSON.stringify(updated.tables, null, 2),
        automations: JSON.stringify(updated.automations, null, 2)
      });
      setNotice(`Parallel-run contract saved. Readiness is ${updated.readiness_score}%.`);
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save the parallel-run contract.");
    }
  };

  const downloadParityContract = () => {
    if (!selected || !parity) return;
    const blob = new Blob([JSON.stringify(parity, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${selected.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-parallel-run-contract.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <ManagerShell
      title="External integrations"
      subtitle="Tenant-scoped AppSheet and REST work-order intake with field mapping, idempotency, and sync evidence."
      metrics={[
        { label: "Integrations", value: integrations.length },
        { label: "Active", value: integrations.filter((item) => item.is_active).length },
        { label: "Failed events", value: logs.filter((item) => item.status === "failed").length },
        { label: "Parity readiness", value: parity ? `${parity.readiness_score}%` : "—" }
      ]}
    >
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}

      {revealed && (
        <section className="card" style={{ borderColor: "#f59e0b" }}>
          <h3>Copy this API key now</h3>
          <p className="muted">Only the hash is stored. Closing this panel permanently hides the key.</p>
          <code style={{ display: "block", overflowWrap: "anywhere", padding: 12, background: "#f8fafc" }}>
            {revealed.api_key}
          </code>
          <div className="two-col" style={{ marginTop: 12 }}>
            <button type="button" onClick={() => void navigator.clipboard.writeText(revealed.api_key)}>
              Copy API key
            </button>
            <button type="button" onClick={() => setRevealed(null)}>I saved it</button>
          </div>
        </section>
      )}

      {isAdmin && (
        <section className="card">
          <h3>Create integration</h3>
          <form onSubmit={create}>
            <div className="two-col">
              <label>
                Name
                <input value={form.name} onChange={(event) => setForm((previous) => ({ ...previous, name: event.target.value }))} required minLength={2} />
              </label>
              <label>
                Provider
                <select value={form.provider} onChange={(event) => setForm((previous) => ({ ...previous, provider: event.target.value as ExternalIntegrationProvider }))}>
                  {providers.map((provider) => <option value={provider.value} key={provider.value}>{provider.label}</option>)}
                </select>
              </label>
            </div>
            <label>
              Field mapping (OpenPartsFlow field → external column)
              <textarea value={form.mapping} onChange={(event) => setForm((previous) => ({ ...previous, mapping: event.target.value }))} rows={8} spellCheck={false} />
            </label>
            <label>
              Outbound webhook URL (HTTPS)
              <input value={form.webhook_url} onChange={(event) => setForm((previous) => ({ ...previous, webhook_url: event.target.value }))} placeholder="https://example.com/openpartsflow/events" />
            </label>
            <fieldset>
              <legend>Outbound events</legend>
              {webhookEvents.map((item) => (
                <label key={item.value} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <input type="checkbox" checked={form.subscribed_events.includes(item.value)} onChange={(event) => toggleEvent("form", item.value, event.target.checked)} style={{ width: 20, minHeight: 20 }} />
                  {item.label}
                </label>
              ))}
            </fieldset>
            <button type="submit">Create and reveal API key</button>
          </form>
        </section>
      )}

      <section className="card">
        <h3>Configured integrations</h3>
        {integrations.length === 0 ? (
          <div className="empty-state">No external integrations configured.</div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {integrations.map((integration) => (
              <button
                type="button"
                className="nav-item"
                style={{ textAlign: "left", borderColor: integration.id === selectedId ? "#155eef" : undefined }}
                key={integration.id}
                onClick={() => setSelectedId(integration.id)}
              >
                <strong>{integration.name}</strong> · {integration.provider} · {integration.is_active ? "active" : "inactive"}
                <span className="muted" style={{ display: "block" }}>
                  {integration.masked_api_key} · last used {integration.last_used_at ? new Date(integration.last_used_at).toLocaleString() : "never"}
                </span>
              </button>
            ))}
          </div>
        )}
      </section>

      {selected && (
        <>
          <section className="card">
            <h3>{selected.name}</h3>
            <p><strong>Webhook:</strong> <code style={{ overflowWrap: "anywhere" }}>{webhookUrl}</code></p>
            <p className="muted">
              Send `X-API-Key` and a unique `X-Idempotency-Key` header. Reusing the same key and payload safely returns the original result.
            </p>
            <pre style={{ overflowX: "auto", padding: 12, background: "#f8fafc", borderRadius: 8 }}>
{`{
  "external_id": "appsheet-row-key",
  "data": {
    "WO ID": "WO-1001",
    "Site": "Customer site",
    "Issue": "No cooling",
    "Model": "ACME-9000"
  }
}`}
            </pre>
            {isAdmin ? (
              <>
                <label>
                  Integration name
                  <input value={editor.name} onChange={(event) => setEditor((previous) => ({ ...previous, name: event.target.value }))} />
                </label>
                <label>
                  Field mapping
                  <textarea value={editor.mapping} onChange={(event) => setEditor((previous) => ({ ...previous, mapping: event.target.value }))} rows={9} spellCheck={false} />
                </label>
                <label>
                  Outbound webhook URL (HTTPS)
                  <input value={editor.webhook_url} onChange={(event) => setEditor((previous) => ({ ...previous, webhook_url: event.target.value }))} placeholder="https://example.com/openpartsflow/events" />
                </label>
                <fieldset>
                  <legend>Outbound events</legend>
                  {webhookEvents.map((item) => (
                    <label key={item.value} style={{ display: "flex", gap: 10, alignItems: "center" }}>
                      <input type="checkbox" checked={editor.subscribed_events.includes(item.value)} onChange={(event) => toggleEvent("editor", item.value, event.target.checked)} style={{ width: 20, minHeight: 20 }} />
                      {item.label}
                    </label>
                  ))}
                </fieldset>
                <label style={{ display: "flex", gap: 10, alignItems: "center", margin: "12px 0" }}>
                  <input type="checkbox" checked={editor.is_active} onChange={(event) => setEditor((previous) => ({ ...previous, is_active: event.target.checked }))} style={{ width: 20, minHeight: 20 }} />
                  API key active
                </label>
                <div className="two-col">
                  <button type="button" onClick={() => void save()}>Save settings</button>
                  <button type="button" onClick={() => void rotate()}>Rotate API key</button>
                </div>
              </>
            ) : (
              <p className="notice">Managers may inspect mappings and sync logs. Only administrators can create, edit, deactivate, or rotate keys.</p>
            )}
          </section>

          {parity && (
            <section className="card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "flex-start", flexWrap: "wrap" }}>
                <div>
                  <h3 style={{ marginBottom: 4 }}>Parallel-run contract</h3>
                  <p className="muted" style={{ marginTop: 0 }}>
                    Versioned AppSheet/Google Sheets field dictionary and automation coverage. This documents external columns without granting new write permissions.
                  </p>
                </div>
                <div style={{ textAlign: "right" }}>
                  <strong style={{ fontSize: 28 }}>{parity.readiness_score}%</strong>
                  <div className="muted">{parity.readiness_status} · contract v{parity.version}</div>
                </div>
              </div>

              <div className="pilot-grid" style={{ marginBottom: 16 }}>
                {parity.required_capabilities.map((capability) => {
                  const covered = parity.covered_capabilities.includes(capability);
                  return (
                    <div className={`pilot-metric${covered ? "" : " pilot-metric--alert"}`} key={capability}>
                      <strong>{covered ? "Covered" : "Gap"}</strong>
                      <small>{capabilityLabels[capability]}</small>
                    </div>
                  );
                })}
              </div>

              {parity.gaps.length > 0 && (
                <div style={{ display: "grid", gap: 8, marginBottom: 16 }}>
                  {parity.gaps.map((gap, index) => (
                    <div className={`notice ${gap.severity === "error" ? "notice-error" : ""}`} key={`${gap.code}-${index}`}>
                      <strong>{gap.severity === "error" ? "Blocking gap" : "Review note"}:</strong> {gap.message}
                    </div>
                  ))}
                </div>
              )}

              <div className="table-wrap" style={{ marginBottom: 16 }}>
                <table>
                  <thead><tr><th>External table</th><th>Purpose</th><th>Key</th><th>Columns</th><th>Mapped</th></tr></thead>
                  <tbody>
                    {parity.tables.map((table) => (
                      <tr key={`${table.canonical_object}-${table.external_name}`}>
                        <td>{table.external_name}</td>
                        <td>{table.canonical_object}</td>
                        <td>{table.key_column}</td>
                        <td>{table.columns.length}</td>
                        <td>{table.columns.filter((column) => column.canonical_field).length}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {isAdmin ? (
                <>
                  <label>
                    Source revision or discovery date
                    <input
                      value={parityEditor.source_revision}
                      onChange={(event) => setParityEditor((previous) => ({ ...previous, source_revision: event.target.value }))}
                      placeholder="AppSheet metadata export 2026-08-08"
                      maxLength={160}
                    />
                  </label>
                  <label>
                    External tables and columns (JSON)
                    <textarea
                      value={parityEditor.tables}
                      onChange={(event) => setParityEditor((previous) => ({ ...previous, tables: event.target.value }))}
                      rows={16}
                      spellCheck={false}
                    />
                  </label>
                  <label>
                    Bots and automations (JSON)
                    <textarea
                      value={parityEditor.automations}
                      onChange={(event) => setParityEditor((previous) => ({ ...previous, automations: event.target.value }))}
                      rows={12}
                      spellCheck={false}
                    />
                  </label>
                  <div className="two-col">
                    <button type="button" onClick={() => void saveParityContract()}>Validate and save contract</button>
                    <button type="button" onClick={downloadParityContract}>Download contract JSON</button>
                  </div>
                </>
              ) : (
                <button type="button" onClick={downloadParityContract}>Download contract JSON</button>
              )}
              <p className="muted" style={{ overflowWrap: "anywhere" }}>
                Fingerprint: <code>{parity.source_fingerprint}</code>
                {parity.validated_at ? ` · validated ${new Date(parity.validated_at).toLocaleString()}` : " · template not saved"}
              </p>
            </section>
          )}

          <section className="card">
            <h3>Synchronization log</h3>
            {logs.length === 0 ? (
              <div className="empty-state">No webhook calls recorded.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Time</th><th>Direction / event</th><th>External ID</th><th>Status</th><th>Attempts</th><th>Work order</th><th>Changed fields / error</th><th>Action</th></tr>
                  </thead>
                  <tbody>
                    {logs.map((log) => (
                      <tr key={log.id}>
                        <td>{new Date(log.created_at).toLocaleString()}</td>
                        <td>{log.direction} / {log.event_type}</td>
                        <td>{log.external_id}</td>
                        <td>{log.status}</td>
                        <td>{log.attempt_count}</td>
                        <td>{log.work_order_id || "—"}</td>
                        <td>{log.error_message || log.changed_fields.join(", ") || "No changes"}</td>
                        <td>
                          {isAdmin && log.direction === "outbound" && log.status !== "processed" ? (
                            <button type="button" onClick={() => void retryDelivery(log)}>Retry</button>
                          ) : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </ManagerShell>
  );
}
