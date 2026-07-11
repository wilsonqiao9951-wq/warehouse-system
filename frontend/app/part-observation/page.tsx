"use client";

import { useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { getApiPublicOrigin } from "@/lib/api";

export default function PartObservationPage() {
  const [machine, setMachine] = useState("");
  const [partNumber, setPartNumber] = useState("");
  const [partName, setPartName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [message, setMessage] = useState("");
  const submit = async () => {
    if (!machine || !partNumber || !partName) { setMessage("请填写机型、物料号和物料名称。"); return; }
    const form = new FormData(); form.set("machine_model", machine); form.set("part_number", partNumber); form.set("part_name", partName); if (file) form.set("file", file);
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const response = await fetch(`${process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api"}/parts/recognition/observations`, { method: "POST", body: form, headers: token ? { Authorization: `Bearer ${token}` } : {} });
    const data = await response.json();
    setMessage(response.ok ? `已记忆：${data.machine_model} → ${partNumber}，累计确认 ${data.confirmed_count} 次。${data.photo_url ? `照片：${getApiPublicOrigin()}${data.photo_url}` : ""}` : data.detail || "保存失败");
  };
  return <ManagerShell title="Part photo memory" subtitle="没有二维码时，拍照并告诉系统这是哪个机型的哪个零件。" metrics={[{ label: "Memory", value: "机型关联" }]}><section className="card"><h3>上传物料照片</h3><p className="muted">员工确认一次，系统就会记住该机型与零件的关系，后续优先推荐。</p><input placeholder="机型，例如 ACME-9000" value={machine} onChange={(e) => setMachine(e.target.value)} /><input placeholder="物料号，例如 FILTER-1" value={partNumber} onChange={(e) => setPartNumber(e.target.value)} style={{ marginTop: 8 }} /><input placeholder="物料名称" value={partName} onChange={(e) => setPartName(e.target.value)} style={{ marginTop: 8 }} /><input type="file" accept="image/*" capture="environment" onChange={(e) => setFile(e.target.files?.[0] || null)} style={{ marginTop: 12 }} /><button type="button" onClick={() => void submit()} style={{ marginTop: 12 }}>保存并记忆</button>{message && <p className="success">{message}</p>}</section></ManagerShell>;
}
