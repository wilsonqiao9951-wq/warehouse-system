"use client";

import { useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { PilotAttestationType, PilotCampaign, PilotChecklist, PilotRole } from "@/types";

const today = () => new Date().toISOString().slice(0, 10);
const plusDays = (days: number) => {
  const value = new Date();
  value.setDate(value.getDate() + days);
  return value.toISOString().slice(0, 10);
};
const label = (code: string) => code.replaceAll("_", " ");

export default function PilotChecklistPage() {
  const [checklist, setChecklist] = useState<PilotChecklist | null>(null);
  const [campaigns, setCampaigns] = useState<PilotCampaign[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [role, setRole] = useState<string>("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [campaignName, setCampaignName] = useState("Three-day controlled pilot");
  const [plannedStart, setPlannedStart] = useState(today());
  const [plannedEnd, setPlannedEnd] = useState(plusDays(2));
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const [attestationType, setAttestationType] = useState<PilotAttestationType>("training");
  const [completedItems, setCompletedItems] = useState<string[]>([]);
  const [attestationNote, setAttestationNote] = useState("");
  const [issueSeverity, setIssueSeverity] = useState<"sev1" | "sev2" | "sev3">("sev3");
  const [issueTitle, setIssueTitle] = useState("");
  const [issueDetail, setIssueDetail] = useState("");

  const selected = useMemo(
    () => campaigns.find((item) => item.id === selectedId) ?? campaigns[0] ?? null,
    [campaigns, selectedId]
  );
  const operationalRole = (["admin", "manager", "warehouse", "engineer"] as string[]).includes(role)
    ? (role as PilotRole)
    : null;
  const required = selected && operationalRole
    ? selected.required_items[operationalRole][attestationType]
    : [];
  const canCreate = role === "admin" || role === "manager";

  const refresh = async (preferredId?: number) => {
    const [currentChecklist, currentCampaigns, me] = await Promise.all([
      api.getPilotChecklist().catch(() => null),
      api.listPilotCampaigns(),
      api.getMe(),
    ]);
    setChecklist(currentChecklist);
    setCampaigns(currentCampaigns);
    setRole(me.role);
    const candidate = preferredId ?? selectedId ?? currentCampaigns[0]?.id ?? null;
    setSelectedId(candidate);
  };

  useEffect(() => {
    refresh().catch((e: Error) => setError(e.message || "Failed to load pilot governance."));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setCompletedItems([]);
  }, [attestationType, selectedId]);

  const run = async (action: () => Promise<PilotCampaign>, success: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await action();
      await refresh(updated.id);
      setNotice(success);
      setPassword("");
      setReason("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pilot action failed.");
    } finally {
      setBusy(false);
    }
  };

  const createCampaign = async () => {
    setBusy(true);
    setError("");
    try {
      const created = await api.createPilotCampaign({
        name: campaignName,
        planned_start: plannedStart,
        planned_end: plannedEnd,
      });
      await refresh(created.id);
      setNotice("Draft pilot campaign created. Activate it only when the controlled window is ready.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to create pilot campaign.");
    } finally {
      setBusy(false);
    }
  };

  const recordAttestation = (result: "passed" | "failed") => {
    if (!selected) return;
    run(
      () => api.attestPilotCampaign(selected.id, {
        attestation_type: attestationType,
        result,
        completed_items: completedItems,
        note: attestationNote,
        account_password: password,
      }),
      `${attestationType} evidence recorded for the signed-in ${role} account.`
    ).then(() => {
      setCompletedItems([]);
      setAttestationNote("");
    });
  };

  const reportIssue = async () => {
    if (!selected) return;
    await run(
      () => api.createPilotIssue(selected.id, {
        severity: issueSeverity,
        title: issueTitle,
        detail: issueDetail,
      }),
      "Pilot issue recorded with your account attribution."
    );
    setIssueTitle("");
    setIssueDetail("");
  };

  return (
    <ManagerShell
      title="Pilot Governance"
      subtitle="Authenticated training, UAT, issue closure, and internal Go/No-Go evidence. A Go decision is not customer legal acceptance."
      showDefaultControls={false}
    >
      {error && <p className="notice notice-error">{error}</p>}
      {notice && <p className="notice notice-success">{notice}</p>}

      {checklist && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Live readiness snapshot</h3>
          <div className={`notice ${checklist.readiness_status === "ready" ? "notice-success" : checklist.readiness_status === "blocked" ? "notice-error" : ""}`}>
            <strong>{checklist.readiness_status}</strong>
            {checklist.readiness_reasons.length > 0 && (
              <ul style={{ marginBottom: 0 }}>
                {checklist.readiness_reasons.map((item) => <li key={item}>{item}</li>)}
              </ul>
            )}
          </div>
          <div className="pilot-metric-grid">
            <div className="pilot-metric"><div className="muted">System</div><div className="metric" style={{ fontSize: 20 }}>{checklist.system_health}</div></div>
            <div className="pilot-metric"><div className="muted">Users</div><div className="metric">{checklist.total_users}</div></div>
            <div className="pilot-metric"><div className="muted">Work orders</div><div className="metric">{checklist.total_work_orders}</div></div>
            <div className={`pilot-metric${checklist.integration_parallel_readiness !== "matched" ? " pilot-metric--alert" : ""}`}>
              <div className="muted">Parallel run</div><div className="metric" style={{ fontSize: 18 }}>{checklist.integration_parallel_readiness}</div>
            </div>
          </div>
        </section>
      )}

      {canCreate && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Create controlled pilot</h3>
          <div className="two-col">
            <label>Name<input value={campaignName} onChange={(e) => setCampaignName(e.target.value)} /></label>
            <label>Start<input type="date" value={plannedStart} onChange={(e) => setPlannedStart(e.target.value)} /></label>
            <label>End<input type="date" value={plannedEnd} onChange={(e) => setPlannedEnd(e.target.value)} /></label>
          </div>
          <button className="primary" disabled={busy || !campaignName.trim()} onClick={createCampaign}>Create draft</button>
        </section>
      )}

      {campaigns.length > 0 && (
        <section className="card">
          <label>
            Pilot campaign
            <select value={selected?.id ?? ""} onChange={(e) => setSelectedId(Number(e.target.value))}>
              {campaigns.map((item) => <option value={item.id} key={item.id}>{item.name} · {item.status}</option>)}
            </select>
          </label>
        </section>
      )}

      {selected && (
        <>
          <section className="card">
            <div style={{ display: "flex", gap: 12, justifyContent: "space-between", flexWrap: "wrap" }}>
              <div>
                <h3 style={{ margin: 0 }}>{selected.name}</h3>
                <p className="muted" style={{ marginBottom: 0 }}>{selected.planned_start} → {selected.planned_end} · version {selected.version}</p>
              </div>
              <strong>{selected.status}</strong>
            </div>
            <div className="pilot-metric-grid" style={{ marginTop: 16 }}>
              {Object.entries(selected.gates).map(([gate, passed]) => (
                <div className={`pilot-metric${passed ? "" : " pilot-metric--alert"}`} key={gate}>
                  <div className="muted">{label(gate)}</div><strong>{passed ? "passed" : "required"}</strong>
                </div>
              ))}
            </div>
            {selected.gate_reasons.length > 0 && <ul>{selected.gate_reasons.map((item) => <li key={item}>{item}</li>)}</ul>}
            {selected.decision_fingerprint && (
              <p><strong>Immutable decision evidence:</strong> <code>{selected.decision_fingerprint}</code></p>
            )}
          </section>

          {selected.can_manage && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>Campaign state</h3>
              <div className="two-col">
                <label>Current account password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
                <label>Operational reason<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              </div>
              {selected.status === "draft" && <button className="primary" disabled={busy || !password || !reason} onClick={() => run(() => api.transitionPilotCampaign(selected.id, { expected_version: selected.version, target_status: "active", account_password: password, reason }), "Pilot activated.")}>Activate</button>}
              {selected.status === "active" && <button className="primary" disabled={busy || !password || !reason} onClick={() => run(() => api.transitionPilotCampaign(selected.id, { expected_version: selected.version, target_status: "decision_pending", account_password: password, reason }), "Pilot moved to decision review.")}>Request decision</button>}
              {selected.status === "decision_pending" && <button disabled={busy || !password || !reason} onClick={() => run(() => api.transitionPilotCampaign(selected.id, { expected_version: selected.version, target_status: "active", account_password: password, reason }), "Pilot returned to active remediation.")}>Return to active</button>}
            </section>
          )}

          {selected.can_attest && operationalRole && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>My authenticated training / UAT evidence</h3>
              <p className="muted">Only your signed-in account and current role are recorded. Pass is refused until every fixed item is checked.</p>
              <label>Evidence type<select value={attestationType} onChange={(e) => setAttestationType(e.target.value as PilotAttestationType)}><option value="training">training</option><option value="uat">UAT</option></select></label>
              <div style={{ display: "grid", gap: 8, margin: "12px 0" }}>
                {required.map((item) => (
                  <label key={item} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <input
                      type="checkbox"
                      checked={completedItems.includes(item)}
                      onChange={(e) => setCompletedItems((current) => e.target.checked ? [...current, item] : current.filter((value) => value !== item))}
                    />
                    {label(item)}
                  </label>
                ))}
              </div>
              <div className="two-col">
                <label>Evidence note<input value={attestationNote} onChange={(e) => setAttestationNote(e.target.value)} /></label>
                <label>Current account password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
              </div>
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <button className="primary" disabled={busy || !password || attestationNote.trim().length < 3 || completedItems.length !== required.length} onClick={() => recordAttestation("passed")}>Record passed</button>
                <button disabled={busy || !password || attestationNote.trim().length < 3} onClick={() => recordAttestation("failed")}>Record failed / blocked</button>
              </div>
              {selected.latest_attestations.map((item) => (
                <p key={item.id} className="muted">{item.attestation_type}: {item.result} · {new Date(item.created_at).toLocaleString()} · <code>{item.evidence_fingerprint.slice(0, 12)}…</code></p>
              ))}
            </section>
          )}

          {selected.status === "active" || selected.status === "decision_pending" ? (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>Report pilot issue</h3>
              <div className="two-col">
                <label>Severity<select value={issueSeverity} onChange={(e) => setIssueSeverity(e.target.value as "sev1" | "sev2" | "sev3")}><option value="sev1">sev1 — stop</option><option value="sev2">sev2 — material</option><option value="sev3">sev3 — minor</option></select></label>
                <label>Title<input value={issueTitle} onChange={(e) => setIssueTitle(e.target.value)} /></label>
              </div>
              <label>Observed result<textarea value={issueDetail} onChange={(e) => setIssueDetail(e.target.value)} /></label>
              <button disabled={busy || issueTitle.trim().length < 3 || issueDetail.trim().length < 3} onClick={reportIssue}>Report with my account</button>
            </section>
          ) : null}

          {selected.issues.length > 0 && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>Issues</h3>
              {selected.issues.map((item) => (
                <article key={item.id} style={{ borderTop: "1px solid var(--border)", padding: "12px 0" }}>
                  <strong>{item.severity} · {item.status} · {item.title}</strong>
                  <p>{item.detail}</p>
                  {selected.can_resolve_issues && item.status === "open" && (
                    <button disabled={busy || !password || !reason} onClick={() => run(() => api.resolvePilotIssue(selected.id, item.id, { expected_version: item.version, resolution_reason: reason, account_password: password }), "Issue resolved with versioned evidence.")}>Resolve using password and reason above</button>
                  )}
                </article>
              ))}
            </section>
          )}

          {selected.can_decide && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>Final internal technical decision</h3>
              <p className="notice">Go requires all role training/UAT gates, no open sev1, and a matched latest parallel run. It does not represent customer commercial or legal acceptance.</p>
              <div className="two-col">
                <label>Current admin password<input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" /></label>
                <label>Decision reason<input value={reason} onChange={(e) => setReason(e.target.value)} /></label>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button className="primary" disabled={busy || !password || !reason || !selected.gates.go_ready} onClick={() => run(() => api.decidePilotCampaign(selected.id, { expected_version: selected.version, decision: "go", reason, account_password: password }), "Internal Go decision recorded.")}>Record Go</button>
                <button disabled={busy || !password || !reason} onClick={() => run(() => api.decidePilotCampaign(selected.id, { expected_version: selected.version, decision: "no_go", reason, account_password: password }), "No-Go decision recorded; AppSheet remains primary.")}>Record No-Go</button>
              </div>
            </section>
          )}
        </>
      )}
    </ManagerShell>
  );
}
