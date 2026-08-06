"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Organization, PlanCode, SubscriptionStatus } from "@/types";

const planDefaults: Record<PlanCode, {
  max_users: string;
  max_warehouses: string;
  max_vehicle_warehouses: string;
  ai_monthly_limit: string;
  api_monthly_limit: string;
}> = {
  starter: {
    max_users: "5",
    max_warehouses: "1",
    max_vehicle_warehouses: "1",
    ai_monthly_limit: "0",
    api_monthly_limit: "0"
  },
  professional: {
    max_users: "50",
    max_warehouses: "10",
    max_vehicle_warehouses: "50",
    ai_monthly_limit: "2000",
    api_monthly_limit: "10000"
  },
  enterprise: {
    max_users: "",
    max_warehouses: "",
    max_vehicle_warehouses: "",
    ai_monthly_limit: "",
    api_monthly_limit: ""
  }
};

const emptyForm = {
  name: "",
  slug: "",
  admin_name: "",
  admin_email: "",
  admin_password: "",
  plan_code: "professional" as PlanCode,
  trial_days: 14
};

type CommercialEdit = {
  organization_id: number;
  expected_version: number;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  trial_ends_at: string;
  max_users: string;
  max_warehouses: string;
  max_vehicle_warehouses: string;
  ai_monthly_limit: string;
  api_monthly_limit: string;
};

function localDateTime(value?: string | null): string {
  if (!value) return "";
  const date = new Date(value);
  const offset = date.getTimezoneOffset() * 60_000;
  return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

function optionalLimit(value: string): number | null {
  return value ? Number(value) : null;
}

function usageLabel(used: number, limit?: number | null): string {
  if (limit === 0) return "not included";
  return `${used.toLocaleString()}/${limit == null ? "unlimited" : limit.toLocaleString()}`;
}

export default function PlatformPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [edit, setEdit] = useState<CommercialEdit | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = () => api.listOrganizations().then(setOrganizations).catch((err: Error) => setError(err.message));

  useEffect(() => {
    void load();
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      setMessage("");
      await api.createOrganization(form);
      setForm(emptyForm);
      setMessage("Customer organization, trial, plan, and first administrator created.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create customer.");
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (organization: Organization) => {
    try {
      setError("");
      await api.updateOrganization(organization.id, {
        expected_version: organization.settings_version,
        is_active: !organization.is_active
      });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update customer.");
    }
  };

  const beginEdit = (organization: Organization) => {
    setEdit({
      organization_id: organization.id,
      expected_version: organization.settings_version,
      plan_code: organization.plan_code,
      subscription_status: organization.subscription_status,
      trial_ends_at: localDateTime(organization.trial_ends_at),
      max_users: organization.max_users?.toString() || "",
      max_warehouses: organization.max_warehouses?.toString() || "",
      max_vehicle_warehouses: organization.max_vehicle_warehouses?.toString() || "",
      ai_monthly_limit: organization.ai_monthly_limit?.toString() || "",
      api_monthly_limit: organization.api_monthly_limit?.toString() || ""
    });
    setError("");
    setMessage("");
  };

  const saveCommercial = async (event: FormEvent) => {
    event.preventDefault();
    if (!edit) return;
    try {
      setBusy(true);
      setError("");
      const trialEnd = edit.trial_ends_at
        ? new Date(edit.trial_ends_at).toISOString()
        : null;
      await api.updateOrganization(edit.organization_id, {
        expected_version: edit.expected_version,
        plan_code: edit.plan_code,
        subscription_status: edit.subscription_status,
        trial_ends_at: trialEnd,
        max_users: optionalLimit(edit.max_users),
        max_warehouses: optionalLimit(edit.max_warehouses),
        max_vehicle_warehouses: optionalLimit(edit.max_vehicle_warehouses),
        ai_monthly_limit: optionalLimit(edit.ai_monthly_limit),
        api_monthly_limit: optionalLimit(edit.api_monthly_limit)
      });
      window.dispatchEvent(new Event("opf-organization-branding"));
      setMessage("Commercial plan and capacity controls saved.");
      setEdit(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save plan.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section className="card">
        <h1>Customer organizations</h1>
        <p className="muted">Create an isolated company account, commercial trial, plan, and first administrator.</p>
        <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
          <div className="two-col">
            <input placeholder="Company name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <input placeholder="company-slug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })} required />
            <input placeholder="Administrator name" value={form.admin_name} onChange={(e) => setForm({ ...form, admin_name: e.target.value })} required />
            <input type="email" placeholder="Administrator email" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} required />
            <input type="password" minLength={10} placeholder="Initial password" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} required />
            <select value={form.plan_code} onChange={(e) => setForm({ ...form, plan_code: e.target.value as PlanCode })}>
              <option value="starter">Starter</option>
              <option value="professional">Professional</option>
              <option value="enterprise">Enterprise</option>
            </select>
            <label>
              Trial days
              <input type="number" min={0} max={90} value={form.trial_days} onChange={(e) => setForm({ ...form, trial_days: Number(e.target.value) })} />
            </label>
          </div>
          {error && <div className="error">{error}</div>}
          {message && <div className="success">{message}</div>}
          <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create customer"}</button>
        </form>
      </section>

      {edit && (
        <section className="card">
          <h2>Edit commercial controls</h2>
          <p className="muted">Blank limits mean unlimited or contract-governed. Changing a plan loads its standard limits; explicit values are stored as customer overrides.</p>
          <form onSubmit={saveCommercial} style={{ display: "grid", gap: 12 }}>
            <div className="two-col">
              <label>
                Plan
                <select
                  value={edit.plan_code}
                  onChange={(event) => {
                    const plan_code = event.target.value as PlanCode;
                    setEdit({ ...edit, plan_code, ...planDefaults[plan_code] });
                  }}
                >
                  <option value="starter">Starter</option>
                  <option value="professional">Professional</option>
                  <option value="enterprise">Enterprise</option>
                </select>
              </label>
              <label>
                Subscription status
                <select
                  value={edit.subscription_status}
                  onChange={(event) => {
                    const subscription_status = event.target.value as SubscriptionStatus;
                    const trial_ends_at = (
                      subscription_status === "trialing" && !edit.trial_ends_at
                    )
                      ? localDateTime(new Date(Date.now() + 14 * 86_400_000).toISOString())
                      : edit.trial_ends_at;
                    setEdit({ ...edit, subscription_status, trial_ends_at });
                  }}
                >
                  <option value="trialing">Trialing</option>
                  <option value="active">Active</option>
                  <option value="past_due">Past due</option>
                  <option value="suspended">Suspended</option>
                  <option value="cancelled">Cancelled</option>
                </select>
              </label>
              <label>
                Trial ends
                <input type="datetime-local" value={edit.trial_ends_at} onChange={(event) => setEdit({ ...edit, trial_ends_at: event.target.value })} />
              </label>
              <label>User limit<input type="number" min={1} value={edit.max_users} onChange={(event) => setEdit({ ...edit, max_users: event.target.value })} /></label>
              <label>Main warehouse limit<input type="number" min={1} value={edit.max_warehouses} onChange={(event) => setEdit({ ...edit, max_warehouses: event.target.value })} /></label>
              <label>Vehicle inventory limit<input type="number" min={1} value={edit.max_vehicle_warehouses} onChange={(event) => setEdit({ ...edit, max_vehicle_warehouses: event.target.value })} /></label>
              <label>AI monthly limit<input type="number" min={0} value={edit.ai_monthly_limit} onChange={(event) => setEdit({ ...edit, ai_monthly_limit: event.target.value })} /></label>
              <label>API monthly limit<input type="number" min={0} value={edit.api_monthly_limit} onChange={(event) => setEdit({ ...edit, api_monthly_limit: event.target.value })} /></label>
            </div>
            <div className="two-col">
              <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save commercial controls"}</button>
              <button type="button" className="secondary-button" onClick={() => setEdit(null)}>Cancel</button>
            </div>
          </form>
        </section>
      )}

      <section className="card">
        <h2>Customers</h2>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead>
              <tr>
                <th>Company</th>
                <th>Access</th>
                <th>Plan</th>
                <th>Capacity</th>
                <th>Work orders</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {organizations.map((organization) => (
                <tr key={organization.id}>
                  <td>
                    {organization.name}
                    <div className="muted">{organization.slug}</div>
                  </td>
                  <td>
                    {organization.is_active ? organization.subscription_status : "suspended by platform"}
                    {organization.trial_ends_at && <div className="muted">until {new Date(organization.trial_ends_at).toLocaleDateString()}</div>}
                  </td>
                  <td>{organization.plan_code}</td>
                  <td>
                    <div>Seats {organization.active_users + organization.pending_invitations}/{organization.max_users ?? "∞"}</div>
                    <div className="muted">Warehouses {organization.active_warehouses}/{organization.max_warehouses ?? "∞"} · Vans {organization.active_vehicle_warehouses}/{organization.max_vehicle_warehouses ?? "∞"}</div>
                    <div className="muted">AI {usageLabel(organization.ai_monthly_used, organization.ai_monthly_limit)} · API {usageLabel(organization.api_monthly_used, organization.api_monthly_limit)}</div>
                    <div className="muted">Period {organization.usage_period_start}</div>
                  </td>
                  <td>{organization.total_work_orders}</td>
                  <td>
                    <div style={{ display: "grid", gap: 8 }}>
                      <button type="button" onClick={() => beginEdit(organization)}>Plan & limits</button>
                      <button type="button" className="secondary-button" onClick={() => void toggle(organization)}>
                        {organization.is_active ? "Suspend" : "Activate"}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
