"use client";

import { useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api, getApiPublicOrigin } from "@/lib/api";
import { getCurrentRole } from "@/lib/role";
import {
  PartRecognitionCandidate,
  PartRecognitionObservation,
  PartRecognitionStatus,
} from "@/types";

const statusLabels: Record<PartRecognitionStatus, string> = {
  ai_candidate: "AI candidate",
  employee_confirmed: "Employee confirmed",
  admin_confirmed: "Admin confirmed",
  usage_verified: "Usage verified",
  trusted: "Trusted knowledge",
  rejected: "Rejected",
};

function imageUrl(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  return `${getApiPublicOrigin()}${path.startsWith("/") ? path : `/${path}`}`;
}

export default function PartObservationPage() {
  const [machineModel, setMachineModel] = useState("");
  const [labelText, setLabelText] = useState("");
  const [workOrderId, setWorkOrderId] = useState("");
  const [notes, setNotes] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [observations, setObservations] = useState<PartRecognitionObservation[]>([]);
  const [rejectionReason, setRejectionReason] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [role, setRole] = useState("engineer");

  useEffect(() => {
    setRole(getCurrentRole());
    api.listPartRecognitionCandidates()
      .then((rows) => {
        setObservations(rows);
        setError("");
      })
      .catch((loadError: Error) => {
        setError(loadError.message || "Unable to load recognition queue.");
      });
  }, []);

  const totals = useMemo(() => {
    const candidates = observations.flatMap((observation) => observation.candidates);
    return {
      review: candidates.filter((candidate) => !["trusted", "rejected"].includes(candidate.status)).length,
      trusted: candidates.filter((candidate) => candidate.status === "trusted").length,
    };
  }, [observations]);

  const submit = async () => {
    if (!file) {
      setError("Take or select a part photo.");
      return;
    }
    const parsedWorkOrderId = workOrderId.trim() ? Number(workOrderId) : undefined;
    if (parsedWorkOrderId !== undefined && (!Number.isInteger(parsedWorkOrderId) || parsedWorkOrderId < 1)) {
      setError("Work-order ID must be a positive number.");
      return;
    }
    if (!machineModel.trim() && !labelText.trim() && !parsedWorkOrderId) {
      setError("Add a machine model, visible label text, or work-order ID.");
      return;
    }
    try {
      setBusy(true);
      setError("");
      setMessage("");
      const created = await api.createPartRecognitionCandidates({
        file,
        machineModel: machineModel.trim() || undefined,
        labelText: labelText.trim() || undefined,
        workOrderId: parsedWorkOrderId,
        notes: notes.trim() || undefined,
      });
      setObservations((previous) => [created, ...previous.filter((row) => row.id !== created.id)]);
      setMessage(
        created.candidates.length
          ? `${created.candidates.length} candidates generated. A person must confirm the correct part.`
          : "Photo saved, but no safe candidate was found. Add clearer label text or machine context.",
      );
      setFile(null);
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "Unable to create candidates.");
    } finally {
      setBusy(false);
    }
  };

  const runAction = async (
    observation: PartRecognitionObservation,
    candidate: PartRecognitionCandidate,
    action: "employee_confirm" | "admin_confirm" | "verify_usage" | "promote_trusted" | "reject",
  ) => {
    if (action === "reject" && rejectionReason.trim().length < 3) {
      setError("Enter a rejection reason with at least 3 characters.");
      return;
    }
    try {
      setBusy(true);
      setError("");
      const updated = await api.actOnPartRecognitionCandidate(
        candidate,
        action,
        observation.work_order_id,
        action === "reject" ? rejectionReason.trim() : undefined,
      );
      setObservations((previous) => previous.map((row) => row.id === updated.id ? updated : row));
      setMessage(`Candidate moved to ${statusLabels[
        updated.candidates.find((row) => row.id === candidate.id)?.status || candidate.status
      ]}.`);
      if (action === "reject") setRejectionReason("");
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Recognition action failed.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ManagerShell
      title="Controlled part recognition"
      subtitle="Photos create candidates only. Inventory and trusted knowledge stay unchanged until the required people and actual work-order usage verify the result."
      metrics={[
        { label: "Needs review", value: totals.review },
        { label: "Trusted", value: totals.trusted },
        { label: "Workflow", value: "5 stages" },
      ]}
    >
      <section className="card">
        <h3 style={{ marginTop: 0 }}>Take a part photo</h3>
        <p className="muted">
          This first vision foundation ranks visible label text, machine knowledge, and completed-job
          history. Image-model and OCR providers can add signals later without bypassing human review.
        </p>
        <div className="two-col">
          <label>
            Machine model
            <input
              placeholder="ACME-9000"
              value={machineModel}
              onChange={(event) => setMachineModel(event.target.value)}
            />
          </label>
          <label>
            Work-order ID (optional)
            <input
              inputMode="numeric"
              placeholder="123"
              value={workOrderId}
              onChange={(event) => setWorkOrderId(event.target.value)}
            />
          </label>
        </div>
        <label style={{ display: "block", marginTop: 10 }}>
          Visible label text
          <input
            placeholder="Part number, barcode, or words visible on the label"
            value={labelText}
            onChange={(event) => setLabelText(event.target.value)}
          />
        </label>
        <label style={{ display: "block", marginTop: 10 }}>
          Field notes
          <textarea
            placeholder="Mounting position, connector color, damage, or other context"
            value={notes}
            onChange={(event) => setNotes(event.target.value)}
          />
        </label>
        <label style={{ display: "block", marginTop: 10 }}>
          Photo
          <input
            type="file"
            accept="image/jpeg,image/png,image/gif,image/webp,image/heic"
            capture="environment"
            onChange={(event) => setFile(event.target.files?.[0] || null)}
          />
        </label>
        <button type="button" onClick={() => void submit()} disabled={busy} style={{ marginTop: 12 }}>
          {busy ? "Working…" : "Generate controlled candidates"}
        </button>
        {message && <p className="notice notice-success">{message}</p>}
        {error && <p className="notice notice-error">{error}</p>}
      </section>

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Recognition review queue</h3>
        <p className="muted">
          AI candidate → employee confirmation → administrator confirmation → work-order usage
          verification → trusted knowledge.
        </p>
        {role === "admin" && (
          <label style={{ display: "block", marginBottom: 12 }}>
            Rejection reason
            <input
              placeholder="Required when rejecting a candidate"
              value={rejectionReason}
              onChange={(event) => setRejectionReason(event.target.value)}
            />
          </label>
        )}
        <div style={{ display: "grid", gap: 12 }}>
          {observations.length === 0 && (
            <div className="empty-state">No visual recognition observations yet.</div>
          )}
          {observations.map((observation) => (
            <article className="job-card" key={observation.id}>
              <div className="two-col" style={{ alignItems: "start" }}>
                <a href={imageUrl(observation.image_url)} target="_blank" rel="noreferrer">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imageUrl(observation.image_url)}
                    alt={`Part recognition observation ${observation.id}`}
                    style={{ width: "100%", maxHeight: 220, objectFit: "cover", borderRadius: 12 }}
                  />
                </a>
                <div>
                  <b>Observation #{observation.id}</b>
                  <p className="muted" style={{ margin: "6px 0" }}>
                    Machine: {observation.machine_model || "not supplied"}
                    {observation.work_order_id ? ` · Work order #${observation.work_order_id}` : ""}
                  </p>
                  {observation.label_text && <p style={{ margin: "6px 0" }}>Label: {observation.label_text}</p>}
                  {observation.notes && <p className="muted">{observation.notes}</p>}
                </div>
              </div>
              <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
                {observation.candidates.length === 0 && (
                  <div className="notice">No safe candidate. Improve the context and submit another photo.</div>
                )}
                {observation.candidates.map((candidate) => (
                  <div className="notice" key={candidate.id}>
                    <div>
                      <b>#{candidate.rank} · {candidate.part.part_number}</b> · {candidate.part.name}
                    </div>
                    <div className="muted">
                      {Math.round(candidate.confidence * 100)}% confidence · {candidate.reason}
                    </div>
                    <div style={{ marginTop: 6 }}>
                      <span className={candidate.status === "rejected" ? "danger" : "app-header-badge"}>
                        {statusLabels[candidate.status]}
                      </span>
                      {candidate.rejection_reason && (
                        <span className="muted"> · {candidate.rejection_reason}</span>
                      )}
                    </div>
                    <div className="one-hand-actions" style={{ marginTop: 8 }}>
                      {candidate.can_employee_confirm && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void runAction(observation, candidate, "employee_confirm")}
                        >
                          This is the part
                        </button>
                      )}
                      {candidate.can_admin_confirm && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void runAction(observation, candidate, "admin_confirm")}
                        >
                          Admin confirm
                        </button>
                      )}
                      {candidate.can_verify_usage && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void runAction(observation, candidate, "verify_usage")}
                        >
                          Verify actual usage
                        </button>
                      )}
                      {candidate.can_promote_trusted && (
                        <button
                          type="button"
                          disabled={busy}
                          onClick={() => void runAction(observation, candidate, "promote_trusted")}
                        >
                          Promote to trusted
                        </button>
                      )}
                      {candidate.can_reject && (
                        <button
                          type="button"
                          className="danger-button"
                          disabled={busy}
                          onClick={() => void runAction(observation, candidate, "reject")}
                        >
                          Reject
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </article>
          ))}
        </div>
      </section>
    </ManagerShell>
  );
}
