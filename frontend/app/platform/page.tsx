"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import {
  BillingLifecycleEvent,
  BillingProvider,
  Organization,
  PlanCode,
  PlatformBillingAccount,
  PlatformCommercialReportRow,
  SubscriptionNotice,
  SubscriptionStatus
} from "@/types";

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

type BillingEdit = {
  organization_id: number;
  expected_version: number;
  provider: BillingProvider;
  external_customer_id: string;
  external_subscription_id: string;
  current_period_start: string;
  current_period_end: string;
  grace_ends_at: string;
  cancel_at_period_end: boolean;
  account_password: string;
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
  const [billingAccounts, setBillingAccounts] = useState<PlatformBillingAccount[]>([]);
  const [billingEvents, setBillingEvents] = useState<BillingLifecycleEvent[]>([]);
  const [billingNotices, setBillingNotices] = useState<SubscriptionNotice[]>([]);
  const [commercialRows, setCommercialRows] = useState<PlatformCommercialReportRow[]>([]);
  const [commercialPeriod, setCommercialPeriod] = useState(`${new Date().toISOString().slice(0, 7)}-01`);
  const [commercialPassword, setCommercialPassword] = useState("");
  const [form, setForm] = useState(emptyForm);
  const [edit, setEdit] = useState<CommercialEdit | null>(null);
  const [billingEdit, setBillingEdit] = useState<BillingEdit | null>(null);
  const [refundForm, setRefundForm] = useState({
    organization_id: "",
    payment_intent_id: "",
    amount_minor: "",
    reason: "requested_by_customer" as "duplicate" | "fraudulent" | "requested_by_customer",
    business_reason: "",
    account_password: ""
  });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [organizationRows, accountRows, eventRows, noticeRows, reportRows] = await Promise.all([
        api.listOrganizations(),
        api.listPlatformBillingAccounts(),
        api.listPlatformBillingEvents(),
        api.listPlatformSubscriptionNotices(),
        api.getPlatformCommercialReport(commercialPeriod)
      ]);
      setOrganizations(organizationRows);
      setBillingAccounts(accountRows);
      setBillingEvents(eventRows);
      setBillingNotices(noticeRows);
      setCommercialRows(reportRows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load platform operations.");
    }
  }, [commercialPeriod]);

  useEffect(() => {
    void load();
  }, [load]);

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

  const beginBillingEdit = (organization: Organization) => {
    const account = billingAccounts.find((row) => row.organization_id === organization.id);
    setBillingEdit({
      organization_id: organization.id,
      expected_version: account?.version || 0,
      provider: account?.provider || "manual",
      external_customer_id: account?.external_customer_id || "",
      external_subscription_id: account?.external_subscription_id || "",
      current_period_start: localDateTime(account?.current_period_start),
      current_period_end: localDateTime(account?.current_period_end),
      grace_ends_at: localDateTime(account?.grace_ends_at),
      cancel_at_period_end: account?.cancel_at_period_end || false,
      account_password: ""
    });
    setError("");
    setMessage("");
  };

  const saveBilling = async (event: FormEvent) => {
    event.preventDefault();
    if (!billingEdit) return;
    try {
      setBusy(true);
      setError("");
      const external = billingEdit.provider !== "manual";
      await api.putPlatformBillingAccount(billingEdit.organization_id, {
        expected_version: billingEdit.expected_version,
        provider: billingEdit.provider,
        external_customer_id: external ? billingEdit.external_customer_id.trim() || null : null,
        external_subscription_id: external ? billingEdit.external_subscription_id.trim() || null : null,
        current_period_start: billingEdit.current_period_start ? new Date(billingEdit.current_period_start).toISOString() : null,
        current_period_end: billingEdit.current_period_end ? new Date(billingEdit.current_period_end).toISOString() : null,
        grace_ends_at: billingEdit.grace_ends_at ? new Date(billingEdit.grace_ends_at).toISOString() : null,
        cancel_at_period_end: billingEdit.cancel_at_period_end,
        account_password: billingEdit.account_password
      });
      setBillingEdit(null);
      setMessage("Billing lifecycle binding saved.");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to save billing binding.");
    } finally {
      setBusy(false);
    }
  };

  const reconcileBilling = async () => {
    try {
      setBusy(true);
      setError("");
      const result = await api.reconcilePlatformBilling();
      setMessage(`Billing lifecycle checked ${result.organizations_checked} customers; created ${result.notices_created} and resolved ${result.notices_resolved} notices.`);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to reconcile billing lifecycle.");
    } finally {
      setBusy(false);
    }
  };

  const createRefund = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      const result = await api.createStripeRefund({
        organization_id: Number(refundForm.organization_id),
        payment_intent_id: refundForm.payment_intent_id.trim(),
        amount_minor: refundForm.amount_minor ? Number(refundForm.amount_minor) : null,
        reason: refundForm.reason,
        business_reason: refundForm.business_reason.trim(),
        client_request_id: crypto.randomUUID(),
        account_password: refundForm.account_password
      });
      setMessage(`Stripe refund recorded: ${result.external_object_id || `operation ${result.operation_id}`}.`);
      setRefundForm((current) => ({
        ...current,
        payment_intent_id: "",
        amount_minor: "",
        business_reason: "",
        account_password: ""
      }));
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to create Stripe refund.");
    } finally {
      setBusy(false);
    }
  };

  const refreshCommercialReport = async () => {
    try {
      setBusy(true);
      setError("");
      setCommercialRows(await api.getPlatformCommercialReport(commercialPeriod));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to load commercial report.");
    } finally {
      setBusy(false);
    }
  };

  const exportCommercialReport = async () => {
    try {
      setBusy(true);
      setError("");
      await api.downloadPlatformCommercialReport(commercialPeriod, commercialPassword);
      setCommercialPassword("");
      setMessage("Commercial CSV export generated and audited.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to export commercial report.");
    } finally {
      setBusy(false);
    }
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

      {billingEdit && (
        <section className="card">
          <h2>Billing lifecycle binding</h2>
          <p className="muted">
            Manual mode keeps lifecycle control inside OpenPartsFlow. Generic and Stripe modes accept signed, timestamped provider events with tenant-bound references. No card or payment-method data is stored.
          </p>
          <form onSubmit={saveBilling} style={{ display: "grid", gap: 12 }}>
            <div className="two-col">
              <label>
                Provider mode
                <select
                  value={billingEdit.provider}
                  onChange={(event) => {
                    const provider = event.target.value as BillingProvider;
                    setBillingEdit({
                      ...billingEdit,
                      provider,
                      external_customer_id: provider === "manual" ? "" : billingEdit.external_customer_id,
                      external_subscription_id: provider === "manual" ? "" : billingEdit.external_subscription_id
                    });
                  }}
                >
                  <option value="manual">Manual</option>
                  <option value="generic">Signed generic webhook</option>
                  <option value="stripe">Stripe Billing</option>
                </select>
              </label>
              <label>
                External customer reference
                <input
                  value={billingEdit.external_customer_id}
                  onChange={(event) => setBillingEdit({ ...billingEdit, external_customer_id: event.target.value })}
                  disabled={billingEdit.provider === "manual"}
                  required={billingEdit.provider === "generic"}
                />
              </label>
              <label>
                External subscription reference
                <input
                  value={billingEdit.external_subscription_id}
                  onChange={(event) => setBillingEdit({ ...billingEdit, external_subscription_id: event.target.value })}
                  disabled={billingEdit.provider === "manual"}
                  required={billingEdit.provider === "generic"}
                />
              </label>
              <label>
                Current period starts
                <input type="datetime-local" value={billingEdit.current_period_start} onChange={(event) => setBillingEdit({ ...billingEdit, current_period_start: event.target.value })} />
              </label>
              <label>
                Current period ends
                <input type="datetime-local" value={billingEdit.current_period_end} onChange={(event) => setBillingEdit({ ...billingEdit, current_period_end: event.target.value })} />
              </label>
              <label>
                Payment grace ends
                <input type="datetime-local" value={billingEdit.grace_ends_at} onChange={(event) => setBillingEdit({ ...billingEdit, grace_ends_at: event.target.value })} />
              </label>
              <label style={{ display: "flex", gap: 10, alignItems: "center" }}>
                <input
                  type="checkbox"
                  checked={billingEdit.cancel_at_period_end}
                  onChange={(event) => setBillingEdit({ ...billingEdit, cancel_at_period_end: event.target.checked })}
                  style={{ width: 20, minHeight: 20 }}
                />
                Cancel at period end
              </label>
              <label>
                Confirm platform administrator password
                <input
                  type="password"
                  minLength={10}
                  autoComplete="current-password"
                  value={billingEdit.account_password}
                  onChange={(event) => setBillingEdit({ ...billingEdit, account_password: event.target.value })}
                  required
                />
              </label>
            </div>
            <div className="two-col">
              <button type="submit" disabled={busy}>{busy ? "Saving…" : "Save billing binding"}</button>
              <button type="button" className="secondary-button" onClick={() => setBillingEdit(null)}>Cancel</button>
            </div>
          </form>
        </section>
      )}

      <section className="card">
        <h2>Stripe refund</h2>
        <p className="muted">
          Refunds require platform administrator reauthentication. The server retrieves the PaymentIntent and verifies its Stripe customer belongs to the selected company before issuing the refund.
        </p>
        <form onSubmit={createRefund} style={{ display: "grid", gap: 12 }}>
          <div className="two-col">
            <label>
              Company
              <select
                value={refundForm.organization_id}
                onChange={(event) => setRefundForm({ ...refundForm, organization_id: event.target.value })}
                required
              >
                <option value="">Select company</option>
                {organizations.map((organization) => (
                  <option value={organization.id} key={organization.id}>{organization.name}</option>
                ))}
              </select>
            </label>
            <label>
              Stripe PaymentIntent
              <input
                value={refundForm.payment_intent_id}
                onChange={(event) => setRefundForm({ ...refundForm, payment_intent_id: event.target.value })}
                placeholder="pi_..."
                pattern="pi_[A-Za-z0-9_]+"
                required
              />
            </label>
            <label>
              Amount in minor units (blank for full refund)
              <input
                type="number"
                min="1"
                step="1"
                value={refundForm.amount_minor}
                onChange={(event) => setRefundForm({ ...refundForm, amount_minor: event.target.value })}
              />
            </label>
            <label>
              Stripe reason
              <select
                value={refundForm.reason}
                onChange={(event) => setRefundForm({
                  ...refundForm,
                  reason: event.target.value as typeof refundForm.reason
                })}
              >
                <option value="requested_by_customer">Requested by customer</option>
                <option value="duplicate">Duplicate</option>
                <option value="fraudulent">Fraudulent</option>
              </select>
            </label>
            <label>
              Business reason
              <textarea
                minLength={10}
                maxLength={1000}
                value={refundForm.business_reason}
                onChange={(event) => setRefundForm({ ...refundForm, business_reason: event.target.value })}
                required
              />
            </label>
            <label>
              Confirm platform administrator password
              <input
                type="password"
                minLength={10}
                autoComplete="current-password"
                value={refundForm.account_password}
                onChange={(event) => setRefundForm({ ...refundForm, account_password: event.target.value })}
                required
              />
            </label>
          </div>
          <button type="submit" disabled={busy}>{busy ? "Processing…" : "Issue verified refund"}</button>
        </form>
      </section>

      <section className="card">
        <div className="two-col" style={{ alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Customers</h2>
          <button type="button" className="secondary-button" onClick={() => void reconcileBilling()} disabled={busy}>Reconcile billing notices</button>
        </div>
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
                    {organization.custom_domain && <div className="muted">{organization.custom_domain} · {organization.custom_domain_status}</div>}
                    {organization.email_sender_address && <div className="muted">{organization.email_sender_address}</div>}
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
                      <button type="button" className="secondary-button" onClick={() => beginBillingEdit(organization)}>Billing lifecycle</button>
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

      <section className="two-col">
        <div className="card">
          <h2>Subscription notices</h2>
          <div style={{ display: "grid", gap: 10 }}>
            {billingNotices.slice(0, 20).map((item) => {
              const organization = organizations.find((row) => row.id === item.organization_id);
              return (
                <div className="notice" key={item.id}>
                  <strong>{organization?.name || `Organization ${item.organization_id}`}</strong>
                  <div>{item.notice_type.replaceAll("_", " ")} · {item.severity} · {item.status}</div>
                  <div>{item.message}</div>
                  <div className="muted">{new Date(item.effective_at).toLocaleString()}</div>
                </div>
              );
            })}
            {!billingNotices.length && <div className="empty-state">No subscription notices.</div>}
          </div>
        </div>
        <div className="card">
          <h2>Provider event evidence</h2>
          <div style={{ display: "grid", gap: 10 }}>
            {billingEvents.slice(0, 20).map((item) => {
              const organization = organizations.find((row) => row.id === item.organization_id);
              return (
                <div className="notice" key={item.id}>
                  <strong>{organization?.name || `Organization ${item.organization_id}`}</strong>
                  <div>{item.event_type} · {item.processing_status}</div>
                  <div className="muted">{item.before_subscription_status} → {item.after_subscription_status} · {new Date(item.occurred_at).toLocaleString()}</div>
                  <div className="muted">Event {item.external_event_id}</div>
                </div>
              );
            })}
            {!billingEvents.length && <div className="empty-state">No provider events received.</div>}
          </div>
        </div>
      </section>

      <section className="card">
        <h2>Commercial usage report</h2>
        <p className="muted">Usage is fixed to the selected UTC month. Capacity and limits show the current contract and are labeled as current in the CSV.</p>
        <div className="two-col" style={{ alignItems: "end" }}>
          <label>
            UTC report month
            <input type="month" value={commercialPeriod.slice(0, 7)} onChange={(event) => setCommercialPeriod(`${event.target.value}-01`)} />
          </label>
          <button type="button" className="secondary-button" onClick={() => void refreshCommercialReport()} disabled={busy}>Refresh period</button>
          <label>
            Confirm platform administrator password for CSV
            <input type="password" minLength={10} autoComplete="current-password" value={commercialPassword} onChange={(event) => setCommercialPassword(event.target.value)} />
          </label>
          <button type="button" onClick={() => void exportCommercialReport()} disabled={busy || commercialPassword.length < 10}>Export audited CSV</button>
        </div>
        <div style={{ overflowX: "auto", marginTop: 12 }}>
          <table>
            <thead><tr><th>Customer</th><th>AI usage</th><th>API usage</th><th>Seats</th><th>Inventory locations</th></tr></thead>
            <tbody>
              {commercialRows.map((row) => (
                <tr key={row.organization_id}>
                  <td>{row.organization_name}<div className="muted">{row.plan_code} · {row.subscription_status}</div></td>
                  <td>{row.ai_requests.toLocaleString()} / {row.ai_monthly_limit ?? "Unlimited"}</td>
                  <td>{row.api_requests.toLocaleString()} / {row.api_monthly_limit ?? "Unlimited"}</td>
                  <td>{row.active_users + row.pending_invitations} / {row.max_users ?? "Unlimited"}</td>
                  <td>{row.active_warehouses} main · {row.active_vehicle_warehouses} vehicle</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
