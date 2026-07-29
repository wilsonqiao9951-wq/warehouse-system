"use client";

import { useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api, getApiPublicOrigin } from "@/lib/api";
import { AppRole, getCurrentRole } from "@/lib/role";
import {
  MachineKnowledgeEntry,
  MachineKnowledgeEntryType,
  MachineKnowledgeProfile,
  Part,
} from "@/types";

const entryLabels: Record<MachineKnowledgeEntryType, string> = {
  fault: "Common fault",
  repair_step: "Repair step",
  tool: "Required tool",
  caution: "Safety / caution",
  common_error: "Common mistake",
  photo: "Field photo",
  video: "Repair video",
  note: "Service note",
};

const emptyEntry = {
  entryType: "fault" as MachineKnowledgeEntryType,
  title: "",
  content: "",
  faultCode: "",
  relatedPartId: "",
  sourceWorkOrderId: "",
  mediaUrl: "",
  sortOrder: "0",
};

function knowledgeMediaUrl(value: string): string {
  if (/^https?:\/\//i.test(value)) return value;
  return `${getApiPublicOrigin()}${value.startsWith("/") ? value : `/${value}`}`;
}

export default function KnowledgeBasePage() {
  const [role, setRole] = useState<AppRole>("engineer");
  const [profiles, setProfiles] = useState<MachineKnowledgeProfile[]>([]);
  const [parts, setParts] = useState<Part[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [newProfile, setNewProfile] = useState({
    manufacturer: "",
    model: "",
    equipmentType: "",
    summary: "",
  });
  const [entryForm, setEntryForm] = useState(emptyEntry);
  const [editingEntryId, setEditingEntryId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const curator = role === "admin" || role === "manager";
  const selected = profiles.find((profile) => profile.id === selectedId) || profiles[0] || null;

  const totals = useMemo(() => {
    const entries = profiles.flatMap((profile) => profile.entries);
    return {
      published: entries.filter((entry) => entry.status === "published").length,
      drafts: entries.filter((entry) => entry.status === "draft").length,
    };
  }, [profiles]);

  useEffect(() => {
    const currentRole = getCurrentRole();
    const params = new URLSearchParams(window.location.search);
    const requestedModel = params.get("model") || "";
    setRole(currentRole);
    setSearch(requestedModel);
    const canCurate = currentRole === "admin" || currentRole === "manager";
    Promise.all([
      api.listMachineKnowledge({
        model: requestedModel || undefined,
        includeInactive: canCurate,
      }),
      canCurate ? api.listParts() : Promise.resolve([] as Part[]),
    ])
      .then(([knowledge, availableParts]) => {
        setProfiles(knowledge);
        setParts(availableParts);
        setSelectedId(knowledge[0]?.id || null);
      })
      .catch((loadError: Error) => {
        setError(loadError.message || "Unable to load the machine knowledge base.");
      });
  }, []);

  const replaceProfile = (profile: MachineKnowledgeProfile) => {
    setProfiles((previous) => {
      const exists = previous.some((row) => row.id === profile.id);
      return exists
        ? previous.map((row) => row.id === profile.id ? profile : row)
        : [...previous, profile].sort((a, b) => a.model.localeCompare(b.model));
    });
    setSelectedId(profile.id);
  };

  const runSearch = async () => {
    try {
      setBusy(true);
      setError("");
      const rows = await api.listMachineKnowledge({
        q: search.trim() || undefined,
        includeInactive: curator,
      });
      setProfiles(rows);
      setSelectedId(rows[0]?.id || null);
    } catch (searchError) {
      setError(searchError instanceof Error ? searchError.message : "Knowledge search failed.");
    } finally {
      setBusy(false);
    }
  };

  const createProfile = async () => {
    if (!newProfile.model.trim()) {
      setError("Machine model is required.");
      return;
    }
    try {
      setBusy(true);
      setError("");
      const created = await api.createMachineKnowledge({
        model: newProfile.model.trim(),
        manufacturer: newProfile.manufacturer.trim() || undefined,
        equipment_type: newProfile.equipmentType.trim() || undefined,
        summary: newProfile.summary.trim() || undefined,
      });
      replaceProfile(created);
      setNewProfile({ manufacturer: "", model: "", equipmentType: "", summary: "" });
      setMessage("Machine profile created. Add draft knowledge for administrator review.");
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : "Unable to create machine profile.");
    } finally {
      setBusy(false);
    }
  };

  const resetEntryForm = () => {
    setEntryForm(emptyEntry);
    setEditingEntryId(null);
  };

  const editEntry = (entry: MachineKnowledgeEntry) => {
    setEditingEntryId(entry.id);
    setEntryForm({
      entryType: entry.entry_type,
      title: entry.title,
      content: entry.content,
      faultCode: entry.fault_code || "",
      relatedPartId: entry.related_part ? String(entry.related_part.id) : "",
      sourceWorkOrderId: entry.source_work_order_id ? String(entry.source_work_order_id) : "",
      mediaUrl: entry.media_url || "",
      sortOrder: String(entry.sort_order),
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const saveEntry = async () => {
    if (!selected || !entryForm.title.trim() || !entryForm.content.trim()) {
      setError("Select a machine and enter a title and guidance.");
      return;
    }
    const relatedPartId = entryForm.relatedPartId ? Number(entryForm.relatedPartId) : undefined;
    const sourceWorkOrderId = entryForm.sourceWorkOrderId
      ? Number(entryForm.sourceWorkOrderId)
      : undefined;
    const sortOrder = Number(entryForm.sortOrder || "0");
    if (
      (relatedPartId !== undefined && (!Number.isInteger(relatedPartId) || relatedPartId < 1))
      || (sourceWorkOrderId !== undefined && (!Number.isInteger(sourceWorkOrderId) || sourceWorkOrderId < 1))
      || !Number.isInteger(sortOrder)
      || sortOrder < 0
    ) {
      setError("Part, work-order, and order values must be valid positive numbers.");
      return;
    }
    try {
      setBusy(true);
      setError("");
      const commonPayload = {
        entry_type: entryForm.entryType,
        title: entryForm.title.trim(),
        content: entryForm.content.trim(),
        fault_code: entryForm.faultCode.trim() || undefined,
        related_part_id: relatedPartId,
        source_work_order_id: sourceWorkOrderId,
        media_url: entryForm.mediaUrl.trim() || undefined,
        sort_order: sortOrder,
      };
      const editing = selected.entries.find((entry) => entry.id === editingEntryId);
      const updated = editing
        ? await api.updateMachineKnowledgeEntry(editing, commonPayload)
        : await api.createMachineKnowledgeEntry(selected.id, commonPayload);
      replaceProfile(updated);
      resetEntryForm();
      setMessage(editing ? "Draft knowledge updated." : "Draft knowledge added for review.");
    } catch (saveError) {
      setError(saveError instanceof Error ? saveError.message : "Unable to save knowledge.");
    } finally {
      setBusy(false);
    }
  };

  const runEntryAction = async (
    entry: MachineKnowledgeEntry,
    action: "publish" | "archive" | "reopen",
  ) => {
    try {
      setBusy(true);
      setError("");
      const updated = await api.actOnMachineKnowledgeEntry(entry, action);
      replaceProfile(updated);
      setMessage(`Knowledge entry moved to ${action === "publish" ? "published" : action === "reopen" ? "draft" : "archived"}.`);
    } catch (actionError) {
      setError(actionError instanceof Error ? actionError.message : "Knowledge action failed.");
    } finally {
      setBusy(false);
    }
  };

  const toggleProfile = async () => {
    if (!selected) return;
    try {
      setBusy(true);
      setError("");
      const updated = await api.updateMachineKnowledge(selected, {
        is_active: !selected.is_active,
      });
      replaceProfile(updated);
      setMessage(updated.is_active ? "Machine profile reactivated." : "Machine profile deactivated.");
    } catch (toggleError) {
      setError(toggleError instanceof Error ? toggleError.message : "Unable to update machine profile.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <ManagerShell
      title="Machine service knowledge"
      subtitle="Published guidance is shared with every field engineer. Drafts remain curator-only until an administrator approves them."
      metrics={[
        { label: "Machine profiles", value: profiles.length },
        { label: "Published guidance", value: totals.published },
        { label: "Draft review", value: totals.drafts },
      ]}
    >
      <section className="card">
        <h3 style={{ marginTop: 0 }}>Find a machine</h3>
        <div className="two-col">
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void runSearch();
            }}
            placeholder="Model, manufacturer, equipment type, or keyword"
          />
          <button type="button" onClick={() => void runSearch()} disabled={busy}>
            Search knowledge
          </button>
        </div>
        {message && <p className="notice notice-success">{message}</p>}
        {error && <p className="notice notice-error">{error}</p>}
      </section>

      {curator && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Create machine profile</h3>
          <div className="two-col">
            <label>
              Manufacturer
              <input
                value={newProfile.manufacturer}
                onChange={(event) => setNewProfile((previous) => ({ ...previous, manufacturer: event.target.value }))}
                placeholder="ACME"
              />
            </label>
            <label>
              Model
              <input
                value={newProfile.model}
                onChange={(event) => setNewProfile((previous) => ({ ...previous, model: event.target.value }))}
                placeholder="ACME-9000"
              />
            </label>
          </div>
          <label style={{ display: "block", marginTop: 10 }}>
            Equipment type
            <input
              value={newProfile.equipmentType}
              onChange={(event) => setNewProfile((previous) => ({ ...previous, equipmentType: event.target.value }))}
              placeholder="Cooling unit"
            />
          </label>
          <label style={{ display: "block", marginTop: 10 }}>
            Profile summary
            <textarea
              value={newProfile.summary}
              onChange={(event) => setNewProfile((previous) => ({ ...previous, summary: event.target.value }))}
              placeholder="Scope, variants, and important service context"
            />
          </label>
          <button type="button" onClick={() => void createProfile()} disabled={busy} style={{ marginTop: 10 }}>
            Create profile
          </button>
        </section>
      )}

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Machine profiles</h3>
        <div className="one-hand-actions">
          {profiles.map((profile) => (
            <button
              key={profile.id}
              type="button"
              className={selected?.id === profile.id ? "" : "secondary-button"}
              onClick={() => setSelectedId(profile.id)}
            >
              {profile.manufacturer ? `${profile.manufacturer} ` : ""}{profile.model}
              {!profile.is_active ? " · inactive" : ""}
            </button>
          ))}
        </div>
        {profiles.length === 0 && (
          <div className="empty-state">No published knowledge matches this search.</div>
        )}
      </section>

      {selected && (
        <>
          <section className="card">
            <div className="two-col" style={{ alignItems: "start" }}>
              <div>
                <span className="app-header-badge">{selected.equipment_type || "Machine"}</span>
                <h2 style={{ marginBottom: 4 }}>
                  {selected.manufacturer ? `${selected.manufacturer} ` : ""}{selected.model}
                </h2>
                <p className="muted">{selected.summary || "No profile summary yet."}</p>
              </div>
              <div>
                <strong>Verified field evidence</strong>
                <p className="muted" style={{ marginBottom: 4 }}>
                  {selected.evidence.completed_work_orders} completed jobs ·{" "}
                  {selected.evidence.first_time_fix_rate == null
                    ? "success not labeled"
                    : `${Math.round(selected.evidence.first_time_fix_rate * 100)}% first-time fix`}
                </p>
                <p className="muted" style={{ marginTop: 0 }}>
                  {selected.evidence.average_repair_minutes == null
                    ? "Repair duration not available"
                    : `${Math.round(selected.evidence.average_repair_minutes)} min average repair`}
                </p>
                {selected.can_edit && (
                  <button type="button" onClick={() => void toggleProfile()} disabled={busy}>
                    {selected.is_active ? "Deactivate profile" : "Reactivate profile"}
                  </button>
                )}
              </div>
            </div>
          </section>

          <section className="card">
            <h3 style={{ marginTop: 0 }}>Known parts</h3>
            <div className="grid">
              {selected.related_parts.map((part) => (
                <div className="notice" key={part.id}>
                  <b>{part.part_number}</b>
                  <div>{part.name}</div>
                  <div className="muted">
                    {part.recognition_source || "knowledge link"}
                    {part.confidence == null ? "" : ` · ${Math.round(part.confidence * 100)}%`}
                    {part.confirmed_count == null ? "" : ` · ${part.confirmed_count} confirmations`}
                  </div>
                </div>
              ))}
            </div>
            {selected.related_parts.length === 0 && (
              <div className="empty-state">No confirmed machine-part associations yet.</div>
            )}
          </section>

          {selected.can_add_entry && (
            <section className="card">
              <h3 style={{ marginTop: 0 }}>{editingEntryId ? "Edit knowledge draft" : "Add knowledge draft"}</h3>
              <div className="two-col">
                <label>
                  Knowledge type
                  <select
                    value={entryForm.entryType}
                    onChange={(event) => setEntryForm((previous) => ({
                      ...previous,
                      entryType: event.target.value as MachineKnowledgeEntryType,
                    }))}
                  >
                    {Object.entries(entryLabels).map(([value, label]) => (
                      <option value={value} key={value}>{label}</option>
                    ))}
                  </select>
                </label>
                <label>
                  Title
                  <input
                    value={entryForm.title}
                    onChange={(event) => setEntryForm((previous) => ({ ...previous, title: event.target.value }))}
                    placeholder="Low airflow diagnosis"
                  />
                </label>
              </div>
              <label style={{ display: "block", marginTop: 10 }}>
                Guidance
                <textarea
                  value={entryForm.content}
                  onChange={(event) => setEntryForm((previous) => ({ ...previous, content: event.target.value }))}
                  placeholder="Symptoms, checks, sequence, verification, and expected result"
                />
              </label>
              <div className="two-col" style={{ marginTop: 10 }}>
                <label>
                  Fault / error code
                  <input
                    value={entryForm.faultCode}
                    onChange={(event) => setEntryForm((previous) => ({ ...previous, faultCode: event.target.value }))}
                    placeholder="Optional"
                  />
                </label>
                <label>
                  Related part
                  <select
                    value={entryForm.relatedPartId}
                    onChange={(event) => setEntryForm((previous) => ({ ...previous, relatedPartId: event.target.value }))}
                  >
                    <option value="">No linked part</option>
                    {parts.map((part) => (
                      <option key={part.id} value={part.id}>{part.part_number} · {part.name}</option>
                    ))}
                  </select>
                </label>
              </div>
              <div className="two-col" style={{ marginTop: 10 }}>
                <label>
                  Completed work-order ID
                  <input
                    inputMode="numeric"
                    value={entryForm.sourceWorkOrderId}
                    onChange={(event) => setEntryForm((previous) => ({ ...previous, sourceWorkOrderId: event.target.value }))}
                    placeholder="Optional evidence"
                  />
                </label>
                <label>
                  Display order
                  <input
                    inputMode="numeric"
                    value={entryForm.sortOrder}
                    onChange={(event) => setEntryForm((previous) => ({ ...previous, sortOrder: event.target.value }))}
                  />
                </label>
              </div>
              <label style={{ display: "block", marginTop: 10 }}>
                Photo / video URL
                <input
                  value={entryForm.mediaUrl}
                  onChange={(event) => setEntryForm((previous) => ({ ...previous, mediaUrl: event.target.value }))}
                  placeholder="https://… or /uploads/…"
                />
              </label>
              <div className="one-hand-actions" style={{ marginTop: 10 }}>
                <button type="button" onClick={() => void saveEntry()} disabled={busy}>
                  {editingEntryId ? "Save draft changes" : "Add draft"}
                </button>
                {editingEntryId && (
                  <button type="button" className="secondary-button" onClick={resetEntryForm} disabled={busy}>
                    Cancel edit
                  </button>
                )}
              </div>
            </section>
          )}

          <section className="card">
            <h3 style={{ marginTop: 0 }}>Service guidance</h3>
            <div style={{ display: "grid", gap: 10 }}>
              {selected.entries.map((entry) => (
                <article className="job-card" key={entry.id}>
                  <div className="two-col" style={{ alignItems: "start" }}>
                    <div>
                      <span className="app-header-badge">{entryLabels[entry.entry_type]}</span>
                      <h3 style={{ marginBottom: 4 }}>{entry.title}</h3>
                      {entry.fault_code && <div className="muted">Code: {entry.fault_code}</div>}
                    </div>
                    <div style={{ textAlign: "right" }}>
                      <span className={entry.status === "published" ? "notice-success notice" : "notice"}>
                        {entry.status}
                      </span>
                    </div>
                  </div>
                  <p style={{ whiteSpace: "pre-wrap" }}>{entry.content}</p>
                  {entry.related_part && (
                    <p className="muted">
                      Part: {entry.related_part.part_number} · {entry.related_part.name}
                    </p>
                  )}
                  {entry.source_work_order_id && (
                    <p className="muted">Evidence: completed work order #{entry.source_work_order_id}</p>
                  )}
                  {entry.media_url && (
                    <a className="nav-item" href={knowledgeMediaUrl(entry.media_url)} target="_blank" rel="noreferrer">
                      Open field media
                    </a>
                  )}
                  <div className="one-hand-actions" style={{ marginTop: 10 }}>
                    {entry.can_edit && (
                      <button type="button" onClick={() => editEntry(entry)} disabled={busy}>
                        Edit draft
                      </button>
                    )}
                    {entry.can_publish && (
                      <button type="button" onClick={() => void runEntryAction(entry, "publish")} disabled={busy}>
                        Admin publish
                      </button>
                    )}
                    {entry.can_archive && (
                      <button type="button" className="danger-button" onClick={() => void runEntryAction(entry, "archive")} disabled={busy}>
                        Archive
                      </button>
                    )}
                    {entry.can_reopen && (
                      <button type="button" onClick={() => void runEntryAction(entry, "reopen")} disabled={busy}>
                        Reopen as draft
                      </button>
                    )}
                  </div>
                </article>
              ))}
            </div>
            {selected.entries.length === 0 && (
              <div className="empty-state">
                {curator ? "No knowledge entries yet. Add the first draft above." : "No published guidance for this machine yet."}
              </div>
            )}
          </section>
        </>
      )}
    </ManagerShell>
  );
}
