"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { api, clearLocalAuthentication, hasStoredAuthentication } from "@/lib/api";
import type { UserRole } from "@/types";

const PERMISSIONS_KEY = "opf_effective_permissions";
const PLATFORM_ADMIN_KEY = "opf_is_platform_admin";

type AccessSession = {
  authenticated: boolean;
  loading: boolean;
  role: UserRole | null;
  permissions: string[] | null;
  isPlatformAdmin: boolean;
  refresh: () => Promise<void>;
};

const AccessSessionContext = createContext<AccessSession | null>(null);

function savedRole(): UserRole | null {
  const value = window.localStorage.getItem("opf_role");
  return ["admin", "manager", "warehouse", "engineer", "assistant"].includes(value || "")
    ? value as UserRole
    : null;
}

function savedPermissions(): string[] | null {
  try {
    const value = JSON.parse(window.localStorage.getItem(PERMISSIONS_KEY) || "null") as unknown;
    return Array.isArray(value) && value.every((item) => typeof item === "string")
      ? value
      : null;
  } catch {
    return null;
  }
}

export function AccessSessionProvider({ children }: { children: React.ReactNode }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [loading, setLoading] = useState(true);
  const [role, setRole] = useState<UserRole | null>(null);
  const [permissions, setPermissions] = useState<string[] | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);

  const refresh = useCallback(async () => {
    if (!hasStoredAuthentication()) {
      setAuthenticated(false);
      setRole(null);
      setPermissions(null);
      setIsPlatformAdmin(false);
      setLoading(false);
      return;
    }

    const cachedRole = savedRole();
    const cachedPermissions = savedPermissions();
    const cachedPlatformAdmin = window.localStorage.getItem(PLATFORM_ADMIN_KEY) === "true";
    if (cachedRole && window.localStorage.getItem("opf_user_id")) {
      setAuthenticated(true);
      setRole(cachedRole);
      setPermissions(cachedPermissions);
      setIsPlatformAdmin(cachedPlatformAdmin);
    }

    if (!navigator.onLine) {
      setLoading(false);
      return;
    }

    setLoading(true);
    try {
      const [user, permissionMatrix] = await Promise.all([
        api.getMe(),
        api.getMyPermissions(),
      ]);
      setAuthenticated(true);
      setRole(user.role);
      setPermissions(permissionMatrix.effective_permissions);
      setIsPlatformAdmin(user.is_platform_admin);
      window.localStorage.setItem("opf_role", user.role);
      window.localStorage.setItem("opf_user_id", String(user.id));
      window.localStorage.setItem(
        PERMISSIONS_KEY,
        JSON.stringify(permissionMatrix.effective_permissions),
      );
      window.localStorage.setItem(PLATFORM_ADMIN_KEY, String(user.is_platform_admin));
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      const networkUnavailable = (
        message.includes("Network unavailable")
        || message.includes("API unavailable")
      );
      if (!networkUnavailable) {
        clearLocalAuthentication();
        setAuthenticated(false);
        setRole(null);
        setPermissions(null);
        setIsPlatformAdmin(false);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const handleOnline = () => void refresh();
    window.addEventListener("online", handleOnline);
    return () => window.removeEventListener("online", handleOnline);
  }, [refresh]);

  const value = useMemo<AccessSession>(() => ({
    authenticated,
    loading,
    role,
    permissions,
    isPlatformAdmin,
    refresh,
  }), [authenticated, isPlatformAdmin, loading, permissions, refresh, role]);

  return (
    <AccessSessionContext.Provider value={value}>
      {children}
    </AccessSessionContext.Provider>
  );
}

export function useAccessSession(): AccessSession {
  const context = useContext(AccessSessionContext);
  if (!context) throw new Error("useAccessSession must be used inside AccessSessionProvider");
  return context;
}
