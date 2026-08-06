"use client";

import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { CompletionPolicy, OrganizationSettings } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";

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

function usageLabel(used: number, limit?: number | null): string {
  if (limit === 0) return "Not included";
  return `${used.toLocaleString()} used / ${limit == null ? "Unlimited" : limit.toLocaleString()}`;
}

export default function SettingsPage() {
  const [policies, setPolicies] = useState<CompletionPolicy[]>([]);
  const [form, setForm] = useState({ ...emptyPolicy });
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [role, setRole] = useState<AppRole>("manager");
  const [organization, setOrganization] = useState<OrganizationSettings | null>(null);
  const [branding, setBranding] = useState({
    brand_logo_url: "",
    brand_primary_color: "#155eef",
    brand_login_headline: ""
  });

  const refreshPolicies = () => api.listCompletionPolicies().then(setPolicies).catch((e: Error) => setError(e.message));
  const refreshOrganization = () => api.getOrganizationSettings().then((settings) => {
    setOrganization(settings);
    setBranding({
      brand_logo_url: settings.brand_logo_url || "",
      brand_primary_color: settings.brand_primary_color,
      brand_login_headline: settings.brand_login_headline || ""
    });
  }).catch((e: Error) => setError(e.message));
  useEffect(() => {
    setRole(getCurrentRole());
    void refreshPolicies();
    void refreshOrganization();
  }, []);

  const save = async (event: FormEvent) => {
    event.preventDefault();
    try {
      await api.saveCompletionPolicy({ ...form, job_type: form.job_type?.trim() || null });
      setNotice("Completion policy saved.");
      setError("");
      await refreshPolicies();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save completion policy.");
    }
  };

  const saveBranding = async (event: FormEvent) => {
    event.preventDefault();
    if (!organization) return;
    try {
      const updated = await api.updateOrganizationBranding({
        expected_version: organization.settings_version,
        brand_logo_url: branding.brand_logo_url.trim() || null,
        brand_primary_color: branding.brand_primary_color,
        brand_login_headline: branding.brand_login_headline.trim() || null
      });
      setOrganization(updated);
      setNotice("Company branding saved.");
      setError("");
      window.dispatchEvent(new Event("opf-organization-branding"));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save company branding.");
    }
  };

  const seatsUsed = organization
    ? organization.active_users + organization.pending_invitations
    : 0;

  return (
    <ManagerShell
      title="Settings"
      subtitle="Company identity, subscription usage, and job completion controls."
      metrics={[
        { label: "Plan", value: organization?.plan_code || "—" },
        {
          label: "Seats",
          value: organization
            ? `${seatsUsed}/${organization.max_users ?? "Unlimited"}`
            : "—"
        },
        { label: "Completion policies", value: policies.length }
      ]}
    >
      {notice && <p className="notice notice-success" role="status">{notice}</p>}
      {error && <p className="notice notice-error" role="alert">{error}</p>}
      {organization && (
        <section className="two-col">
          <div className="card">
            <h3>Company branding</h3>
            <p className="muted">
              Branding appears in the app shell and at{" "}
              <a href={`/login?organization=${encodeURIComponent(organization.slug)}`}>
                the company login link
              </a>.
            </p>
            {role === "admin" ? (
              <form onSubmit={saveBranding} style={{ display: "grid", gap: 12 }}>
                <label>
                  HTTPS logo URL
                  <input
                    type="url"
                    placeholder="https://company.example/logo.png"
                    value={branding.brand_logo_url}
                    onChange={(event) => setBranding((current) => ({
                      ...current,
                      brand_logo_url: event.target.value
                    }))}
                  />
                </label>
                <label>
                  Primary color
                  <input
                    type="color"
                    value={branding.brand_primary_color}
                    onChange={(event) => setBranding((current) => ({
                      ...current,
                      brand_primary_color: event.target.value
                    }))}
                  />
                </label>
                <label>
                  Login headline
                  <input
                    maxLength={200}
                    placeholder="Welcome to your field service workspace"
                    value={branding.brand_login_headline}
                    onChange={(event) => setBranding((current) => ({
                      ...current,
                      brand_login_headline: event.target.value
                    }))}
                  />
                </label>
                <button type="submit">Save branding</button>
              </form>
            ) : (
              <p className="muted">Only a company administrator can change branding.</p>
            )}
          </div>
          <div className="card">
            <h3>Subscription and capacity</h3>
            <div style={{ display: "grid", gap: 10 }}>
              <div><strong>{organization.plan_code}</strong> · {organization.subscription_status}</div>
              {organization.trial_ends_at && (
                <div className="muted">Trial ends {new Date(organization.trial_ends_at).toLocaleString()}</div>
              )}
              <div>Users: {organization.active_users} active + {organization.pending_invitations} invited / {organization.max_users ?? "Unlimited"}</div>
              <div>Main warehouses: {organization.active_warehouses} / {organization.max_warehouses ?? "Unlimited"}</div>
              <div>Vehicle inventories: {organization.active_vehicle_warehouses} / {organization.max_vehicle_warehouses ?? "Unlimited"}</div>
              <div>AI requests: {usageLabel(organization.ai_monthly_used, organization.ai_monthly_limit)}</div>
              <div>External API requests: {usageLabel(organization.api_monthly_used, organization.api_monthly_limit)}</div>
              <div className="muted">Current UTC billing period started {organization.usage_period_start}.</div>
            </div>
          </div>
        </section>
      )}
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
