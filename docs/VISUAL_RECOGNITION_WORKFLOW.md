# Controlled visual part recognition

Phase 4 starts with a safe candidate and verification contract. A photographed part is never written directly to inventory or trusted knowledge.

## Current candidate signals

The first implementation retains the image and ranks existing tenant parts using:

- part numbers and barcodes found in employee-entered visible label text
- part-name overlap with visible label text
- catalog machine compatibility
- employee-confirmed photo memory for the same machine
- completed-work-order part recommendations when a work order is linked

This batch does not claim that a computer-vision model or OCR provider has classified the image bytes. It establishes the storage, ranking, review, audit, and trust boundaries that later OCR/CV providers must use.

## Required state chain

```text
AI candidate
→ Employee confirmed
→ Administrator confirmed
→ Work-order usage verified
→ Trusted knowledge
```

An administrator may reject any non-final candidate with a reason. Every transition uses `expected_version`; stale clients receive `409` without overwriting newer review work.

Only one candidate can be actively selected for an observation. If an administrator rejects that selection, another still-pending candidate can be selected.

## Identity and work-order ownership

- Administrators, managers, warehouse users, and engineers can create standalone observations.
- Evidence linked to a work order can be created or employee-confirmed only by the claiming engineer on the bound device and matching claim version, or by an administrator.
- Other engineers, managers, and warehouse users can read the organization queue but cannot attach or confirm evidence on another engineer's work order.
- Administrator confirmation, usage verification, trusted promotion, and rejection are administrator-only.
- Administrator confirmation must use a different account from the employee confirmation.
- All observations, candidates, parts, work orders, and knowledge records are tenant-scoped.

## Usage verification and inventory isolation

`verify_usage` succeeds only when the linked work order contains a server-recorded `WorkOrderPart` row for the selected part. The recognition workflow itself never creates, adjusts, transfers, reserves, or consumes inventory.

Promotion to trusted knowledge updates only `PartMachineAssociation`:

- recognition source becomes `verified_visual`
- confidence becomes at least `0.99`
- the verified photo becomes the association photo
- confirmation count increases

The machine model is required before trusted promotion.

## API

### Create candidates

`POST /api/parts/recognition/candidates`

Multipart fields:

- `file` — required validated image
- `machine_model` — optional when work-order context supplies it
- `label_text` — optional visible label transcription
- `work_order_id` — optional owner-controlled work-order context
- `notes` — optional field context

At least one of machine model, visible label text, or work-order context is required.

### Review queue

`GET /api/parts/recognition/candidates`

Optional query:

- `status=ai_candidate|employee_confirmed|admin_confirmed|usage_verified|trusted|rejected`

Responses include nested part details and server-calculated action capabilities.

### Transition a candidate

`POST /api/parts/recognition/candidates/{candidate_id}/actions`

```json
{
  "action": "employee_confirm",
  "expected_version": 0,
  "work_order_id": 123,
  "reason": null
}
```

Supported actions:

- `employee_confirm`
- `admin_confirm`
- `verify_usage`
- `promote_trusted`
- `reject`
