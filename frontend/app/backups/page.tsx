"use client";

import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { OrganizationDataExport, OrganizationDataRestore } from "@/types";

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function BackupsPage() {
  const [rows, setRows] = useState<OrganizationDataExport[]>([]);
  const [restores, setRestores] = useState<OrganizationDataRestore[]>([]);
  const [accountPassword, setAccountPassword] = useState("");
  const [includeFiles, setIncludeFiles] = useState(true);
  const [busy, setBusy] = useState(false);
  const [restoreFile, setRestoreFile] = useState<File | null>(null);
  const [restorePassword, setRestorePassword] = useState("");
  const [decisionNote, setDecisionNote] = useState("Reviewed checksum and dry-run results");
  const [restoreBusy, setRestoreBusy] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    const [exportRows, restoreRows] = await Promise.all([
      api.listOrganizationDataExports(),
      api.listOrganizationDataRestores()
    ]);
    setRows(exportRows);
    setRestores(restoreRows);
  };

  useEffect(() => {
    refresh().catch((value: unknown) => {
      setError(value instanceof Error ? value.message : "Unable to load backup evidence.");
    });
  }, []);

  const generate = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      setMessage("");
      await api.downloadOrganizationDataExport(includeFiles, accountPassword);
      setAccountPassword("");
      setMessage("Portable backup generated, downloaded, and recorded in the audit trail.");
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to generate portable backup.");
    } finally {
      setBusy(false);
    }
  };

  const rehearse = async (event: FormEvent) => {
    event.preventDefault();
    if (!restoreFile) return;
    try {
      setRestoreBusy("rehearsal");
      setError("");
      setMessage("");
      const result = await api.createOrganizationDataRestoreRehearsal(
        restoreFile,
        restorePassword
      );
      setRestorePassword("");
      setMessage(
        result.conflict_count
          ? `Rehearsal recorded with ${result.conflict_count} conflict(s); approval is blocked.`
          : `Rehearsal recorded with ${result.update_count} eligible update(s).`
      );
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to validate restore archive.");
    } finally {
      setRestoreBusy(null);
    }
  };

  const decide = async (row: OrganizationDataRestore, decision: "approve" | "reject") => {
    try {
      setRestoreBusy(`${decision}-${row.id}`);
      setError("");
      setMessage("");
      await api.decideOrganizationDataRestore(
        row.id,
        row.version,
        decision,
        decisionNote,
        restorePassword
      );
      setRestorePassword("");
      setMessage(`Restore rehearsal ${decision === "approve" ? "approved" : "rejected"}.`);
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to record restore decision.");
    } finally {
      setRestoreBusy(null);
    }
  };

  const applyRestore = async (row: OrganizationDataRestore) => {
    if (!restoreFile) {
      setError("Select the exact ZIP used for this approved rehearsal.");
      return;
    }
    try {
      setRestoreBusy(`apply-${row.id}`);
      setError("");
      setMessage("");
      await api.applyOrganizationDataRestore(
        row.id,
        row.version,
        restoreFile,
        restorePassword
      );
      setRestorePassword("");
      setMessage("Approved database restore applied; rollback evidence is available.");
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to apply approved restore.");
    } finally {
      setRestoreBusy(null);
    }
  };

  const rollbackRestore = async (row: OrganizationDataRestore) => {
    try {
      setRestoreBusy(`rollback-${row.id}`);
      setError("");
      setMessage("");
      await api.rollbackOrganizationDataRestore(row.id, row.version, restorePassword);
      setRestorePassword("");
      setMessage("Restore changes rolled back to the pre-application snapshot.");
      await refresh();
    } catch (value) {
      setError(value instanceof Error ? value.message : "Unable to roll back restore.");
    } finally {
      setRestoreBusy(null);
    }
  };

  return (
    <ManagerShell
      title="Customer data backups"
      subtitle="Generate a tenant-isolated portable archive and retain integrity evidence."
      metrics={[
        { label: "Recorded exports", value: rows.length },
        { label: "Restore rehearsals", value: restores.length },
        { label: "Approved / applied", value: restores.filter((row) => ["approved", "applied"].includes(row.status)).length }
      ]}
    >
      {message && <p className="notice notice-success" role="status">{message}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <section className="card">
        <h3>Generate portable backup</h3>
        <p className="muted">
          The ZIP contains JSON Lines for every company-owned data table, a checksum manifest,
          and optionally the local photos, voice notes, and knowledge media referenced by those records.
          Password hashes, device secrets, API key hashes, invitation tokens, and DNS challenges are excluded.
        </p>
        <form onSubmit={generate} style={{ display: "grid", gap: 12 }}>
          <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <input
              type="checkbox"
              checked={includeFiles}
              onChange={(event) => setIncludeFiles(event.target.checked)}
              style={{ width: 20, minHeight: 20 }}
            />
            Include referenced local evidence files
          </label>
          <label>
            Confirm administrator password
            <input
              type="password"
              autoComplete="current-password"
              minLength={10}
              maxLength={128}
              value={accountPassword}
              onChange={(event) => setAccountPassword(event.target.value)}
              required
            />
          </label>
          <button type="submit" disabled={busy || accountPassword.length < 10}>
            {busy ? "Generating…" : "Generate and download ZIP"}
          </button>
        </form>
      </section>
      <section className="card">
        <h3>Controlled restore rehearsal</h3>
        <p className="muted">
          Upload an <code>opf-portable-v1</code> ZIP to verify every manifest checksum and preview
          existing-row changes. Authentication, billing, audit, inventory transaction, custody,
          and other control-plane records are protected. Missing records are reported as conflicts;
          media is verified but is not written to storage in this stage.
        </p>
        <form onSubmit={rehearse} style={{ display: "grid", gap: 12 }}>
          <label>
            Portable backup ZIP
            <input
              type="file"
              accept=".zip,application/zip"
              onChange={(event) => setRestoreFile(event.target.files?.[0] ?? null)}
              required
            />
          </label>
          <label>
            Decision note
            <input
              type="text"
              minLength={3}
              maxLength={1000}
              value={decisionNote}
              onChange={(event) => setDecisionNote(event.target.value)}
            />
          </label>
          <label>
            Confirm administrator password for each restore action
            <input
              type="password"
              autoComplete="current-password"
              minLength={10}
              maxLength={128}
              value={restorePassword}
              onChange={(event) => setRestorePassword(event.target.value)}
              required
            />
          </label>
          <button
            type="submit"
            disabled={restoreBusy !== null || !restoreFile || restorePassword.length < 10}
          >
            {restoreBusy === "rehearsal" ? "Validating…" : "Validate and create rehearsal"}
          </button>
        </form>
      </section>
      <section className="card">
        <h3>Restore approvals and rollback evidence</h3>
        <p className="muted">
          Application requires the exact approved archive and recalculates the dry-run plan against
          live data. Any archive mismatch or post-approval data drift stops the operation.
        </p>
        {restores.length === 0 ? (
          <div className="empty-state">No restore rehearsals have been recorded.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Created</th>
                  <th>Status</th>
                  <th>Updates</th>
                  <th>Conflicts</th>
                  <th>Protected</th>
                  <th>Archive / plan</th>
                  <th>Review</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {restores.map((row) => (
                  <tr key={row.id}>
                    <td>{new Date(row.created_at).toLocaleString()}</td>
                    <td>{row.status.replace("_", " ")}</td>
                    <td>{row.update_count.toLocaleString()}</td>
                    <td>{row.conflict_count.toLocaleString()}</td>
                    <td>{row.protected_count.toLocaleString()}</td>
                    <td>
                      <code title={row.archive_sha256}>{row.archive_sha256.slice(0, 12)}…</code>
                      <br />
                      <code title={row.plan_sha256}>{row.plan_sha256.slice(0, 12)}…</code>
                      {row.matched_export_id ? <><br /><span className="muted">Export #{row.matched_export_id}</span></> : null}
                    </td>
                    <td>
                      <details>
                        <summary>Dry-run details</summary>
                        <ul style={{ margin: "8px 0", paddingLeft: 18 }}>
                          {Object.entries(row.table_summary)
                            .filter(([, summary]) => summary.updates || summary.conflicts || summary.protected)
                            .map(([table, summary]) => (
                              <li key={table}>
                                <code>{table}</code>: {summary.updates} update(s), {summary.conflicts} conflict(s), {summary.protected} protected
                              </li>
                            ))}
                          {row.validation_messages.map((entry) => <li key={entry}>{entry}</li>)}
                        </ul>
                      </details>
                    </td>
                    <td>
                      <div style={{ display: "grid", gap: 8, minWidth: 150 }}>
                        {row.status === "validated" && (
                          <>
                            <button
                              type="button"
                              disabled={
                                restoreBusy !== null ||
                                restorePassword.length < 10 ||
                                decisionNote.trim().length < 3 ||
                                row.conflict_count > 0 ||
                                row.update_count === 0
                              }
                              onClick={() => decide(row, "approve")}
                            >
                              Approve
                            </button>
                            <button
                              type="button"
                              className="secondary"
                              disabled={restoreBusy !== null || restorePassword.length < 10 || decisionNote.trim().length < 3}
                              onClick={() => decide(row, "reject")}
                            >
                              Reject
                            </button>
                          </>
                        )}
                        {row.status === "approved" && (
                          <button
                            type="button"
                            disabled={restoreBusy !== null || restorePassword.length < 10 || !restoreFile}
                            onClick={() => applyRestore(row)}
                          >
                            Apply exact ZIP
                          </button>
                        )}
                        {row.status === "applied" && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={restoreBusy !== null || restorePassword.length < 10}
                            onClick={() => rollbackRestore(row)}
                          >
                            Roll back {row.update_count} row(s)
                          </button>
                        )}
                        {row.approval_note && <span className="muted">{row.approval_note}</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="card">
        <h3>Integrity evidence</h3>
        <p className="muted">
          Compare the SHA-256 value below with a checksum calculated from the downloaded ZIP.
          Missing file references are reported in the archive manifest and never hidden.
        </p>
        {rows.length === 0 ? (
          <div className="empty-state">No portable backups have been generated.</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Generated</th>
                  <th>Records</th>
                  <th>Files</th>
                  <th>Missing</th>
                  <th>Size</th>
                  <th>SHA-256</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.id}>
                    <td>{new Date(row.generated_at).toLocaleString()}</td>
                    <td>{row.record_count.toLocaleString()}</td>
                    <td>{row.include_files ? row.file_count.toLocaleString() : "Not included"}</td>
                    <td>{row.missing_file_count.toLocaleString()}</td>
                    <td>{sizeLabel(row.size_bytes)}</td>
                    <td><code style={{ wordBreak: "break-all" }}>{row.sha256}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </ManagerShell>
  );
}
