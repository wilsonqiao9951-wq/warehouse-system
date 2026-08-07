"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import {
  EnterpriseAgentEvidence,
  EnterpriseAgentIntent,
  EnterpriseAgentOptions,
  EnterpriseAgentResponse,
  EnterpriseAgentRun
} from "@/types";

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function defaultDates() {
  const to = new Date();
  const from = new Date(to);
  from.setUTCDate(from.getUTCDate() - 29);
  return { from_date: isoDate(from), to_date: isoDate(to) };
}

const presets: Array<{ label: string; intent: EnterpriseAgentIntent; question: string }> = [
  { label: "Daily brief", intent: "daily_brief", question: "Give me the daily operating brief and prioritize the risks that need attention." },
  { label: "Backlog", intent: "backlog_risk", question: "Which backlog risks should operations review first?" },
  { label: "Service quality", intent: "service_quality", question: "Explain our first-time-fix, rework, and repair-duration evidence." },
  { label: "Inventory", intent: "inventory_risk", question: "Where are our current stock and replenishment risks?" },
  { label: "Integrations", intent: "integration_health", question: "Are any outbound integration deliveries failed, pending, or stuck?" }
];

function evidenceValue(item: EnterpriseAgentEvidence): string {
  if (typeof item.value === "string") return item.value;
  if (item.unit === "percent") return `${item.value.toFixed(1)}%`;
  if (item.unit === "currency") return item.value.toLocaleString(undefined, { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  return item.value.toLocaleString();
}

function intentLabel(value: EnterpriseAgentIntent): string {
  return value.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

export default function EnterpriseAgentPage() {
  const [form, setForm] = useState(() => ({
    ...defaultDates(),
    question: presets[0].question,
    intent: "daily_brief" as EnterpriseAgentIntent | "auto",
    engineer_id: "",
    job_type: ""
  }));
  const [options, setOptions] = useState<EnterpriseAgentOptions>({ intents: [], engineers: [], job_types: [] });
  const [result, setResult] = useState<EnterpriseAgentResponse | null>(null);
  const [runs, setRuns] = useState<EnterpriseAgentRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const loadSupportingData = async () => {
    try {
      const [nextOptions, nextRuns] = await Promise.all([
        api.getEnterpriseAgentOptions(),
        api.listEnterpriseAgentRuns(12)
      ]);
      setOptions(nextOptions);
      setRuns(nextRuns);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to load the operations agent.");
    }
  };

  useEffect(() => {
    void loadSupportingData();
  }, []);

  const choosePreset = (preset: (typeof presets)[number]) => {
    setForm((value) => ({ ...value, question: preset.question, intent: preset.intent }));
  };

  const runAgent = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      const response = await api.runEnterpriseAgent({
        question: form.question.trim(),
        intent: form.intent === "auto" ? undefined : form.intent,
        from_date: form.from_date,
        to_date: form.to_date,
        engineer_id: form.engineer_id ? Number(form.engineer_id) : undefined,
        job_type: form.job_type || undefined
      });
      setResult(response);
      setOptions((value) => ({
        ...value,
        engineers: response.filters.engineers,
        job_types: response.filters.job_types
      }));
      setRuns(await api.listEnterpriseAgentRuns(12));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The operations agent could not complete this review.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ManagerShell
      title="Enterprise operations agent"
      subtitle="Read-only, tenant-scoped operational reasoning with source definitions and durable run evidence."
      metrics={[
        { label: "Priority", value: result?.priority || "Not run" },
        { label: "Confidence", value: result ? `${(result.confidence * 100).toFixed(0)}%` : "—" },
        { label: "Evidence run", value: result ? `#${result.run_id}` : "—" }
      ]}
    >
      {error && <p className="notice notice-error" role="alert">{error}</p>}

      <section className="card">
        <h3>Ask an operating question</h3>
        <p className="muted">Each successful run consumes one AI request. The raw question is used for this response but only its SHA-256 digest and length are retained.</p>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
          {presets.map((preset) => <button key={preset.intent} type="button" className="secondary" onClick={() => choosePreset(preset)}>{preset.label}</button>)}
        </div>
        <form onSubmit={runAgent}>
          <label>
            Question
            <textarea required minLength={3} maxLength={1000} rows={4} value={form.question} onChange={(event) => setForm((value) => ({ ...value, question: event.target.value }))} />
          </label>
          <div className="grid">
            <label>Intent<select value={form.intent} onChange={(event) => setForm((value) => ({ ...value, intent: event.target.value as EnterpriseAgentIntent | "auto" }))}><option value="auto">Auto-detect</option>{options.intents.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
            <label>From (UTC)<input type="date" required value={form.from_date} onChange={(event) => setForm((value) => ({ ...value, from_date: event.target.value }))} /></label>
            <label>To (UTC)<input type="date" required value={form.to_date} onChange={(event) => setForm((value) => ({ ...value, to_date: event.target.value }))} /></label>
            <label>Engineer<select value={form.engineer_id} onChange={(event) => setForm((value) => ({ ...value, engineer_id: event.target.value }))}><option value="">All engineers</option>{options.engineers.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
            <label>Job type<select value={form.job_type} onChange={(event) => setForm((value) => ({ ...value, job_type: event.target.value }))}><option value="">All job types</option>{options.job_types.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
          </div>
          <button type="submit" disabled={busy || form.question.trim().length < 3} style={{ marginTop: 12 }}>{busy ? "Reviewing evidence…" : "Run read-only review"}</button>
        </form>
      </section>

      {result && <>
        <section className="card">
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
            <div><div className="muted">Resolved intent</div><h3>{intentLabel(result.intent)}</h3></div>
            <div><div className="muted">Generated</div><strong>{new Date(result.generated_at).toLocaleString()}</strong></div>
          </div>
          <p>{result.summary}</p>
          <p className="muted">Tools: {result.tools_used.join(", ")}</p>
        </section>

        <section className="grid">
          {result.findings.map((finding) => <article className="card" key={finding.code}>
            <div className={finding.severity === "critical" ? "danger" : "muted"}>{finding.severity.toUpperCase()}</div>
            <h3>{finding.title}</h3>
            <p>{finding.summary}</p>
            <p><strong>Recommended next step:</strong> {finding.recommendation}</p>
            <div className="table-wrap"><table><thead><tr><th>Evidence</th><th>Value</th><th>Source and definition</th></tr></thead><tbody>
              {finding.evidence.map((item) => <tr key={item.code}><td>{item.label}</td><td><strong>{evidenceValue(item)}</strong></td><td><div>{item.source}</div><small className="muted">{item.definition}</small></td></tr>)}
            </tbody></table></div>
            {finding.links.length > 0 && <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 12 }}>{finding.links.map((href) => <Link href={href} key={href}>Open {href}</Link>)}</div>}
          </article>)}
        </section>

        <section className="two-col">
          <div className="card">
            <h3>Guardrails</h3>
            <ul>
              <li>Read-only: {result.guardrails.read_only ? "enforced" : "not enforced"}</li>
              <li>Business mutations performed: {result.guardrails.mutations_performed.length}</li>
              <li>Raw question retained: {result.guardrails.raw_question_retained ? "yes" : "no"}</li>
              <li>Cross-tenant access: {result.guardrails.cross_tenant_access ? "yes" : "no"}</li>
              <li>External model called: {result.guardrails.external_model_called ? "yes" : "no"}</li>
            </ul>
          </div>
          <div className="card">
            <h3>Limitations</h3>
            <ul>{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul>
          </div>
        </section>
      </>}

      <section className="card">
        <h3>Recent evidence runs</h3>
        <p className="muted">Question text and generated narrative are not stored. This ledger retains enough metadata to prove who ran which bounded tools and filters.</p>
        <div className="table-wrap"><table><thead><tr><th>Run</th><th>Time</th><th>Intent</th><th>Findings</th><th>Duration</th><th>Question digest</th></tr></thead><tbody>
          {runs.map((run) => <tr key={run.id}><td>#{run.id}</td><td>{new Date(run.created_at).toLocaleString()}</td><td>{intentLabel(run.intent)}</td><td>{run.finding_count}</td><td>{run.duration_ms} ms</td><td><code>{run.question_sha256.slice(0, 16)}…</code></td></tr>)}
          {runs.length === 0 && <tr><td colSpan={6} className="muted">No Agent runs have been recorded.</td></tr>}
        </tbody></table></div>
      </section>
    </ManagerShell>
  );
}
