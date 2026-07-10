"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { User, WorkOrder } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function WorkOrdersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [engineers, setEngineers] = useState<User[]>([]);
  const [form, setForm] = useState({
    ticket_number: "",
    store_name: "",
    engineer_id: "",
    revenue: "0",
    status: "open"
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [editing, setEditing] = useState<Record<number, { status: string; engineer_id: string; revenue: string }>>({});
  const [role, setRole] = useState<AppRole>("admin");
  const [filters, setFilters] = useState({
    technician_id: searchParams.get("technician_id") || "",
    status: searchParams.get("status") || "",
    city: searchParams.get("city") || "",
    job_type: searchParams.get("job_type") || "",
    date_from: searchParams.get("date_from") || "",
    date_to: searchParams.get("date_to") || "",
    q: searchParams.get("q") || ""
  });
  const [page, setPage] = useState(Number(searchParams.get("page") || "0"));
  const pageSize = 20;

  useEffect(() => {
    setRole(getCurrentRole());
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [orders, users] = await Promise.all([
        api.listWorkOrders({
          skip: page * pageSize,
          limit: pageSize,
          technician_id: filters.technician_id ? Number(filters.technician_id) : undefined,
          status: filters.status || undefined,
          city: filters.city || undefined,
          job_type: filters.job_type || undefined,
          date_from: filters.date_from || undefined,
          date_to: filters.date_to || undefined,
          q: filters.q || undefined
        }),
        api.listEngineers()
      ]);
      setWorkOrders(orders);
      setEngineers(users);
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to load work orders." });
      setWorkOrders([]);
    } finally {
      setLoading(false);
    }
  }, [
    page,
    pageSize,
    filters.technician_id,
    filters.status,
    filters.city,
    filters.job_type,
    filters.date_from,
    filters.date_to,
    filters.q
  ]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const query = new URLSearchParams();
    if (filters.technician_id) query.set("technician_id", filters.technician_id);
    if (filters.status) query.set("status", filters.status);
    if (filters.city) query.set("city", filters.city);
    if (filters.job_type) query.set("job_type", filters.job_type);
    if (filters.date_from) query.set("date_from", filters.date_from);
    if (filters.date_to) query.set("date_to", filters.date_to);
    if (filters.q) query.set("q", filters.q);
    query.set("page", String(page));
    router.replace(`/work-orders?${query.toString()}`);
  }, [filters, page, router]);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!form.ticket_number.trim()) {
      setNotice({ type: "error", text: "Ticket number is required." });
      return;
    }
    try {
      setSaving(true);
      if (role !== "manager" && role !== "admin") {
        setNotice({ type: "error", text: "Only manager/admin can create work orders." });
        return;
      }
      await api.createWorkOrder({
        ticket_number: form.ticket_number,
        store_name: form.store_name,
        engineer_id: form.engineer_id ? Number(form.engineer_id) : undefined,
        assigned_user_id: form.engineer_id ? Number(form.engineer_id) : undefined,
        revenue: Number(form.revenue) || 0,
        status: form.status
      });
      setForm({ ticket_number: "", store_name: "", engineer_id: "", revenue: "0", status: "open" });
      setNotice({ type: "success", text: "Work order created." });
      await load();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to create work order." });
    } finally {
      setSaving(false);
    }
  };

  const setRowField = (id: number, field: "status" | "engineer_id" | "revenue", value: string, order: WorkOrder) => {
    const base = editing[id] || {
      status: order.status,
      engineer_id: String(order.engineer_id || order.assigned_user_id || ""),
      revenue: String(order.revenue)
    };
    setEditing((prev) => ({ ...prev, [id]: { ...base, [field]: value } }));
  };

  const saveRow = async (order: WorkOrder) => {
    const row = editing[order.id];
    if (!row) return;
    try {
      await api.updateWorkOrder(order.id, {
        status: row.status,
        ...(role === "manager" || role === "admin"
          ? {
              revenue: Number(row.revenue) || 0,
              engineer_id: row.engineer_id ? Number(row.engineer_id) : null,
              assigned_user_id: row.engineer_id ? Number(row.engineer_id) : null
            }
          : {})
      });
      setNotice({ type: "success", text: `Work order ${order.ticket_number} updated.` });
      await load();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : `Failed to update ${order.ticket_number}.` });
    }
  };

  const filterBody = (
    <div className="two-col filter-details-body">
      <select value={filters.technician_id} onChange={(e) => setFilters((f) => ({ ...f, technician_id: e.target.value }))}>
        <option value="">All technicians</option>
        {engineers.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name}
          </option>
        ))}
      </select>
      <select value={filters.status} onChange={(e) => setFilters((f) => ({ ...f, status: e.target.value }))}>
        <option value="">All status</option>
        <option value="open">open</option>
        <option value="in_progress">in_progress</option>
        <option value="completed">completed</option>
        <option value="IN_PROGRESS">IN_PROGRESS</option>
        <option value="COMPLETED">COMPLETED</option>
      </select>
      <input placeholder="City" value={filters.city} onChange={(e) => setFilters((f) => ({ ...f, city: e.target.value }))} />
      <input placeholder="WO / Outlet / Address" value={filters.q} onChange={(e) => setFilters((f) => ({ ...f, q: e.target.value }))} />
      <input placeholder="Job type" value={filters.job_type} onChange={(e) => setFilters((f) => ({ ...f, job_type: e.target.value }))} />
      <input type="date" value={filters.date_from} onChange={(e) => setFilters((f) => ({ ...f, date_from: e.target.value }))} />
      <input type="date" value={filters.date_to} onChange={(e) => setFilters((f) => ({ ...f, date_to: e.target.value }))} />
    </div>
  );

  return (
    <ManagerShell
      title="Work Orders"
      subtitle="Manage and track all service jobs."
      metrics={[
        { label: "On this page", value: workOrders.length },
        { label: "Open (page)", value: workOrders.filter((w) => w.status === "open").length },
        { label: "Completed (page)", value: workOrders.filter((w) => w.status === "completed").length }
      ]}
    >
      <details className="card filter-details" open>
        <summary>Filters</summary>
        {filterBody}
      </details>
      <section className="two-col">
        {(role === "manager" || role === "admin") && (
          <div className="card">
            <h3>Create Job</h3>
            <form onSubmit={onSubmit}>
              <div style={{ marginBottom: 8 }}>
                <input
                  placeholder="Ticket number"
                  value={form.ticket_number}
                  onChange={(e) => setForm({ ...form, ticket_number: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <input
                  placeholder="Store name"
                  value={form.store_name}
                  onChange={(e) => setForm({ ...form, store_name: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <select value={form.engineer_id} onChange={(e) => setForm({ ...form, engineer_id: e.target.value })}>
                  <option value="">Assign engineer</option>
                  {engineers.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.name}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ marginBottom: 8 }}>
                <input
                  type="number"
                  placeholder="Revenue"
                  value={form.revenue}
                  onChange={(e) => setForm({ ...form, revenue: e.target.value })}
                />
              </div>
              <div style={{ marginBottom: 8 }}>
                <select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                  <option value="open">open</option>
                  <option value="in_progress">in_progress</option>
                  <option value="completed">completed</option>
                </select>
              </div>
              <button type="submit" disabled={saving}>
                {saving ? "Creating..." : "Create Work Order"}
              </button>
            </form>
            {notice && <p className={`notice ${notice.type === "success" ? "notice-success" : "notice-error"}`}>{notice.text}</p>}
          </div>
        )}

        <div className="card">
          <h3>Jobs</h3>
          {notice && notice.type === "error" && !loading && (
            <p className="notice notice-error" style={{ marginTop: 0 }}>
              {notice.text}
            </p>
          )}
          {loading ? (
            <div style={{ display: "grid", gap: 8 }}>
              <div className="skeleton" style={{ width: "70%" }} />
              <div className="skeleton" style={{ width: "90%" }} />
              <div className="skeleton" style={{ width: "55%" }} />
            </div>
          ) : workOrders.length === 0 ? (
            <div className="empty-state">No work orders match these filters.</div>
          ) : (
            <>
              <div className="wo-card-list">
                {workOrders.map((w) => (
                  <div key={w.id} className={`job-card${w.is_locked ? " job-card--locked" : ""}`}>
                    <div>
                      <strong>{w.ticket_number}</strong>{" "}
                      <span className="muted">
                        {w.wo_number ? `· ${w.wo_number}` : ""} ({w.status})
                      </span>
                    </div>
                    {(role === "manager" || role === "admin") && (
                      <>
                        <select
                          style={{ marginTop: 8 }}
                          value={editing[w.id]?.engineer_id ?? String(w.engineer_id || w.assigned_user_id || "")}
                          onChange={(e) => setRowField(w.id, "engineer_id", e.target.value, w)}
                        >
                          <option value="">Engineer</option>
                          {engineers.map((u) => (
                            <option key={u.id} value={u.id}>
                              {u.name}
                            </option>
                          ))}
                        </select>
                        <input
                          style={{ marginTop: 8 }}
                          type="number"
                          value={editing[w.id]?.revenue ?? String(w.revenue)}
                          onChange={(e) => setRowField(w.id, "revenue", e.target.value, w)}
                        />
                      </>
                    )}
                    <select
                      style={{ marginTop: 8 }}
                      value={editing[w.id]?.status ?? w.status}
                      onChange={(e) => setRowField(w.id, "status", e.target.value, w)}
                    >
                      <option value="open">open</option>
                      <option value="in_progress">in_progress</option>
                      <option value="completed">completed</option>
                    </select>
                    <div className="one-hand-actions" style={{ marginTop: 10 }}>
                      <button type="button" onClick={() => saveRow(w)}>
                        Save
                      </button>
                      <Link className="nav-item" href={`/work-order-details?work_order_id=${w.id}`}>
                        Details
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
              <div className="table-wrap wo-table-desktop">
                <table>
                  <thead>
                    <tr>
                      <th>Ticket</th>
                      {(role === "manager" || role === "admin") && <th>Engineer</th>}
                      {(role === "manager" || role === "admin") && <th>Revenue</th>}
                      <th>Status</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {workOrders.map((w) => (
                      <tr key={w.id}>
                        <td>{w.ticket_number}</td>
                        {(role === "manager" || role === "admin") && (
                          <td>
                            <select
                              value={editing[w.id]?.engineer_id ?? String(w.engineer_id || w.assigned_user_id || "")}
                              onChange={(e) => setRowField(w.id, "engineer_id", e.target.value, w)}
                            >
                              <option value="">-</option>
                              {engineers.map((u) => (
                                <option key={u.id} value={u.id}>
                                  {u.name}
                                </option>
                              ))}
                            </select>
                          </td>
                        )}
                        {(role === "manager" || role === "admin") && (
                          <td>
                            <input
                              type="number"
                              value={editing[w.id]?.revenue ?? String(w.revenue)}
                              onChange={(e) => setRowField(w.id, "revenue", e.target.value, w)}
                            />
                          </td>
                        )}
                        <td>
                          <select
                            value={editing[w.id]?.status ?? w.status}
                            onChange={(e) => setRowField(w.id, "status", e.target.value, w)}
                          >
                            <option value="open">open</option>
                            <option value="in_progress">in_progress</option>
                            <option value="completed">completed</option>
                          </select>
                        </td>
                        <td>
                          <div style={{ display: "grid", gap: 6 }}>
                            <button type="button" onClick={() => saveRow(w)}>
                              Save
                            </button>
                            <Link className="nav-item" href={`/work-order-details?work_order_id=${w.id}`}>
                              Details
                            </Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}
          <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
            <button type="button" onClick={() => setPage((p) => Math.max(0, p - 1))}>
              Prev
            </button>
            <button type="button" onClick={() => setPage((p) => p + 1)}>
              Next
            </button>
            <span className="muted" style={{ alignSelf: "center" }}>
              Page {page + 1}
            </span>
          </div>
        </div>
      </section>
    </ManagerShell>
  );
}
