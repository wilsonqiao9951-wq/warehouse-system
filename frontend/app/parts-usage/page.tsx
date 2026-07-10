"use client";

import { FormEvent, useEffect, useId, useState } from "react";
import { api } from "@/lib/api";
import { Part, User, Warehouse, WorkOrder } from "@/types";

type SubmitPhase = "idle" | "uploading" | "saving";

export default function PartsUsagePage() {
  const cameraInputId = useId();
  const libraryInputId = useId();
  const [parts, setParts] = useState<Part[]>([]);
  const [orders, setOrders] = useState<WorkOrder[]>([]);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [engineers, setEngineers] = useState<User[]>([]);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [submitPhase, setSubmitPhase] = useState<SubmitPhase>("idle");
  const [uploadPct, setUploadPct] = useState(0);
  const [photoFile, setPhotoFile] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState("");

  const [form, setForm] = useState({
    work_order_id: "",
    part_id: "",
    warehouse_id: "",
    user_id: "",
    quantity: "1"
  });

  const revokePreview = (url: string) => {
    if (url.startsWith("blob:")) {
      URL.revokeObjectURL(url);
    }
  };

  const setPhotoFromFile = (file: File | null) => {
    setPhotoFile(file);
    setPhotoPreview((prev) => {
      revokePreview(prev);
      return file ? URL.createObjectURL(file) : "";
    });
  };

  useEffect(() => {
    return () => revokePreview(photoPreview);
  }, [photoPreview]);

  useEffect(() => {
    Promise.all([api.listParts(), api.listWorkOrders(), api.listWarehouses(), api.listEngineers()])
      .then(([p, w, wh, u]) => {
        setParts(p);
        setOrders(w);
        setWarehouses(wh);
        setEngineers(u);
      })
      .catch((e: Error) => setError(e.message || "Failed to load data"));
  }, []);

  const onSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!form.work_order_id || !form.part_id || !form.warehouse_id || !form.quantity) {
      setError("Please complete all required fields.");
      return;
    }
    try {
      setError("");
      setMessage("");
      let notes = "";
      if (photoFile) {
        setSubmitPhase("uploading");
        setUploadPct(0);
        const uploaded = await api.uploadPartUsagePhoto(Number(form.work_order_id), photoFile, (p) => setUploadPct(p));
        notes = `photo_url=${uploaded.url}`;
        setUploadPct(100);
      }
      setSubmitPhase("saving");
      await api.usePartOnWorkOrder(Number(form.work_order_id), {
        work_order_id: Number(form.work_order_id),
        part_id: Number(form.part_id),
        warehouse_id: Number(form.warehouse_id),
        user_id: form.user_id ? Number(form.user_id) : null,
        quantity: Number(form.quantity),
        unit_cost: parts.find((p) => p.id === Number(form.part_id))?.default_cost || 0,
        notes
      });
      setMessage("Part used successfully. Inventory auto-deducted.");
      setPhotoFromFile(null);
      setUploadPct(0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to submit part usage.");
    } finally {
      setSubmitPhase("idle");
      setUploadPct(0);
    }
  };

  const busy = submitPhase !== "idle";

  return (
    <section className="card">
      <h3>Parts Usage</h3>
      <p className="muted">Assign part usage to a work order. Optional photo attaches to the usage note.</p>
      <form onSubmit={onSubmit}>
        <div className="two-col">
          <select value={form.work_order_id} onChange={(e) => setForm({ ...form, work_order_id: e.target.value })}>
            <option value="">Select work order</option>
            {orders.map((w) => (
              <option key={w.id} value={w.id}>
                {w.ticket_number}
              </option>
            ))}
          </select>

          <select value={form.part_id} onChange={(e) => setForm({ ...form, part_id: e.target.value })}>
            <option value="">Select part</option>
            {parts.map((p) => (
              <option key={p.id} value={p.id}>
                {p.part_number} - {p.name}
              </option>
            ))}
          </select>

          <select value={form.warehouse_id} onChange={(e) => setForm({ ...form, warehouse_id: e.target.value })}>
            <option value="">Stock warehouse</option>
            {warehouses.map((wh) => (
              <option key={wh.id} value={wh.id}>
                {wh.name}
              </option>
            ))}
          </select>

          <select value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}>
            <option value="">Engineer (optional)</option>
            {engineers.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>

          <input
            type="number"
            min={1}
            value={form.quantity}
            onChange={(e) => setForm({ ...form, quantity: e.target.value })}
            placeholder="Quantity"
          />
        </div>

        <div style={{ marginTop: 16 }}>
          <div className="muted" style={{ marginBottom: 8, fontWeight: 600 }}>
            Optional photo (camera or library)
          </div>
          <input
            id={cameraInputId}
            className="visually-hidden"
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              setPhotoFromFile(file);
              e.target.value = "";
            }}
          />
          <input
            id={libraryInputId}
            className="visually-hidden"
            type="file"
            accept="image/*"
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              setPhotoFromFile(file);
              e.target.value = "";
            }}
          />
          <div className="photo-upload-actions">
            <label htmlFor={cameraInputId}>Take photo</label>
            <label htmlFor={libraryInputId}>Choose from library</label>
            {photoFile && (
              <button type="button" className="photo-upload-clear" onClick={() => setPhotoFromFile(null)}>
                Remove photo
              </button>
            )}
          </div>
          {photoPreview && (
            <div style={{ marginTop: 12 }}>
              <p className="muted" style={{ marginBottom: 6 }}>
                Preview
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={photoPreview}
                alt="Selected part usage"
                style={{ width: "100%", maxWidth: 360, maxHeight: 280, objectFit: "contain", borderRadius: 10, border: "1px solid var(--border)" }}
              />
              {photoFile && (
                <p className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {photoFile.name} · {(photoFile.size / 1024).toFixed(0)} KB
                </p>
              )}
            </div>
          )}
          {submitPhase === "uploading" && (
            <div style={{ marginTop: 12 }} role="status" aria-live="polite">
              <p className="muted" style={{ margin: "0 0 6px" }}>
                Uploading photo… {uploadPct > 0 ? `${uploadPct}%` : ""}
              </p>
              <div className="upload-progress" aria-hidden>
                <div className="upload-progress__bar" style={{ width: `${Math.max(uploadPct, 4)}%` }} />
              </div>
            </div>
          )}
          {submitPhase === "saving" && (
            <p className="muted" style={{ marginTop: 12 }} role="status">
              Saving part usage…
            </p>
          )}
        </div>

        <button type="submit" disabled={busy} style={{ marginTop: 16 }}>
          {busy ? (submitPhase === "uploading" ? "Uploading…" : "Saving…") : "Use Part"}
        </button>
      </form>
      {message && <p className="notice notice-success">{message}</p>}
      {error && <p className="notice notice-error">{error}</p>}
    </section>
  );
}
