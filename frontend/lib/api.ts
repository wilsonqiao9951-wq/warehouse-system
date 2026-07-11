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

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api";

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
  const userId = typeof window !== "undefined" ? window.localStorage.getItem("opf_user_id") : null;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  else if (userId) headers["X-User-Id"] = userId;

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
  if (typeof navigator !== "undefined" && !navigator.onLine) {
    const method = init?.method || "GET";
    if (method !== "GET" && typeof window !== "undefined" && typeof init?.body === "string") {
      const queue = JSON.parse(window.localStorage.getItem("opf_offline_queue") || "[]") as Array<{ path: string; method: string; body: string; queuedAt: string }>;
      queue.push({ path, method, body: init.body, queuedAt: new Date().toISOString() });
      window.localStorage.setItem("opf_offline_queue", JSON.stringify(queue));
      window.dispatchEvent(new Event("opf-offline-queued"));
      return { queued: true } as T;
    }
    throw new Error("You are offline. This action will be available when connection returns.");
  }
  const isFormData = init?.body instanceof FormData;
  let authHeaders: Record<string, string> = {};
  if (typeof window !== "undefined") {
    const token = window.localStorage.getItem("opf_access_token");
    const userId = window.localStorage.getItem("opf_user_id");
    if (token) {
      authHeaders = { Authorization: `Bearer ${token}` };
    } else if (userId) {
      authHeaders = { "X-User-Id": userId };
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
  return (await res.json()) as T;
}

export async function syncOfflineQueue(): Promise<number> {
  if (typeof window === "undefined" || !navigator.onLine) return 0;
  const queue = JSON.parse(window.localStorage.getItem("opf_offline_queue") || "[]") as Array<{ path: string; method: string; body: string; queuedAt: string }>;
  if (!queue.length) return 0;
  let synced = 0;
  for (const item of queue) {
    try { await request(item.path, { method: item.method, body: item.body }); synced += 1; } catch { break; }
  }
  const remaining = queue.slice(synced);
  if (remaining.length) window.localStorage.setItem("opf_offline_queue", JSON.stringify(remaining));
  else window.localStorage.removeItem("opf_offline_queue");
  return synced;
}

export function getOfflineQueue(): Array<{ path: string; method: string; queuedAt: string }> {
  if (typeof window === "undefined") return [];
  return (JSON.parse(window.localStorage.getItem("opf_offline_queue") || "[]") as Array<{ path: string; method: string; body: string; queuedAt: string }>).map(({ path, method, queuedAt }) => ({ path, method, queuedAt }));
}

export const api = {
  login: (email: string, password: string) => {
    const form = new URLSearchParams({ username: email, password });
    return request<AuthToken>("/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
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
  listReplenishmentRequests: () => request<ReplenishmentRequest[]>("/inventory/replenishment-requests"),
  updateReplenishmentRequest: (id: number, status: string) => request<ReplenishmentRequest>(`/inventory/replenishment-requests/${id}?status=${status}`, { method: "PATCH" }),
  createStorageLocation: (payload: Omit<StorageLocation, "id">) =>
    request<StorageLocation>("/storage-locations", { method: "POST", body: JSON.stringify(payload) }),
  listInventoryBalances: () => request<StockBalance[]>("/inventory/balances?limit=500"),
  listLocationBalances: (warehouseId?: number) =>
    request<LocationStockBalance[]>(`/inventory/location-balances${warehouseId ? `?warehouse_id=${warehouseId}` : ""}`),
  getVanInventory: (userId: number) =>
    request<StockBalance[]>(`/employees/${userId}/van-inventory?limit=500`),
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
  } = {}) => request<WorkOrder>(`/work-orders/${workOrderId}/complete`, { method: "POST", body: JSON.stringify(payload) }),
  getLowStockAlerts: () => request<LowStockAlert[]>("/inventory/low-stock-alerts?limit=300"),
  getAbnormalUsage: () => request<AbnormalUsageRow[]>("/reports/abnormal-usage?limit=300")
  ,
  getPilotChecklist: () => request<PilotChecklist>("/pilot/checklist"),
  listWorkOrderParts: (params?: { limit?: number }) => {
    const q = new URLSearchParams();
    q.set("limit", String(Math.min(100, Math.max(1, params?.limit ?? 100))));
    return request<WorkOrderPart[]>(`/work-order-parts?${q.toString()}`);
  }
};
