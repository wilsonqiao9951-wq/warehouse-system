"use client";

import { useEffect, useMemo } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useAccessSession } from "@/components/access-session-provider";
import { api, clearLocalAuthentication } from "@/lib/api";
import { policyAllows, routeAccessPolicies } from "@/lib/access-policy";

function sortEngineerLinks(items: typeof routeAccessPolicies) {
  const order = ["/today", "/my-jobs", "/work-orders", "/performance", "/my-van-inventory", "/knowledge-base", "/inventory-scan", "/sync-center", "/profile", "/map", "/part-observation"];
  return [...items].sort((a, b) => {
    const ai = order.indexOf(a.href); const bi = order.indexOf(b.href);
    return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
  });
}

export default function Nav() {
  const pathname = usePathname();
  const {
    authenticated,
    role,
    permissions,
    isPlatformAdmin,
  } = useAccessSession();

  useEffect(() => {
    if (role === "engineer") {
      document.body.classList.add("has-bottom-nav");
    } else {
      document.body.classList.remove("has-bottom-nav");
    }
    return () => document.body.classList.remove("has-bottom-nav");
  }, [role]);

  const visibleLinks = useMemo(() => {
    if (!authenticated || !role) return [];
    const items = routeAccessPolicies.filter((link) => (
      link.navigation !== false
      && policyAllows(link, { role, permissions, isPlatformAdmin })
    ));
    if (role === "engineer") {
      return sortEngineerLinks(items);
    }
    return items;
  }, [authenticated, isPlatformAdmin, permissions, role]);

  return (
    <>
      <div className="topbar container" style={{ marginBottom: 0, paddingTop: 4 }}>
        {!authenticated && <Link href="/login">Sign in</Link>}
        {authenticated && (
          <button
            type="button"
            onClick={async () => {
              try {
                await api.logout();
              } finally {
                clearLocalAuthentication();
                window.location.href = "/login";
              }
            }}
          >
            Sign out
          </button>
        )}
      </div>
      <nav
        className={role === "engineer" ? "mobile-bottom-nav" : "topbar container"}
        style={role === "engineer" ? { marginBottom: 0 } : undefined}
        aria-label="Primary"
      >
        {visibleLinks.map((link) => {
          const active =
            link.href === "/"
              ? pathname === "/" || pathname === ""
              : link.exact
              ? pathname === link.href
              : pathname === link.href || pathname.startsWith(`${link.href}/`);
          return (
            <Link
              key={link.href}
              href={link.href}
              className={`nav-item${active ? " nav-item--active" : ""}`}
            >
              {link.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}
