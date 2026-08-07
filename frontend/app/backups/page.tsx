"use client";

import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { OrganizationDataExport } from "@/types";

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function BackupsPage() {
  const [rows, setRows] = useState<OrganizationDataExport[]>([]);
  const [accountPassword, setAccountPassword] = useState("");
  const [includeFiles, setIncludeFiles] = useState(true);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = () => api.listOrganizationDataExports().then(setRows);

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

  return (
    <ManagerShell
      title="Customer data backups"
      subtitle="Generate a tenant-isolated portable archive and retain integrity evidence."
      metrics={[
        { label: "Recorded exports", value: rows.length },
        { label: "Latest records", value: rows[0]?.record_count ?? "—" },
        { label: "Latest files", value: rows[0]?.file_count ?? "—" }
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
