"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { StockBalance } from "@/types";

export default function MyVanInventoryPage() {
  const [items, setItems] = useState<StockBalance[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const uid = window.localStorage.getItem("opf_user_id");
    if (!uid) {
      setError("Sign in again to load your van inventory.");
      return;
    }
    api.getVanInventory(Number(uid)).then(setItems).catch(() => setError("Failed to load van inventory."));
  }, []);

  return (
    <section className="card">
      <h3>My Van Inventory</h3>
      {error && <p className="notice notice-error">{error}</p>}
      <table>
        <thead>
          <tr>
            <th>Part</th>
            <th>Qty</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={`${it.part_id}-${it.warehouse_id}`}>
              <td>{it.part_number} - {it.part_name}</td>
              <td className={it.is_low_stock ? "danger" : ""}>{it.quantity}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
