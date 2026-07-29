# Configurable work-order forms

Schema heads `20260729_0029` and `20260729_0030` introduce organization-owned form templates, immutable per-work-order snapshots, and durable follow-up actions.

## Operational model

1. An administrator creates an active template and ordered field definitions.
2. A manager or administrator selects the template while creating a work order.
3. The server verifies the optional exact machine-type and job-type applicability rules.
4. The current template version, field schema, rules, and default values are copied onto the work order.
5. Later template changes increment the template version but never rewrite existing work orders.
6. Every same-organization engineer can read the form with the rest of the shared work-order record.
7. Only an administrator or the engineer account, registered device, and current claim generation that own the job can update values.
8. Pending-approval and completed work orders freeze the form.

This preserves historical evidence and the existing account/device ownership boundary.

## Field types

- `text`
- `textarea`
- `number`
- `boolean`
- `date`
- `select`
- `photo`
- `signature`

Each field has a stable lowercase key, label, optional help and placeholder text, optional typed default, ordered position, and these independent controls:

- required at completion
- require photo evidence
- require signature evidence
- require manager approval
- record a notification trigger
- declare inventory impact
- include in AI learning

Photo and signature requirement flags are accepted only for their matching field type. Select fields require at least one unique option. Defaults are validated using the same server-side type and option rules as field submissions.

`affects_inventory` never directly changes an inventory transaction; physical custody remains in the dedicated stock workflows. A changed field with `triggers_notification` creates an operational-notification task. A changed field with `affects_inventory` creates an inventory-review task that warehouse staff must resolve with notes after using the appropriate replenishment, transfer, return, or count workflow. Task records contain the field identity and form revision, not the submitted value. AI-learning field identities and task creation are also recorded in tenant audit evidence.

## Template APIs

Managers have read access. Administrator identity is required to create or change definitions.

```text
GET   /api/work-order-form-templates
GET   /api/work-order-form-templates/{template_id}
POST  /api/work-order-form-templates
PATCH /api/work-order-form-templates/{template_id}
```

`PATCH` requires `expected_version`. A stale version returns `409` and prevents one browser from silently overwriting another administrator's changes.

Example:

```json
{
  "name": "HVAC commissioning",
  "industry": "HVAC",
  "applicable_machine_type": "ACME-9000",
  "applicable_job_type": "commissioning",
  "default_work_order_status": "scheduled",
  "fields": [
    {
      "field_key": "startup_pressure",
      "label": "Startup pressure",
      "field_type": "number",
      "required_at_completion": true,
      "include_in_ai_learning": true,
      "sort_order": 0
    },
    {
      "field_key": "site_photo",
      "label": "Installed unit",
      "field_type": "photo",
      "requires_photo": true,
      "sort_order": 1
    }
  ]
}
```

## Work-order form APIs

```text
GET   /api/work-orders/{work_order_id}/form
PATCH /api/work-orders/{work_order_id}/form
```

Updates are partial, typed, bounded to 100 known fields and 256 KiB, and require `expected_version`. Engineer writes also require the bearer session, registered-device secret, and `X-Claim-Version`. A stale form version returns `409`.

Example:

```json
{
  "expected_version": 0,
  "values": {
    "startup_pressure": 42.5,
    "site_photo": "/uploads/7f68d2-photo.jpg"
  }
}
```

The read response returns ordered snapshot fields, current values, `missing_required_fields`, edit capability, and frozen state. Completion endpoints repeat the validation on the server; hiding or bypassing the browser form cannot complete an incomplete job. A field with `requires_approval` merges into the effective completion policy and sends an engineer completion through the existing manager-approval workflow.

Signature values must be valid bounded PNG data URLs. As with the standard customer signature, the dynamic signature payload is redacted from non-owner engineers and warehouse readers; administrators, managers reviewing approval evidence, and the verified owner retain access.

## Form action APIs

```text
GET   /api/work-order-form-actions
GET   /api/work-orders/{work_order_id}/form-actions
PATCH /api/work-order-form-actions/{task_id}
```

The global inbox is available to administrators, managers, and warehouse users. Warehouse users receive inventory-review tasks only. Managers acknowledge and resolve notification tasks, warehouse users acknowledge and resolve inventory-review tasks, and administrators can process either type. Inventory resolution requires notes. Every transition uses `expected_version`, actor/timestamp attribution, and a tenant audit record.

Engineers cannot open or mutate the global inbox, but every same-organization engineer can see read-only action progress on a work order. Cross-organization task reads and mutations remain hidden by the automatic tenant scope.

Re-saving identical form values is a no-op: it does not advance the form version or create duplicate tasks. A later real change creates new tasks keyed to the new form revision.

## User interfaces

- `/work-order-templates`: administrator visual form builder and manager read-only review.
- `/work-orders`: template selection plus job-type and machine-type assignment during work-order creation.
- `/work-order-details`: dynamic mobile controls, camera upload, drawn signature, required-field status, verified save, and read-only visibility for non-owners.
- `/form-actions`: role-scoped notification/inventory-review inbox with acknowledgment, resolution, and links back to the source job.

## Migration

Revision `20260729_0029` creates:

- `work_order_form_templates`
- `work_order_form_fields`
- the template link, template version, form version, schema snapshot, and value snapshot on `work_orders`

Revision `20260729_0030` creates `work_order_form_actions` with trigger uniqueness, status/type/version constraints, actor attribution, resolution evidence, and organization/status/type indexes. Downgrade is blocked while action evidence exists so acknowledged or resolved workflow history cannot be silently discarded.

Apply with:

```text
alembic upgrade head
```
