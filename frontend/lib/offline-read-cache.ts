const DATABASE_NAME = "opf_offline_read_cache";
const DATABASE_VERSION = 1;
const STORE_NAME = "responses";
const MAX_ITEM_BYTES = 1_500_000;
const MAX_CACHE_BYTES = 12_000_000;
const MAX_CACHE_ENTRIES = 120;

interface OfflineReadRecord {
  key: string;
  userId: string;
  deviceId: string;
  path: string;
  payloadJson: string;
  byteSize: number;
  storedAt: string;
}

export interface OfflineReadCacheSummary {
  path: string;
  byteSize: number;
  storedAt: string;
}

function cacheKey(userId: string, deviceId: string, path: string): string {
  return `${userId}\u001f${deviceId}\u001f${path}`;
}

function openDatabase(): Promise<IDBDatabase> {
  if (typeof window === "undefined" || !window.indexedDB) {
    return Promise.reject(new Error("This browser does not support offline read storage."));
  }
  return new Promise((resolve, reject) => {
    const request = window.indexedDB.open(DATABASE_NAME, DATABASE_VERSION);
    request.onupgradeneeded = () => {
      const database = request.result;
      if (!database.objectStoreNames.contains(STORE_NAME)) {
        database.createObjectStore(STORE_NAME, { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(new Error("Offline read storage could not be opened."));
    request.onblocked = () => reject(new Error("Offline read storage upgrade is blocked by another app window."));
  });
}

async function allRecords(database: IDBDatabase): Promise<OfflineReadRecord[]> {
  return new Promise((resolve, reject) => {
    const request = database
      .transaction(STORE_NAME, "readonly")
      .objectStore(STORE_NAME)
      .getAll();
    request.onsuccess = () => resolve(request.result as OfflineReadRecord[]);
    request.onerror = () => reject(new Error("Offline read snapshots could not be inspected."));
  });
}

async function deleteKeys(database: IDBDatabase, keys: string[]): Promise<void> {
  if (!keys.length) return;
  await new Promise<void>((resolve, reject) => {
    const transaction = database.transaction(STORE_NAME, "readwrite");
    const store = transaction.objectStore(STORE_NAME);
    keys.forEach((key) => store.delete(key));
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(new Error("Old offline read snapshots could not be pruned."));
    transaction.onabort = () => reject(new Error("Offline read snapshot pruning was interrupted."));
  });
}

export async function saveOfflineReadResponse(
  userId: string,
  deviceId: string,
  path: string,
  payload: unknown
): Promise<void> {
  const payloadJson = JSON.stringify(payload);
  const byteSize = new Blob([payloadJson]).size;
  if (byteSize > MAX_ITEM_BYTES) return;
  const database = await openDatabase();
  try {
    const key = cacheKey(userId, deviceId, path);
    const ownerRecords = (await allRecords(database))
      .filter((record) => record.userId === userId && record.deviceId === deviceId)
      .filter((record) => record.key !== key)
      .sort((a, b) => a.storedAt.localeCompare(b.storedAt));
    let projectedBytes = ownerRecords.reduce((total, record) => total + record.byteSize, 0) + byteSize;
    let projectedEntries = ownerRecords.length + 1;
    const removeKeys: string[] = [];
    for (const record of ownerRecords) {
      if (projectedBytes <= MAX_CACHE_BYTES && projectedEntries <= MAX_CACHE_ENTRIES) break;
      projectedBytes -= record.byteSize;
      projectedEntries -= 1;
      removeKeys.push(record.key);
    }
    await deleteKeys(database, removeKeys);
    const record: OfflineReadRecord = {
      key,
      userId,
      deviceId,
      path,
      payloadJson,
      byteSize,
      storedAt: new Date().toISOString()
    };
    await new Promise<void>((resolve, reject) => {
      const transaction = database.transaction(STORE_NAME, "readwrite");
      transaction.objectStore(STORE_NAME).put(record);
      transaction.oncomplete = () => resolve();
      transaction.onerror = () => reject(new Error("Offline read snapshot could not be saved."));
      transaction.onabort = () => reject(new Error("Offline read snapshot storage was interrupted."));
    });
    window.dispatchEvent(new Event("opf-offline-read-cache"));
  } finally {
    database.close();
  }
}

export async function readOfflineReadResponse<T>(
  userId: string,
  deviceId: string,
  path: string
): Promise<{ payload: T; storedAt: string }> {
  const database = await openDatabase();
  try {
    const record = await new Promise<OfflineReadRecord | undefined>((resolve, reject) => {
      const request = database
        .transaction(STORE_NAME, "readonly")
        .objectStore(STORE_NAME)
        .get(cacheKey(userId, deviceId, path));
      request.onsuccess = () => resolve(request.result as OfflineReadRecord | undefined);
      request.onerror = () => reject(new Error("Offline read snapshot could not be loaded."));
    });
    if (!record) {
      throw new Error("This information has not been opened on this account and device while online.");
    }
    try {
      return {
        payload: JSON.parse(record.payloadJson) as T,
        storedAt: record.storedAt
      };
    } catch {
      throw new Error("The retained offline snapshot is invalid.");
    }
  } finally {
    database.close();
  }
}

export async function listOfflineReadResponses(
  userId: string,
  deviceId: string
): Promise<OfflineReadCacheSummary[]> {
  const database = await openDatabase();
  try {
    return (await allRecords(database))
      .filter((record) => record.userId === userId && record.deviceId === deviceId)
      .sort((a, b) => b.storedAt.localeCompare(a.storedAt))
      .map((record) => ({
        path: record.path,
        byteSize: record.byteSize,
        storedAt: record.storedAt
      }));
  } finally {
    database.close();
  }
}
