import {
  EngineerDashboard,
  ExternalIntegration,
  ExternalIntegrationProvider,
  ExternalIntegrationSecret,
  ExternalSyncLog,
  JobStatus,
  LowStockAlert,
  LocationStockBalance,
  MachineKnowledgeDraftGeneration,
  MachineKnowledgeEntry,
  MachineKnowledgeEntryType,
  MachineKnowledgePartRole,
  MachineKnowledgeProfile,
  Organization,
  PilotChecklist,
  Part,
  PartRecognitionCandidate,
  PartRecognitionObservation,
  QCPicture,
  ReturnEquipment,
  StockBalance,
  StorageLocation,
  InventoryScanResult,
  InventoryLocationScan,
  InventoryLocationLabel,
  InventoryNotification,
  ReplenishmentRequest,
  VehicleReturnRequest,
  InventoryCount,
  User,
  Warehouse,
  WorkOrder,
  WorkOrderPart,
  AbnormalUsageRow,
  AuthToken,
  ImportBatch,
  InvitationCreated,
  InvitationInfo,
  WorkOrderProfit,
  WorkOrderPartRecommendation,
  WorkOrderVoiceNote,
  WorkOrderServiceContext,
  WorkOrderServiceIntelligence,
  CompletionPolicy,
  WorkOrderForm,
  WorkOrderFormAction,
  WorkOrderFormConflict,
  WorkOrderFormConflictReceipt,
  WorkOrderFormConflictStatus,
  WorkOrderFormField,
  WorkOrderFormTemplate,
  WorkOrderFormValue,
  OfflineQueuedResult
} from "@/types";
import { ensureDeviceCredentials, getCurrentDeviceId, getCurrentDeviceToken } from "@/lib/device";
import {
  deleteOfflineImage,
  isOfflineMediaMarker,
  listOfflineImages,
  OfflineMediaSummary,
  OfflineMediaPurpose,
  queueOfflineImage,
  readOfflineImage
} from "@/lib/offline-media";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";
const OFFLINE_QUEUE_KEY = "opf_offline_queue";
const CLAIM_VERSIONS_KEY = "opf_claim_versions";

interface OfflineQueueItem {
  id: string;
  path: string;
  method: string;
  body: string;
  queuedAt: string;
  updatedAt: string;
  userId: string;
  deviceId: string;
  workOrderId?: number;
  claimVersion?: number;
  operationType: "work_order_form" | "work_order_evidence" | "other";
  syncState: "pending" | "failed" | "conflict" | "blocked";
  attemptCount: number;
  lastAttemptAt?: string;
  blockedReason?: string;
  serverConflictId?: number;
}

class ApiRequestError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
  }
}

function queueId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `offline-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function operationTypeForPath(path: string): OfflineQueueItem["operationType"] {
  if (/^\/work-orders\/\d+\/form(?:\?|$)/.test(path)) return "work_order_form";
  if (/^\/(qc-pictures|return-equipments)(?:\?|$)/.test(path)) return "work_order_evidence";
  return "other";
}

function readJsonStorage<T>(key: string, fallback: T): T {
  if (typeof window === "undefined") return fallback;
  try {
    return JSON.parse(window.localStorage.getItem(key) || "") as T;
  } catch {
    return fallback;
  }
}

function readClaimVersions(): Record<string, number> {
  return readJsonStorage<Record<string, number>>(CLAIM_VERSIONS_KEY, {});
}

function rememberWorkOrderClaimVersion(workOrder: Pick<WorkOrder, "id" | "claim_version">): void {
  if (typeof window === "undefined" || !Number.isInteger(workOrder.id) || !Number.isInteger(workOrder.claim_version)) return;
  const versions = readClaimVersions();
  versions[String(workOrder.id)] = workOrder.claim_version;
  window.localStorage.setItem(CLAIM_VERSIONS_KEY, JSON.stringify(versions));
}

function rememberClaimVersionsFromPayload(payload: unknown): void {
  const rows = Array.isArray(payload) ? payload : [payload];
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const candidate = row as { id?: unknown; claim_version?: unknown };
    if (typeof candidate.id === "number" && typeof candidate.claim_version === "number") {
      rememberWorkOrderClaimVersion(candidate as Pick<WorkOrder, "id" | "claim_version">);
    }
  }
}

function workOrderIdForRequest(path: string, init?: RequestInit): number | undefined {
  const pathMatch = path.match(/^\/work-orders\/(\d+)(?:\/|$)/);
  if (pathMatch) return Number(pathMatch[1]);
  if (init?.body instanceof FormData) {
    const value = init.body.get("work_order_id");
    return value ? Number(value) || undefined : undefined;
  }
  if (typeof init?.body !== "string") return undefined;
  try {
    const payload = JSON.parse(init.body) as { work_order_id?: unknown };
    return typeof payload.work_order_id === "number" ? payload.work_order_id : undefined;
  } catch {
    return undefined;
  }
}

function isOfflineQueueableMutation(path: string, method: string): boolean {
  if (method === "PATCH" && /^\/work-orders\/\d+\/form(?:\?|$)/.test(path)) {
    return true;
  }
  return (
    method === "POST"
    && (
      /^\/qc-pictures(?:\?|$)/.test(path)
      || /^\/return-equipments(?:\?|$)/.test(path)
    )
  );
}

function readOfflineQueue(): OfflineQueueItem[] {
  const raw = readJsonStorage<OfflineQueueItem[]>(OFFLINE_QUEUE_KEY, []);
  let migrated = false;
  const normalized = raw.map((item) => {
    const unsafeLegacyMutation = !isOfflineQueueableMutation(
      item.path,
      (item.method || "GET").toUpperCase()
    );
    if (
      !item.id
      || !item.updatedAt
      || !item.operationType
      || !item.syncState
      || item.attemptCount === undefined
      || (unsafeLegacyMutation && item.syncState !== "blocked")
    ) {
      migrated = true;
    }
    return {
      ...item,
      id: item.id || queueId(),
      updatedAt: item.updatedAt || item.queuedAt,
      operationType: item.operationType || operationTypeForPath(item.path),
      syncState: unsafeLegacyMutation
        ? "blocked" as const
        : item.syncState || (item.blockedReason ? "failed" : "pending"),
      attemptCount: item.attemptCount || 0,
      blockedReason: unsafeLegacyMutation
        ? "Legacy operation is outside the reviewed offline-write allowlist and will not be replayed."
        : item.blockedReason
    };
  });
  if (migrated && typeof window !== "undefined") {
    window.localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(normalized));
  }
  return normalized;
}

function writeOfflineQueue(queue: OfflineQueueItem[]): void {
  if (typeof window === "undefined") return;
  if (queue.length) window.localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
  else window.localStorage.removeItem(OFFLINE_QUEUE_KEY);
  window.dispatchEvent(new Event("opf-offline-queued"));
}

function queueOfflineMutation<T>(
  path: string,
  method: string,
  body: string,
  workOrderId?: number
): T {
  if (typeof window === "undefined") {
    throw new Error("Offline storage is not available.");
  }
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  if (!userId || !deviceId) {
    throw new Error("Sign in on this registered device before saving offline work.");
  }
  const claimVersion = workOrderId === undefined ? undefined : readClaimVersions()[String(workOrderId)];
  if (workOrderId !== undefined && !Number.isInteger(claimVersion)) {
    throw new Error("Open and claim this work order online before saving offline work.");
  }
  const queue = readOfflineQueue();
  const now = new Date().toISOString();
  const operationType = operationTypeForPath(path);
  let queuedItem: OfflineQueueItem | undefined;
  if (operationType === "work_order_form") {
    queuedItem = queue.find((item) => (
      item.path === path
      && item.method === method
      && item.userId === userId
      && item.deviceId === deviceId
      && item.claimVersion === claimVersion
      && item.syncState !== "conflict"
      && item.syncState !== "blocked"
    ));
    if (queuedItem) {
      try {
        const existing = JSON.parse(queuedItem.body) as {
          expected_version: number;
          values: Record<string, WorkOrderFormValue>;
        };
        const incoming = JSON.parse(body) as {
          expected_version: number;
          values: Record<string, WorkOrderFormValue>;
        };
        if (existing.expected_version === incoming.expected_version) {
          queuedItem.body = JSON.stringify({
            expected_version: existing.expected_version,
            values: { ...existing.values, ...incoming.values }
          });
          queuedItem.updatedAt = now;
          queuedItem.syncState = "pending";
          queuedItem.blockedReason = undefined;
        } else {
          queuedItem = undefined;
        }
      } catch {
        queuedItem = undefined;
      }
    }
  }
  if (!queuedItem) {
    queuedItem = {
      id: queueId(),
      path,
      method,
      body,
      queuedAt: now,
      updatedAt: now,
      userId,
      deviceId,
      workOrderId,
      claimVersion,
      operationType,
      syncState: "pending",
      attemptCount: 0
    };
    queue.push(queuedItem);
  }
  writeOfflineQueue(queue);
  return {
    queued: true,
    queue_id: queuedItem.id,
    queued_at: queuedItem.queuedAt
  } as T;
}

export function clearOfflineSession(): void {
  if (typeof window === "undefined") return;
  // Retain unsynchronized work across sign-out. Queue reads and replays remain
  // isolated by the original user id and registered device id.
  window.localStorage.removeItem(CLAIM_VERSIONS_KEY);
  window.dispatchEvent(new Event("opf-offline-queued"));
}

/** Origin for resolving relative upload paths (e.g. `/uploads/...`) to absolute URLs on phones. */
export function getApiPublicOrigin(): string {
  const trimmed = API_BASE.replace(/\/+$/, "");
  const withoutApi = trimmed.replace(/\/api$/i, "");
  return withoutApi || "http://127.0.0.1:8000";
}

export function resolveUploadedImageUrl(relativeOrAbsolute: string): string {
  const s = relativeOrAbsolute.trim();
  if (s.startsWith("http://") || s.startsWith("https://")) return s;
  const path = s.startsWith("/") ? s : `/${s}`;
  return `${getApiPublicOrigin()}${path}`;
}

async function xhrUploadPartPhoto(
  workOrderId: number,
  file: File,
  onProgress: (pct: number) => void
): Promise<{ url: string }> {
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    throw new Error("You are offline. Connect to the network and try again.");
  }
  const token = typeof window !== "undefined" ? window.localStorage.getItem("opf_access_token") : null;
  const headers: Record<string, string> = {};
  if (token) {
    headers.Authorization = `Bearer ${token}`;
    const deviceToken = getCurrentDeviceToken();
    if (deviceToken) headers["X-Device-Token"] = deviceToken;
    const claimVersion = readClaimVersions()[String(workOrderId)];
    if (Number.isInteger(claimVersion)) headers["X-Claim-Version"] = String(claimVersion);
  }

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/uploads/work-order-parts`);
    Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (ev) => {
      if (ev.lengthComputable) {
        onProgress(Math.round((ev.loaded / ev.total) * 100));
      } else {
        onProgress(0);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const body = JSON.parse(xhr.responseText) as { url?: string };
          if (!body?.url) reject(new Error("Upload succeeded but response had no url."));
          else resolve({ url: body.url });
        } catch {
          reject(new Error("Invalid upload response."));
        }
      } else {
        let detail = `Upload failed (${xhr.status})`;
        try {
          const body = JSON.parse(xhr.responseText) as { detail?: string | string[] };
          if (body?.detail) detail = Array.isArray(body.detail) ? body.detail.join(", ") : body.detail;
        } catch {
          // ignore
        }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error("Network unavailable during upload."));
    xhr.onabort = () => reject(new Error("Upload cancelled."));
    const fd = new FormData();
    fd.append("work_order_id", String(workOrderId));
    fd.append("file", file);
    xhr.send(fd);
  });
}

async function request<T>(path: string, init?: RequestInit, allowNetworkFailureQueue = true): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const workOrderId = workOrderIdForRequest(path, init);
  const bodyContainsPassword = typeof init?.body === "string" && /password/i.test(init.body);
  const canQueueMutation = (
    method !== "GET"
    && typeof init?.body === "string"
    && isOfflineQueueableMutation(path, method)
    && !bodyContainsPassword
  );
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    if (!isOfflineQueueableMutation(path, method) || bodyContainsPassword) {
      throw new Error("This verified action requires a network connection.");
    }
    if (canQueueMutation) {
      return queueOfflineMutation<T>(path, method, init.body as string, workOrderId);
    }
    throw new Error("You are offline. This action will be available when connection returns.");
  }
  const isFormData = init?.body instanceof FormData;
  let authHeaders: Record<string, string> = {};
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("opf_access_token");
    if (token) {
      authHeaders = { Authorization: `Bearer ${token}` };
      const deviceToken = getCurrentDeviceToken();
      if (deviceToken) authHeaders["X-Device-Token"] = deviceToken;
      if (method !== "GET" && workOrderId !== undefined) {
        const claimVersion = readClaimVersions()[String(workOrderId)];
        if (Number.isInteger(claimVersion)) authHeaders["X-Claim-Version"] = String(claimVersion);
      }
    }
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: {
        ...(isFormData ? {} : { "Content-Type": "application/json" }),
        ...authHeaders,
        ...(init?.headers || {})
      },
      cache: "no-store"
    });
  } catch (e) {
    const msg = e instanceof Error ? e.message : "Network error";
    if (
      allowNetworkFailureQueue
      && canQueueMutation
      && (msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed"))
    ) {
      return queueOfflineMutation<T>(path, method, init?.body as string, workOrderId);
    }
    throw new Error(
      msg.includes("Failed to fetch") || msg.includes("NetworkError") || msg.includes("Load failed")
        ? "Network unavailable. Check VPN or server URL (NEXT_PUBLIC_API_BASE_URL)."
        : msg
    );
  }
  if (!res.ok) {
    let detail = `API error ${res.status}`;
    try {
      const payload = (await res.json()) as { detail?: string | string[] | { message?: string; missing?: string[] } };
      if (payload?.detail) {
        if (Array.isArray(payload.detail)) detail = payload.detail.join(", ");
        else if (typeof payload.detail === "string") detail = payload.detail;
        else detail = `${payload.detail.message || "Request failed"}${payload.detail.missing?.length ? `: ${payload.detail.missing.join(", ")}` : ""}`;
      }
    } catch {
      // ignore parse failure
    }
    throw new ApiRequestError(detail, res.status);
  }
  const payload = (await res.json()) as T;
  rememberClaimVersionsFromPayload(payload);
  return payload;
}

async function uploadOfflineMediaForQueueItem(
  item: OfflineQueueItem,
  userId: string,
  deviceId: string,
  persistQueue: () => void
): Promise<void> {
  if (!item.body.includes("opf-offline-media://")) return;
  if (item.workOrderId === undefined || item.claimVersion === undefined) {
    throw new Error("Offline photo is missing its work-order claim context.");
  }
  let payload: unknown;
  try {
    payload = JSON.parse(item.body);
  } catch {
    throw new Error("Offline photo operation contains invalid queued data.");
  }
  const uploaded = new Map<string, string>();
  const consumedMarkers: string[] = [];
  const replaceMarkers = async (value: unknown): Promise<unknown> => {
    if (isOfflineMediaMarker(value)) {
      const existingUrl = uploaded.get(value);
      if (existingUrl) return existingUrl;
      const media = await readOfflineImage(value, {
        userId,
        deviceId,
        workOrderId: item.workOrderId as number,
        claimVersion: item.claimVersion as number
      });
      const expectedPurpose: OfflineMediaPurpose = item.operationType === "work_order_form"
        ? "configured_form_photo"
        : "qc_photo";
      if (media.purpose !== expectedPurpose) {
        throw new Error("Offline photo purpose does not match the queued operation.");
      }
      const formData = new FormData();
      formData.append("work_order_id", String(item.workOrderId));
      formData.append("file", media.blob, media.fileName);
      const result = await request<{ url: string }>(
        "/uploads/work-order-parts",
        { method: "POST", body: formData },
        false
      );
      uploaded.set(value, result.url);
      consumedMarkers.push(value);
      return result.url;
    }
    if (Array.isArray(value)) {
      return Promise.all(value.map((entry) => replaceMarkers(entry)));
    }
    if (value && typeof value === "object") {
      const replaced: Record<string, unknown> = {};
      for (const [key, entry] of Object.entries(value)) {
        replaced[key] = await replaceMarkers(entry);
      }
      return replaced;
    }
    return value;
  };
  payload = await replaceMarkers(payload);
  item.body = JSON.stringify(payload);
  item.updatedAt = new Date().toISOString();
  // Persist server URLs before deleting device blobs so a tab or device crash
  // cannot leave a queue marker pointing at media that no longer exists.
  persistQueue();
  for (const marker of consumedMarkers) {
    await deleteOfflineImage(marker, {
      userId,
      deviceId,
      workOrderId: item.workOrderId,
      claimVersion: item.claimVersion
    });
  }
}

export async function syncOfflineQueue(): Promise<number> {
  if (typeof window === "undefined" || !navigator.onLine) return 0;
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  if (!userId || !deviceId) return 0;
  const queue = readOfflineQueue();
  if (!queue.length) return 0;
  const currentQueue = queue.filter((row) => row.userId === userId && row.deviceId === deviceId);
  const queuedWorkOrderIds = Array.from(new Set(
    currentQueue
      .map((row) => row.workOrderId)
      .filter((id): id is number => id !== undefined)
  ));
  if (queuedWorkOrderIds.length) {
    try {
      for (const workOrderId of queuedWorkOrderIds) {
        await request<WorkOrder>(`/work-orders/${workOrderId}`);
      }
    } catch {
      return 0;
    }
  }
  let remaining = [...queue];
  let synced = 0;
  for (const item of currentQueue) {
    if (item.syncState === "conflict") {
      if (item.serverConflictId) {
        try {
          const receipt = await request<WorkOrderFormConflictReceipt>(
            `/work-order-form-conflicts/${item.serverConflictId}/status`,
            undefined,
            false
          );
          if (receipt.status !== "pending") {
            remaining = remaining.filter((row) => row !== item);
            synced += 1;
          }
        } catch (error) {
          item.blockedReason = error instanceof Error
            ? error.message
            : "Could not refresh administrator conflict resolution.";
        }
        continue;
      }
      if (item.operationType !== "work_order_form") {
        item.syncState = "blocked";
        item.blockedReason = "This legacy conflict requires manual review before retry.";
        continue;
      }
      // Upgrade pre-server-conflict queue records by replaying once. A stale
      // version will enter the authenticated registration path below.
      item.syncState = "pending";
      item.blockedReason = undefined;
    }
    if (item.syncState === "blocked") {
      continue;
    }
    if (item.workOrderId !== undefined) {
      const currentVersion = readClaimVersions()[String(item.workOrderId)];
      if (!Number.isInteger(item.claimVersion) || currentVersion !== item.claimVersion) {
        item.syncState = "blocked";
        item.blockedReason = "Work order was released, reclaimed, or moved to a new claim generation.";
        continue;
      }
    }
    try {
      item.attemptCount += 1;
      item.lastAttemptAt = new Date().toISOString();
      await uploadOfflineMediaForQueueItem(
        item,
        userId,
        deviceId,
        () => writeOfflineQueue(remaining)
      );
      await request(item.path, {
        method: item.method,
        body: item.body,
        headers: item.claimVersion === undefined ? undefined : { "X-Claim-Version": String(item.claimVersion) }
      }, false);
      remaining = remaining.filter((row) => row !== item);
      synced += 1;
    } catch (error) {
      item.blockedReason = error instanceof Error ? error.message : "Sync failed";
      if (
        item.operationType === "work_order_form"
        && error instanceof ApiRequestError
        && error.status === 409
        && error.message === "Work-order form version is stale"
        && item.workOrderId !== undefined
        && item.claimVersion !== undefined
      ) {
        try {
          const formPayload = JSON.parse(item.body) as {
            expected_version: number;
            values: Record<string, WorkOrderFormValue>;
          };
          const receipt = await request<WorkOrderFormConflictReceipt>(
            "/work-order-form-conflicts",
            {
              method: "POST",
              body: JSON.stringify({
                work_order_id: item.workOrderId,
                client_queue_id: item.id,
                claim_version: item.claimVersion,
                base_form_version: formPayload.expected_version,
                local_values: formPayload.values
              }),
              headers: { "X-Claim-Version": String(item.claimVersion) }
            },
            false
          );
          item.serverConflictId = receipt.id;
          item.syncState = "conflict";
          item.blockedReason = "Server form changed; administrator resolution is pending.";
          continue;
        } catch (registrationError) {
          item.blockedReason = registrationError instanceof Error
            ? `Conflict retained locally; server registration failed: ${registrationError.message}`
            : "Conflict retained locally; server registration failed.";
          item.syncState = (
            registrationError instanceof ApiRequestError
            && [401, 403, 409, 428].includes(registrationError.status)
          )
            ? "blocked"
            : "failed";
          continue;
        }
      }
      item.syncState = (
        error instanceof ApiRequestError && error.status === 409
          ? "blocked"
          : error instanceof ApiRequestError && [401, 403, 428].includes(error.status)
            ? "blocked"
            : "failed"
      );
    }
  }
  writeOfflineQueue(remaining);
  return synced;
}

export function retryOfflineQueueItem(id: string): void {
  const queue = readOfflineQueue();
  const item = queue.find((row) => row.id === id);
  if (!item) return;
  item.syncState = "pending";
  item.blockedReason = undefined;
  writeOfflineQueue(queue);
}

export function getOfflineQueue(): Array<{
  id: string;
  path: string;
  method: string;
  queuedAt: string;
  updatedAt: string;
  workOrderId?: number;
  claimVersion?: number;
  operationType: OfflineQueueItem["operationType"];
  syncState: OfflineQueueItem["syncState"];
  attemptCount: number;
  lastAttemptAt?: string;
  serverConflictId?: number;
  stale: boolean;
  blockedReason?: string;
}> {
  if (typeof window === "undefined") return [];
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  const versions = readClaimVersions();
  return readOfflineQueue()
    .filter((row) => row.userId === userId && row.deviceId === deviceId)
    .map(({ id, path, method, queuedAt, updatedAt, workOrderId, claimVersion, operationType, syncState, attemptCount, lastAttemptAt, serverConflictId, blockedReason }) => ({
      id,
      path,
      method,
      queuedAt,
      updatedAt,
      workOrderId,
      claimVersion,
      operationType,
      syncState,
      attemptCount,
      lastAttemptAt,
      serverConflictId,
      stale: workOrderId !== undefined && versions[String(workOrderId)] !== claimVersion,
      blockedReason
    }));
}

export async function getOfflineMediaQueue(): Promise<Array<OfflineMediaSummary & { referenced: boolean }>> {
  if (typeof window === "undefined") return [];
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  if (!userId || !deviceId) return [];
  const queue = readOfflineQueue().filter(
    (item) => item.userId === userId && item.deviceId === deviceId
  );
  return (await listOfflineImages(userId, deviceId)).map((media) => ({
    ...media,
    referenced: queue.some((item) => item.body.includes(media.marker))
  }));
}

export async function discardUnreferencedOfflineMedia(
  marker: string,
  workOrderId: number,
  claimVersion: number
): Promise<void> {
  if (typeof window === "undefined") return;
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  if (!userId || !deviceId) {
    throw new Error("Sign in on the originating device before discarding an offline photo.");
  }
  const referenced = readOfflineQueue().some(
    (item) => (
      item.userId === userId
      && item.deviceId === deviceId
      && item.body.includes(marker)
    )
  );
  if (referenced) {
    throw new Error("This photo is attached to a retained operation and cannot be discarded separately.");
  }
  await deleteOfflineImage(marker, {
    userId,
    deviceId,
    workOrderId,
    claimVersion
  });
}

function requestWithOfflineMediaQueue<T>(
  path: string,
  init: RequestInit
): Promise<T | OfflineQueuedResult> {
  const method = (init.method || "POST").toUpperCase();
  if (
    typeof init.body === "string"
    && init.body.includes("opf-offline-media://")
  ) {
    if (!isOfflineQueueableMutation(path, method)) {
      return Promise.reject(new Error("This photo operation is not approved for offline replay."));
    }
    const queued = queueOfflineMutation<OfflineQueuedResult>(
      path,
      method,
      init.body,
      workOrderIdForRequest(path, init)
    );
    if (typeof navigator !== "undefined" && navigator.onLine) {
      void syncOfflineQueue();
    }
    return Promise.resolve(queued);
  }
  return request<T>(path, init);
}

export const api = {
  login: (email: string, password: string) => {
    const device = ensureDeviceCredentials();
    const form = new URLSearchParams({ username: email, password });
    return request<AuthToken>("/auth/login", {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Device-Id": device.deviceId,
        "X-Device-Token": device.deviceToken,
        "X-Device-Name": device.deviceName
      },
      body: form.toString()
    });
  },
  getMe: () => request<User>("/auth/me"),
  createInvitation: (payload: { name: string; email: string; role: string }) =>
    request<InvitationCreated>("/users/invitations", { method: "POST", body: JSON.stringify(payload) }),
  getInvitation: (token: string) =>
    request<InvitationInfo>(`/auth/invitations/${encodeURIComponent(token)}`),
  acceptInvitation: (token: string, password: string) =>
    request<User>("/auth/invitations/accept", {
      method: "POST",
      body: JSON.stringify({ token, password })
    }),
  listOrganizations: () => request<Organization[]>("/platform/organizations"),
  createOrganization: (payload: {
    name: string;
    slug: string;
    admin_name: string;
    admin_email: string;
    admin_password: string;
  }) => request<Organization>("/platform/organizations", { method: "POST", body: JSON.stringify(payload) }),
  updateOrganization: (organizationId: number, isActive: boolean) =>
    request<Organization>(`/platform/organizations/${organizationId}`, {
      method: "PATCH",
      body: JSON.stringify({ is_active: isActive })
    }),
  listIntegrations: () => request<ExternalIntegration[]>("/integrations"),
  createIntegration: (payload: {
    name: string;
    provider: ExternalIntegrationProvider;
    field_mapping: Record<string, string>;
    webhook_url?: string | null;
    subscribed_events?: ExternalIntegration["subscribed_events"];
  }) => request<ExternalIntegrationSecret>("/integrations", {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  updateIntegration: (
    integrationId: number,
    payload: {
      expected_version: number;
      name?: string;
      field_mapping?: Record<string, string>;
      webhook_url?: string | null;
      subscribed_events?: ExternalIntegration["subscribed_events"];
      is_active?: boolean;
    }
  ) => request<ExternalIntegration>(`/integrations/${integrationId}`, {
    method: "PATCH",
    body: JSON.stringify(payload)
  }),
  rotateIntegrationKey: (integrationId: number, expectedVersion: number) =>
    request<ExternalIntegrationSecret>(`/integrations/${integrationId}/rotate-key`, {
      method: "POST",
      body: JSON.stringify({ expected_version: expectedVersion })
    }),
  listIntegrationSyncLogs: (integrationId: number) =>
    request<ExternalSyncLog[]>(`/integrations/${integrationId}/sync-logs?limit=100`),
  retryIntegrationDelivery: (integrationId: number, logId: number) =>
    request<ExternalSyncLog>(`/integrations/${integrationId}/sync-logs/${logId}/retry`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  previewPartsImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportBatch>("/imports/parts/preview", { method: "POST", body: form });
  },
  commitPartsImport: (batchId: number) =>
    request<ImportBatch>(`/imports/parts/${batchId}/commit`, { method: "POST", body: JSON.stringify({}) }),
  listPartsImports: () => request<ImportBatch[]>("/imports/parts?limit=50"),
  previewOpeningInventoryImport: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportBatch>("/imports/opening-inventory/preview", { method: "POST", body: form });
  },
  commitOpeningInventoryImport: (batchId: number) =>
    request<ImportBatch>(`/imports/opening-inventory/${batchId}/commit`, {
      method: "POST",
      body: JSON.stringify({})
    }),
  listOpeningInventoryImports: () => request<ImportBatch[]>("/imports/opening-inventory?limit=50"),
  listWorkOrders: (params?: {
    skip?: number;
    limit?: number;
    scope?: "all" | "mine" | "available";
    technician_id?: number;
    status?: string;
    city?: string;
    job_type?: string;
    q?: string;
    date_from?: string;
    date_to?: string;
  }) => {
    const query = new URLSearchParams();
    if (params?.skip !== undefined) query.set("skip", String(params.skip));
    if (params?.limit !== undefined) query.set("limit", String(params.limit));
    if (params?.scope) query.set("scope", params.scope);
    if (params?.technician_id) query.set("technician_id", String(params.technician_id));
    if (params?.status) query.set("status", params.status);
    if (params?.city) query.set("city", params.city);
    if (params?.job_type) query.set("job_type", params.job_type);
    if (params?.q) query.set("q", params.q);
    if (params?.date_from) query.set("date_from", params.date_from);
    if (params?.date_to) query.set("date_to", params.date_to);
    if (!query.has("limit")) query.set("limit", "100");
    return request<WorkOrder[]>(`/work-orders?${query.toString()}`);
  },
  getWorkOrder: (workOrderId: number) =>
    request<WorkOrder>(`/work-orders/${workOrderId}`),
  createWorkOrder: (payload: Partial<WorkOrder> & { ticket_number: string }) =>
    request<WorkOrder>("/work-orders", { method: "POST", body: JSON.stringify(payload) }),
  listWorkOrderFormTemplates: (includeInactive = false) =>
    request<WorkOrderFormTemplate[]>(
      `/work-order-form-templates${includeInactive ? "?include_inactive=true" : ""}`
    ),
  createWorkOrderFormTemplate: (payload: {
    name: string;
    industry?: string | null;
    description?: string | null;
    applicable_machine_type?: string | null;
    applicable_job_type?: string | null;
    default_work_order_status: "open" | "scheduled";
    fields: WorkOrderFormField[];
  }) =>
    request<WorkOrderFormTemplate>("/work-order-form-templates", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updateWorkOrderFormTemplate: (
    templateId: number,
    payload: {
      expected_version: number;
      name?: string;
      industry?: string | null;
      description?: string | null;
      applicable_machine_type?: string | null;
      applicable_job_type?: string | null;
      default_work_order_status?: "open" | "scheduled";
      is_active?: boolean;
      fields?: WorkOrderFormField[];
    }
  ) =>
    request<WorkOrderFormTemplate>(`/work-order-form-templates/${templateId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  getWorkOrderForm: (workOrderId: number) =>
    request<WorkOrderForm>(`/work-orders/${workOrderId}/form`),
  updateWorkOrderForm: (
    workOrderId: number,
    expectedVersion: number,
    values: Record<string, WorkOrderFormValue>
  ) =>
    requestWithOfflineMediaQueue<WorkOrderForm>(`/work-orders/${workOrderId}/form`, {
      method: "PATCH",
      body: JSON.stringify({ expected_version: expectedVersion, values })
    }),
  listWorkOrderFormConflicts: (params?: {
    status?: WorkOrderFormConflictStatus;
    work_order_id?: number;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.work_order_id) query.set("work_order_id", String(params.work_order_id));
    if (params?.limit) query.set("limit", String(params.limit));
    const suffix = query.toString();
    return request<WorkOrderFormConflict[]>(
      `/work-order-form-conflicts${suffix ? `?${suffix}` : ""}`
    );
  },
  resolveWorkOrderFormConflict: (
    conflictId: number,
    payload: {
      expected_version: number;
      expected_server_form_version: number;
      action: "keep_server" | "apply_local" | "merge";
      values?: Record<string, WorkOrderFormValue>;
      resolution_notes: string;
    }
  ) =>
    request<WorkOrderFormConflict>(`/work-order-form-conflicts/${conflictId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  listWorkOrderFormActions: (params?: {
    status?: "pending" | "acknowledged" | "resolved";
    action_type?: "notification" | "inventory_review";
    work_order_id?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.action_type) query.set("action_type", params.action_type);
    if (params?.work_order_id) query.set("work_order_id", String(params.work_order_id));
    query.set("limit", "200");
    return request<WorkOrderFormAction[]>(`/work-order-form-actions?${query.toString()}`);
  },
  listWorkOrderFormActionProgress: (workOrderId: number) =>
    request<WorkOrderFormAction[]>(`/work-orders/${workOrderId}/form-actions`),
  updateWorkOrderFormAction: (
    taskId: number,
    payload: {
      expected_version: number;
      action: "acknowledge" | "resolve";
      resolution_notes?: string | null;
    }
  ) =>
    request<WorkOrderFormAction>(`/work-order-form-actions/${taskId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  claimWorkOrder: (workOrderId: number) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/claim`, { method: "POST", body: JSON.stringify({}) }),
  releaseWorkOrder: (workOrderId: number, reason: string) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/release`, {
      method: "POST",
      body: JSON.stringify({ reason })
    }),
  updateWorkOrder: (
    workOrderId: number,
    payload: Partial<Pick<WorkOrder, "status" | "revenue" | "engineer_id" | "assigned_user_id" | "labor_cost">>
  ) => request<WorkOrder>(`/work-orders/${workOrderId}`, { method: "PATCH", body: JSON.stringify(payload) }),
  listUsers: () => request<User[]>("/users?limit=100"),
  listEngineers: async () => {
    const users = await request<User[]>("/users?limit=100");
    return users.filter((u) => u.role === "engineer");
  },
  listParts: () => request<Part[]>("/parts?limit=100"),
  createPartRecognitionCandidates: (payload: {
    file: File;
    machineModel?: string;
    labelText?: string;
    workOrderId?: number;
    notes?: string;
  }) => {
    const form = new FormData();
    form.append("file", payload.file);
    if (payload.machineModel) form.append("machine_model", payload.machineModel);
    if (payload.labelText) form.append("label_text", payload.labelText);
    if (payload.workOrderId) form.append("work_order_id", String(payload.workOrderId));
    if (payload.notes) form.append("notes", payload.notes);
    return request<PartRecognitionObservation>("/parts/recognition/candidates", {
      method: "POST",
      body: form
    });
  },
  listPartRecognitionCandidates: (status?: string) =>
    request<PartRecognitionObservation[]>(
      `/parts/recognition/candidates${status ? `?status=${encodeURIComponent(status)}` : ""}`
    ),
  actOnPartRecognitionCandidate: (
    candidate: Pick<PartRecognitionCandidate, "id" | "version">,
    action: "employee_confirm" | "admin_confirm" | "verify_usage" | "promote_trusted" | "reject",
    workOrderId?: number | null,
    reason?: string
  ) => request<PartRecognitionObservation>(
    `/parts/recognition/candidates/${candidate.id}/actions`,
    {
      method: "POST",
      body: JSON.stringify({
        action,
        expected_version: candidate.version,
        work_order_id: workOrderId || undefined,
        reason
      })
    }
  ),
  listMachineKnowledge: (params?: {
    q?: string;
    model?: string;
    includeInactive?: boolean;
  }) => {
    const query = new URLSearchParams();
    if (params?.q) query.set("q", params.q);
    if (params?.model) query.set("model", params.model);
    if (params?.includeInactive) query.set("include_inactive", "true");
    query.set("limit", "100");
    return request<MachineKnowledgeProfile[]>(`/machine-knowledge?${query.toString()}`);
  },
  getMachineKnowledge: (profileId: number) =>
    request<MachineKnowledgeProfile>(`/machine-knowledge/${profileId}`),
  createMachineKnowledge: (payload: {
    model: string;
    manufacturer?: string;
    equipment_type?: string;
    summary?: string;
  }) => request<MachineKnowledgeProfile>("/machine-knowledge", {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  updateMachineKnowledge: (
    profile: Pick<MachineKnowledgeProfile, "id" | "version">,
    payload: {
      model?: string;
      manufacturer?: string | null;
      equipment_type?: string | null;
      summary?: string | null;
      is_active?: boolean;
    }
  ) => request<MachineKnowledgeProfile>(`/machine-knowledge/${profile.id}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_version: profile.version, ...payload })
  }),
  createMachineKnowledgeEntry: (
    profileId: number,
    payload: {
      entry_type: MachineKnowledgeEntryType;
      title: string;
      content: string;
      fault_code?: string;
      related_part_id?: number;
      related_part_role?: MachineKnowledgePartRole;
      alternative_for_part_id?: number;
      installation_location?: string;
      source_work_order_id?: number;
      media_url?: string;
      sort_order?: number;
    }
  ) => request<MachineKnowledgeProfile>(`/machine-knowledge/${profileId}/entries`, {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  updateMachineKnowledgeEntry: (
    entry: Pick<MachineKnowledgeEntry, "id" | "version">,
    payload: {
      entry_type?: MachineKnowledgeEntryType;
      title?: string;
      content?: string;
      fault_code?: string | null;
      related_part_id?: number | null;
      related_part_role?: MachineKnowledgePartRole | null;
      alternative_for_part_id?: number | null;
      installation_location?: string | null;
      source_work_order_id?: number | null;
      media_url?: string | null;
      sort_order?: number;
    }
  ) => request<MachineKnowledgeProfile>(`/machine-knowledge/entries/${entry.id}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_version: entry.version, ...payload })
  }),
  actOnMachineKnowledgeEntry: (
    entry: Pick<MachineKnowledgeEntry, "id" | "version">,
    action: "publish" | "archive" | "reopen"
  ) => request<MachineKnowledgeProfile>(`/machine-knowledge/entries/${entry.id}/actions`, {
    method: "POST",
    body: JSON.stringify({ action, expected_version: entry.version })
  }),
  generateMachineKnowledgeDrafts: (profileId: number, workOrderId: number) =>
    request<MachineKnowledgeDraftGeneration>(
      `/machine-knowledge/${profileId}/drafts/from-work-order`,
      {
        method: "POST",
        body: JSON.stringify({ work_order_id: workOrderId })
      }
    ),
  uploadMachineKnowledgeMedia: (
    profileId: number,
    payload: {
      file: File;
      title: string;
      description: string;
      sourceWorkOrderId?: number;
      sortOrder?: number;
    }
  ) => {
    const form = new FormData();
    form.append("file", payload.file);
    form.append("title", payload.title);
    form.append("description", payload.description);
    if (payload.sourceWorkOrderId) {
      form.append("source_work_order_id", String(payload.sourceWorkOrderId));
    }
    if (payload.sortOrder !== undefined) {
      form.append("sort_order", String(payload.sortOrder));
    }
    return request<MachineKnowledgeProfile>(
      `/machine-knowledge/${profileId}/media`,
      { method: "POST", body: form }
    );
  },
  openMachineKnowledgeMedia: async (entryId: number) => {
    if (typeof window === "undefined") throw new Error("Media preview requires a browser.");
    const preview = window.open("about:blank", "_blank");
    const token = window.localStorage.getItem("opf_access_token");
    try {
      const response = await fetch(`${API_BASE}/machine-knowledge/media/${entryId}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {}
      });
      if (!response.ok) {
        let detail = `Unable to open media (${response.status})`;
        try {
          const body = await response.json() as { detail?: string };
          if (body.detail) detail = body.detail;
        } catch {
          // Keep the status fallback.
        }
        throw new Error(detail);
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      if (preview) preview.location.href = objectUrl;
      else window.location.href = objectUrl;
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 300_000);
    } catch (error) {
      preview?.close();
      throw error;
    }
  },
  listWarehouses: () => request<Warehouse[]>("/warehouses?limit=100"),
  getWorkOrderServiceContext: (workOrderId: number, historyLimit = 5) =>
    request<WorkOrderServiceContext>(`/work-orders/${workOrderId}/service-context?history_limit=${historyLimit}`),
  getWorkOrderServiceIntelligence: (workOrderId: number) =>
    request<WorkOrderServiceIntelligence>(`/work-orders/${workOrderId}/service-intelligence`),
  listCompletionPolicies: () => request<CompletionPolicy[]>("/completion-policies"),
  saveCompletionPolicy: (payload: Omit<CompletionPolicy, "id" | "organization_id" | "source">) =>
    request<CompletionPolicy>("/completion-policies", { method: "POST", body: JSON.stringify(payload) }),
  getCompletionPolicy: (workOrderId: number) =>
    request<CompletionPolicy>(`/work-orders/${workOrderId}/completion-policy`),
  approveCompletion: (workOrderId: number) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/approve-completion`, { method: "POST", body: JSON.stringify({}) }),
  rejectCompletion: (workOrderId: number, notes: string) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/reject-completion`, { method: "POST", body: JSON.stringify({ notes }) }),
  listStorageLocations: (warehouseId?: number) =>
    request<StorageLocation[]>(`/storage-locations${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  scanInventory: (payload: { barcode?: string; part_number?: string; quantity?: number; warehouse_id?: number; location_id?: number }) =>
    request<InventoryScanResult>("/inventory/scan", { method: "POST", body: JSON.stringify(payload) }),
  scanInventoryLocation: (payload: { label: string; expected_warehouse_id?: number }) =>
    request<InventoryLocationScan>("/inventory/location-scan", { method: "POST", body: JSON.stringify(payload) }),
  listInventoryLocationLabels: (warehouseId: number) =>
    request<InventoryLocationLabel[]>(`/inventory/location-labels?warehouse_id=${warehouseId}`),
  listInventoryNotifications: () => request<InventoryNotification[]>("/inventory/notifications"),
  updateInventoryNotification: (id: number, status: string) => request<InventoryNotification>(`/inventory/notifications/${id}?status=${status}`, { method: "PATCH" }),
  createReplenishmentRequest: (id: number, quantity: number, sourceWarehouseId?: number) => request<ReplenishmentRequest>(`/inventory/notifications/${id}/create-request?quantity=${quantity}${sourceWarehouseId ? `&source_warehouse_id=${sourceWarehouseId}` : ""}`, { method: "POST" }),
  createManualReplenishmentRequest: (payload: {
    part_id: number;
    destination_warehouse_id: number;
    quantity: number;
    source_warehouse_id?: number;
    reason: string;
    client_request_id: string;
  }) => request<ReplenishmentRequest>("/inventory/replenishment-requests", {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  listReplenishmentRequests: () => request<ReplenishmentRequest[]>("/inventory/replenishment-requests"),
  actOnReplenishmentRequest: (
    id: number,
    payload: {
      action: "approve" | "reject" | "start_picking" | "ship" | "receive" | "complete" | "cancel";
      expected_version: number;
      source_warehouse_id?: number;
      reason?: string;
      account_password?: string;
    }
  ) => request<ReplenishmentRequest>(`/inventory/replenishment-requests/${id}/actions`, {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  reconcileReplenishmentRequest: (
    id: number,
    payload: {
      expected_version: number;
      resolution: "reset_requested" | "accept_historical";
      reason: string;
      account_password: string;
    }
  ) => request<ReplenishmentRequest>(`/inventory/replenishment-requests/${id}/reconcile`, {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  listVehicleReturnDestinations: () => request<Warehouse[]>("/inventory/vehicle-return-destinations"),
  createVehicleReturnRequest: (payload: {
    part_id: number;
    source_warehouse_id: number;
    destination_warehouse_id: number;
    quantity: number;
    reason: string;
    client_request_id: string;
  }) => request<VehicleReturnRequest>("/inventory/vehicle-returns", {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  listVehicleReturnRequests: () => request<VehicleReturnRequest[]>("/inventory/vehicle-returns"),
  actOnVehicleReturnRequest: (
    id: number,
    payload: {
      action: "approve" | "ship" | "receive" | "cancel";
      expected_version: number;
      reason?: string;
      account_password?: string;
    }
  ) => request<VehicleReturnRequest>(`/inventory/vehicle-returns/${id}/actions`, {
    method: "POST",
    body: JSON.stringify(payload)
  }),
  listInventoryCounts: () => request<InventoryCount[]>("/inventory/counts"),
  createInventoryCount: (payload: {
    client_request_id: string; warehouse_id: number; location_id?: number; title: string; notes?: string;
  }) => request<InventoryCount>("/inventory/counts", { method: "POST", body: JSON.stringify(payload) }),
  recordInventoryCountLine: (id: number, payload: {
    part_id: number; counted_quantity: number; notes?: string; expected_version: number;
  }) => request<InventoryCount>(`/inventory/counts/${id}/lines`, { method: "PUT", body: JSON.stringify(payload) }),
  actOnInventoryCount: (id: number, payload: {
    action: "submit" | "approve" | "cancel"; expected_version: number; reason?: string; password?: string;
  }) => request<InventoryCount>(`/inventory/counts/${id}/actions`, { method: "POST", body: JSON.stringify(payload) }),
  createStorageLocation: (payload: Omit<StorageLocation, "id">) =>
    request<StorageLocation>("/storage-locations", { method: "POST", body: JSON.stringify(payload) }),
  listInventoryBalances: () => request<StockBalance[]>("/inventory/balances?limit=500"),
  listLocationBalances: (warehouseId?: number) =>
    request<LocationStockBalance[]>(`/inventory/location-balances${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  getVanInventory: (userId: number) =>
    request<StockBalance[]>(`/employees/${userId}/van-inventory?limit=500`),
  getMyVanInventory: () => request<StockBalance[]>("/inventory/my-van?limit=500"),
  usePartOnWorkOrder: (
    workOrderId: number,
    payload: {
      work_order_id: number;
      part_id: number;
      warehouse_id: number;
      user_id?: number | null;
      quantity: number;
      unit_cost?: number;
      notes?: string;
    }
  ) =>
    request(`/work-orders/${workOrderId}/use-part`, {
      method: "POST",
      body: JSON.stringify({
        ...payload,
        installed: "yes",
        old_part_returned: "no"
      })
    }),
  uploadPartUsagePhoto: async (
    workOrderId: number,
    file: File,
    onProgress?: (percent: number) => void,
    offlinePurpose?: OfflineMediaPurpose
  ): Promise<{ url: string; queued_offline?: boolean }> => {
    const retainOffline = async () => {
      if (!offlinePurpose || typeof window === "undefined") {
        throw new Error("Photo upload requires a network connection.");
      }
      const userId = window.localStorage.getItem("opf_user_id");
      const deviceId = getCurrentDeviceId();
      const claimVersion = readClaimVersions()[String(workOrderId)];
      if (!userId || !deviceId || !Number.isInteger(claimVersion)) {
        throw new Error("Open and claim this work order online before retaining an offline photo.");
      }
      const marker = await queueOfflineImage(
        file,
        {
          userId,
          deviceId,
          workOrderId,
          claimVersion
        },
        offlinePurpose
      );
      return { url: marker, queued_offline: true };
    };
    if (typeof navigator !== "undefined" && !navigator.onLine) {
      return retainOffline();
    }
    try {
      if (onProgress) {
        const result = await xhrUploadPartPhoto(workOrderId, file, onProgress);
        onProgress(100);
        return result;
      }
      const formData = new FormData();
      formData.append("work_order_id", String(workOrderId));
      formData.append("file", file);
      return await request<{ url: string }>("/uploads/work-order-parts", {
        method: "POST",
        body: formData
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      if (
        offlinePurpose
        && (
          message.includes("Network unavailable")
          || message.includes("Failed to fetch")
          || message.includes("NetworkError")
          || message.includes("Load failed")
        )
      ) {
        return retainOffline();
      }
      throw error;
    }
  },
  getWorkOrderProfit: (workOrderId: number) => request<WorkOrderProfit>(`/work-orders/${workOrderId}/profit`),
  getWorkOrderPartRecommendations: (workOrderId: number) => request<WorkOrderPartRecommendation[]>(`/work-orders/${workOrderId}/part-recommendations`),
  getEngineerDashboard: (userId: number) => request<EngineerDashboard>(`/dashboard/engineers/${userId}`),
  listQCPictures: (workOrderId?: number) =>
    request<QCPicture[]>(`/qc-pictures${workOrderId ? `?work_order_id=${workOrderId}` : ""}`),
  createQCPicture: (payload: { work_order_id: number; image_url: string; uploaded_by?: number | null }) =>
    requestWithOfflineMediaQueue<QCPicture>("/qc-pictures", { method: "POST", body: JSON.stringify(payload) }),
  listVoiceNotes: (workOrderId: number) =>
    request<WorkOrderVoiceNote[]>(`/work-orders/${workOrderId}/voice-notes`),
  uploadVoiceNote: (workOrderId: number, blob: Blob, durationSeconds: number) => {
    const form = new FormData();
    form.append("file", blob, `voice-note.${blob.type.includes("ogg") ? "ogg" : "webm"}`);
    form.append("duration_seconds", String(durationSeconds));
    return request<WorkOrderVoiceNote>(`/work-orders/${workOrderId}/voice-notes`, { method: "POST", body: form });
  },
  listJobStatus: (workOrderId?: number) =>
    request<JobStatus[]>(`/job-status${workOrderId ? `?work_order_id=${workOrderId}` : ""}`),
  createJobStatus: (payload: { work_order_id: number; status: string; timestamp?: string }) =>
    request<JobStatus>("/job-status", { method: "POST", body: JSON.stringify(payload) }),
  listReturnEquipments: (workOrderId?: number) =>
    request<ReturnEquipment[]>(`/return-equipments${workOrderId ? `?work_order_id=${workOrderId}` : ""}`),
  createReturnEquipment: (payload: { work_order_id: number; equipment_type: string; quantity: number }) =>
    request<ReturnEquipment | OfflineQueuedResult>("/return-equipments", { method: "POST", body: JSON.stringify(payload) }),
  startJob: (workOrderId: number) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/start`, { method: "POST", body: JSON.stringify({}) }),
  pauseJob: (workOrderId: number, notes?: string) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/pause`, { method: "POST", body: JSON.stringify({ notes }) }),
  completeJob: (workOrderId: number, payload: {
    repair_result?: string;
    fault_type?: string;
    error_code?: string;
    environment_info?: string;
    final_outcome?: string;
    first_time_fix?: boolean;
    is_rework?: boolean;
    checklist_json?: string;
    customer_signature_name?: string;
    customer_signature_data?: string;
    account_password?: string;
  } = {}) => request<WorkOrder>(`/work-orders/${workOrderId}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  getLowStockAlerts: () => request<LowStockAlert[]>("/inventory/low-stock-alerts?limit=300"),
  getAbnormalUsage: () => request<AbnormalUsageRow[]>("/reports/abnormal-usage?limit=300")
  ,
  getPilotChecklist: () => request<PilotChecklist>("/pilot/checklist"),
  listWorkOrderParts: (params?: { limit?: number; work_order_id?: number }) => {
    const q = new URLSearchParams();
    q.set("limit", String(Math.min(100, Math.max(1, params?.limit ?? 100))));
    if (params?.work_order_id) q.set("work_order_id", String(params.work_order_id));
    return request<WorkOrderPart[]>(`/work-order-parts?${q.toString()}`);
  }
};
