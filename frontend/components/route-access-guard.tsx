"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useAccessSession } from "@/components/access-session-provider";
import {
  canAccessPath,
  homeRouteForRole,
  isPublicPath,
  routePolicyForPath,
} from "@/lib/access-policy";

const roleLabels: Record<string, string> = {
  admin: "administrator",
  manager: "manager",
  warehouse: "warehouse",
  engineer: "technician",
  assistant: "assistant",
};

export default function RouteAccessGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const session = useAccessSession();
  const publicPage = isPublicPath(pathname);

  useEffect(() => {
    if (!publicPage && !session.loading && !session.authenticated) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, publicPage, router, session.authenticated, session.loading]);

  if (publicPage) return children;
  if (session.loading) {
    return <section className="card">Checking account permissions…</section>;
  }
  if (!session.authenticated || !session.role) {
    return <section className="card">Sign in is required to open this page.</section>;
  }

  const access = {
    role: session.role,
    permissions: session.permissions,
    isPlatformAdmin: session.isPlatformAdmin,
  };
  if (canAccessPath(pathname, access)) return children;

  const policy = routePolicyForPath(pathname);
  return (
    <section className="card" style={{ maxWidth: 720, margin: "40px auto" }}>
      <div className="app-header-badge" style={{ display: "inline-block", marginBottom: 12 }}>
        ACCESS RESTRICTED
      </div>
      <h1 style={{ marginTop: 0 }}>This page is not available for your account.</h1>
      <p className="muted">
        Signed in as {roleLabels[session.role] || session.role}. {policy
          ? `${policy.label} is assigned to a different role or permission policy.`
          : "This route is not included in the approved application access policy."}
      </p>
      <Link className="nav-item" href={homeRouteForRole(session.role)}>
        Return to your workspace
      </Link>
    </section>
  );
}
