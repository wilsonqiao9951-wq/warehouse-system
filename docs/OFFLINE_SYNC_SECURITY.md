# Offline sync security and operations

OpenPartsFlow treats offline storage as delayed, authenticated work rather than as permission to bypass the server. Every replay repeats the same server authorization and validation as an online request.

## Read-only snapshots

Successful reviewed GET responses are retained in a separate IndexedDB store so an engineer can reopen previously viewed work while disconnected. Snapshots are keyed by the exact request path plus the authenticated user account and registered device. A different account or device cannot list or read them.

Reviewed snapshots cover:

- current user identity needed to restore the offline shell
- work-order pools and exact work-order records
- configured forms, completion policy, service context/intelligence, recommendations, and form-action progress
- job-status, QC-picture, return-equipment, voice-note metadata, and work-order part records
- part and warehouse reference lists
- the engineer's vehicle stock, replenishment status, vehicle-return status, and approved return destinations

Profit, administration, imports, integration configuration, and arbitrary GET endpoints are not in the offline read allowlist. API responses are not stored in the Service Worker cache; the account/device-scoped IndexedDB store is used instead.

Each snapshot is limited to 1.5 MB. The store retains at most 120 responses and 12 MB per account/device, pruning the oldest snapshots only when a newer successful online response needs space. `/sync-center` shows paths, sizes, and timestamps without expanding the retained payload. The offline banner displays the timestamp whenever retained data is used.

If the browser still reports online while the API is unreachable, reviewed reads fall back to the same snapshots. This includes direct fetch failures and 502/503/504 responses returned by a gateway or the Service Worker after an upstream failure. Eligible queued writes use the same upstream-unavailable classification, while every non-allowlisted mutation still fails closed. A network failure does not erase the local login state. A real non-gateway API response clears the retained-data warning and refreshes the snapshot.

Snapshots never authorize writes. Buttons for claiming, status, completion, inventory, approval, or configuration still execute the live-only request path and fail closed while disconnected.

## Reviewed write allowlist

Only these JSON mutations can enter the browser queue:

| Operation | Method and path | Why it is allowed |
| --- | --- | --- |
| Configured work-order form | `PATCH /api/work-orders/{id}/form` | Versioned evidence; server validates immutable schema, owner device, claim generation, frozen state, and conflicts |
| QC picture record | `POST /api/qc-pictures` | Field evidence; server validates owner device, claim generation, and work-order state |
| Return-equipment record | `POST /api/return-equipments` | Field evidence only; it does not post inventory custody |

Every other mutation requires a live connection. This includes claim/release, start/pause/status, completion/approval, part usage, replenishment, transfer/receipt, vehicle returns, inventory counts, imports, configuration, integrations, users, and conflict decisions.

The allowlist is intentional. New API mutations remain online-only until their replay, idempotency, ownership, and conflict semantics are explicitly reviewed. Queue records created by older clients outside the current allowlist are retained as blocked evidence and are never replayed automatically.

## Account, phone, and work-order binding

Every queued record contains the originating user id, registered device id, work-order id, and exact claim generation. Queue listing filters by the currently authenticated account and device. Before replay, the client reads every queued work order directly and compares its current claim generation.

A released, reassigned, or reclaimed job blocks the retained operation. The local copy is not silently deleted. Normal server bearer, device-secret, `X-Claim-Version`, tenant, ownership, frozen-evidence, optimistic-version, type, and payload-size checks still run during replay.

## Offline photo storage

Configured-form and QC photos can be retained in IndexedDB when the browser is offline or a real upload fails while the browser still reports that it is online.

Each photo is bound to:

- originating user account
- registered device
- work order
- claim generation
- purpose (`configured_form_photo` or `qc_photo`)

Limits are 10 MiB per image, 12 retained images, and 50 MiB per account/device. Only image files are accepted into the device store. Server upload still checks the actual file signature and configured server size limit.

The JSON queue contains an opaque local marker, never inline photo bytes. On replay the client:

1. refreshes the exact work-order claim generation;
2. reads the photo only from the matching account/device/work-order/claim context;
3. confirms that the photo purpose matches the queued operation;
4. uploads through the protected work-order photo endpoint;
5. durably replaces the local marker with the returned server URL in the queue;
6. removes the now-recoverable device blob;
7. submits the normal form or QC operation.

If upload or submission fails, the operation remains retained. Unattached photos are visible in `/sync-center` and can be explicitly discarded. Photos referenced by a queued operation cannot be discarded separately.

Part-usage photos remain online-only because part usage changes the inventory ledger. Voice-note binary caching is not enabled in this batch.

## Conflict handling

A stale configured-form version is registered as a durable server conflict. The phone keeps its local queue record and receives only a conflict receipt. Only an administrator can view both snapshots and keep the server version, apply the offline copy, or merge fields in `/sync-conflicts`.

After resolution, only the originating account and device can poll the receipt and clear its local record. See `CONFIGURABLE_WORK_ORDER_FORMS.md` for conflict APIs and resolution rules.

## Operator checks

- Apply migrations with `alembic upgrade head`.
- Confirm the PWA service worker cache is `openpartsflow-static-v3`.
- Open the job pool, one job detail, configured form, recommendations, and vehicle inventory online before testing offline views.
- Test once with browser offline mode and once by stopping the API while the browser still reports online.
- Verify `/sync-center` shows claim version, operation state, attempts, retained photos, read-snapshot timestamps, and conflicts without submitted values.
- Verify part usage and every inventory custody action return the live-connection requirement while offline.
- Resolve a form conflict in `/sync-conflicts`, reconnect the originating phone, and confirm its local record clears.
