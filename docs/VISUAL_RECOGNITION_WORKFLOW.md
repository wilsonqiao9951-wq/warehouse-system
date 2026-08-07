# Controlled AI visual part recognition

Phase 4 now implements the complete photo-to-candidate path while preserving the original human-verification boundary. A photographed part is never written directly to inventory or trusted knowledge.

## Recognition flow

```text
Engineer photo
→ server validates and stores the image in private media storage
→ OpenAI vision reads the label and visual features
→ server matches only current-tenant catalog parts
→ employee confirms one candidate
→ a different administrator confirms it
→ server verifies actual work-order use
→ administrator promotes verified knowledge
```

The Responses API receives the image as a base64 `input_image`. The request uses strict Structured Outputs and `detail: original`, which OpenAI recommends for OCR and other fine-detail image tasks. See the official [images and vision guide](https://developers.openai.com/api/docs/guides/images-vision) and [Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

## Configuration

Recognition is fail-closed and disabled by default:

```env
VISION_RECOGNITION_ENABLED=true
OPENAI_API_KEY=sk-...
OPENAI_API_BASE_URL=https://api.openai.com
VISION_RECOGNITION_MODEL=gpt-5.6-terra
VISION_RECOGNITION_IMAGE_DETAIL=original
VISION_RECOGNITION_TIMEOUT_SECONDS=45
VISION_RECOGNITION_MAX_OUTPUT_TOKENS=1600
VISION_RECOGNITION_MAX_CATALOG_PARTS=250
VISION_RECOGNITION_STALE_MINUTES=5
```

The API key remains server-side. The base URL is restricted to the official HTTPS API host, redirects are disabled, and model/detail/output/catalog limits are server-owned. Operators should choose an OpenAI project with the required regional and retention controls before enabling customer photos.

New recognition photos use private random storage keys. The queue loads them through a tenant-authenticated endpoint; direct public static-file URLs are not issued.

Every request sets `store: false`. This avoids creating a stored Responses object, but it is not a claim of Zero Data Retention: abuse-monitoring and prompt-cache behavior depends on the OpenAI organization's data-control configuration. Review the official [API data controls](https://developers.openai.com/api/docs/guides/your-data) before production use.

## Provider and model safety

- Employee label text, notes, and image text are explicitly treated as untrusted data, not model instructions.
- Output must pass a strict JSON schema and bounded Pydantic validation.
- The model may select only an ID from the bounded current-tenant catalog; the server verifies the reported part number against that ID.
- Hallucinated or cross-tenant identifiers are discarded.
- Normalized OCR/visual evidence can rank candidates only. It cannot create parts, change knowledge, or write inventory.
- JPEG, PNG, WEBP, and non-animated GIF are accepted for AI analysis. Unsupported stored formats remain available for manual review.

## Durable attempt evidence and idempotency

Revision `20260807_0047` adds an immutable attempt sequence for each observation. Each attempt records:

- tenant, observation, requesting user, and client request ID
- attempt number, provider, model, and prompt version
- status (`pending`, `succeeded`, or `failed`)
- image, canonical request, and normalized output SHA-256 evidence
- safe provider request ID and bounded failure code
- validated structured result and resulting candidate count
- start/update/completion timestamps

Raw provider responses, API keys, authorization headers, and arbitrary provider error bodies are not retained. A repeated client request ID is idempotent and does not consume the AI allowance twice. A failed provider call remains charged because external work was attempted; validation and disabled/misconfigured requests are rejected before charging. Interrupted attempts can be retired after the configured stale window without deleting their evidence.

The portable customer export includes attempt evidence and protected referenced photos because both models participate in the tenant export set. Controlled restore keeps recognition and audit evidence immutable.

## Required candidate state chain

```text
AI candidate
→ Employee confirmed
→ Administrator confirmed
→ Work-order usage verified
→ Trusted knowledge
```

An administrator may reject any non-final candidate with a reason. Every transition uses `expected_version`; stale clients receive `409` without overwriting newer review work. Only one candidate can be actively selected for an observation. AI retry is blocked as soon as any candidate receives human confirmation.

## Identity and work-order ownership

- Administrators, managers, warehouse users, and engineers can create standalone observations.
- A standalone analysis can be run only by its creator or an administrator.
- Work-order-linked upload, analysis, and employee confirmation require the claiming engineer's bearer-authenticated registered device and current claim version, or an administrator.
- Other engineers, managers, and warehouse users can read the organization queue but cannot change another engineer's linked observation.
- Administrator confirmation, usage verification, trusted promotion, and rejection are administrator-only.
- Administrator confirmation must use a different account from the employee confirmation.
- Observations, analyses, candidates, parts, work orders, and knowledge records are tenant-scoped.

## Usage verification and inventory isolation

`verify_usage` succeeds only when the linked work order contains a server-recorded `WorkOrderPart` row for the selected part. Recognition never creates, adjusts, transfers, reserves, or consumes inventory.

Promotion to trusted knowledge updates only `PartMachineAssociation`:

- recognition source becomes `verified_visual`
- confidence becomes at least `0.99`
- the verified photo becomes the association photo
- confirmation count increases

The machine model is required before trusted promotion.

## API

### Provider status

`GET /api/parts/recognition/config`

Returns safe availability, provider, model, and image-detail information. It never exposes secrets.

### Read a protected observation photo

`GET /api/parts/recognition/observations/{observation_id}/image`

Requires an authenticated user in the same tenant. Responses use private caching, MIME sniffing protection, and a sandbox content policy. This preserves organization-wide visibility without making customer photos public.

### Store a photo and initial context candidates

`POST /api/parts/recognition/candidates`

Multipart fields:

- `file` — required validated image
- `machine_model` — optional
- `label_text` — optional employee transcription
- `work_order_id` — optional owner-controlled work-order context
- `notes` — optional field context

A photo without textual context is valid because AI can analyze the image in the next operation. If AI is disabled, supplied context still drives the original deterministic tenant-catalog ranking.

### Analyze or retry a stored photo

`POST /api/parts/recognition/observations/{observation_id}/analyze`

```json
{
  "client_request_id": "web-photo-3f399c7e-4a9d-4e61-9eb8-2678951e14da",
  "expected_analysis_version": 0
}
```

The mobile workspace calls this automatically after upload when the provider is available and exposes a retry action after safe failures.

### Review queue

`GET /api/parts/recognition/candidates`

Optional `status` values are `ai_candidate`, `employee_confirmed`, `admin_confirmed`, `usage_verified`, `trusted`, and `rejected`. Responses include analysis evidence, nested part details, and server-calculated action capabilities.

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

Supported actions are `employee_confirm`, `admin_confirm`, `verify_usage`, `promote_trusted`, and `reject`.
