import {
  EngineerDashboard,
  JobStatus,
  LowStockAlert,
  LocationStockBalance,
  Organization,
  PilotChecklist,
  Part,
  QCPicture,
  ReturnEquipment,
  StockBalance,
  StorageLocation,
  InventoryScanResult,
  InventoryNotification,
  ReplenishmentRequest,
  VehicleReturnRequest,
  User,
  Warehouse,
  WorkOrder,
  WorkOrderPart,
  AbnormalUsageRow,
  AuthToken,
  ImportBatch,
  InvitationCreated,
  InvitationInfo,
  WorkOrderProfit
  ,WorkOrderPartRecommendation, WorkOrderVoiceNote, WorkOrderServiceContext, CompletionPolicy
} from "@/types";
import { ensureDeviceCredentials, getCurrentDeviceId, getCurrentDeviceToken } from "@/lib/device";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";
const OFFLINE_QUEUE_KEY = "opf_offline_queue";
const CLAIM_VERSIONS_KEY = "opf_claim_versions";

interface OfflineQueueItem {
  path: string;
  method: string;
  body: string;
  queuedAt: string;
  userId: string;
  deviceId: string;
  workOrderId?: number;
  claimVersion?: number;
  blockedReason?: string;
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

function isOnlineOnlyMutation(path: string, method: string): boolean {
  if (method === "GET") return false;
  if (path.startsWith("/auth/") || path.startsWith("/platform/")) return true;
  if (path === "/inventory/replenishment-requests" || path.startsWith("/inventory/replenishment-requests/")) return true;
  if (path === "/inventory/vehicle-returns" || path.startsWith("/inventory/vehicle-returns/")) return true;
  if (/^\/inventory\/notifications\/\d+\/create-request(?:\?|$)/.test(path)) return true;
  if (/^\/work-orders\/\d+\/(claim|release|start|pause|complete|request-completion|approve-completion|reject-completion)$/.test(path)) return true;
  return path === "/job-status";
}

function readOfflineQueue(): OfflineQueueItem[] {
  return readJsonStorage<OfflineQueueItem[]>(OFFLINE_QUEUE_KEY, []);
}

function writeOfflineQueue(queue: OfflineQueueItem[]): void {
  if (typeof window === "undefined") return;
  if (queue.length) window.localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue));
  else window.localStorage.removeItem(OFFLINE_QUEUE_KEY);
  window.dispatchEvent(new Event("opf-offline-queued"));
}

export function clearOfflineSession(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(OFFLINE_QUEUE_KEY);
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method || "GET").toUpperCase();
  const workOrderId = workOrderIdForRequest(path, init);
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    const bodyContainsPassword = typeof init?.body === "string" && /password/i.test(init.body);
    if (isOnlineOnlyMutation(path, method) || bodyContainsPassword) {
      throw new Error("This verified action requires a network connection.");
    }
    if (method !== "GET" && typeof window !== "undefined" && typeof init?.body === "string") {
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
      queue.push({
        path,
        method,
        body: init.body,
        queuedAt: new Date().toISOString(),
        userId,
        deviceId,
        workOrderId,
        claimVersion
      });
      writeOfflineQueue(queue);
      return { queued: true } as T;
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
    throw new Error(
      msg.includes("Failed to fetch") || msg.includes("NetworkError")
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
    throw new Error(detail);
  }
  const payload = (await res.json()) as T;
  rememberClaimVersionsFromPayload(payload);
  return payload;
}

export async function syncOfflineQueue(): Promise<number> {
  if (typeof window === "undefined" || !navigator.onLine) return 0;
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  if (!userId || !deviceId) return 0;
  const queue = readOfflineQueue();
  if (!queue.length) return 0;
  const currentQueue = queue.filter((row) => row.userId === userId && row.deviceId === deviceId);
  if (currentQueue.some((row) => row.workOrderId !== undefined)) {
    try {
      await request<WorkOrder[]>("/work-orders?scope=all&limit=100");
    } catch {
      return 0;
    }
  }
  let remaining = [...queue];
  let synced = 0;
  for (const item of currentQueue) {
    if (item.workOrderId !== undefined) {
      const currentVersion = readClaimVersions()[String(item.workOrderId)];
      if (!Number.isInteger(item.claimVersion) || currentVersion !== item.claimVersion) break;
    }
    try {
      await request(item.path, {
        method: item.method,
        body: item.body,
        headers: item.claimVersion === undefined ? undefined : { "X-Claim-Version": String(item.claimVersion) }
      });
      remaining = remaining.filter((row) => row !== item);
      synced += 1;
    } catch (error) {
      item.blockedReason = error instanceof Error ? error.message : "Sync failed";
      break;
    }
  }
  writeOfflineQueue(remaining);
  return synced;
}

export function getOfflineQueue(): Array<{ path: string; method: string; queuedAt: string; claimVersion?: number; stale: boolean; blockedReason?: string }> {
  if (typeof window === "undefined") return [];
  const userId = window.localStorage.getItem("opf_user_id");
  const deviceId = getCurrentDeviceId();
  const versions = readClaimVersions();
  return readOfflineQueue()
    .filter((row) => row.userId === userId && row.deviceId === deviceId)
    .map(({ path, method, queuedAt, workOrderId, claimVersion, blockedReason }) => ({
      path,
      method,
      queuedAt,
      claimVersion,
      stale: workOrderId !== undefined && versions[String(workOrderId)] !== claimVersion,
      blockedReason
    }));
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
  createWorkOrder: (payload: Partial<WorkOrder> & { ticket_number: string }) =>
    request<WorkOrder>("/work-orders", { method: "POST", body: JSON.stringify(payload) }),
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
  listWarehouses: () => request<Warehouse[]>("/warehouses?limit=100"),
  getWorkOrderServiceContext: (workOrderId: number, historyLimit = 5) =>
    request<WorkOrderServiceContext>(`/work-orders/${workOrderId}/service-context?history_limit=${historyLimit}`),
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
      action: "start_picking" | "ship" | "receive" | "complete" | "cancel";
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
  uploadPartUsagePhoto: async (workOrderId: number, file: File, onProgress?: (percent: number) => void) => {
    if (onProgress) {
      const result = await xhrUploadPartPhoto(workOrderId, file, onProgress);
      onProgress(100);
      return result;
    }
    const formData = new FormData();
    formData.append("work_order_id", String(workOrderId));
    formData.append("file", file);
    return request<{ url: string }>("/uploads/work-order-parts", {
      method: "POST",
      body: formData
    });
  },
  getWorkOrderProfit: (workOrderId: number) => request<WorkOrderProfit>(`/work-orders/${workOrderId}/profit`),
  getWorkOrderPartRecommendations: (workOrderId: number) => request<WorkOrderPartRecommendation[]>(`/work-orders/${workOrderId}/part-recommendations`),
  getEngineerDashboard: (userId: number) => request<EngineerDashboard>(`/dashboard/engineers/${userId}`),
  listQCPictures: (workOrderId?: number) =>
    request<QCPicture[]>(`/qc-pictures${workOrderId ? `?work_order_id=${workOrderId}` : ""}`),
  createQCPicture: (payload: { work_order_id: number; image_url: string; uploaded_by?: number | null }) =>
    request<QCPicture>("/qc-pictures", { method: "POST", body: JSON.stringify(payload) }),
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
    request<ReturnEquipment>("/return-equipments", { method: "POST", body: JSON.stringify(payload) }),
  startJob: (workOrderId: number) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/start`, { method: "POST", body: JSON.stringify({}) }),
  pauseJob: (workOrderId: number, notes?: string) =>
    request<WorkOrder>(`/work-orders/${workOrderId}/pause`, { method: "POST", body: JSON.stringify({ notes }) }),
  completeJob: (workOrderId: number, payload: {
    repair_result?: string;
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
