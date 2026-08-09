import type { UserRole } from "@/types";

export type RouteAccessPolicy = {
  href: string;
  label: string;
  roles: readonly UserRole[];
  platformOnly?: boolean;
  exact?: boolean;
  permission?: string;
  navigation?: boolean;
};

export type AccessContext = {
  role: UserRole;
  permissions: readonly string[] | null;
  isPlatformAdmin: boolean;
};

export const routeAccessPolicies: readonly RouteAccessPolicy[] = [
  { href: "/", label: "Dashboard", roles: ["manager", "admin"], exact: true },
  { href: "/work-orders", label: "Work Orders", roles: ["manager", "admin", "engineer"] },
  { href: "/calendar", label: "Calendar", roles: ["manager", "admin"] },
  { href: "/map", label: "Map", roles: ["manager", "admin", "engineer"] },
  { href: "/inventory", label: "Inventory", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-ledger", label: "Inventory Ledger", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-reconciliation", label: "Inventory Reconciliation", roles: ["warehouse", "manager", "admin"] },
  { href: "/van-inventory-planning", label: "Van Planning", roles: ["warehouse", "manager", "admin"] },
  { href: "/regions", label: "Regions", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-scan", label: "Scan & Check", roles: ["warehouse", "manager", "admin", "engineer"] },
  { href: "/warehouse-tasks", label: "Warehouse Tasks", roles: ["warehouse", "manager", "admin"] },
  { href: "/low-stock-rules", label: "Low-stock Rules", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-counts", label: "Inventory Counts", roles: ["warehouse", "manager", "admin"] },
  { href: "/knowledge-base", label: "Service Knowledge", roles: ["warehouse", "manager", "admin", "engineer"] },
  { href: "/part-observation", label: "Photo Memory", roles: ["warehouse", "manager", "admin", "engineer"] },
  { href: "/employees", label: "Employees", roles: ["manager", "admin"], permission: "users.read" },
  { href: "/reports", label: "Reports", roles: ["manager", "admin"], permission: "reports.read" },
  { href: "/abnormal-usage", label: "Usage Reviews", roles: ["manager", "admin"], permission: "reports.read" },
  { href: "/analytics", label: "Analytics", roles: ["manager", "admin"], permission: "reports.read" },
  { href: "/profit-snapshots", label: "Profit Snapshots", roles: ["manager", "admin"], permission: "reports.read" },
  { href: "/performance", label: "Performance", roles: ["manager", "admin", "engineer"] },
  { href: "/agent", label: "Operations Agent", roles: ["manager", "admin"], permission: "agent.use" },
  { href: "/audit-logs", label: "Audit Logs", roles: ["manager", "admin"], permission: "audit.read" },
  { href: "/backups", label: "Backups", roles: ["admin"] },
  { href: "/pilot-checklist", label: "Pilot Governance", roles: ["engineer", "warehouse", "manager", "admin"] },
  { href: "/settings", label: "Settings", roles: ["manager", "admin"] },
  { href: "/work-order-templates", label: "Job Forms", roles: ["manager", "admin"] },
  { href: "/form-actions", label: "Form Actions", roles: ["warehouse", "manager", "admin"] },
  { href: "/sync-conflicts", label: "Sync Conflicts", roles: ["admin"] },
  { href: "/integrations", label: "Integrations", roles: ["manager", "admin"], permission: "integrations.read" },
  { href: "/integration-reconciliation", label: "Parallel Run", roles: ["manager", "admin"], permission: "integrations.read" },
  { href: "/platform", label: "Customers", roles: ["admin"], platformOnly: true, exact: true },
  { href: "/platform/operations", label: "Operations", roles: ["admin"], platformOnly: true },
  { href: "/parts-usage", label: "Parts Usage", roles: ["warehouse", "admin"] },
  { href: "/parts-import", label: "Parts Import", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-import", label: "Opening Stock", roles: ["warehouse", "manager", "admin"] },
  { href: "/work-order-details", label: "WO Details", roles: ["engineer", "warehouse", "manager", "admin"], navigation: false },
  { href: "/today", label: "Today", roles: ["engineer"] },
  { href: "/my-jobs", label: "My Jobs", roles: ["engineer"] },
  { href: "/my-van-inventory", label: "My Van", roles: ["engineer"] },
  { href: "/sync-center", label: "Sync", roles: ["engineer", "warehouse", "manager", "admin"] },
  { href: "/profile", label: "Profile", roles: ["engineer", "warehouse", "manager", "admin", "assistant"] },
];

const publicPaths = new Set([
  "/login",
  "/forgot-password",
  "/reset-password",
  "/accept-invitation",
]);

function normalizedPath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function isPublicPath(pathname: string): boolean {
  return publicPaths.has(normalizedPath(pathname));
}

export function policyAllows(policy: RouteAccessPolicy, access: AccessContext): boolean {
  if (policy.platformOnly && !access.isPlatformAdmin) return false;
  if (policy.permission && access.permissions !== null) {
    return access.permissions.includes(policy.permission);
  }
  return policy.roles.includes(access.role);
}

export function routePolicyForPath(pathname: string): RouteAccessPolicy | null {
  const path = normalizedPath(pathname);
  const matches = routeAccessPolicies.filter((policy) => (
    policy.exact || policy.href === "/"
      ? path === policy.href
      : path === policy.href || path.startsWith(`${policy.href}/`)
  ));
  return matches.sort((left, right) => right.href.length - left.href.length)[0] || null;
}

export function canAccessPath(pathname: string, access: AccessContext): boolean {
  if (isPublicPath(pathname)) return true;
  const policy = routePolicyForPath(pathname);
  return policy ? policyAllows(policy, access) : false;
}

export function homeRouteForRole(role: UserRole): string {
  if (role === "engineer") return "/today";
  if (role === "warehouse") return "/inventory";
  if (role === "assistant") return "/profile";
  return "/";
}
