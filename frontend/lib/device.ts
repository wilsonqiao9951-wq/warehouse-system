export interface DeviceCredentials {
  deviceId: string;
  deviceToken: string;
  deviceName: string;
}

const DEVICE_ID_KEY = "opf_device_id";
const DEVICE_TOKEN_KEY = "opf_device_token";
const DEVICE_NAME_KEY = "opf_device_name";

function randomBase64Url(byteLength: number): string {
  const bytes = new Uint8Array(byteLength);
  window.crypto.getRandomValues(bytes);
  let binary = "";
  bytes.forEach((value) => {
    binary += String.fromCharCode(value);
  });
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function describeDevice(): string {
  const platform = navigator.platform || "mobile-web";
  const browser = navigator.userAgent.match(/(Edg|Chrome|CriOS|Firefox|FxiOS|Safari)\/[\d.]+/)?.[0] || "browser";
  // HTTP header values must remain portable across native WebViews and browsers.
  return `${platform} ${browser}`.replace(/[^\x20-\x7E]/g, "").slice(0, 120) || "OpenPartsFlow device";
}

export function getStoredDeviceCredentials(): DeviceCredentials | null {
  if (typeof window === "undefined") return null;
  const deviceId = window.localStorage.getItem(DEVICE_ID_KEY);
  const deviceToken = window.localStorage.getItem(DEVICE_TOKEN_KEY);
  if (!deviceId || !deviceToken) return null;
  return {
    deviceId,
    deviceToken,
    deviceName: window.localStorage.getItem(DEVICE_NAME_KEY) || describeDevice()
  };
}

export function ensureDeviceCredentials(): DeviceCredentials {
  if (typeof window === "undefined" || !window.crypto?.getRandomValues) {
    throw new Error("Secure device registration requires a supported browser.");
  }
  const existing = getStoredDeviceCredentials();
  if (existing) return existing;

  const credentials: DeviceCredentials = {
    deviceId: `opf-${randomBase64Url(24)}`,
    deviceToken: randomBase64Url(32),
    deviceName: describeDevice()
  };
  window.localStorage.setItem(DEVICE_ID_KEY, credentials.deviceId);
  window.localStorage.setItem(DEVICE_TOKEN_KEY, credentials.deviceToken);
  window.localStorage.setItem(DEVICE_NAME_KEY, credentials.deviceName);
  return credentials;
}

export function getCurrentDeviceId(): string | null {
  return getStoredDeviceCredentials()?.deviceId || null;
}

export function getCurrentDeviceToken(): string | null {
  return getStoredDeviceCredentials()?.deviceToken || null;
}
