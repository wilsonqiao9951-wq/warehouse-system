"use client";

import { FormEvent, useCallback, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, resolveUploadedImageUrl } from "@/lib/api";
import { JobStatus, Part, QCPicture, ReturnEquipment, User, WorkOrder, WorkOrderPart } from "@/types";

export default function WorkOrderDetailsPage() {
  const params = useSearchParams();
  const initialId = params.get("work_order_id") || "";

  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [partsCatalog, setPartsCatalog] = useState<Part[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedWorkOrderId, setSelectedWorkOrderId] = useState(initialId);
  const [jobStatusRows, setJobStatusRows] = useState<JobStatus[]>([]);
  const [qcPictures, setQcPictures] = useState<QCPicture[]>([]);
  const [returnEquipments, setReturnEquipments] = useState<ReturnEquipment[]>([]);
  const [woParts, setWoParts] = useState<WorkOrderPart[]>([]);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const qcCameraInputId = useId();
  const qcLibraryInputId = useId();
  const [statusInput, setStatusInput] = useState("in_progress");
  const [qcForm, setQcForm] = useState({ image_url: "", uploaded_by: "" });
  const [qcPhotoFile, setQcPhotoFile] = useState<File | null>(null);
  const [qcPhotoPreview, setQcPhotoPreview] = useState("");
  const [qcUploadPct, setQcUploadPct] = useState(0);
  const [qcBusy, setQcBusy] = useState(false);
  const [retForm, setRetForm] = useState({ equipment_type: "", quantity: "1" });

  const revokeQcPreview = (url: string) => {
    if (url.startsWith("blob:")) URL.revokeObjectURL(url);
  };

  const setQcPhotoFromFile = (file: File | null) => {
    setQcPhotoFile(file);
    setQcPhotoPreview((prev) => {
      revokeQcPreview(prev);
      return file ? URL.createObjectURL(file) : "";
    });
  };

  useEffect(() => {
    return () => revokeQcPreview(qcPhotoPreview);
  }, [qcPhotoPreview]);

  useEffect(() => {
    Promise.all([api.listWorkOrders(), api.listParts(), api.listUsers().catch(() => [])])
      .then(([wo, parts, us]) => {
        setWorkOrders(wo);
        setPartsCatalog(parts);
        setUsers(us as User[]);
        if (!initialId && wo.length > 0) {
          setSelectedWorkOrderId(String(wo[0].id));
        }
      })
      .catch((e: Error) => setNotice({ type: "error", text: e.message || "Failed to load work orders." }));
  }, [initialId]);

  const currentWorkOrderId = useMemo(() => Number(selectedWorkOrderId || 0), [selectedWorkOrderId]);
  const selectedWorkOrder = useMemo(
    () => workOrders.find((w) => w.id === currentWorkOrderId),
    [workOrders, currentWorkOrderId]
  );
  const locked = Boolean(selectedWorkOrder?.is_locked);

  const partName = (id: number) => partsCatalog.find((p) => p.id === id)?.name || `Part #${id}`;

  const reloadDetails = useCallback(async () => {
    if (!currentWorkOrderId) return;
    try {
      const [statuses, pictures, equipments, allParts] = await Promise.all([
        api.listJobStatus(currentWorkOrderId),
        api.listQCPictures(currentWorkOrderId),
        api.listReturnEquipments(currentWorkOrderId),
        api.listWorkOrderParts({ limit: 100 }).catch(() => [] as WorkOrderPart[])
      ]);
      setJobStatusRows(statuses);
      setQcPictures(pictures);
      setReturnEquipments(equipments);
      setWoParts(allParts.filter((r) => r.work_order_id === currentWorkOrderId));
    } catch (e) {
      const err = e instanceof Error ? e.message : "Failed to load detail records.";
      setNotice({ type: "error", text: err });
    }
  }, [currentWorkOrderId]);

  useEffect(() => {
    void reloadDetails();
  }, [reloadDetails]);

  const onStartJob = async () => {
    if (!currentWorkOrderId) return;
    try {
      await api.startJob(currentWorkOrderId);
      setNotice({ type: "success", text: "Job started." });
      const wo = await api.listWorkOrders();
      setWorkOrders(wo);
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to start job." });
    }
  };

  const onCompleteJob = async () => {
    if (!currentWorkOrderId) return;
    try {
      await api.completeJob(currentWorkOrderId);
      setNotice({ type: "success", text: "Job completed and locked." });
      const wo = await api.listWorkOrders();
      setWorkOrders(wo);
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to complete job." });
    }
  };

  const onCreateJobStatus = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId || !statusInput) return;
    try {
      await api.createJobStatus({ work_order_id: currentWorkOrderId, status: statusInput });
      setNotice({ type: "success", text: "Job status added." });
      void reloadDetails();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to add job status." });
    }
  };

  const onCreateQCPicture = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId) return;
    const manual = qcForm.image_url.trim();
    if (!qcPhotoFile && !manual) {
      setNotice({ type: "error", text: "Take a photo, choose from library, or paste an image URL." });
      return;
    }
    try {
      setQcBusy(true);
      setQcUploadPct(0);
      let imageUrl = manual;
      if (qcPhotoFile) {
        const uploaded = await api.uploadPartUsagePhoto(currentWorkOrderId, qcPhotoFile, (p) => setQcUploadPct(p));
        imageUrl = resolveUploadedImageUrl(uploaded.url);
        setQcUploadPct(100);
      } else if (manual && !manual.startsWith("http://") && !manual.startsWith("https://")) {
        imageUrl = resolveUploadedImageUrl(manual);
      }
      await api.createQCPicture({
        work_order_id: currentWorkOrderId,
        image_url: imageUrl,
        uploaded_by: qcForm.uploaded_by ? Number(qcForm.uploaded_by) : null
      });
      setQcForm({ image_url: "", uploaded_by: qcForm.uploaded_by });
      setQcPhotoFromFile(null);
      setQcUploadPct(0);
      setNotice({ type: "success", text: "QC picture added." });
      void reloadDetails();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to add QC picture." });
    } finally {
      setQcBusy(false);
      setQcUploadPct(0);
    }
  };

  const onCreateReturnEquipment = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId || !retForm.equipment_type.trim()) return;
    try {
      await api.createReturnEquipment({
        work_order_id: currentWorkOrderId,
        equipment_type: retForm.equipment_type.trim(),
        quantity: Number(retForm.quantity) || 1
      });
      setRetForm({ equipment_type: "", quantity: "1" });
      setNotice({ type: "success", text: "Return equipment added." });
      void reloadDetails();
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to add return equipment." });
    }
  };

  const sortedStatuses = useMemo(
    () => [...jobStatusRows].sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp))),
    [jobStatusRows]
  );

  const jobDescription = [selectedWorkOrder?.description, selectedWorkOrder?.problem_description]
    .filter(Boolean)
    .join("\n\n");

  return (
    <div className="detail-stack">
      <div className="card">
        <h3 className="section-title">Work order</h3>
        <select value={selectedWorkOrderId} onChange={(e) => setSelectedWorkOrderId(e.target.value)} aria-label="Select work order">
          {workOrders.map((wo) => (
            <option key={wo.id} value={wo.id}>
              {wo.wo_number || wo.ticket_number} ({wo.status})
            </option>
          ))}
        </select>
        {notice && (
          <p className={`notice ${notice.type === "success" ? "notice-success" : "notice-error"}`}>{notice.text}</p>
        )}
      </div>

      {selectedWorkOrder && (
        <>
          <div className={`card job-card${locked ? " job-card--locked" : ""}`}>
            <h3 className="section-title">Job summary</h3>
            <p style={{ margin: "4px 0" }}>
              <strong>{selectedWorkOrder.wo_number || selectedWorkOrder.ticket_number}</strong>
              <span className="muted"> · {selectedWorkOrder.status}</span>
            </p>
            <p className="muted" style={{ margin: "4px 0" }}>
              {selectedWorkOrder.outlet_name || selectedWorkOrder.store_name || "Outlet"} ·{" "}
              {selectedWorkOrder.job_type || "—"}
            </p>
            <p className="muted" style={{ margin: "4px 0" }}>
              Revenue ${Number(selectedWorkOrder.revenue).toFixed(2)}
            </p>
            {locked && <span className="job-card__lock">Completed — locked (no edits)</span>}
            <div className="sticky-actions">
              <button type="button" onClick={onStartJob} disabled={locked}>
                Start job
              </button>
              <button type="button" onClick={onCompleteJob} disabled={locked}>
                Complete job
              </button>
            </div>
          </div>

          <div className="card">
            <h3 className="section-title">Address</h3>
            <p style={{ marginTop: 0 }}>
              {[selectedWorkOrder.address, selectedWorkOrder.city, selectedWorkOrder.state, selectedWorkOrder.zip]
                .filter(Boolean)
                .join(", ") || "—"}
            </p>
            {selectedWorkOrder.address && (
              <a
                className="nav-item"
                style={{ marginTop: 8, width: "100%" }}
                href={`https://maps.google.com/?q=${encodeURIComponent(selectedWorkOrder.address)}`}
                target="_blank"
                rel="noreferrer"
              >
                Navigate
              </a>
            )}
          </div>

          <div className="card">
            <h3 className="section-title">Contact</h3>
            <p style={{ marginTop: 0 }}>{selectedWorkOrder.contact_phone || "—"}</p>
            {selectedWorkOrder.contact_phone && (
              <a className="nav-item" style={{ marginTop: 8, display: "block" }} href={`tel:${selectedWorkOrder.contact_phone}`}>
                Call
              </a>
            )}
          </div>

          <div className="card">
            <h3 className="section-title">Job description</h3>
            <p style={{ marginTop: 0, whiteSpace: "pre-wrap" }}>{jobDescription || "—"}</p>
          </div>
        </>
      )}

      <div className="card">
        <h3 className="section-title">Status timeline</h3>
        <form onSubmit={onCreateJobStatus} style={{ marginBottom: 12 }}>
          <div className="two-col" style={{ alignItems: "stretch" }}>
            <select value={statusInput} onChange={(e) => setStatusInput(e.target.value)} disabled={locked}>
              <option value="open">open</option>
              <option value="in_progress">in_progress</option>
              <option value="completed">completed</option>
            </select>
            <button type="submit" disabled={locked}>
              Add status
            </button>
          </div>
        </form>
        {sortedStatuses.length === 0 ? (
          <div className="empty-state">No status history yet.</div>
        ) : (
          sortedStatuses.map((row) => (
            <div key={row.id} className="timeline-item">
              <strong>{row.status}</strong>
              <div className="muted" style={{ fontSize: 13 }}>
                {row.timestamp || "—"}
              </div>
            </div>
          ))
        )}
      </div>

      <div className="card">
        <h3 className="section-title">Parts used</h3>
        {woParts.length === 0 ? (
          <div className="empty-state">No parts recorded on this job.</div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {woParts.map((row) => (
              <div key={row.id} className="job-card" style={{ margin: 0 }}>
                <div>
                  <strong>{partName(row.part_id)}</strong>
                </div>
                <div className="muted">
                  Qty {row.quantity} · ${Number(row.total_cost).toFixed(2)}
                </div>
                {row.notes && (
                  <div style={{ fontSize: 13, marginTop: 6 }}>
                    <span className="muted">Notes: </span>
                    {row.notes}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="muted" style={{ marginBottom: 0, fontSize: 13 }}>
          To add usage, use{" "}
          <Link href="/parts-usage" className="nav-item" style={{ display: "inline-flex", width: "auto", padding: "4px 10px" }}>
            Parts Usage
          </Link>{" "}
          (warehouse / admin) or the field workflow your pilot defines.
        </p>
      </div>

      <div className="card">
        <h3 className="section-title">QC pictures</h3>
        <p className="muted" style={{ fontSize: 14, marginTop: 0 }}>
          Use camera or library (uploads to server), or paste a direct image URL.
        </p>
        <form onSubmit={onCreateQCPicture}>
          <input
            id={qcCameraInputId}
            className="visually-hidden"
            type="file"
            accept="image/*"
            capture="environment"
            disabled={locked || qcBusy}
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              setQcPhotoFromFile(file);
              e.target.value = "";
            }}
          />
          <input
            id={qcLibraryInputId}
            className="visually-hidden"
            type="file"
            accept="image/*"
            disabled={locked || qcBusy}
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              setQcPhotoFromFile(file);
              e.target.value = "";
            }}
          />
          <div className="photo-upload-actions" style={{ marginBottom: 12 }}>
            <label htmlFor={qcCameraInputId} style={{ opacity: locked || qcBusy ? 0.5 : 1, pointerEvents: locked || qcBusy ? "none" : "auto" }}>
              Take QC photo
            </label>
            <label htmlFor={qcLibraryInputId} style={{ opacity: locked || qcBusy ? 0.5 : 1, pointerEvents: locked || qcBusy ? "none" : "auto" }}>
              Choose from library
            </label>
            {qcPhotoFile && (
              <button type="button" className="photo-upload-clear" disabled={locked || qcBusy} onClick={() => setQcPhotoFromFile(null)}>
                Remove photo
              </button>
            )}
          </div>
          {qcPhotoPreview && (
            <div style={{ marginBottom: 12 }}>
              <p className="muted" style={{ marginBottom: 6 }}>
                Preview
              </p>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={qcPhotoPreview}
                alt="QC preview"
                style={{ width: "100%", maxWidth: 360, maxHeight: 220, objectFit: "contain", borderRadius: 10, border: "1px solid var(--border)" }}
              />
            </div>
          )}
          {qcBusy && qcPhotoFile && (
            <div style={{ marginBottom: 12 }} role="status" aria-live="polite">
              <p className="muted" style={{ margin: "0 0 6px" }}>
                Uploading… {qcUploadPct > 0 ? `${qcUploadPct}%` : ""}
              </p>
              <div className="upload-progress" aria-hidden>
                <div className="upload-progress__bar" style={{ width: `${Math.max(qcUploadPct, 4)}%` }} />
              </div>
            </div>
          )}
          <input
            placeholder="Or paste image URL"
            value={qcForm.image_url}
            onChange={(e) => setQcForm((prev) => ({ ...prev, image_url: e.target.value }))}
            style={{ marginBottom: 8 }}
            disabled={locked || qcBusy}
          />
          <select
            value={qcForm.uploaded_by}
            onChange={(e) => setQcForm((prev) => ({ ...prev, uploaded_by: e.target.value }))}
            disabled={locked || qcBusy}
          >
            <option value="">Uploaded by (optional)</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name}
              </option>
            ))}
          </select>
          <button type="submit" style={{ marginTop: 8 }} disabled={locked || qcBusy}>
            {qcBusy ? "Working…" : "Add QC picture"}
          </button>
        </form>
        {qcPictures.length === 0 ? (
          <div className="empty-state" style={{ marginTop: 12 }}>
            No QC photos yet.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 12 }}>
            {qcPictures.map((row) => (
              <div key={row.id} className="job-card" style={{ margin: 0 }}>
                <a href={resolveUploadedImageUrl(row.image_url)} target="_blank" rel="noreferrer">
                  {/* External QC URLs — use native img for static export */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={resolveUploadedImageUrl(row.image_url)}
                    alt="QC"
                    style={{ width: "100%", maxHeight: 200, objectFit: "cover", borderRadius: 8 }}
                  />
                </a>
                <div className="muted" style={{ fontSize: 13, marginTop: 6 }}>
                  {users.find((u) => u.id === row.uploaded_by)?.name || "—"}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="section-title">Returned equipment</h3>
        <form onSubmit={onCreateReturnEquipment}>
          <input
            placeholder="Equipment type"
            value={retForm.equipment_type}
            onChange={(e) => setRetForm((prev) => ({ ...prev, equipment_type: e.target.value }))}
            style={{ marginBottom: 8 }}
            disabled={locked}
          />
          <input
            type="number"
            min={1}
            value={retForm.quantity}
            onChange={(e) => setRetForm((prev) => ({ ...prev, quantity: e.target.value }))}
            style={{ marginBottom: 8 }}
            disabled={locked}
          />
          <button type="submit" disabled={locked}>
            Add return line
          </button>
        </form>
        {returnEquipments.length === 0 ? (
          <div className="empty-state" style={{ marginTop: 12 }}>
            No returns logged.
          </div>
        ) : (
          <ul style={{ paddingLeft: 18, marginBottom: 0 }}>
            {returnEquipments.map((row) => (
              <li key={row.id} style={{ marginBottom: 6 }}>
                <strong>{row.equipment_type}</strong> × {row.quantity}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
