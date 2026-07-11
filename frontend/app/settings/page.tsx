"use client";

import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { CompletionPolicy } from "@/types";

const emptyPolicy = {
  job_type: null as string | null,
  require_repair_result: false,
  require_customer_signature: false,
  require_completion_photo: false,
  require_all_checklist_items: false,
  require_parts_usage: false,
  require_manager_approval: false
};

const rules = [
  ["require_repair_result", "Require repair result"],
  ["require_customer_signature", "Require customer signature"],
  ["require_completion_photo", "Require at least one field photo"],
  ["require_all_checklist_items", "Require all field checklist items"],
  ["require_parts_usage", "Require at least one recorded part"],
  ["require_manager_approval", "Require manager approval before locking"]
] as const;

export default function SettingsPage() {
  const [policies, setPolicies] = useState<CompletionPolicy[]>([]);
  const [form, setForm] = useState({ ...emptyPolicy });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const refresh = () => api.listCompletionPolicies().then(setPolicies).catch((e: Error) => setError(e.message));
  useEffect(() => { void refresh(); }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.saveCompletionPolicy({ ...form, job_type: form.job_type?.trim() || null });
      setNotice("Completion policy saved.");
      setError("");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save completion policy.");
    }
  };

  return (
    <ManagerShell title="Settings" subtitle="Company and job-type completion controls." metrics={[{ label: "Completion policies", value: policies.length }]}>
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      <section className="card">
        <h3>Work-order completion policy</h3>
        <p className="muted">Leave job type blank for the company default. A matching job type overrides that default.</p>
        <form onSubmit={save}>
          <label>
            Job type override
            <input value={form.job_type || ""} onChange={(e) => setForm((prev) => ({ ...prev, job_type: e.target.value || null }))} placeholder="Blank = all work orders" />
          </label>
          <div style={{ display: "grid", gap: 10, margin: "16px 0" }}>
            {rules.map(([key, label]) => <label key={key} style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <input type="checkbox" checked={form[key]} onChange={(e) => setForm((prev) => ({ ...prev, [key]: e.target.checked }))} style={{ width: 20, minHeight: 20 }} />
              {label}
            </label>)}
          </div>
          <button type="submit">Save policy</button>
          <button type="button" onClick={() => setForm({ ...emptyPolicy })} style={{ marginLeft: 8 }}>New default</button>
        </form>
      </section>
      <section className="card">
        <h3>Configured policies</h3>
        {policies.length === 0 ? <div className="empty-state">No policy configured. Legacy-compatible completion rules apply.</div> : policies.map((policy) => (
          <button key={policy.id || policy.job_type || "default"} type="button" className="nav-item" style={{ display: "block", width: "100%", textAlign: "left", marginBottom: 8 }} onClick={() => setForm({
            job_type: policy.job_type || null,
            require_repair_result: policy.require_repair_result,
            require_customer_signature: policy.require_customer_signature,
            require_completion_photo: policy.require_completion_photo,
            require_all_checklist_items: policy.require_all_checklist_items,
            require_parts_usage: policy.require_parts_usage,
            require_manager_approval: policy.require_manager_approval
          })}>
            <strong>{policy.job_type || "Company default"}</strong> · {rules.filter(([key]) => policy[key]).length} active rules
          </button>
        ))}
      </section>
    </ManagerShell>
  );
}
