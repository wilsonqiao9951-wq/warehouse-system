const DATABASE_NAME = "opf_offline_media";
const DATABASE_VERSION = 1;
const STORE_NAME = "media";
const MARKER_PREFIX = "opf-offline-media://";
const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const MAX_DEVICE_MEDIA_BYTES = 50 * 1024 * 1024;
const MAX_DEVICE_MEDIA_ITEMS = 12;

export type OfflineMediaPurpose = "configured_form_photo" | "qc_photo";

interface OfflineMediaRecord {
  id: string;
  blob: Blob;
  fileName: string;
  mimeType: string;
  byteSize: number;
  userId: string;
  deviceId: string;
  workOrderId: number;
  claimVersion: number;
  purpose: OfflineMediaPurpose;
  createdAt: string;
}

export interface OfflineMediaContext {
  userId: string;
  deviceId: string;
  workOrderId: number;
  claimVersion: number;
}

export interface OfflineMediaSummary {
  marker: string;
  workOrderId: number;
  claimVersion: number;
  purpose: OfflineMediaPurpose;
  byteSize: number;
  createdAt: string;
}

function openDatabase(): Promise<IDBDatabase> {
  if (typeof window === "undefined" || !window.indexedDB) {
    return Promise.reject(new Error("This browser does not support secure offline photo storage."));
  }
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Offline photo storage could not be opened."));
    request.onblocked = () => reject(new Error("Offline photo storage upgrade is blocked by another app window."));
  });
}

async function allRecords(database: IDBDatabase): Promise<OfflineMediaRecord[]> {
  return new Promise((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readonly");
    const request = transaction.objectStore(STORE_NAME).getAll();
    request.onsuccess = () => resolve(request.result as OfflineMediaRecord[]);
    request.onerror = () => reject(new Error("Offline photo records could not be read."));
  });
}

function mediaId(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `media-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function isOfflineMediaMarker(value: unknown): value is string {
  return typeof value === "string" && value.startsWith(MARKER_PREFIX);
}

function idFromMarker(marker: string): string {
  if (!isOfflineMediaMarker(marker)) {
    throw new Error("Invalid offline photo reference.");
  }
  const id = marker.slice(MARKER_PREFIX.length);
  if (!id) throw new Error("Invalid offline photo reference.");
  return id;
}

export async function queueOfflineImage(
  file: File,
  context: OfflineMediaContext,
  purpose: OfflineMediaPurpose
): Promise<string> {
  if (!file.size || file.size > MAX_IMAGE_BYTES) {
    throw new Error("Offline photos must be between 1 byte and 10 MiB.");
  }
  if (file.type && !file.type.toLowerCase().startsWith("image/")) {
    throw new Error("Only image files can be retained in the offline photo queue.");
  }
  const database = await openDatabase();
  try {
    const records = (await allRecords(database)).filter(
      (record) => record.userId === context.userId && record.deviceId === context.deviceId
    );
    const usedBytes = records.reduce((total, record) => total + record.byteSize, 0);
    if (
      records.length >= MAX_DEVICE_MEDIA_ITEMS
      || usedBytes + file.size > MAX_DEVICE_MEDIA_BYTES
    ) {
      throw new Error("Offline photo storage is full. Reconnect and sync before taking more photos.");
    }
    const id = mediaId();
    const record: OfflineMediaRecord = {
      id,
      blob: file,
      fileName: file.name.slice(0, 255) || "offline-photo",
      mimeType: file.type || "application/octet-stream",
      byteSize: file.size,
      userId: context.userId,
      deviceId: context.deviceId,
      workOrderId: context.workOrderId,
      claimVersion: context.claimVersion,
      purpose,
      createdAt: new Date().toISOString()
    };
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).add(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("Offline photo could not be retained."));
      transaction.onabort = () => reject(new Error("Offline photo storage was interrupted."));
    });
    window.dispatchEvent(new Event("opf-offline-media"));
    return `${MARKER_PREFIX}${id}`;
  } finally {
    database.close();
  }
}

export async function readOfflineImage(
  marker: string,
  context: OfflineMediaContext
): Promise<{ blob: Blob; fileName: string; purpose: OfflineMediaPurpose }> {
  const database = await openDatabase();
  try {
    const id = idFromMarker(marker);
    const record = await new Promise<OfflineMediaRecord | undefined>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readonly");
      const request = transaction.objectStore(STORE_NAME).get(id);
      request.onsuccess = () => resolve(request.result as OfflineMediaRecord | undefined);
      request.onerror = () => reject(new Error("Offline photo could not be read."));
    });
    if (!record) throw new Error("Offline photo data is missing from this device.");
    if (
      record.userId !== context.userId
      || record.deviceId !== context.deviceId
      || record.workOrderId !== context.workOrderId
      || record.claimVersion !== context.claimVersion
    ) {
      throw new Error("Offline photo belongs to another account, device, work order, or claim generation.");
    }
    return {
      blob: record.blob,
      fileName: record.fileName,
      purpose: record.purpose
    };
  } finally {
    database.close();
  }
}

export async function listOfflineImages(
  userId: string,
  deviceId: string
): Promise<OfflineMediaSummary[]> {
  const database = await openDatabase();
  try {
    return (await allRecords(database))
      .filter((record) => record.userId === userId && record.deviceId === deviceId)
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt))
      .map((record) => ({
        marker: `${MARKER_PREFIX}${record.id}`,
        workOrderId: record.workOrderId,
        claimVersion: record.claimVersion,
        purpose: record.purpose,
        byteSize: record.byteSize,
        createdAt: record.createdAt
      }));
  } finally {
    database.close();
  }
}

export async function deleteOfflineImage(
  marker: string,
  context?: OfflineMediaContext
): Promise<void> {
  if (context) {
    await readOfflineImage(marker, context);
  }
  const database = await openDatabase();
  try {
    const id = idFromMarker(marker);
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).delete(id);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("Synchronized offline photo could not be removed."));
      transaction.onabort = () => reject(new Error("Offline photo cleanup was interrupted."));
    });
    window.dispatchEvent(new Event("opf-offline-media"));
  } finally {
    database.close();
  }
}
