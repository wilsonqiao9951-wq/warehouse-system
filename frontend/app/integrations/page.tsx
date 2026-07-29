"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api, getApiPublicOrigin } from "@/lib/api";
import {
  ExternalIntegration,
  ExternalIntegrationProvider,
  ExternalIntegrationSecret,
  ExternalSyncLog
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

export default function IntegrationsPage() {
  const [integrations, setIntegrations] = useState<ExternalIntegration[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [logs, setLogs] = useState<ExternalSyncLog[]>([]);
  const [role, setRole] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [revealed, setRevealed] = useState<ExternalIntegrationSecret | null>(null);
  const [form, setForm] = useState({
    name: "AppSheet field service",
    provider: "appsheet" as ExternalIntegrationProvider,
    mapping: JSON.stringify(defaultMapping, null, 2)
  });
  const [editor, setEditor] = useState({
    name: "",
    mapping: "{}",
    is_active: true
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
      return;
    }
    setEditor({
      name: selected.name,
      mapping: JSON.stringify(selected.field_mapping, null, 2),
      is_active: selected.is_active
    });
    api.listIntegrationSyncLogs(selected.id)
      .then(setLogs)
      .catch((reason: Error) => setError(reason.message));
  }, [selected]);

  const create = async (event: FormEvent) => {
    event.preventDefault();
    try {
      const result = await api.createIntegration({
        name: form.name.trim(),
        provider: form.provider,
        field_mapping: parseMapping(form.mapping)
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

  return (
    <ManagerShell
      title="External integrations"
      subtitle="Tenant-scoped AppSheet and REST work-order intake with field mapping, idempotency, and sync evidence."
      metrics={[
        { label: "Integrations", value: integrations.length },
        { label: "Active", value: integrations.filter((item) => item.is_active).length },
        { label: "Failed events", value: logs.filter((item) => item.status === "failed").length }
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

          <section className="card">
            <h3>Synchronization log</h3>
            {logs.length === 0 ? (
              <div className="empty-state">No webhook calls recorded.</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr><th>Time</th><th>External ID</th><th>Status</th><th>Attempts</th><th>Work order</th><th>Changed fields / error</th></tr>
                  </thead>
                  <tbody>
                    {logs.map((log) => (
                      <tr key={log.id}>
                        <td>{new Date(log.created_at).toLocaleString()}</td>
                        <td>{log.external_id}</td>
                        <td>{log.status}</td>
                        <td>{log.attempt_count}</td>
                        <td>{log.work_order_id || "—"}</td>
                        <td>{log.error_message || log.changed_fields.join(", ") || "No changes"}</td>
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
