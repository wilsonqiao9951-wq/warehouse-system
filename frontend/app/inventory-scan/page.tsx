"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import ManagerShell from "@/components/manager-shell";
import { InventoryLocationLabel, InventoryLocationScan, InventoryScanResult } from "@/types";

export default function InventoryScanPage() {
  const video = useRef<HTMLVideoElement>(null);
  const [scanValue, setScanValue] = useState("");
  const [warehouse, setWarehouse] = useState<InventoryLocationScan | null>(null);
  const [location, setLocation] = useState<InventoryLocationScan | null>(null);
  const [partResult, setPartResult] = useState<InventoryScanResult | null>(null);
  const [labels, setLabels] = useState<InventoryLocationLabel[]>([]);
  const [quantity, setQuantity] = useState(1);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);

  useEffect(() => () => {
    if (video.current?.srcObject) (video.current.srcObject as MediaStream).getTracks().forEach((track) => track.stop());
  }, []);

  const stage = !warehouse ? "warehouse" : !location ? "location" : "part";
  const stageLabel = stage === "warehouse" ? "warehouse label" : stage === "location" ? "shelf / bin label" : "part barcode";

  async function submit(value = scanValue) {
    const normalized = value.trim();
    if (!normalized) return;
    setError("");
    try {
      if (stage === "warehouse") {
        const result = await api.scanInventoryLocation({ label: normalized });
        if (result.scan_type !== "warehouse") throw new Error("Scan the warehouse label before scanning a location.");
        setWarehouse(result);
        setLabels(await api.listInventoryLocationLabels(result.warehouse_id));
      } else if (stage === "location") {
        if (!warehouse) throw new Error("Scan the warehouse label first.");
        const result = await api.scanInventoryLocation({ label: normalized, expected_warehouse_id: warehouse.warehouse_id });
        if (result.scan_type !== "location") throw new Error("A shelf or bin label is required at this step.");
        setLocation(result);
      } else {
        if (!warehouse || !location?.location_id) throw new Error("Scan warehouse and location labels first.");
        setPartResult(await api.scanInventory({
          barcode: normalized, quantity, warehouse_id: warehouse.warehouse_id,
          location_id: location.location_id
        }));
      }
      setScanValue("");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Scan could not be validated");
    }
  }

  async function startCamera() {
    setError("");
    if (!("BarcodeDetector" in window)) {
      setError("This browser does not support automatic barcode detection. Enter the label value manually.");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      if (!video.current) return;
      video.current.srcObject = stream;
      await video.current.play();
      setScanning(true);
      const detector = new (window as unknown as {
        BarcodeDetector: new () => { detect: (element: HTMLVideoElement) => Promise<{ rawValue: string }[]> }
      }).BarcodeDetector();
      const loop = async () => {
        if (!video.current || !stream.active) return;
        const codes = await detector.detect(video.current);
        if (codes[0]) {
          setScanning(false);
          stream.getTracks().forEach((track) => track.stop());
          await submit(codes[0].rawValue);
          return;
        }
        requestAnimationFrame(loop);
      };
      void loop();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Camera could not be opened");
    }
  }

  function reset() {
    setWarehouse(null); setLocation(null); setPartResult(null); setLabels([]); setScanValue(""); setError("");
  }

  return <ManagerShell title="Warehouse location scan" subtitle="Validate warehouse, shelf, and part labels in order before trusting a stock quantity."
    metrics={[{ label: "Current step", value: stage === "warehouse" ? "1 / 3" : stage === "location" ? "2 / 3" : "3 / 3" }]}>
    <section className="card">
      <div className="section-heading-row"><div><h3 style={{ margin: 0 }}>Scan {stageLabel}</h3><p className="muted" style={{ margin: "4px 0 0" }}>Required order: warehouse → shelf/bin → part.</p></div>
        {(warehouse || location) && <button type="button" className="secondary-button" onClick={reset}>Start over</button>}</div>
      <video ref={video} muted playsInline style={{ width: "100%", maxHeight: 280, display: scanning ? "block" : "none", background: "#111", borderRadius: 8, marginTop: 12 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
        <input aria-label={`Scan ${stageLabel}`} placeholder={`Scan or enter ${stageLabel}`} value={scanValue} onChange={(event) => setScanValue(event.target.value)} />
        {stage === "part" && <input aria-label="Quantity to check" type="number" min={1} value={quantity} onChange={(event) => setQuantity(Math.max(1, Number(event.target.value)))} style={{ maxWidth: 110 }} />}
        <button type="button" disabled={!scanValue.trim()} onClick={() => void submit()}>Validate</button>
        <button type="button" className="secondary-button" onClick={() => void startCamera()}>Open camera</button>
      </div>
      {error && <div className="notice notice-error" style={{ marginTop: 12 }}>{error}</div>}
    </section>

    <section className="card">
      <h3>Verified scan context</h3>
      <div className="custody-route">
        <div><span className="muted">Warehouse</span><strong>{warehouse ? `${warehouse.warehouse_code} — ${warehouse.warehouse_name}` : "Not scanned"}</strong></div>
        <span aria-hidden="true">→</span>
        <div><span className="muted">Shelf / bin</span><strong>{location ? `${location.location_code} — ${location.location_name || "Location"}` : "Not scanned"}</strong></div>
        <span aria-hidden="true">→</span>
        <div><span className="muted">Part</span><strong>{partResult?.part ? `${partResult.part.part_number} — ${partResult.part.name}` : "Not scanned"}</strong></div>
      </div>
      {partResult && <div className={`notice ${partResult.matched ? "" : "notice-error"}`} style={{ marginTop: 12 }}>
        <strong>{partResult.feedback}</strong>
        {partResult.part && <div>Location quantity: {partResult.current_quantity ?? "—"} · Check quantity: {partResult.quantity_requested} · Remaining: {partResult.projected_quantity ?? "—"}</div>}
      </div>}
    </section>

    {warehouse && <section className="card">
      <h3>Registered labels for {warehouse.warehouse_name}</h3>
      <p className="muted">Use these exact values when generating or replacing QR/barcode labels. Stale labels are rejected.</p>
      <div className="table-wrap"><table><thead><tr><th>Type</th><th>Code</th><th>Label token</th></tr></thead><tbody>
        {labels.map((label) => <tr key={label.label_token}><td>{label.location_id ? "Location" : "Warehouse"}</td><td>{label.location_code || label.warehouse_code}</td><td><code>{label.label_token}</code></td></tr>)}
      </tbody></table></div>
    </section>}
  </ManagerShell>;
}
