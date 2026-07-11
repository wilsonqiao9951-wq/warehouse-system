"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import ManagerShell from "@/components/manager-shell";
import { InventoryScanResult } from "@/types";

export default function InventoryScanPage() {
  const video = useRef<HTMLVideoElement>(null);
  const [barcode, setBarcode] = useState("");
  const [quantity, setQuantity] = useState(1);
  const [result, setResult] = useState<InventoryScanResult | null>(null);
  const [error, setError] = useState("");
  const [scanning, setScanning] = useState(false);

  useEffect(() => () => { if (video.current?.srcObject) (video.current.srcObject as MediaStream).getTracks().forEach((track) => track.stop()); }, []);
  const submit = async (value = barcode) => {
    setError("");
    try { setResult(await api.scanInventory({ barcode: value.trim(), quantity })); }
    catch (err) { setError(err instanceof Error ? err.message : "识别失败"); }
  };
  const startCamera = async () => {
    setError("");
    if (!("BarcodeDetector" in window)) { setError("当前浏览器不支持自动扫码，请输入条码或使用手机浏览器。 "); return; }
    const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
    if (!video.current) return;
    video.current.srcObject = stream; await video.current.play(); setScanning(true);
    const detector = new (window as unknown as { BarcodeDetector: new () => { detect: (el: HTMLVideoElement) => Promise<{ rawValue: string }[]> } }).BarcodeDetector();
    const loop = async () => { if (!video.current) return; const codes = await detector.detect(video.current); if (codes[0]) { setBarcode(codes[0].rawValue); await submit(codes[0].rawValue); setScanning(false); stream.getTracks().forEach((track) => track.stop()); return; } requestAnimationFrame(loop); };
    void loop();
  };
  return <ManagerShell title="Scan inventory" subtitle="拍照或扫描零件标签，自动核对库存。" metrics={[{ label: "Recognition", value: result ? `${Math.round(result.confidence * 100)}%` : "—" }]}>
    <section className="card">
      <h3>扫码 / AI 识别入口</h3>
      <p className="muted">条形码优先匹配；拍照识别接口预留，后续可接入视觉模型识别外观和标签。</p>
      <video ref={video} muted playsInline style={{ width: "100%", maxHeight: 280, display: scanning ? "block" : "none", background: "#111", borderRadius: 8 }} />
      <div style={{ display: "flex", gap: 8, marginTop: 12 }}><input placeholder="扫描或输入条形码" value={barcode} onChange={(e) => setBarcode(e.target.value)} /><input type="number" min={1} value={quantity} onChange={(e) => setQuantity(Number(e.target.value))} style={{ maxWidth: 90 }} /><button type="button" onClick={() => void submit()}>核对库存</button><button type="button" onClick={() => void startCamera()}>打开相机</button></div>
      {error && <p className="danger">{error}</p>}
      {result && <div className={`card ${result.matched ? "" : "danger"}`} style={{ marginTop: 16 }}><strong>{result.feedback}</strong>{result.part && <p>{result.part.part_number} — {result.part.name}<br />当前数量：{result.current_quantity ?? "未指定仓库"}，本次数量：{result.quantity_requested}，预计：{result.projected_quantity ?? "—"}</p>}</div>}
    </section>
  </ManagerShell>;
}
