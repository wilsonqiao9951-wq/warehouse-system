"use client";

import { FormEvent, useEffect, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { CompletionPolicy, OrganizationDomain, OrganizationSettings } from "@/types";
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
  const [domain, setDomain] = useState<OrganizationDomain | null>(null);
  const [domainInput, setDomainInput] = useState("");
  const [domainPassword, setDomainPassword] = useState("");
  const [domainBusy, setDomainBusy] = useState(false);
  const [emailIdentity, setEmailIdentity] = useState({
    from_name: "",
    local_part: "dispatch",
    enabled: false
  });
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

  useEffect(() => {
    if (role !== "admin" || !organization || organization.plan_code === "starter") return;
    api.getOrganizationDomain().then((value) => {
      setDomain(value);
      setDomainInput(value?.domain || "");
      setEmailIdentity({
        from_name: value?.email_from_name || organization.name,
        local_part: value?.email_from_local_part || "dispatch",
        enabled: value?.email_identity_enabled || false
      });
    }).catch((e: Error) => setError(e.message));
  }, [organization, role]);

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

  const saveDomain = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setDomainBusy(true);
      setError("");
      const updated = await api.putOrganizationDomain(domainInput.trim(), domainPassword, domain?.version);
      setDomain(updated);
      setDomainInput(updated.domain);
      setDomainPassword("");
      setNotice(updated.status === "verified" ? "Custom domain saved." : "Custom domain challenge created. Add the TXT record, then verify it.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save custom domain.");
    } finally {
      setDomainBusy(false);
    }
  };

  const verifyDomain = async () => {
    if (!domain) return;
    try {
      setDomainBusy(true);
      setError("");
      const updated = await api.verifyOrganizationDomain(domain.version);
      setDomain(updated);
      setNotice(updated.status === "verified" ? "Domain ownership verified." : "DNS record is not visible yet. Check the value and try again after propagation.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to verify custom domain.");
    } finally {
      setDomainBusy(false);
    }
  };

  const rotateDomainChallenge = async () => {
    if (!domain) return;
    try {
      setDomainBusy(true);
      setError("");
      const updated = await api.rotateOrganizationDomainChallenge(domain.version, domainPassword);
      setDomain(updated);
      setDomainPassword("");
      setEmailIdentity((current) => ({ ...current, enabled: false }));
      setNotice("DNS challenge rotated. The previous TXT value is no longer valid.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to rotate DNS challenge.");
    } finally {
      setDomainBusy(false);
    }
  };

  const saveEmailIdentity = async (event: FormEvent) => {
    event.preventDefault();
    if (!domain) return;
    try {
      setDomainBusy(true);
      setError("");
      const updated = await api.updateOrganizationEmailIdentity({
        expected_version: domain.version,
        account_password: domainPassword,
        ...emailIdentity
      });
      setDomain(updated);
      setDomainPassword("");
      setEmailIdentity({
        from_name: updated.email_from_name || "",
        local_part: updated.email_from_local_part || "dispatch",
        enabled: updated.email_identity_enabled
      });
      setNotice(updated.email_identity_enabled ? "Customer sender identity enabled." : "Customer sender identity disabled.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to save sender identity.");
    } finally {
      setDomainBusy(false);
    }
  };

  const removeDomain = async () => {
    if (!domain || !window.confirm("Remove this verified domain and sender identity?")) return;
    try {
      setDomainBusy(true);
      setError("");
      await api.deleteOrganizationDomain(domain.version, domainPassword);
      setDomain(null);
      setDomainInput("");
      setDomainPassword("");
      setEmailIdentity({ from_name: organization?.name || "", local_part: "dispatch", enabled: false });
      setNotice("Custom domain removed.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unable to remove custom domain.");
    } finally {
      setDomainBusy(false);
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
      {organization && role === "admin" && (
        <section className="card">
          <h3>Custom domain and sender identity</h3>
          {organization.plan_code === "starter" ? (
            <p className="muted">Custom domains are available on Professional and Enterprise plans.</p>
          ) : (
            <div style={{ display: "grid", gap: 16 }}>
              <form onSubmit={saveDomain} style={{ display: "grid", gap: 10 }}>
                <label>
                  Customer portal hostname
                  <input
                    placeholder="service.company.com"
                    value={domainInput}
                    onChange={(event) => setDomainInput(event.target.value)}
                    required
                  />
                </label>
                <label>
                  Confirm administrator password
                  <input
                    type="password"
                    autoComplete="current-password"
                    minLength={10}
                    value={domainPassword}
                    onChange={(event) => setDomainPassword(event.target.value)}
                    required
                  />
                </label>
                <p className="muted" style={{ margin: 0 }}>
                  Required to configure or change the domain, rotate its challenge,
                  change its sender identity, or remove it. DNS checks do not use your password.
                </p>
                <button type="submit" disabled={domainBusy}>{domainBusy ? "Saving…" : domain ? "Change domain" : "Configure domain"}</button>
              </form>
              {domain && (
                <>
                  <div>
                    <strong>{domain.domain}</strong> · {domain.status}
                    {domain.login_url && <div><a href={domain.login_url}>Open branded login</a></div>}
                    {domain.last_checked_at && <div className="muted">Last checked {new Date(domain.last_checked_at).toLocaleString()}</div>}
                    {domain.verification_error && <div className="error">{domain.verification_error}</div>}
                  </div>
                  {domain.status === "pending" && (
                    <div className="notice">
                      Add this DNS record at your DNS provider:
                      <div style={{ marginTop: 8 }}><strong>Type:</strong> {domain.verification_record_type}</div>
                      <div><strong>Name:</strong> <code>{domain.verification_name}</code></div>
                      <div><strong>Value:</strong> <code>{domain.verification_value}</code></div>
                    </div>
                  )}
                  <div className="two-col">
                    <button type="button" onClick={() => void verifyDomain()} disabled={domainBusy}>Check DNS</button>
                    <button type="button" className="secondary-button" onClick={() => void rotateDomainChallenge()} disabled={domainBusy}>Rotate challenge</button>
                  </div>
                  {domain.status === "verified" && (
                    <form onSubmit={saveEmailIdentity} style={{ display: "grid", gap: 10 }}>
                      <h4 style={{ marginBottom: 0 }}>Customer sender identity</h4>
                      <p className="muted" style={{ margin: 0 }}>This reserves the verified From identity for future notification delivery. An outbound email provider must still be connected before messages are sent.</p>
                      <div className="two-col">
                        <label>
                          Sender name
                          <input value={emailIdentity.from_name} onChange={(event) => setEmailIdentity({ ...emailIdentity, from_name: event.target.value })} required />
                        </label>
                        <label>
                          Address before @
                          <input value={emailIdentity.local_part} onChange={(event) => setEmailIdentity({ ...emailIdentity, local_part: event.target.value.toLowerCase() })} required />
                        </label>
                      </div>
                      <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
                        <input type="checkbox" checked={emailIdentity.enabled} onChange={(event) => setEmailIdentity({ ...emailIdentity, enabled: event.target.checked })} style={{ width: 20, minHeight: 20 }} />
                        Enable {emailIdentity.local_part || "dispatch"}@{domain.domain}
                      </label>
                      <button type="submit" disabled={domainBusy}>Save sender identity</button>
                    </form>
                  )}
                  <button type="button" className="secondary-button" onClick={() => void removeDomain()} disabled={domainBusy}>Remove custom domain</button>
                </>
              )}
            </div>
          )}
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
