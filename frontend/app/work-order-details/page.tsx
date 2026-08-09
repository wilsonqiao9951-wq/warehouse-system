"use client";

import { FormEvent, useCallback, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { api, resolveUploadedImageUrl } from "@/lib/api";
import { isOfflineMediaMarker } from "@/lib/offline-media";
import { CompletionPolicy, JobStatus, Part, QCPicture, ReturnEquipment, User, WorkOrder, WorkOrderForm, WorkOrderFormAction, WorkOrderFormValue, WorkOrderMedia, WorkOrderMediaCategory, WorkOrderPart, WorkOrderServiceContext, WorkOrderServiceIntelligence, WorkOrderVoiceNote } from "@/types";
import { SignaturePad } from "@/components/signature-pad";
import { VoiceRecorder } from "@/components/voice-recorder";

export default function WorkOrderDetailsPage() {
  const params = useSearchParams();
  const initialId = params.get("work_order_id") || "";

  const [workOrders, setWorkOrders] = useState<WorkOrder[]>([]);
  const [partsCatalog, setPartsCatalog] = useState<Part[]>([]);
  const [users, setUsers] = useState<User[]>([]);
  const [selectedWorkOrderId, setSelectedWorkOrderId] = useState(initialId);
  const [jobStatusRows, setJobStatusRows] = useState<JobStatus[]>([]);
  const [qcPictures, setQcPictures] = useState<QCPicture[]>([]);
  const [workOrderMedia, setWorkOrderMedia] = useState<WorkOrderMedia[]>([]);
  const [returnEquipments, setReturnEquipments] = useState<ReturnEquipment[]>([]);
  const [woParts, setWoParts] = useState<WorkOrderPart[]>([]);
  const [voiceNotes, setVoiceNotes] = useState<WorkOrderVoiceNote[]>([]);
  const [serviceContext, setServiceContext] = useState<WorkOrderServiceContext | null>(null);
  const [serviceIntelligence, setServiceIntelligence] = useState<WorkOrderServiceIntelligence | null>(null);
  const [serviceIntelligenceLoaded, setServiceIntelligenceLoaded] = useState(false);
  const [completionPolicy, setCompletionPolicy] = useState<CompletionPolicy | null>(null);
  const [dynamicForm, setDynamicForm] = useState<WorkOrderForm | null>(null);
  const [formActions, setFormActions] = useState<WorkOrderFormAction[]>([]);
  const [dynamicFormValues, setDynamicFormValues] = useState<Record<string, WorkOrderFormValue>>({});
  const [dynamicFormSaving, setDynamicFormSaving] = useState(false);
  const [dynamicPhotoBusy, setDynamicPhotoBusy] = useState("");
  const [role, setRole] = useState("");
  const [completionPassword, setCompletionPassword] = useState("");
  const [claimBusy, setClaimBusy] = useState(false);
  const [releaseReason, setReleaseReason] = useState("");
  const [releaseBusy, setReleaseBusy] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);

  const qcCameraInputId = useId();
  const qcLibraryInputId = useId();
  const fieldMediaCameraInputId = useId();
  const fieldMediaLibraryInputId = useId();
  const [statusInput, setStatusInput] = useState("in_progress");
  const [qcForm, setQcForm] = useState({ image_url: "" });
  const [qcPhotoFile, setQcPhotoFile] = useState<File | null>(null);
  const [qcPhotoPreview, setQcPhotoPreview] = useState("");
  const [qcUploadPct, setQcUploadPct] = useState(0);
  const [qcBusy, setQcBusy] = useState(false);
  const [fieldMediaFile, setFieldMediaFile] = useState<File | null>(null);
  const [fieldMediaPreview, setFieldMediaPreview] = useState("");
  const [fieldMediaBusy, setFieldMediaBusy] = useState(false);
  const [fieldMediaForm, setFieldMediaForm] = useState<{
    category: WorkOrderMediaCategory;
    caption: string;
  }>({ category: "before", caption: "" });
  const [retForm, setRetForm] = useState({ equipment_type: "", quantity: "1" });
  const [completion, setCompletion] = useState({
    repairResult: "",
    faultType: "",
    errorCode: "",
    environmentInfo: "",
    finalOutcome: "repaired",
    firstTimeFix: false,
    isRework: false,
    signatureName: "",
    signatureData: "",
    equipmentSafe: false,
    siteClean: false,
    customerBriefed: false
  });

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

  const setFieldMediaFromFile = (file: File | null) => {
    setFieldMediaFile(file);
    setFieldMediaPreview((prev) => {
      revokeQcPreview(prev);
      return file ? URL.createObjectURL(file) : "";
    });
  };

  useEffect(() => {
    return () => revokeQcPreview(qcPhotoPreview);
  }, [qcPhotoPreview]);

  useEffect(() => {
    return () => revokeQcPreview(fieldMediaPreview);
  }, [fieldMediaPreview]);

  useEffect(() => {
    setRole(window.localStorage.getItem("opf_role") || "");
    Promise.all([api.listWorkOrders({ scope: "all" }), api.listParts(), api.listUsers().catch(() => [])])
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
  const pendingApproval = selectedWorkOrder?.status === "PENDING_APPROVAL";
  const canEdit = Boolean(selectedWorkOrder?.can_edit);
  const canComplete = Boolean(selectedWorkOrder?.can_complete);
  const evidenceFrozen = locked || pendingApproval || !canEdit;
  const canReleaseClaim = Boolean(
    selectedWorkOrder?.claimed_by_id
    && ["admin", "manager"].includes(role)
    && !locked
    && !pendingApproval
  );

  useEffect(() => {
    if (!selectedWorkOrder) return;
    let checklist: Record<string, boolean> = {};
    try {
      checklist = selectedWorkOrder.checklist_json ? JSON.parse(selectedWorkOrder.checklist_json) : {};
    } catch {
      checklist = {};
    }
    setCompletion({
      repairResult: selectedWorkOrder.repair_result || "",
      faultType: selectedWorkOrder.fault_type || selectedWorkOrder.job_type || "",
      errorCode: selectedWorkOrder.error_code || "",
      environmentInfo: selectedWorkOrder.environment_info || "",
      finalOutcome: selectedWorkOrder.final_outcome || "repaired",
      firstTimeFix: selectedWorkOrder.first_time_fix ?? false,
      isRework: selectedWorkOrder.is_rework || false,
      signatureName: selectedWorkOrder.customer_signature_name || "",
      signatureData: selectedWorkOrder.customer_signature_data || "",
      equipmentSafe: Boolean(checklist.equipment_safe),
      siteClean: Boolean(checklist.site_clean),
      customerBriefed: Boolean(checklist.customer_briefed)
    });
    setCompletionPassword("");
    setReleaseReason("");
  }, [selectedWorkOrder]);

  const partName = (id: number) => partsCatalog.find((p) => p.id === id)?.name || `Part #${id}`;

  const reloadDetails = useCallback(async () => {
    if (!currentWorkOrderId) return;
    try {
      const [statuses, pictures, media, equipments, allParts, notes] = await Promise.all([
        api.listJobStatus(currentWorkOrderId),
        api.listQCPictures(currentWorkOrderId),
        api.listWorkOrderMedia(currentWorkOrderId).catch(() => [] as WorkOrderMedia[]),
        api.listReturnEquipments(currentWorkOrderId),
        api.listWorkOrderParts({ limit: 100, work_order_id: currentWorkOrderId }).catch(() => [] as WorkOrderPart[]),
        api.listVoiceNotes(currentWorkOrderId)
      ]);
      setJobStatusRows(statuses);
      setQcPictures(pictures);
      setWorkOrderMedia(media);
      setReturnEquipments(equipments);
      setWoParts(allParts);
      setVoiceNotes(notes);
    } catch (e) {
      const err = e instanceof Error ? e.message : "Failed to load detail records.";
      setNotice({ type: "error", text: err });
    }
  }, [currentWorkOrderId]);

  useEffect(() => {
    void reloadDetails();
  }, [reloadDetails]);

  useEffect(() => {
    if (!currentWorkOrderId) return;
    let active = true;
    setServiceContext(null);
    setServiceIntelligence(null);
    setServiceIntelligenceLoaded(false);
    setDynamicForm(null);
    setDynamicFormValues({});
    setFormActions([]);
    api.getWorkOrderServiceContext(currentWorkOrderId, 5)
      .then(setServiceContext)
      .catch(() => setServiceContext({ history: [] }));
    api.getWorkOrderServiceIntelligence(currentWorkOrderId)
      .then((result) => {
        if (active) setServiceIntelligence(result);
      })
      .catch(() => {
        if (active) setServiceIntelligence(null);
      })
      .finally(() => {
        if (active) setServiceIntelligenceLoaded(true);
      });
    api.getCompletionPolicy(currentWorkOrderId)
      .then(setCompletionPolicy)
      .catch(() => setCompletionPolicy(null));
    api.getWorkOrderForm(currentWorkOrderId)
      .then((result) => {
        if (active) {
          setDynamicForm(result);
          setDynamicFormValues(result.values);
        }
      })
      .catch(() => {
        if (active) {
          setDynamicForm(null);
          setDynamicFormValues({});
        }
      });
    api.listWorkOrderFormActionProgress(currentWorkOrderId)
      .then((result) => {
        if (active) setFormActions(result);
      })
      .catch(() => {
        if (active) setFormActions([]);
      });
    return () => {
      active = false;
    };
  }, [currentWorkOrderId]);

  const onStartJob = async () => {
    if (!currentWorkOrderId || !canEdit) return;
    try {
      await api.startJob(currentWorkOrderId);
      setNotice({ type: "success", text: "Job started." });
      const wo = await api.listWorkOrders({ scope: "all" });
      setWorkOrders(wo);
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to start job." });
    }
  };

  const onClaimJob = async () => {
    if (!currentWorkOrderId || !selectedWorkOrder?.can_claim) return;
    try {
      setClaimBusy(true);
      await api.claimWorkOrder(currentWorkOrderId);
      setWorkOrders(await api.listWorkOrders({ scope: "all" }));
      setNotice({ type: "success", text: "Job claimed and bound to this account and device." });
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to claim job." });
    } finally {
      setClaimBusy(false);
    }
  };

  const onReleaseClaim = async () => {
    if (!currentWorkOrderId || !canReleaseClaim) return;
    if (releaseReason.trim().length < 3) {
      setNotice({ type: "error", text: "Enter a release reason of at least 3 characters." });
      return;
    }
    try {
      setReleaseBusy(true);
      await api.releaseWorkOrder(currentWorkOrderId, releaseReason.trim());
      setWorkOrders(await api.listWorkOrders({ scope: "all" }));
      setReleaseReason("");
      setNotice({ type: "success", text: "Claim released. The job is available to engineers again." });
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to release claim." });
    } finally {
      setReleaseBusy(false);
    }
  };

  const onCompleteJob = async () => {
    if (!currentWorkOrderId || !canComplete) return;
    const missing: string[] = [];
    if (completionPolicy?.require_repair_result && !completion.repairResult.trim()) missing.push("repair result");
    if (completionPolicy?.require_customer_signature && (!completion.signatureName.trim() || !completion.signatureData)) missing.push("customer signature");
    if (
      completionPolicy?.require_completion_photo
      && qcPictures.length === 0
      && !workOrderMedia.some((item) => item.media_type === "photo")
    ) missing.push("field photo");
    if (completionPolicy?.require_parts_usage && woParts.length === 0) missing.push("part usage");
    if (completionPolicy?.require_all_checklist_items && !(completion.equipmentSafe && completion.siteClean && completion.customerBriefed)) missing.push("field checklist");
    if (dynamicForm?.missing_required_fields.length) {
      missing.push(...dynamicForm.missing_required_fields.map((key) => {
        const field = dynamicForm.fields.find((item) => item.field_key === key);
        return field?.label || key;
      }));
    }
    if (missing.length) {
      setNotice({ type: "error", text: `Complete the required evidence: ${missing.join(", ")}.` });
      return;
    }
    if (!completionPassword) {
      setNotice({ type: "error", text: "Enter your account password to verify who is completing this job." });
      return;
    }
    const accountPassword = completionPassword;
    setCompletionPassword("");
    try {
      const result = await api.completeJob(currentWorkOrderId, {
        repair_result: completion.repairResult.trim(),
        fault_type: completion.faultType.trim(),
        error_code: completion.errorCode.trim(),
        environment_info: completion.environmentInfo.trim(),
        final_outcome: completion.finalOutcome,
        first_time_fix: completion.firstTimeFix,
        is_rework: completion.isRework,
        customer_signature_name: completion.signatureName.trim(),
        customer_signature_data: completion.signatureData,
        checklist_json: JSON.stringify({
          equipment_safe: completion.equipmentSafe,
          site_clean: completion.siteClean,
          customer_briefed: completion.customerBriefed
        }),
        account_password: accountPassword
      });
      setNotice({ type: "success", text: result.status === "PENDING_APPROVAL" ? "Completion submitted for manager approval." : "Job completed and locked." });
      const wo = await api.listWorkOrders({ scope: "all" });
      setWorkOrders(wo);
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to complete job." });
    }
  };

  const onSaveDynamicForm = async () => {
    if (!currentWorkOrderId || !dynamicForm?.can_edit) return;
    try {
      setDynamicFormSaving(true);
      const result = await api.updateWorkOrderForm(
        currentWorkOrderId,
        dynamicForm.form_version,
        dynamicFormValues
      );
      if ("queued" in result) {
        const missingRequiredFields = dynamicForm.fields
          .filter((field) => (
            field.required_at_completion
            || field.requires_photo
            || field.requires_signature
          ))
          .filter((field) => {
            const value = dynamicFormValues[field.field_key];
            return value === null
              || value === undefined
              || (typeof value === "string" && !value.trim());
          })
          .map((field) => field.field_key);
        setDynamicForm({
          ...dynamicForm,
          values: dynamicFormValues,
          missing_required_fields: missingRequiredFields
        });
        setNotice({
          type: "success",
          text: "Offline form changes are saved on this account and device. They will sync only while this claim remains current."
        });
        return;
      }
      setDynamicForm(result);
      setDynamicFormValues(result.values);
      setFormActions(await api.listWorkOrderFormActionProgress(currentWorkOrderId));
      setNotice({ type: "success", text: "Configured job form saved with verified ownership." });
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to save configured job form."
      });
    } finally {
      setDynamicFormSaving(false);
    }
  };

  const onUploadDynamicPhoto = async (fieldKey: string, file: File | null) => {
    if (!file || !currentWorkOrderId || !dynamicForm?.can_edit) return;
    try {
      setDynamicPhotoBusy(fieldKey);
      const uploaded = await api.uploadPartUsagePhoto(
        currentWorkOrderId,
        file,
        () => undefined,
        "configured_form_photo"
      );
      setDynamicFormValues((current) => ({
        ...current,
        [fieldKey]: uploaded.url
      }));
      setNotice({
        type: "success",
        text: uploaded.queued_offline
          ? "Photo retained on this account and device. Save the configured form to add it to the sync queue."
          : "Photo uploaded. Save the configured form to record it."
      });
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to upload configured-form photo."
      });
    } finally {
      setDynamicPhotoBusy("");
    }
  };

  const onApproveCompletion = async () => {
    if (!currentWorkOrderId) return;
    try {
      await api.approveCompletion(currentWorkOrderId);
      setNotice({ type: "success", text: "Completion approved and work order locked." });
      setWorkOrders(await api.listWorkOrders({ scope: "all" }));
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Approval failed." });
    }
  };

  const onRejectCompletion = async () => {
    if (!currentWorkOrderId) return;
    try {
      await api.rejectCompletion(currentWorkOrderId, "Completion evidence requires correction");
      setNotice({ type: "success", text: "Completion rejected for correction." });
      setWorkOrders(await api.listWorkOrders({ scope: "all" }));
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Rejection failed." });
    }
  };

  const onPauseJob = async () => {
    if (!currentWorkOrderId || !canEdit) return;
    try {
      await api.pauseJob(currentWorkOrderId);
      setNotice({ type: "success", text: "Job paused." });
      setWorkOrders(await api.listWorkOrders({ scope: "all" }));
      void reloadDetails();
    } catch (e) {
      setNotice({ type: "error", text: e instanceof Error ? e.message : "Failed to pause job." });
    }
  };

  const onCreateJobStatus = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId || !statusInput || !canEdit) return;
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
    if (!currentWorkOrderId || !canEdit) return;
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
        const uploaded = await api.uploadPartUsagePhoto(
          currentWorkOrderId,
          qcPhotoFile,
          (p) => setQcUploadPct(p),
          "qc_photo"
        );
        imageUrl = uploaded.url;
        if (!uploaded.queued_offline) setQcUploadPct(100);
      } else if (manual && !manual.startsWith("http://") && !manual.startsWith("https://")) {
        imageUrl = resolveUploadedImageUrl(manual);
      }
      const created = await api.createQCPicture({
        work_order_id: currentWorkOrderId,
        image_url: imageUrl
      });
      setQcForm({ image_url: "" });
      setQcPhotoFromFile(null);
      setQcUploadPct(0);
      if ("queued" in created) {
        setNotice({ type: "success", text: "QC photo retained on this account and device for verified sync." });
      } else {
        setNotice({ type: "success", text: "QC picture added." });
        void reloadDetails();
      }
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to add QC picture." });
    } finally {
      setQcBusy(false);
      setQcUploadPct(0);
    }
  };

  const onCreateFieldMedia = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId || !canEdit) return;
    if (!fieldMediaFile) {
      setNotice({ type: "error", text: "Take a photo or choose a photo/video first." });
      return;
    }
    try {
      setFieldMediaBusy(true);
      await api.createWorkOrderMedia(currentWorkOrderId, {
        file: fieldMediaFile,
        category: fieldMediaForm.category,
        caption: fieldMediaForm.caption,
        clientRequestId: `field-media-${crypto.randomUUID()}`
      });
      setFieldMediaFromFile(null);
      setFieldMediaForm({ category: "before", caption: "" });
      setNotice({ type: "success", text: "Private field media evidence added." });
      void reloadDetails();
    } catch (err) {
      setNotice({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to add field media."
      });
    } finally {
      setFieldMediaBusy(false);
    }
  };

  const onOpenFieldMedia = async (media: WorkOrderMedia) => {
    try {
      await api.openWorkOrderMedia(media);
    } catch (err) {
      setNotice({
        type: "error",
        text: err instanceof Error ? err.message : "Failed to open field media."
      });
    }
  };

  const onCreateReturnEquipment = async (e: FormEvent) => {
    e.preventDefault();
    if (!currentWorkOrderId || !retForm.equipment_type.trim() || !canEdit) return;
    try {
      const created = await api.createReturnEquipment({
        work_order_id: currentWorkOrderId,
        equipment_type: retForm.equipment_type.trim(),
        quantity: Number(retForm.quantity) || 1
      });
      setRetForm({ equipment_type: "", quantity: "1" });
      if ("queued" in created) {
        setNotice({ type: "success", text: "Return-equipment evidence retained for verified sync." });
      } else {
        setNotice({ type: "success", text: "Return equipment added." });
        void reloadDetails();
      }
    } catch (err) {
      setNotice({ type: "error", text: err instanceof Error ? err.message : "Failed to add return equipment." });
    }
  };

  const sortedStatuses = useMemo(
    () => [...jobStatusRows].sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp))),
    [jobStatusRows]
  );

  const fieldMediaPreviewIsVideo = Boolean(
    fieldMediaFile
    && (
      fieldMediaFile.type.startsWith("video/")
      || /\.(mp4|mov|webm)$/i.test(fieldMediaFile.name)
    )
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
            {locked && <span className="job-card__lock">Completed — locked (no edits)</span>}
            <div className={canEdit ? "notice notice-success" : "notice"} style={{ marginTop: 10 }}>
              {selectedWorkOrder.completed_by_name
                ? `Completed by ${selectedWorkOrder.completed_by_name}${selectedWorkOrder.completed_device_name ? ` on ${selectedWorkOrder.completed_device_name}` : ""}`
                : canEdit
                  ? role === "admin"
                    ? "Administrator access: field records may be corrected, but only the claiming engineer can complete the job."
                    : "Verified owner: this account and device may record and complete field work."
                  : selectedWorkOrder.claimed_by_name
                    ? `Read-only: claimed by ${selectedWorkOrder.claimed_by_name}.`
                    : "Read-only until you claim this job."}
            </div>
            <div className="sticky-actions">
              {selectedWorkOrder.can_claim && <button type="button" onClick={onClaimJob} disabled={claimBusy}>
                {claimBusy ? "Claiming…" : "Claim this job"}
              </button>}
              {canEdit && <button type="button" onClick={onStartJob} disabled={evidenceFrozen}>
                Start job
              </button>}
              {canComplete && <button type="button" onClick={onCompleteJob} disabled={evidenceFrozen}>
                {completionPolicy?.require_manager_approval && role === "engineer" ? "Submit for approval" : "Complete job"}
              </button>}
              {canEdit && <button type="button" onClick={onPauseJob} disabled={evidenceFrozen || selectedWorkOrder.status !== "IN_PROGRESS"}>
                Pause
              </button>}
              {pendingApproval && ["admin", "manager"].includes(role) && <>
                <button type="button" onClick={onApproveCompletion}>Approve &amp; lock</button>
                <button type="button" onClick={onRejectCompletion}>Reject</button>
              </>}
            </div>
            {canReleaseClaim && <div className="card" style={{ margin: "12px 0 0", background: "#f9fafb" }}>
              <strong>Release engineer claim</strong>
              <p className="muted" style={{ margin: "4px 0 8px" }}>Managers and administrators can return this job to the shared pool without changing its field records.</p>
              <div className="two-col" style={{ alignItems: "stretch" }}>
                <input
                  value={releaseReason}
                  onChange={(e) => setReleaseReason(e.target.value)}
                  placeholder="Required release reason"
                  minLength={3}
                  disabled={releaseBusy}
                />
                <button type="button" onClick={() => void onReleaseClaim()} disabled={releaseBusy || releaseReason.trim().length < 3}>
                  {releaseBusy ? "Releasing…" : "Release claim"}
                </button>
              </div>
            </div>}
          </div>

          <div className="card">
            <h3 className="section-title">Customer &amp; equipment</h3>
            <div className="two-col">
              <div>
                <strong>{serviceContext?.customer?.name || serviceContext?.fallback_customer_name || "Customer not linked"}</strong>
                <div className="muted">{serviceContext?.customer?.contact_name || "No contact name"}</div>
                <div className="muted">{serviceContext?.customer?.phone || serviceContext?.fallback_contact_phone || "No phone"}</div>
                {serviceContext?.customer?.account_number && <div className="muted">Account {serviceContext.customer.account_number}</div>}
              </div>
              <div>
                <strong>{serviceContext?.equipment?.model || serviceContext?.fallback_equipment_model || "Equipment not linked"}</strong>
                <div className="muted">{[serviceContext?.equipment?.manufacturer, serviceContext?.equipment?.equipment_type].filter(Boolean).join(" · ") || "No equipment profile"}</div>
                {serviceContext?.equipment?.asset_tag && <div className="muted">Asset {serviceContext.equipment.asset_tag}</div>}
                {serviceContext?.equipment?.serial_number && <div className="muted">Serial {serviceContext.equipment.serial_number}</div>}
              </div>
            </div>
            {(serviceContext?.equipment?.model || serviceContext?.fallback_equipment_model) && (
              <Link
                className="nav-item"
                style={{ marginTop: 10 }}
                href={`/knowledge-base?model=${encodeURIComponent(
                  serviceContext?.equipment?.model || serviceContext?.fallback_equipment_model || "",
                )}`}
              >
                Open machine service knowledge
              </Link>
            )}
          </div>

          <div className="card">
            <h3 className="section-title">Service history</h3>
            {!serviceContext ? <div className="skeleton" style={{ width: "80%" }} /> : serviceContext.history.length === 0 ? (
              <div className="empty-state">No completed repair history found for this equipment.</div>
            ) : serviceContext.history.map((item) => (
              <details key={item.id} style={{ padding: "10px 0", borderBottom: "1px solid #e2e8f0" }}>
                <summary style={{ cursor: "pointer" }}>
                  <strong>{item.ticket_number}</strong> · {item.job_type || "service"} · <time>{item.completed_at ? new Date(item.completed_at).toLocaleDateString() : item.schedule_date || "Date unavailable"}</time>
                </summary>
                <p><strong>Problem:</strong> {item.problem_description || "Not recorded"}</p>
                <p><strong>Result:</strong> {item.repair_result || "Not recorded"}</p>
                <p><strong>Learning:</strong> {[item.fault_type, item.error_code, item.final_outcome].filter(Boolean).join(" · ") || "Not recorded"}</p>
                <p><strong>First-time fix:</strong> {item.first_time_fix === null || item.first_time_fix === undefined ? "Unknown" : item.first_time_fix ? "Yes" : "No"} · <strong>Rework:</strong> {item.is_rework ? "Yes" : "No"} · <strong>Duration:</strong> {item.repair_duration_minutes ?? "—"} min</p>
                {item.parts_used.length > 0 && <div><strong>Parts:</strong><ul>{item.parts_used.map((part) => (
                  <li key={part.part_number}>{part.part_number} · {part.name} × {part.quantity}</li>
                ))}</ul></div>}
              </details>
            ))}
          </div>

          <div className="card">
            <h3 className="section-title">Service intelligence</h3>
            {!serviceIntelligenceLoaded ? (
              <div className="skeleton" style={{ width: "80%" }} />
            ) : !serviceIntelligence ? (
              <div className="empty-state">Service intelligence is currently unavailable.</div>
            ) : (
              <>
                <p style={{ marginTop: 0 }}>{serviceIntelligence.fault_analysis.summary}</p>
                <div className="grid" style={{ marginBottom: 12 }}>
                  <div className="card" style={{ marginBottom: 0 }}>
                    <div className="muted">Same-model evidence</div>
                    <div className="metric">{serviceIntelligence.fault_analysis.completed_work_orders}</div>
                  </div>
                  <div className="card" style={{ marginBottom: 0 }}>
                    <div className="muted">First-time fix</div>
                    <div className="metric">
                      {serviceIntelligence.fault_analysis.first_time_fix_rate == null
                        ? "—"
                        : `${Math.round(serviceIntelligence.fault_analysis.first_time_fix_rate * 100)}%`}
                    </div>
                  </div>
                  <div className="card" style={{ marginBottom: 0 }}>
                    <div className="muted">Rework</div>
                    <div className="metric">
                      {serviceIntelligence.fault_analysis.rework_rate == null
                        ? "—"
                        : `${Math.round(serviceIntelligence.fault_analysis.rework_rate * 100)}%`}
                    </div>
                  </div>
                  <div className="card" style={{ marginBottom: 0 }}>
                    <div className="muted">Average repair</div>
                    <div className="metric">
                      {serviceIntelligence.fault_analysis.average_repair_minutes == null
                        ? "—"
                        : `${Math.round(serviceIntelligence.fault_analysis.average_repair_minutes)} min`}
                    </div>
                  </div>
                </div>
                {(serviceIntelligence.fault_analysis.top_fault_types.length > 0
                  || serviceIntelligence.fault_analysis.top_error_codes.length > 0) && (
                  <p className="muted">
                    Frequent evidence:{" "}
                    {[
                      ...serviceIntelligence.fault_analysis.top_fault_types.map((item) => `${item.value} (${item.count})`),
                      ...serviceIntelligence.fault_analysis.top_error_codes.map((item) => `${item.value} (${item.count})`)
                    ].join(" · ")}
                  </p>
                )}
                {serviceIntelligence.fault_analysis.warnings.map((warning) => (
                  <p className="notice" key={warning}>{warning}</p>
                ))}

                <h4>Published machine guidance</h4>
                {serviceIntelligence.knowledge_entries.length === 0 ? (
                  <div className="empty-state">No published exact-model guidance matches this job yet.</div>
                ) : serviceIntelligence.knowledge_entries.map((entry) => (
                  <details key={entry.id} style={{ padding: "10px 0", borderBottom: "1px solid #e2e8f0" }}>
                    <summary style={{ cursor: "pointer" }}>
                      <strong>{entry.title}</strong> · {Math.round(entry.confidence * 100)}% match
                    </summary>
                    <p style={{ whiteSpace: "pre-wrap" }}>{entry.content}</p>
                    <p className="muted">{entry.reason}</p>
                    {entry.related_part && (
                      <p>
                        <strong>{entry.related_part_role || "related"} part:</strong>{" "}
                        {entry.related_part.part_number} · {entry.related_part.name}
                        {entry.installation_location ? ` · ${entry.installation_location}` : ""}
                      </p>
                    )}
                    {entry.alternative_for_part && (
                      <p><strong>Replaces:</strong> {entry.alternative_for_part.part_number} · {entry.alternative_for_part.name}</p>
                    )}
                    {entry.media_url?.startsWith("/api/machine-knowledge/media/") ? (
                      <button
                        type="button"
                        onClick={() => void api.openMachineKnowledgeMedia(entry.id).catch((error: Error) => (
                          setNotice({ type: "error", text: error.message })
                        ))}
                      >
                        Open protected field media
                      </button>
                    ) : entry.media_url ? (
                      <a className="nav-item" href={resolveUploadedImageUrl(entry.media_url)} target="_blank" rel="noreferrer">
                        Open reference media
                      </a>
                    ) : null}
                  </details>
                ))}

                <h4>Similar completed work orders</h4>
                {serviceIntelligence.similar_work_orders.length === 0 ? (
                  <div className="empty-state">No sufficiently similar completed work orders found.</div>
                ) : serviceIntelligence.similar_work_orders.map((item) => (
                  <details key={item.id} style={{ padding: "10px 0", borderBottom: "1px solid #e2e8f0" }}>
                    <summary style={{ cursor: "pointer" }}>
                      <strong>{item.ticket_number}</strong> · {Math.round(item.confidence * 100)}% match ·{" "}
                      {item.completed_at ? new Date(item.completed_at).toLocaleDateString() : "date unavailable"}
                    </summary>
                    <p className="muted">{item.reason}</p>
                    <p><strong>Problem:</strong> {item.problem_description || "Not recorded"}</p>
                    <p><strong>Repair:</strong> {item.repair_result || "Not recorded"}</p>
                    <p>
                      <strong>Outcome:</strong> {item.final_outcome || "Not labeled"} ·{" "}
                      first-time fix {item.first_time_fix == null ? "unknown" : item.first_time_fix ? "yes" : "no"} ·{" "}
                      rework {item.is_rework ? "yes" : "no"} · {item.repair_duration_minutes ?? "—"} min
                    </p>
                    {item.parts_used.length > 0 && (
                      <p><strong>Parts:</strong> {item.parts_used.map((part) => `${part.part_number} × ${part.quantity}`).join(", ")}</p>
                    )}
                  </details>
                ))}
                <p className="muted" style={{ marginBottom: 0 }}>
                  Evidence is limited to this company&apos;s locked completed work orders and published exact-model knowledge.
                </p>
              </>
            )}
          </div>

          {dynamicForm && dynamicForm.fields.length > 0 && (
            <div className="card">
              <h3 className="section-title">{dynamicForm.template_name || "Configured job form"}</h3>
              <p className="muted">
                Template snapshot v{dynamicForm.template_version ?? "—"} · form revision {dynamicForm.form_version}.
                {!dynamicForm.can_edit && " Visible to everyone; editable only by the verified job owner or administrator."}
              </p>
              {dynamicForm.missing_required_fields.length > 0 && (
                <p className="notice">
                  Required before completion:{" "}
                  {dynamicForm.missing_required_fields.map((key) => (
                    dynamicForm.fields.find((field) => field.field_key === key)?.label || key
                  )).join(", ")}
                </p>
              )}
              <div className="form-grid">
                {dynamicForm.fields.map((field) => {
                  const value = dynamicFormValues[field.field_key];
                  const disabled = !dynamicForm.can_edit || dynamicForm.is_frozen;
                  const label = `${field.label}${field.required_at_completion || field.requires_photo || field.requires_signature ? " *" : ""}`;
                  const updateValue = (next: WorkOrderFormValue) => {
                    setDynamicFormValues((current) => ({ ...current, [field.field_key]: next }));
                  };
                  if (field.field_type === "boolean") {
                    return (
                      <label key={field.field_key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                        <input
                          type="checkbox"
                          checked={value === true}
                          disabled={disabled}
                          onChange={(event) => updateValue(event.target.checked)}
                        />
                        {label}
                        {field.help_text && <span className="muted">· {field.help_text}</span>}
                      </label>
                    );
                  }
                  if (field.field_type === "textarea") {
                    return (
                      <label key={field.field_key}>
                        {label}
                        <textarea
                          rows={4}
                          value={String(value ?? "")}
                          placeholder={field.placeholder || ""}
                          disabled={disabled}
                          onChange={(event) => updateValue(event.target.value)}
                        />
                        {field.help_text && <span className="muted">{field.help_text}</span>}
                      </label>
                    );
                  }
                  if (field.field_type === "select") {
                    return (
                      <label key={field.field_key}>
                        {label}
                        <select
                          value={String(value ?? "")}
                          disabled={disabled}
                          onChange={(event) => updateValue(event.target.value)}
                        >
                          <option value="">Select…</option>
                          {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                        {field.help_text && <span className="muted">{field.help_text}</span>}
                      </label>
                    );
                  }
                  if (field.field_type === "photo") {
                    return (
                      <label key={field.field_key}>
                        {label}
                        <input
                          type="file"
                          accept="image/*"
                          capture="environment"
                          disabled={disabled || dynamicPhotoBusy === field.field_key}
                          onChange={(event) => void onUploadDynamicPhoto(
                            field.field_key,
                            event.target.files?.[0] || null
                          )}
                        />
                        {isOfflineMediaMarker(value) && (
                          <span className="notice notice-success" style={{ marginTop: 6, display: "block" }}>
                            Photo retained offline on this account and device.
                          </span>
                        )}
                        {typeof value === "string" && value && !isOfflineMediaMarker(value) && (
                          <a
                            className="nav-item"
                            href={resolveUploadedImageUrl(value)}
                            target="_blank"
                            rel="noreferrer"
                            style={{ marginTop: 6, display: "block" }}
                          >
                            Open uploaded photo
                          </a>
                        )}
                        {dynamicPhotoBusy === field.field_key && <span className="muted">Uploading…</span>}
                        {field.help_text && <span className="muted">{field.help_text}</span>}
                      </label>
                    );
                  }
                  if (field.field_type === "signature") {
                    return (
                      <div key={field.field_key}>
                        <strong>{label}</strong>
                        {typeof value === "string" && value.startsWith("data:image/") ? (
                          <>
                            {/* Signature data is an authenticated evidence payload, not an optimizable asset URL. */}
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={value}
                              alt={field.label}
                              style={{ width: "100%", maxWidth: 420, border: "1px solid #cbd5e1", borderRadius: 8 }}
                            />
                            {!disabled && (
                              <button type="button" onClick={() => updateValue("")}>
                                Replace signature
                              </button>
                            )}
                          </>
                        ) : (
                          <SignaturePad
                            onChange={(signature) => updateValue(signature)}
                            disabled={disabled}
                          />
                        )}
                        {field.help_text && <span className="muted">{field.help_text}</span>}
                      </div>
                    );
                  }
                  return (
                    <label key={field.field_key}>
                      {label}
                      <input
                        type={
                          field.field_type === "number"
                            ? "number"
                            : field.field_type === "date"
                              ? "date"
                            : "text"
                        }
                        value={String(value ?? "")}
                        placeholder={
                          field.placeholder
                          || ""
                        }
                        disabled={disabled}
                        onChange={(event) => updateValue(
                          field.field_type === "number"
                            ? (event.target.value === "" ? null : Number(event.target.value))
                            : event.target.value
                        )}
                      />
                      {field.help_text && <span className="muted">{field.help_text}</span>}
                    </label>
                  );
                })}
              </div>
              {dynamicForm.can_edit && !dynamicForm.is_frozen && (
                <button type="button" disabled={dynamicFormSaving} onClick={() => void onSaveDynamicForm()}>
                  {dynamicFormSaving ? "Saving…" : "Save configured form"}
                </button>
              )}
            </div>
          )}

          {formActions.length > 0 && (
            <div className="card">
              <h3 className="section-title">Configured form action progress</h3>
              <p className="muted">
                Everyone on the work order can see progress. Only the authorized manager, warehouse role, or administrator can process each action.
              </p>
              <div style={{ display: "grid", gap: 8 }}>
                {formActions.map((task) => (
                  <div key={task.id} style={{ borderBottom: "1px solid #e2e8f0", paddingBottom: 8 }}>
                    <strong>{task.field_label}</strong>
                    <span className="muted">
                      {" "}· {task.action_type === "inventory_review" ? "inventory review" : "notification"} · {task.status}
                    </span>
                    <span className="muted" style={{ display: "block" }}>
                      Triggered from form revision {task.triggered_form_version}
                      {task.acknowledged_by_name ? ` · acknowledged by ${task.acknowledged_by_name}` : ""}
                      {task.resolved_by_name ? ` · resolved by ${task.resolved_by_name}` : ""}
                    </span>
                    {task.resolution_notes && <span className="muted">{task.resolution_notes}</span>}
                  </div>
                ))}
              </div>
              {["admin", "manager", "warehouse"].includes(role) && (
                <Link className="nav-item" href="/form-actions" style={{ marginTop: 10, display: "inline-block" }}>
                  Open action inbox
                </Link>
              )}
            </div>
          )}

          <div className="card" id="completion">
            <h3 className="section-title">Field completion</h3>
            {pendingApproval && <p className="notice notice-success">Evidence is frozen while manager approval is pending.</p>}
            {completionPolicy && <div className="notice" style={{ marginBottom: 12 }}>
              <strong>Required for this job:</strong>{" "}
              {[
                completionPolicy.require_repair_result && "repair result",
                completionPolicy.require_customer_signature && "customer signature",
                completionPolicy.require_completion_photo && "field photo",
                completionPolicy.require_all_checklist_items && "all checklist items",
                completionPolicy.require_parts_usage && "part usage",
                completionPolicy.require_manager_approval && "manager approval"
              ].filter(Boolean).join(", ") || "No additional company requirements"}
            </div>}
            <div className="form-grid">
              <label>
                Fault type
                <input value={completion.faultType} onChange={(e) => setCompletion((prev) => ({ ...prev, faultType: e.target.value }))}
                  placeholder="Cooling failure, leak, electrical..." disabled={evidenceFrozen} maxLength={120} />
              </label>
              <label>
                Error code
                <input value={completion.errorCode} onChange={(e) => setCompletion((prev) => ({ ...prev, errorCode: e.target.value }))}
                  placeholder="Optional equipment error code" disabled={evidenceFrozen} maxLength={120} />
              </label>
              <label>
                Final outcome
                <select value={completion.finalOutcome} onChange={(e) => setCompletion((prev) => ({ ...prev, finalOutcome: e.target.value }))} disabled={evidenceFrozen}>
                  <option value="repaired">Repaired</option>
                  <option value="temporary_fix">Temporary fix</option>
                  <option value="parts_required">Parts required</option>
                  <option value="referred">Referred / escalated</option>
                  <option value="unresolved">Unresolved</option>
                </select>
              </label>
            </div>
            <label>
              Environment information
              <textarea value={completion.environmentInfo} onChange={(e) => setCompletion((prev) => ({ ...prev, environmentInfo: e.target.value }))}
                placeholder="Temperature, installation conditions, access constraints, contamination..." disabled={evidenceFrozen} rows={3} maxLength={4000} />
            </label>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", margin: "12px 0" }}>
              <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={completion.firstTimeFix}
                onChange={(e) => setCompletion((prev) => ({ ...prev, firstTimeFix: e.target.checked }))} disabled={evidenceFrozen} /> Fixed on first visit</label>
              <label style={{ display: "flex", gap: 8, alignItems: "center" }}><input type="checkbox" checked={completion.isRework}
                onChange={(e) => setCompletion((prev) => ({ ...prev, isRework: e.target.checked }))} disabled={evidenceFrozen} /> This job is rework</label>
            </div>
            {selectedWorkOrder.repair_duration_minutes !== null && selectedWorkOrder.repair_duration_minutes !== undefined && (
              <p className="muted">Server-recorded field duration: {selectedWorkOrder.repair_duration_minutes} minutes.</p>
            )}
            <label>
              Repair result
              <textarea
                value={completion.repairResult}
                onChange={(e) => setCompletion((prev) => ({ ...prev, repairResult: e.target.value }))}
                placeholder="Describe the repair, verification, and final condition"
                disabled={evidenceFrozen}
                rows={4}
              />
            </label>
            <div style={{ display: "grid", gap: 8, margin: "12px 0" }}>
              {([
                ["equipmentSafe", "Equipment is safe and operational"],
                ["siteClean", "Work area is clean"],
                ["customerBriefed", "Customer was briefed on the result"]
              ] as const).map(([key, label]) => (
                <label key={key} style={{ display: "flex", gap: 8, alignItems: "center" }}>
                  <input
                    type="checkbox"
                    checked={completion[key]}
                    onChange={(e) => setCompletion((prev) => ({ ...prev, [key]: e.target.checked }))}
                    disabled={evidenceFrozen}
                    style={{ width: 20, minHeight: 20 }}
                  />
                  {label}
                </label>
              ))}
            </div>
            <label>
              Customer signature name
              <input
                value={completion.signatureName}
                onChange={(e) => setCompletion((prev) => ({ ...prev, signatureName: e.target.value }))}
                placeholder="Customer full name"
                disabled={evidenceFrozen}
              />
            </label>
            <div style={{ marginTop: 12 }}>
              {locked && completion.signatureData ? (
                // The data URL is validated by the API as a bounded PNG before storage.
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={completion.signatureData}
                  alt={`Signature of ${completion.signatureName || "customer"}`}
                  style={{ width: "100%", maxHeight: 180, objectFit: "contain", border: "1px solid #cbd5e1", borderRadius: 10 }}
                />
              ) : (
                <SignaturePad
                  disabled={evidenceFrozen}
                  onChange={(signatureData) => setCompletion((prev) => ({ ...prev, signatureData }))}
                />
              )}
            </div>
            <p className="muted">The drawn signature, signed name, and completion checklist are stored with the locked work order.</p>
            {canComplete && <label style={{ display: "block", marginTop: 12 }}>
              Verify with your account password
              <input
                type="password"
                autoComplete="current-password"
                value={completionPassword}
                onChange={(e) => setCompletionPassword(e.target.value)}
                placeholder="Required when completing this job"
                disabled={evidenceFrozen}
              />
              <span className="muted" style={{ display: "block", marginTop: 4 }}>
                This confirms the signed-in engineer is the person completing the work order.
              </span>
            </label>}
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
        <h3 className="section-title">Voice notes</h3>
        <p className="muted">Record a hands-free field note. Audio is stored with this work order.</p>
        <VoiceRecorder
          disabled={evidenceFrozen || !currentWorkOrderId}
          onRecorded={async (blob, duration) => {
            await api.uploadVoiceNote(currentWorkOrderId, blob, duration);
            setNotice({ type: "success", text: "Voice note uploaded." });
            await reloadDetails();
          }}
        />
        <div style={{ display: "grid", gap: 10, marginTop: 12 }}>
          {voiceNotes.map((note) => <div key={note.id}>
            <audio controls preload="metadata" src={resolveUploadedImageUrl(note.audio_url)} style={{ width: "100%" }} />
            <div className="muted">{Math.round(note.duration_seconds || 0)}s · {note.transcription_status}</div>
          </div>)}
          {voiceNotes.length === 0 && <div className="empty-state">No voice notes yet.</div>}
        </div>
      </div>

      <div className="card">
        <h3 className="section-title">Status timeline</h3>
        <form onSubmit={onCreateJobStatus} style={{ marginBottom: 12 }}>
          <div className="two-col" style={{ alignItems: "stretch" }}>
            <select value={statusInput} onChange={(e) => setStatusInput(e.target.value)} disabled={evidenceFrozen}>
              <option value="open">open</option>
              <option value="in_progress">in_progress</option>
            </select>
            <button type="submit" disabled={evidenceFrozen}>
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
        <h3 className="section-title">Field media evidence</h3>
        <p className="muted" style={{ fontSize: 14, marginTop: 0 }}>
          Private, account-attributed photos and videos. Everyone on the team can review them;
          only the job owner on the bound phone or an administrator can add evidence.
        </p>
        <form onSubmit={onCreateFieldMedia}>
          <input
            id={fieldMediaCameraInputId}
            className="visually-hidden"
            type="file"
            accept="image/*"
            capture="environment"
            disabled={evidenceFrozen || fieldMediaBusy}
            onChange={(event) => {
              setFieldMediaFromFile(event.target.files?.[0] || null);
              event.target.value = "";
            }}
          />
          <input
            id={fieldMediaLibraryInputId}
            className="visually-hidden"
            type="file"
            accept="image/*,video/mp4,video/quicktime,video/webm"
            disabled={evidenceFrozen || fieldMediaBusy}
            onChange={(event) => {
              setFieldMediaFromFile(event.target.files?.[0] || null);
              event.target.value = "";
            }}
          />
          <div className="photo-upload-actions" style={{ marginBottom: 12 }}>
            <label
              htmlFor={fieldMediaCameraInputId}
              style={{
                opacity: evidenceFrozen || fieldMediaBusy ? 0.5 : 1,
                pointerEvents: evidenceFrozen || fieldMediaBusy ? "none" : "auto"
              }}
            >
              Take field photo
            </label>
            <label
              htmlFor={fieldMediaLibraryInputId}
              style={{
                opacity: evidenceFrozen || fieldMediaBusy ? 0.5 : 1,
                pointerEvents: evidenceFrozen || fieldMediaBusy ? "none" : "auto"
              }}
            >
              Choose photo / video
            </label>
            {fieldMediaFile && (
              <button
                type="button"
                className="photo-upload-clear"
                disabled={evidenceFrozen || fieldMediaBusy}
                onClick={() => setFieldMediaFromFile(null)}
              >
                Remove selection
              </button>
            )}
          </div>
          <div className="form-grid" style={{ marginBottom: 10 }}>
            <label>
              Evidence category
              <select
                value={fieldMediaForm.category}
                disabled={evidenceFrozen || fieldMediaBusy}
                onChange={(event) => setFieldMediaForm((previous) => ({
                  ...previous,
                  category: event.target.value as WorkOrderMediaCategory
                }))}
              >
                <option value="arrival">Arrival</option>
                <option value="before">Before repair</option>
                <option value="during">During repair</option>
                <option value="after">After repair</option>
                <option value="damage">Damage</option>
                <option value="serial_label">Serial / label</option>
                <option value="other">Other</option>
              </select>
            </label>
            <label>
              Caption (optional)
              <input
                maxLength={500}
                value={fieldMediaForm.caption}
                disabled={evidenceFrozen || fieldMediaBusy}
                onChange={(event) => setFieldMediaForm((previous) => ({
                  ...previous,
                  caption: event.target.value
                }))}
                placeholder="What does this evidence show?"
              />
            </label>
          </div>
          {fieldMediaPreview && (
            <div style={{ marginBottom: 12 }}>
              {fieldMediaPreviewIsVideo ? (
                <video
                  src={fieldMediaPreview}
                  controls
                  style={{ width: "100%", maxWidth: 480, maxHeight: 280, borderRadius: 10 }}
                />
              ) : (
                /* eslint-disable-next-line @next/next/no-img-element */
                <img
                  src={fieldMediaPreview}
                  alt="Selected field evidence"
                  style={{ width: "100%", maxWidth: 480, maxHeight: 280, objectFit: "contain", borderRadius: 10, border: "1px solid var(--border)" }}
                />
              )}
            </div>
          )}
          <button type="submit" disabled={evidenceFrozen || fieldMediaBusy || !fieldMediaFile}>
            {fieldMediaBusy ? "Uploading…" : "Add private field evidence"}
          </button>
          {!canEdit && (
            <p className="muted" style={{ marginBottom: 0, fontSize: 13 }}>
              Read-only: this work order is owned by another engineer or is frozen.
            </p>
          )}
        </form>

        {workOrderMedia.length === 0 ? (
          <div className="empty-state" style={{ marginTop: 12 }}>
            No governed field photos or videos yet.
          </div>
        ) : (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
              gap: 12,
              marginTop: 14
            }}
          >
            {workOrderMedia.map((media) => (
              <div key={media.id} className="job-card" style={{ margin: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
                  <strong>{media.media_type === "photo" ? "Photo" : "Video"}</strong>
                  <span className="badge">{media.category.replace("_", " ")}</span>
                </div>
                {media.caption && <p style={{ margin: "8px 0" }}>{media.caption}</p>}
                <div className="muted" style={{ fontSize: 12, lineHeight: 1.5 }}>
                  {(media.size_bytes / (1024 * 1024)).toFixed(2)} MiB · claim {media.claim_version}
                  <br />
                  {users.find((user) => user.id === media.created_by)?.name || "Administrator"} · {new Date(media.created_at).toLocaleString()}
                  <br />
                  SHA-256 {media.file_sha256.slice(0, 12)}…
                </div>
                <button
                  type="button"
                  className="button-secondary"
                  style={{ marginTop: 10 }}
                  onClick={() => void onOpenFieldMedia(media)}
                >
                  Open authenticated media
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="card">
        <h3 className="section-title">Legacy QC pictures</h3>
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
            disabled={evidenceFrozen || qcBusy}
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
            disabled={evidenceFrozen || qcBusy}
            onChange={(e) => {
              const file = e.target.files?.[0] || null;
              setQcPhotoFromFile(file);
              e.target.value = "";
            }}
          />
          <div className="photo-upload-actions" style={{ marginBottom: 12 }}>
            <label htmlFor={qcCameraInputId} style={{ opacity: evidenceFrozen || qcBusy ? 0.5 : 1, pointerEvents: evidenceFrozen || qcBusy ? "none" : "auto" }}>
              Take QC photo
            </label>
            <label htmlFor={qcLibraryInputId} style={{ opacity: evidenceFrozen || qcBusy ? 0.5 : 1, pointerEvents: evidenceFrozen || qcBusy ? "none" : "auto" }}>
              Choose from library
            </label>
            {qcPhotoFile && (
              <button type="button" className="photo-upload-clear" disabled={evidenceFrozen || qcBusy} onClick={() => setQcPhotoFromFile(null)}>
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
            disabled={evidenceFrozen || qcBusy}
          />
          <button type="submit" style={{ marginTop: 8 }} disabled={evidenceFrozen || qcBusy}>
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
            disabled={evidenceFrozen}
          />
          <input
            type="number"
            min={1}
            value={retForm.quantity}
            onChange={(e) => setRetForm((prev) => ({ ...prev, quantity: e.target.value }))}
            style={{ marginBottom: 8 }}
            disabled={evidenceFrozen}
          />
          <button type="submit" disabled={evidenceFrozen}>
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
