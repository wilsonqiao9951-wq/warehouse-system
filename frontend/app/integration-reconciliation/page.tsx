"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import {
  ExternalIntegration,
  IntegrationParallelReconciliation,
  IntegrationParallelSnapshot,
  IntegrationParityContract
} from "@/types";

function emptySnapshot(sourceRevision = ""): IntegrationParallelSnapshot {
  const now = new Date();
  const earlier = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  return {
    source_revision: sourceRevision,
    observed_from: earlier.toISOString(),
    observed_to: now.toISOString(),
    work_orders: [],
    part_usage: [],
    inventory: []
  };
}

function parseSnapshot(value: string): IntegrationParallelSnapshot {
  const parsed = JSON.parse(value) as Partial<IntegrationParallelSnapshot>;
  if (
    !parsed
    || typeof parsed !== "object"
    || typeof parsed.source_revision !== "string"
    || typeof parsed.observed_from !== "string"
    || typeof parsed.observed_to !== "string"
    || !Array.isArray(parsed.work_orders)
    || !Array.isArray(parsed.part_usage)
    || !Array.isArray(parsed.inventory)
  ) {
    throw new Error("Snapshot JSON must contain source_revision, observation dates, and all three arrays.");
  }
  return parsed as IntegrationParallelSnapshot;
}

export default function IntegrationReconciliationPage() {
  const [integrations, setIntegrations] = useState<ExternalIntegration[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [contract, setContract] = useState<IntegrationParityContract | null>(null);
  const [runs, setRuns] = useState<IntegrationParallelReconciliation[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [snapshotText, setSnapshotText] = useState(JSON.stringify(emptySnapshot(), null, 2));
  const [reason, setReason] = useState("Controlled AppSheet parallel-run verification");
  const [password, setPassword] = useState("");
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const selected = useMemo(
    () => integrations.find((integration) => integration.id === selectedId) || null,
    [integrations, selectedId]
  );
  const canRun = canManage;

  useEffect(() => {
    Promise.all([api.listIntegrations(), api.getMyPermissions()])
      .then(([rows, permissionMatrix]) => {
        const supported = rows.filter((row) => (
          row.provider === "appsheet" || row.provider === "google_sheets"
        ));
        setIntegrations(supported);
        setSelectedId(supported[0]?.id ?? null);
        setCanManage(permissionMatrix.effective_permissions.includes("integrations.manage"));
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  useEffect(() => {
    if (!selectedId) {
      setContract(null);
      setRuns([]);
      return;
    }
    Promise.all([
      api.getIntegrationParityContract(selectedId),
      api.listIntegrationParallelReconciliations(selectedId)
    ])
      .then(([nextContract, nextRuns]) => {
        setContract(nextContract);
        setRuns(nextRuns);
        setSnapshotText(JSON.stringify(emptySnapshot(nextContract.source_revision), null, 2));
        setError("");
      })
      .catch((reason: Error) => setError(reason.message));
  }, [selectedId]);

  const loadFile = async (file: File | undefined) => {
    if (!file) return;
    try {
      const text = await file.text();
      const parsed = parseSnapshot(text);
      setSnapshotText(JSON.stringify(parsed, null, 2));
      setError("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to read snapshot JSON.");
    }
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedId) return;
    setSubmitting(true);
    try {
      const snapshot = parseSnapshot(snapshotText);
      const result = await api.createIntegrationParallelReconciliation(selectedId, {
        ...snapshot,
        reason: reason.trim(),
        account_password: password
      });
      setRuns(await api.listIntegrationParallelReconciliations(selectedId));
      setPassword("");
      setSnapshotText(JSON.stringify(emptySnapshot(contract?.source_revision || ""), null, 2));
      setNotice(
        result.status === "matched"
          ? "Parallel-run evidence recorded: all submitted canonical records matched."
          : `Parallel-run evidence recorded with ${result.discrepancy_count} differences.`
      );
      setError("");
    } catch (reason) {
      setPassword("");
      setNotice("");
      setError(reason instanceof Error ? reason.message : "Unable to run reconciliation.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ManagerShell
      title="AppSheet parallel run"
      subtitle="Compare canonical AppSheet or Google Sheets exports with tenant-scoped OpenPartsFlow records and retain append-only evidence."
      metrics={[
        { label: "Supported integrations", value: integrations.length },
        { label: "Recorded runs", value: runs.length },
        { label: "Latest status", value: runs[0]?.status || "not run" },
        { label: "Latest differences", value: runs[0]?.discrepancy_count ?? 0 }
      ]}
    >
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}

      <section className="card">
        <h3>Evidence scope</h3>
        <p>
          This comparison accepts only canonical IDs, statuses, part quantities, and warehouse balances.
          The server stores fingerprints, aggregate counts, and at most 500 bounded discrepancy rows—not the submitted source snapshot.
        </p>
        <p className="muted">
          Work orders and part usage are compared inside the submitted observation window. Inventory is a current non-zero point-in-time balance.
        </p>
        <label>
          Integration
          <select
            value={selectedId ?? ""}
            onChange={(event) => setSelectedId(event.target.value ? Number(event.target.value) : null)}
          >
            <option value="">Select an integration</option>
            {integrations.map((integration) => (
              <option value={integration.id} key={integration.id}>
                {integration.name} · {integration.provider} · {integration.is_active ? "active" : "inactive"}
              </option>
            ))}
          </select>
        </label>
        {contract && (
          <div className={`notice ${contract.readiness_status === "ready" ? "notice-success" : "notice-error"}`}>
            Contract {contract.readiness_status} · {contract.readiness_score}% · revision {contract.source_revision || "not recorded"}
          </div>
        )}
      </section>

      {selected && canRun && (
        <section className="card">
          <h3>Run controlled comparison</h3>
          <form onSubmit={submit}>
            <label>
              Canonical snapshot JSON
              <textarea
                value={snapshotText}
                onChange={(event) => setSnapshotText(event.target.value)}
                rows={18}
                spellCheck={false}
                required
              />
            </label>
            <label>
              Or load a JSON file
              <input
                type="file"
                accept="application/json,.json"
                onChange={(event) => void loadFile(event.target.files?.[0])}
              />
            </label>
            <label>
              Evidence reason
              <input value={reason} onChange={(event) => setReason(event.target.value)} minLength={3} maxLength={500} required />
            </label>
            <label>
              Current account password
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                autoComplete="current-password"
                required
              />
            </label>
            <button type="submit" disabled={submitting || contract?.readiness_status !== "ready"}>
              {submitting ? "Comparing…" : "Compare and record evidence"}
            </button>
          </form>
        </section>
      )}

      {selected && !canRun && (
        <section className="card">
          <p className="notice">This account can inspect evidence but does not have the integrations.manage permission required to submit a source snapshot.</p>
        </section>
      )}

      <section className="card">
        <h3>Append-only reconciliation history</h3>
        {runs.length === 0 ? (
          <div className="empty-state">No parallel-run evidence has been recorded for this integration.</div>
        ) : runs.map((run) => (
          <article className="card" key={run.id} style={{ marginBottom: 12 }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
              <div>
                <strong>Run #{run.id} · {run.status}</strong>
                <div className="muted">{new Date(run.created_at).toLocaleString()} · {run.reason}</div>
              </div>
              <div style={{ textAlign: "right" }}>
                <strong>{run.discrepancy_count} differences</strong>
                <div className="muted">{run.matched_record_count} matched</div>
              </div>
            </div>
            <div className="table-wrap" style={{ marginTop: 12 }}>
              <table>
                <thead><tr><th>Object</th><th>External</th><th>OpenPartsFlow</th><th>Matched</th><th>Differences</th></tr></thead>
                <tbody>
                  {Object.entries(run.object_counts).map(([objectName, counts]) => (
                    <tr key={objectName}>
                      <td>{objectName}</td><td>{counts.external}</td><td>{counts.openpartsflow}</td><td>{counts.matched}</td><td>{counts.discrepancies}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {run.discrepancies.length > 0 && (
              <div className="table-wrap" style={{ marginTop: 12 }}>
                <table>
                  <thead><tr><th>Object / key</th><th>Field</th><th>OpenPartsFlow</th><th>External</th><th>Reason</th></tr></thead>
                  <tbody>
                    {run.discrepancies.map((item, index) => (
                      <tr key={`${item.object_type}-${item.key}-${index}`}>
                        <td>{item.object_type}<br /><code>{item.key}</code></td>
                        <td>{item.field}</td>
                        <td>{item.openpartsflow_value ?? "—"}</td>
                        <td>{item.external_value ?? "—"}</td>
                        <td>{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {run.truncated && <p className="notice notice-error">Stored detail is truncated; aggregate discrepancy count remains complete.</p>}
              </div>
            )}
            <p className="muted" style={{ overflowWrap: "anywhere" }}>
              Evidence <code>{run.evidence_fingerprint}</code>
            </p>
          </article>
        ))}
      </section>
    </ManagerShell>
  );
}
