"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { AbnormalUsageRow, PartUsageBaseline, PartUsageEvaluation } from "@/types";

type QueueStatus = "active" | "pending" | "acknowledged" | "confirmed" | "dismissed" | "all";

const reasonLabels: Record<string, string> = {
  quantity_spike: "Quantity spike",
  unusual_part_combination: "Rare part combination",
  off_hour_usage: "Off-hours usage"
};

export default function AbnormalUsagePage() {
  const [rows, setRows] = useState<AbnormalUsageRow[]>([]);
  const [baselines, setBaselines] = useState<PartUsageBaseline[]>([]);
  const [status, setStatus] = useState<QueueStatus>("active");
  const [severity, setSeverity] = useState<"" | "low" | "medium" | "high">("");
  const [notes, setNotes] = useState<Record<number, string>>({});
  const [evaluation, setEvaluation] = useState<PartUsageEvaluation | null>(null);
  const [showBaselines, setShowBaselines] = useState(false);
  const [busy, setBusy] = useState<number | "evaluate" | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [queue, currentBaselines] = await Promise.all([
        api.getAbnormalUsage({ status, severity: severity || undefined }),
        api.listPartUsageBaselines()
      ]);
      setRows(queue);
      setBaselines(currentBaselines);
      setError("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load part usage reviews.");
    }
  }, [severity, status]);

  useEffect(() => {
    void load();
  }, [load]);

  const counts = useMemo(() => ({
    high: rows.filter((row) => row.severity === "high").length,
    acknowledged: rows.filter((row) => row.status === "acknowledged").length
  }), [rows]);

  const evaluate = async (continueAfter?: number) => {
    try {
      setBusy("evaluate");
      setError("");
      const result = await api.evaluateAbnormalUsage(5000, continueAfter);
      setEvaluation(result);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to evaluate usage history.");
    } finally {
      setBusy(null);
    }
  };

  const act = async (row: AbnormalUsageRow, action: "acknowledge" | "confirm" | "dismiss") => {
    const evidence = (notes[row.id] || "").trim();
    if (evidence.length < 3) {
      setError(action === "acknowledge" ? "Add an acknowledgement note first." : "Add a decision reason first.");
      return;
    }
    try {
      setBusy(row.id);
      setError("");
      await api.actOnAbnormalUsage(row.id, {
        action,
        expected_version: row.version,
        ...(action === "acknowledge" ? { note: evidence } : { reason: evidence })
      });
      setNotes((current) => ({ ...current, [row.id]: "" }));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to update the review.");
    } finally {
      setBusy(null);
    }
  };

  return (
    <ManagerShell
      title="Part Usage Reviews"
      subtitle="Explainable quantity, combination, and local off-hours signals with accountable manager decisions."
      metrics={[
        { label: "Visible reviews", value: rows.length },
        { label: "High severity", value: counts.high },
        { label: "Acknowledged", value: counts.acknowledged },
        { label: "Stored baselines", value: baselines.length }
      ]}
    >
      <section className="card">
        <div className="two-col" style={{ alignItems: "end" }}>
          <label>
            Queue status
            <select value={status} onChange={(event) => setStatus(event.target.value as QueueStatus)}>
              <option value="active">Active</option>
              <option value="pending">Pending</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="confirmed">Confirmed history</option>
              <option value="dismissed">Dismissed history</option>
              <option value="all">All</option>
            </select>
          </label>
          <label>
            Severity
            <select value={severity} onChange={(event) => setSeverity(event.target.value as typeof severity)}>
              <option value="">All severity</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
          </label>
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
          <button type="button" onClick={() => void evaluate()} disabled={busy !== null}>
            {busy === "evaluate" ? "Evaluating…" : "Evaluate stored usage"}
          </button>
          <button type="button" className="secondary" onClick={() => setShowBaselines((value) => !value)}>
            {showBaselines ? "Hide baselines" : "Inspect baselines"}
          </button>
          <button type="button" className="secondary" onClick={() => void load()} disabled={busy !== null}>
            Refresh
          </button>
        </div>
        {evaluation && (
          <p className="notice" style={{ marginTop: 12 }}>
            Scanned {evaluation.scanned}; created {evaluation.created}; already evaluated {evaluation.already_evaluated};
            no signal {evaluation.no_anomaly}{evaluation.truncated ? "; more rows remain" : ""}.
            {evaluation.truncated && evaluation.next_after_id ? (
              <>{" "}<button type="button" className="secondary" onClick={() => void evaluate(evaluation.next_after_id || undefined)} disabled={busy !== null}>Continue scan</button></>
            ) : null}
          </p>
        )}
        {error && <p className="notice notice-error">{error}</p>}
      </section>

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Review queue</h3>
        <p className="muted">
          Signals never change inventory. A manager must acknowledge the evidence before confirming or dismissing it.
        </p>
        {rows.length === 0 && !error ? <div className="empty-state">No reviews match these filters.</div> : null}
        <div style={{ display: "grid", gap: 14 }}>
          {rows.map((row) => (
            <article key={row.id} className="abnormal-card">
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <div>
                  <strong>{row.ticket_number}</strong> · {row.part_number} — {row.part_name}
                  <div className="muted" style={{ marginTop: 3 }}>
                    {row.engineer_name || "Unassigned engineer"} · {row.warehouse_name} · review #{row.id}
                  </div>
                </div>
                <div>
                  <span className={row.severity === "high" ? "danger" : "muted"} style={{ fontWeight: 700 }}>
                    {row.severity.toUpperCase()}
                  </span>{" "}· {row.status}
                </div>
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 10 }}>
                {row.reason_codes.map((code) => (
                  <span key={code} className="status-badge">{reasonLabels[code] || code}</span>
                ))}
              </div>
              <div className="abnormal-card__reason" style={{ marginTop: 10 }}>
                {row.explanations.map((explanation) => <div key={explanation}>{explanation}</div>)}
              </div>
              <div className="two-col" style={{ marginTop: 12 }}>
                <div>
                  <strong>{row.observed_quantity}</strong> observed · ${row.observed_parts_cost.toFixed(2)} parts cost
                  <div className="muted">Local hour {String(row.usage_local_hour ?? "—").padStart(2, "0")}:00 · {row.usage_timezone}</div>
                </div>
                <div>
                  Baseline {row.baseline_scope || "insufficient history"} · {row.baseline_sample_size} samples
                  <div className="muted">
                    Mean {row.baseline_mean_quantity.toFixed(2)} · P90 {row.baseline_p90_quantity.toFixed(2)} · threshold {row.baseline_spike_threshold.toFixed(2)}
                  </div>
                </div>
              </div>
              {row.status === "acknowledged" && row.acknowledged_by_name && (
                <p className="muted">Acknowledged by {row.acknowledged_by_name}: {row.acknowledgement_note}</p>
              )}
              {(row.status === "confirmed" || row.status === "dismissed") && (
                <p className="muted">Decided by {row.reviewed_by_name || "manager"}: {row.decision_reason}</p>
              )}
              {(row.status === "pending" || row.status === "acknowledged") && (
                <div style={{ marginTop: 12 }}>
                  <label>
                    {row.status === "pending" ? "Acknowledgement note" : "Decision reason"}
                    <textarea
                      rows={2}
                      maxLength={row.status === "pending" ? 500 : 1000}
                      value={notes[row.id] || ""}
                      onChange={(event) => setNotes((current) => ({ ...current, [row.id]: event.target.value }))}
                      placeholder={row.status === "pending" ? "Who will check this and what evidence will be reviewed?" : "Why is this signal confirmed or dismissed?"}
                    />
                  </label>
                  {row.status === "pending" ? (
                    <button type="button" onClick={() => void act(row, "acknowledge")} disabled={busy !== null}>
                      {busy === row.id ? "Saving…" : "Acknowledge"}
                    </button>
                  ) : (
                    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                      <button type="button" onClick={() => void act(row, "confirm")} disabled={busy !== null}>Confirm anomaly</button>
                      <button type="button" className="secondary" onClick={() => void act(row, "dismiss")} disabled={busy !== null}>Dismiss signal</button>
                    </div>
                  )}
                </div>
              )}
              <details style={{ marginTop: 12 }}>
                <summary>Evidence identity</summary>
                <code style={{ overflowWrap: "anywhere" }}>{row.evaluation_version} · {row.source_fingerprint}</code>
              </details>
            </article>
          ))}
        </div>
      </section>

      {showBaselines && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Stored baseline evidence</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Part</th><th>Scope</th><th>Context</th><th>Samples</th><th>Mean</th><th>P90</th><th>Spike threshold</th><th>Support</th></tr>
              </thead>
              <tbody>
                {baselines.map((row) => (
                  <tr key={row.id}>
                    <td>{row.part_number}</td>
                    <td>{row.scope}</td>
                    <td>{[row.job_type_key, row.machine_type_key, row.store_key].filter(Boolean).join(" / ") || "organization"}</td>
                    <td>{row.sample_work_orders} / {row.segment_work_orders}</td>
                    <td>{row.mean_quantity.toFixed(2)}</td>
                    <td>{row.p90_quantity.toFixed(2)}</td>
                    <td>{row.spike_threshold.toFixed(2)}</td>
                    <td>{(row.support_ratio * 100).toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </ManagerShell>
  );
}
