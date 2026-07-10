"use client";

import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { Organization } from "@/types";

const emptyForm = {
  name: "",
  slug: "",
  admin_name: "",
  admin_email: "",
  admin_password: ""
};

export default function PlatformPage() {
  const [organizations, setOrganizations] = useState<Organization[]>([]);
  const [form, setForm] = useState(emptyForm);
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
      setMessage("Customer organization and first administrator created.");
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
      await api.updateOrganization(organization.id, !organization.is_active);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to update customer.");
    }
  };

  return (
    <div style={{ display: "grid", gap: 20 }}>
      <section className="card">
        <h1>Customer organizations</h1>
        <p className="muted">Create an isolated company account and its first administrator.</p>
        <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
          <div className="two-col">
            <input placeholder="Company name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} required />
            <input placeholder="company-slug" pattern="[a-z0-9]+(?:-[a-z0-9]+)*" value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toLowerCase() })} required />
            <input placeholder="Administrator name" value={form.admin_name} onChange={(e) => setForm({ ...form, admin_name: e.target.value })} required />
            <input type="email" placeholder="Administrator email" value={form.admin_email} onChange={(e) => setForm({ ...form, admin_email: e.target.value })} required />
            <input type="password" minLength={10} placeholder="Initial password" value={form.admin_password} onChange={(e) => setForm({ ...form, admin_password: e.target.value })} required />
          </div>
          {error && <div className="error">{error}</div>}
          {message && <div className="success">{message}</div>}
          <button type="submit" disabled={busy}>{busy ? "Creating…" : "Create customer"}</button>
        </form>
      </section>

      <section className="card">
        <h2>Customers</h2>
        <div style={{ overflowX: "auto" }}>
          <table>
            <thead><tr><th>Company</th><th>Status</th><th>Users</th><th>Parts</th><th>Work orders</th><th>Action</th></tr></thead>
            <tbody>
              {organizations.map((organization) => (
                <tr key={organization.id}>
                  <td>{organization.name}<div className="muted">{organization.slug}</div></td>
                  <td>{organization.is_active ? "Active" : "Suspended"}</td>
                  <td>{organization.total_users}</td>
                  <td>{organization.total_parts}</td>
                  <td>{organization.total_work_orders}</td>
                  <td><button type="button" onClick={() => void toggle(organization)}>{organization.is_active ? "Suspend" : "Activate"}</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
