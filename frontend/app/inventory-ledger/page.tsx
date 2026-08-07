"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import {
  InventoryLedgerFilters,
  InventoryLedgerOptions,
  InventoryLedgerRow,
  InventoryTransactionType
} from "@/types";

interface FilterForm {
  transactionType: "" | InventoryTransactionType;
  partId: string;
  warehouseId: string;
  userId: string;
  workOrderId: string;
  fromDate: string;
  toDate: string;
}

const TYPE_LABELS: Record<InventoryTransactionType, string> = {
  inbound: "Inbound",
  outbound: "Outbound",
  transfer: "Transfer",
  work_order_used: "Work order use",
  return: "Return",
  adjustment: "Adjustment",
  damage: "Damage"
};

const SOURCE_LABELS: Record<InventoryLedgerRow["source"], string> = {
  manual: "Manual entry",
  work_order: "Work order",
  replenishment: "Replenishment",
  vehicle_return: "Vehicle return",
  inventory_count: "Inventory count"
};

function localDate(daysAgo = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

const DEFAULT_FILTERS: FilterForm = {
  transactionType: "",
  partId: "",
  warehouseId: "",
  userId: "",
  workOrderId: "",
  fromDate: localDate(29),
  toDate: localDate()
};

function toApiFilters(values: FilterForm): InventoryLedgerFilters {
  const from = values.fromDate ? new Date(`${values.fromDate}T00:00:00`) : null;
  const to = values.toDate ? new Date(`${values.toDate}T23:59:59.999`) : null;
  return {
    ...(values.transactionType ? { transaction_type: values.transactionType } : {}),
    ...(Number(values.partId) > 0 ? { part_id: Number(values.partId) } : {}),
    ...(Number(values.warehouseId) > 0 ? { warehouse_id: Number(values.warehouseId) } : {}),
    ...(Number(values.userId) > 0 ? { user_id: Number(values.userId) } : {}),
    ...(Number(values.workOrderId) > 0 ? { work_order_id: Number(values.workOrderId) } : {}),
    ...(from ? { from_at: from.toISOString() } : {}),
    ...(to ? { to_at: to.toISOString() } : {})
  };
}

function formatTimestamp(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(normalized));
}

function formatMoney(value: number) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD"
  }).format(value);
}

function locationLabel(row: InventoryLedgerRow, side: "from" | "to") {
  const code = side === "from" ? row.from_warehouse_code : row.to_warehouse_code;
  const name = side === "from" ? row.from_warehouse_name : row.to_warehouse_name;
  const location = side === "from" ? row.from_location_code : row.to_location_code;
  if (!code && !name) return "External / none";
  return `${code || name}${location ? ` / ${location}` : ""}`;
}

function evidenceLabel(row: InventoryLedgerRow) {
  if (row.replenishment_request_id) return `Replenishment #${row.replenishment_request_id}`;
  if (row.vehicle_return_request_id) return `Vehicle return #${row.vehicle_return_request_id}`;
  if (row.inventory_count_line_id) return `Count line #${row.inventory_count_line_id}`;
  return `Ledger #${row.id}`;
}

export default function InventoryLedgerPage() {
  const [draft, setDraft] = useState<FilterForm>({ ...DEFAULT_FILTERS });
  const [activeFilters, setActiveFilters] = useState<InventoryLedgerFilters>(() => toApiFilters(DEFAULT_FILTERS));
  const [options, setOptions] = useState<InventoryLedgerOptions | null>(null);
  const [rows, setRows] = useState<InventoryLedgerRow[]>([]);
  const [total, setTotal] = useState(0);
  const [nextBeforeId, setNextBeforeId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (
    filters: InventoryLedgerFilters,
    beforeId?: number,
    append = false
  ) => {
    try {
      setLoading(true);
      setError("");
      const page = await api.getInventoryLedger(filters, beforeId);
      setRows((current) => append ? [...current, ...page.items] : page.items);
      setTotal(page.total);
      setNextBeforeId(page.next_before_id ?? null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to load inventory ledger.");
      if (!append) setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = toApiFilters(DEFAULT_FILTERS);
    void Promise.all([
      load(initial),
      api.getInventoryLedgerOptions().then(setOptions)
    ]).catch((caught) => {
      setError(caught instanceof Error ? caught.message : "Unable to load ledger filters.");
    });
  }, [load]);

  const metrics = useMemo(() => {
    const typeCount = new Set(rows.map((row) => row.transaction_type)).size;
    const loadedValue = rows.reduce((sum, row) => sum + row.total_cost, 0);
    return { typeCount, loadedValue };
  }, [rows]);

  const applyFilters = (event: FormEvent) => {
    event.preventDefault();
    if (draft.fromDate && draft.toDate && draft.toDate < draft.fromDate) {
      setError("End date must be on or after start date.");
      return;
    }
    const filters = toApiFilters(draft);
    setActiveFilters(filters);
    void load(filters);
  };

  const resetFilters = () => {
    const next = { ...DEFAULT_FILTERS };
    const filters = toApiFilters(next);
    setDraft(next);
    setActiveFilters(filters);
    void load(filters);
  };

  return (
    <ManagerShell
      title="Inventory Ledger"
      subtitle="Trace every tenant-owned stock movement from operational source to warehouse, work order, and accountable user."
      showDefaultControls={false}
      metrics={[
        { label: "Matching Movements", value: total },
        { label: "Loaded Evidence", value: rows.length },
        { label: "Movement Types", value: metrics.typeCount },
        { label: "Loaded Value", value: formatMoney(metrics.loadedValue) }
      ]}
    >
      <section className="card">
        <form onSubmit={applyFilters}>
          <div className="two-col">
            <label>
              Movement type
              <select
                value={draft.transactionType}
                onChange={(event) => setDraft({ ...draft, transactionType: event.target.value as FilterForm["transactionType"] })}
              >
                <option value="">All movement types</option>
                {(options?.transaction_types || Object.keys(TYPE_LABELS) as InventoryTransactionType[]).map((type) => (
                  <option key={type} value={type}>{TYPE_LABELS[type]}</option>
                ))}
              </select>
            </label>
            <label>
              Part
              <select value={draft.partId} onChange={(event) => setDraft({ ...draft, partId: event.target.value })}>
                <option value="">All referenced parts</option>
                {options?.parts.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
            </label>
            <label>
              Warehouse (source or destination)
              <select value={draft.warehouseId} onChange={(event) => setDraft({ ...draft, warehouseId: event.target.value })}>
                <option value="">All referenced warehouses</option>
                {options?.warehouses.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
            </label>
            <label>
              Accountable user
              <select value={draft.userId} onChange={(event) => setDraft({ ...draft, userId: event.target.value })}>
                <option value="">All referenced users</option>
                {options?.users.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
              </select>
            </label>
            <label>
              Work order ID
              <input type="number" min={1} value={draft.workOrderId} onChange={(event) => setDraft({ ...draft, workOrderId: event.target.value })} />
            </label>
            <span aria-hidden="true" />
            <label>
              From date
              <input type="date" value={draft.fromDate} onChange={(event) => setDraft({ ...draft, fromDate: event.target.value })} />
            </label>
            <label>
              To date
              <input type="date" value={draft.toDate} onChange={(event) => setDraft({ ...draft, toDate: event.target.value })} />
            </label>
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 12 }}>
            <button type="submit" disabled={loading}>Apply filters</button>
            <button type="button" className="secondary" onClick={resetFilters} disabled={loading}>Reset to 30 days</button>
          </div>
        </form>
      </section>

      <section className="card">
        <div style={{ display: "flex", justifyContent: "space-between", gap: 12, alignItems: "baseline" }}>
          <h3>Movement evidence</h3>
          <span className="muted">Showing {rows.length} of {total}</span>
        </div>
        <p className="muted">
          Reconciliation references point to the workflow that created the movement. Stock corrections remain controlled by inventory counts and approved warehouse workflows.
        </p>
        {error && <p className="notice notice-error">{error}</p>}
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Movement</th>
                <th>Part / quantity</th>
                <th>Route</th>
                <th>Work order</th>
                <th>Accountability</th>
                <th>Evidence</th>
              </tr>
            </thead>
            <tbody>
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} className="muted">No inventory movements match these filters.</td></tr>
              )}
              {rows.map((row) => (
                <tr key={row.id}>
                  <td>{formatTimestamp(row.created_at)}</td>
                  <td>
                    <strong>{TYPE_LABELS[row.transaction_type]}</strong>
                    <div className="muted">{SOURCE_LABELS[row.source]}{row.movement_stage ? ` · ${row.movement_stage}` : ""}</div>
                  </td>
                  <td>
                    <strong>{row.part_number}</strong> — {row.part_name}
                    <div>{row.quantity} · {formatMoney(row.unit_cost)} each · {formatMoney(row.total_cost)}</div>
                  </td>
                  <td>
                    <div>{locationLabel(row, "from")}</div>
                    <div className="muted">to {locationLabel(row, "to")}</div>
                  </td>
                  <td>
                    {row.work_order_id ? (
                      <Link href={`/work-order-details?work_order_id=${row.work_order_id}`}>
                        {row.work_order_ticket_number || `Work order #${row.work_order_id}`}
                      </Link>
                    ) : "—"}
                  </td>
                  <td>{row.user_name || (row.user_id ? `User #${row.user_id}` : "System")}</td>
                  <td>
                    <strong>{evidenceLabel(row)}</strong>
                    {row.notes && <div className="muted">{row.notes}</div>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {nextBeforeId && (
          <button
            type="button"
            className="secondary"
            style={{ marginTop: 12 }}
            disabled={loading}
            onClick={() => void load(activeFilters, nextBeforeId, true)}
          >
            {loading ? "Loading..." : "Load more"}
          </button>
        )}
      </section>
    </ManagerShell>
  );
}
