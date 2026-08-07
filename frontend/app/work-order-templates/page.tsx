"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import ManagerShell from "@/components/manager-shell";
import { api } from "@/lib/api";
import { getCurrentRole } from "@/lib/role";
import {
  WorkOrderFormField,
  WorkOrderFormFieldType,
  WorkOrderFormTemplate,
  WorkOrderFormValue
} from "@/types";

type TemplateDraft = {
  name: string;
  industry: string;
  description: string;
  applicable_machine_type: string;
  applicable_job_type: string;
  default_work_order_status: "open" | "scheduled";
  is_active: boolean;
  fields: WorkOrderFormField[];
};

const FIELD_TYPES: Array<{ value: WorkOrderFormFieldType; label: string }> = [
  { value: "text", label: "Short text" },
  { value: "textarea", label: "Long text" },
  { value: "number", label: "Number" },
  { value: "boolean", label: "Yes / No" },
  { value: "date", label: "Date" },
  { value: "select", label: "Choice list" },
  { value: "photo", label: "Photo URL" },
  { value: "signature", label: "Signature evidence" }
];

function blankField(index: number): WorkOrderFormField {
  return {
    field_key: `field_${index + 1}`,
    label: `Field ${index + 1}`,
    field_type: "text",
    help_text: "",
    placeholder: "",
    default_value: null,
    options: [],
    required_at_completion: false,
    requires_photo: false,
    requires_signature: false,
    requires_approval: false,
    triggers_notification: false,
    affects_inventory: false,
    include_in_ai_learning: true,
    sort_order: index
  };
}

function blankTemplate(): TemplateDraft {
  return {
    name: "",
    industry: "",
    description: "",
    applicable_machine_type: "",
    applicable_job_type: "",
    default_work_order_status: "open",
    is_active: true,
    fields: []
  };
}

function templateDraft(template: WorkOrderFormTemplate): TemplateDraft {
  return {
    name: template.name,
    industry: template.industry || "",
    description: template.description || "",
    applicable_machine_type: template.applicable_machine_type || "",
    applicable_job_type: template.applicable_job_type || "",
    default_work_order_status: template.default_work_order_status,
    is_active: template.is_active,
    fields: template.fields.map((field, index) => ({
      ...field,
      options: [...field.options],
      sort_order: index
    }))
  };
}

function defaultValueForInput(
  field: WorkOrderFormField,
  value: string
): WorkOrderFormValue {
  if (!value) return null;
  if (field.field_type === "number") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  if (field.field_type === "boolean") return value === "true";
  return value;
}

export default function WorkOrderTemplatesPage() {
  const [templates, setTemplates] = useState<WorkOrderFormTemplate[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [draft, setDraft] = useState<TemplateDraft>(blankTemplate);
  const [role, setRole] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const selected = useMemo(
    () => templates.find((template) => template.id === selectedId) || null,
    [selectedId, templates]
  );
  const canEdit = role === "admin";

  const load = useCallback(async (preferId?: number) => {
    setLoading(true);
    try {
      const rows = await api.listWorkOrderFormTemplates(true);
      setTemplates(rows);
      const next = rows.find((row) => row.id === preferId)
        || rows.find((row) => row.id === selectedId)
        || rows[0]
        || null;
      if (next) {
        setSelectedId(next.id);
        setDraft(templateDraft(next));
      } else {
        setSelectedId(null);
        setDraft(blankTemplate());
      }
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to load form templates."
      });
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    setRole(getCurrentRole());
    void load();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectTemplate = (template: WorkOrderFormTemplate) => {
    setSelectedId(template.id);
    setDraft(templateDraft(template));
    setNotice(null);
  };

  const startNew = () => {
    setSelectedId(null);
    setDraft(blankTemplate());
    setNotice(null);
  };

  const setField = <K extends keyof WorkOrderFormField>(
    index: number,
    key: K,
    value: WorkOrderFormField[K]
  ) => {
    setDraft((current) => ({
      ...current,
      fields: current.fields.map((field, fieldIndex) => {
        if (fieldIndex !== index) return field;
        if (key === "field_type") {
          const type = value as WorkOrderFormFieldType;
          return {
            ...field,
            field_type: type,
            options: type === "select" ? field.options : [],
            default_value: null,
            requires_photo: type === "photo" ? field.requires_photo : false,
            requires_signature: type === "signature" ? field.requires_signature : false
          };
        }
        return { ...field, [key]: value };
      })
    }));
  };

  const moveField = (index: number, delta: number) => {
    setDraft((current) => {
      const target = index + delta;
      if (target < 0 || target >= current.fields.length) return current;
      const fields = [...current.fields];
      [fields[index], fields[target]] = [fields[target], fields[index]];
      return {
        ...current,
        fields: fields.map((field, fieldIndex) => ({ ...field, sort_order: fieldIndex }))
      };
    });
  };

  const save = async () => {
    if (!canEdit) return;
    if (draft.name.trim().length < 2) {
      setNotice({ type: "error", text: "Template name must contain at least two characters." });
      return;
    }
    const keys = draft.fields.map((field) => field.field_key.trim().toLowerCase());
    if (keys.some((key) => !/^[a-z][a-z0-9_]{1,63}$/.test(key))) {
      setNotice({ type: "error", text: "Field keys must start with a letter and use lowercase letters, numbers, or underscores." });
      return;
    }
    if (new Set(keys).size !== keys.length) {
      setNotice({ type: "error", text: "Every field key must be unique within the template." });
      return;
    }
    if (draft.fields.some((field) => field.field_type === "select" && field.options.length === 0)) {
      setNotice({ type: "error", text: "Every choice-list field needs at least one option." });
      return;
    }
    const fields = draft.fields.map((field, index) => ({
      ...field,
      id: undefined,
      field_key: field.field_key.trim().toLowerCase(),
      label: field.label.trim(),
      help_text: field.help_text?.trim() || null,
      placeholder: field.placeholder?.trim() || null,
      options: field.options.map((value) => value.trim()).filter(Boolean),
      sort_order: index
    }));
    const common = {
      name: draft.name.trim(),
      industry: draft.industry.trim() || null,
      description: draft.description.trim() || null,
      applicable_machine_type: draft.applicable_machine_type.trim() || null,
      applicable_job_type: draft.applicable_job_type.trim() || null,
      default_work_order_status: draft.default_work_order_status,
      fields
    };
    try {
      setSaving(true);
      const saved = selected
        ? await api.updateWorkOrderFormTemplate(selected.id, {
            ...common,
            expected_version: selected.version,
            is_active: draft.is_active
          })
        : await api.createWorkOrderFormTemplate(common);
      setNotice({ type: "success", text: selected ? "Template version saved." : "Template created." });
      await load(saved.id);
    } catch (error) {
      setNotice({
        type: "error",
        text: error instanceof Error ? error.message : "Failed to save template."
      });
    } finally {
      setSaving(false);
    }
  };

  return (
    <ManagerShell
      title="Configurable Job Forms"
      subtitle="Create tenant-specific field sets. Every new job receives an immutable schema snapshot, so later template edits never rewrite historical work."
      metrics={[
        { label: "Templates", value: templates.length },
        { label: "Active", value: templates.filter((template) => template.is_active).length },
        { label: "Selected fields", value: draft.fields.length }
      ]}
    >
      {notice && (
        <p className={`notice ${notice.type === "success" ? "notice-success" : "notice-error"}`}>
          {notice.text}
        </p>
      )}
      {!canEdit && role && (
        <p className="notice">Managers can review form definitions. Only administrators can change them.</p>
      )}
      <section className="two-col">
        <div className="card">
          <div className="one-hand-actions" style={{ justifyContent: "space-between", marginBottom: 12 }}>
            <h3 style={{ margin: 0 }}>Templates</h3>
            {canEdit && <button type="button" onClick={startNew}>New template</button>}
          </div>
          {loading ? (
            <div className="skeleton" />
          ) : templates.length === 0 ? (
            <div className="empty-state">No form templates yet.</div>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              {templates.map((template) => (
                <button
                  type="button"
                  key={template.id}
                  className={selectedId === template.id ? "nav-item nav-item--active" : "nav-item"}
                  style={{ textAlign: "left" }}
                  onClick={() => selectTemplate(template)}
                >
                  <strong>{template.name}</strong>
                  <span className="muted" style={{ display: "block" }}>
                    v{template.version} · {template.fields.length} fields · {template.is_active ? "active" : "inactive"}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="card">
          <h3>{selected ? `Edit ${selected.name}` : "New template"}</h3>
          <div style={{ display: "grid", gap: 10 }}>
            <label>Name
              <input value={draft.name} disabled={!canEdit} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <div className="two-col">
              <label>Industry
                <input value={draft.industry} disabled={!canEdit} placeholder="HVAC, elevator, refrigeration…" onChange={(event) => setDraft({ ...draft, industry: event.target.value })} />
              </label>
              <label>Initial job status
                <select value={draft.default_work_order_status} disabled={!canEdit} onChange={(event) => setDraft({ ...draft, default_work_order_status: event.target.value as "open" | "scheduled" })}>
                  <option value="open">open</option>
                  <option value="scheduled">scheduled</option>
                </select>
              </label>
            </div>
            <div className="two-col">
              <label>Machine type filter
                <input value={draft.applicable_machine_type} disabled={!canEdit} placeholder="Optional exact match" onChange={(event) => setDraft({ ...draft, applicable_machine_type: event.target.value })} />
              </label>
              <label>Job type filter
                <input value={draft.applicable_job_type} disabled={!canEdit} placeholder="Optional exact match" onChange={(event) => setDraft({ ...draft, applicable_job_type: event.target.value })} />
              </label>
            </div>
            <label>Description
              <textarea value={draft.description} disabled={!canEdit} onChange={(event) => setDraft({ ...draft, description: event.target.value })} />
            </label>
            {selected && (
              <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input type="checkbox" checked={draft.is_active} disabled={!canEdit} onChange={(event) => setDraft({ ...draft, is_active: event.target.checked })} />
                Available for new work orders
              </label>
            )}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="one-hand-actions" style={{ justifyContent: "space-between", marginBottom: 12 }}>
          <div>
            <h3 style={{ margin: 0 }}>Fields</h3>
            <p className="muted" style={{ marginBottom: 0 }}>Completion rules are enforced by the server and remain attached to the job snapshot.</p>
          </div>
          {canEdit && (
            <button type="button" onClick={() => setDraft((current) => ({ ...current, fields: [...current.fields, blankField(current.fields.length)] }))}>
              Add field
            </button>
          )}
        </div>
        {draft.fields.length === 0 ? (
          <div className="empty-state">This template has no custom fields.</div>
        ) : (
          <div style={{ display: "grid", gap: 12 }}>
            {draft.fields.map((field, index) => (
              <div className="card" key={`${field.field_key}-${index}`} style={{ marginBottom: 0 }}>
                <div className="two-col">
                  <label>Field label
                    <input value={field.label} disabled={!canEdit} onChange={(event) => setField(index, "label", event.target.value)} />
                  </label>
                  <label>Stable field key
                    <input value={field.field_key} disabled={!canEdit} onChange={(event) => setField(index, "field_key", event.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))} />
                  </label>
                  <label>Type
                    <select value={field.field_type} disabled={!canEdit} onChange={(event) => setField(index, "field_type", event.target.value as WorkOrderFormFieldType)}>
                      {FIELD_TYPES.map((type) => <option key={type.value} value={type.value}>{type.label}</option>)}
                    </select>
                  </label>
                  <label>Placeholder
                    <input value={field.placeholder || ""} disabled={!canEdit} onChange={(event) => setField(index, "placeholder", event.target.value)} />
                  </label>
                </div>
                {field.field_type === "select" && (
                  <label>Options (comma separated)
                    <input value={field.options.join(", ")} disabled={!canEdit} onChange={(event) => setField(index, "options", event.target.value.split(",").map((value) => value.trim()).filter(Boolean))} />
                  </label>
                )}
                <label>Default value
                  {field.field_type === "boolean" ? (
                    <select value={field.default_value === null || field.default_value === undefined ? "" : String(field.default_value)} disabled={!canEdit} onChange={(event) => setField(index, "default_value", defaultValueForInput(field, event.target.value))}>
                      <option value="">No default</option>
                      <option value="true">Yes</option>
                      <option value="false">No</option>
                    </select>
                  ) : field.field_type === "select" ? (
                    <select value={String(field.default_value ?? "")} disabled={!canEdit} onChange={(event) => setField(index, "default_value", defaultValueForInput(field, event.target.value))}>
                      <option value="">No default</option>
                      {field.options.map((option) => <option key={option} value={option}>{option}</option>)}
                    </select>
                  ) : (
                    <input type={field.field_type === "number" ? "number" : field.field_type === "date" ? "date" : "text"} value={String(field.default_value ?? "")} disabled={!canEdit} onChange={(event) => setField(index, "default_value", defaultValueForInput(field, event.target.value))} />
                  )}
                </label>
                <label>Help text
                  <input value={field.help_text || ""} disabled={!canEdit} onChange={(event) => setField(index, "help_text", event.target.value)} />
                </label>
                <div className="two-col" style={{ marginTop: 10 }}>
                  {([
                    ["required_at_completion", "Required before completion"],
                    ["requires_approval", "Require manager approval"],
                    ["triggers_notification", "Record notification trigger"],
                    ["affects_inventory", "Declare inventory impact"],
                    ["include_in_ai_learning", "Include in AI learning"]
                  ] as Array<[keyof WorkOrderFormField, string]>).map(([key, label]) => (
                    <label key={String(key)} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input type="checkbox" checked={Boolean(field[key])} disabled={!canEdit} onChange={(event) => setField(index, key, event.target.checked as never)} />
                      {label}
                    </label>
                  ))}
                  {field.field_type === "photo" && (
                    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input type="checkbox" checked={field.requires_photo} disabled={!canEdit} onChange={(event) => setField(index, "requires_photo", event.target.checked)} />
                      Require photo evidence
                    </label>
                  )}
                  {field.field_type === "signature" && (
                    <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <input type="checkbox" checked={field.requires_signature} disabled={!canEdit} onChange={(event) => setField(index, "requires_signature", event.target.checked)} />
                      Require signature evidence
                    </label>
                  )}
                </div>
                {canEdit && (
                  <div className="one-hand-actions" style={{ marginTop: 12 }}>
                    <button type="button" disabled={index === 0} onClick={() => moveField(index, -1)}>Move up</button>
                    <button type="button" disabled={index === draft.fields.length - 1} onClick={() => moveField(index, 1)}>Move down</button>
                    <button type="button" onClick={() => setDraft((current) => ({ ...current, fields: current.fields.filter((_, fieldIndex) => fieldIndex !== index).map((item, fieldIndex) => ({ ...item, sort_order: fieldIndex })) }))}>Remove</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {canEdit && (
          <button type="button" style={{ marginTop: 16 }} disabled={saving} onClick={() => void save()}>
            {saving ? "Saving…" : selected ? "Save new template version" : "Create template"}
          </button>
        )}
      </section>
    </ManagerShell>
  );
}
