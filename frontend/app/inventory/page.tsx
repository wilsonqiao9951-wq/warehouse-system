"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { LocationStockBalance, LowStockAlert, StockBalance, User } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function InventoryPage() {
  const [balances, setBalances] = useState<StockBalance[]>([]);
  const [engineers, setEngineers] = useState<User[]>([]);
  const [selectedEngineer, setSelectedEngineer] = useState<number | "">("");
  const [vanInventory, setVanInventory] = useState<StockBalance[]>([]);
  const [alerts, setAlerts] = useState(0);
  const [lowStockRows, setLowStockRows] = useState<LowStockAlert[]>([]);
  const [locationBalances, setLocationBalances] = useState<LocationStockBalance[]>([]);
  const [role, setRole] = useState<AppRole>("admin");

  useEffect(() => {
    const currentRole = getCurrentRole();
    setRole(currentRole);
  }, []);

  useEffect(() => {
    Promise.all([role === "engineer" ? Promise.resolve([]) : api.listInventoryBalances(), api.listEngineers()]).then(
      ([b, eng]) => {
        setBalances(b);
        setEngineers(eng);
      }
    );
    api
      .getLowStockAlerts()
      .then((rows) => {
        setAlerts(rows.length);
        setLowStockRows(rows);
      })
      .catch(() => {
        setAlerts(0);
        setLowStockRows([]);
      });
    if (role !== "engineer") api.listLocationBalances().then(setLocationBalances).catch(() => setLocationBalances([]));
  }, [role]);
  useEffect(() => {
    if (role === "engineer") {
      api.listUsers().then((users) => {
        const mine = users.find((u) => u.role === "engineer");
        if (mine) setSelectedEngineer(mine.id);
      });
    }
  }, [role]);


  useEffect(() => {
    if (!selectedEngineer) {
      setVanInventory([]);
      return;
    }
    api.getVanInventory(Number(selectedEngineer)).then(setVanInventory).catch(() => setVanInventory([]));
  }, [selectedEngineer]);

  const grouped = useMemo(() => {
    const rows = new Map<string, { qty: number; low: number }>();
    balances.forEach((item) => {
      const current = rows.get(item.warehouse_name) || { qty: 0, low: 0 };
      current.qty += item.quantity;
      if (item.is_low_stock) current.low += 1;
      rows.set(item.warehouse_name, current);
    });
    return Array.from(rows.entries());
  }, [balances]);

  return (
    <ManagerShell
      title="Inventory"
      subtitle="Warehouse and van stock visibility."
      metrics={[
        { label: "Warehouse Rows", value: grouped.length },
        { label: "Van Items", value: vanInventory.length },
        { label: "Low Stock Alerts", value: alerts }
      ]}
    >
      {lowStockRows.length > 0 && (
        <div className="card" style={{ borderColor: "#fca5a5", background: "#fff7ed" }}>
          <h3 className="section-title" style={{ color: "#9a3412" }}>
            Low stock alerts ({lowStockRows.length})
          </h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {lowStockRows.slice(0, 12).map((row) => (
              <div key={`${row.warehouse_id}-${row.part_id}`} className="job-card" style={{ margin: 0 }}>
                <strong>{row.part_number}</strong> {row.part_name}
                <div className="muted">
                  {row.warehouse_name}: qty {row.quantity} (min {row.min_stock})
                </div>
              </div>
            ))}
            {lowStockRows.length > 12 && (
              <p className="muted" style={{ margin: 0 }}>
                +{lowStockRows.length - 12} more rows in API.
              </p>
            )}
          </div>
        </div>
      )}
    <section className="two-col">
      {role !== "engineer" && (
        <div className="card">
          <h3>Stock Per Warehouse</h3>
          <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Warehouse</th>
                <th>Total Qty</th>
                <th>Low Stock SKU</th>
              </tr>
            </thead>
            <tbody>
              {grouped.map(([name, stat]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td>{stat.qty}</td>
                  <td className={stat.low > 0 ? "danger" : ""}>{stat.low}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </div>
      )}

      <div className="card">
        <h3>Van Inventory</h3>
        <select
          value={selectedEngineer}
          onChange={(e) => setSelectedEngineer(e.target.value ? Number(e.target.value) : "")}
          disabled={role === "engineer"}
        >
          <option value="">Select engineer</option>
          {engineers.map((u) => (
            <option key={u.id} value={u.id}>
              {u.name}
            </option>
          ))}
        </select>
        <div className="table-wrap">
        <table style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>Part</th>
              <th>Qty</th>
            </tr>
          </thead>
          <tbody>
            {vanInventory.map((item) => (
              <tr key={`${item.warehouse_id}-${item.part_id}`}>
                <td>
                  {item.part_number} - {item.part_name}
                </td>
                <td className={item.is_low_stock ? "danger" : ""}>{item.quantity}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      </div>
    </section>
    {role !== "engineer" && locationBalances.some((row) => row.quantity !== 0) && (
      <div className="card">
        <h3>Stock by Storage Location</h3>
        <div className="table-wrap"><table><thead><tr><th>Warehouse</th><th>Location</th><th>Item</th><th>Qty</th></tr></thead>
          <tbody>{locationBalances.filter((row) => row.quantity !== 0).map((row) => (
            <tr key={`${row.location_id}-${row.part_id}`}><td>{row.warehouse_name}</td><td>{row.location_code}</td><td>{row.part_number} — {row.part_name}</td><td>{row.quantity}</td></tr>
          ))}</tbody>
        </table></div>
      </div>
    )}
    </ManagerShell>
  );
}
