"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api, clearOfflineSession } from "@/lib/api";

const links = [
  { href: "/", label: "Dashboard", roles: ["manager", "admin"] },
  { href: "/work-orders", label: "Work Orders", roles: ["manager", "admin"] },
  { href: "/calendar", label: "Calendar", roles: ["manager", "admin"] },
  { href: "/map", label: "Map", roles: ["manager", "admin", "engineer"] },
  { href: "/inventory", label: "Inventory", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-scan", label: "Scan & Check", roles: ["warehouse", "manager", "admin", "engineer"] },
  { href: "/warehouse-tasks", label: "Warehouse Tasks", roles: ["warehouse", "manager", "admin"] },
  { href: "/part-observation", label: "Photo Memory", roles: ["warehouse", "manager", "admin", "engineer"] },
  { href: "/employees", label: "Employees", roles: ["manager", "admin"] },
  { href: "/reports", label: "Reports", roles: ["manager", "admin"] },
  { href: "/pilot-checklist", label: "Pilot Checklist", roles: ["manager", "admin"] },
  { href: "/settings", label: "Settings", roles: ["manager", "admin"] },
  { href: "/platform", label: "Customers", roles: ["admin"] },
  { href: "/parts-usage", label: "Parts Usage", roles: ["warehouse", "admin"] },
  { href: "/parts-import", label: "Parts Import", roles: ["warehouse", "manager", "admin"] },
  { href: "/inventory-import", label: "Opening Stock", roles: ["warehouse", "manager", "admin"] },
  { href: "/work-order-details", label: "WO Details", roles: ["admin"] },
  { href: "/today", label: "Today", roles: ["engineer"] },
  { href: "/my-jobs", label: "My Jobs", roles: ["engineer"] },
  { href: "/my-van-inventory", label: "My Van", roles: ["engineer"] },
  { href: "/sync-center", label: "Sync", roles: ["engineer", "warehouse", "manager", "admin"] },
  { href: "/profile", label: "Profile", roles: ["engineer"] }
];

function sortEngineerLinks(items: typeof links) {
  const order = ["/today", "/my-jobs", "/inventory-scan", "/my-van-inventory", "/profile", "/map", "/part-observation"];
  return [...items].sort((a, b) => {
    const ai = order.indexOf(a.href); const bi = order.indexOf(b.href);
    return (ai < 0 ? order.length : ai) - (bi < 0 ? order.length : bi);
  });
}

export default function Nav() {
  const pathname = usePathname();
  const [role, setRole] = useState("admin");
  const [authenticated, setAuthenticated] = useState(false);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("opf_role");
    const token = window.localStorage.getItem("opf_access_token");
    if (saved) {
      setRole(saved);
    }
    if (token) {
      api.getMe()
        .then((user) => {
          setAuthenticated(true);
          setRole(user.role);
          setIsPlatformAdmin(user.is_platform_admin);
          window.localStorage.setItem("opf_role", user.role);
          window.localStorage.setItem("opf_user_id", String(user.id));
        })
        .catch(() => {
          window.localStorage.removeItem("opf_access_token");
          setAuthenticated(false);
        });
    }
  }, []);

  useEffect(() => {
    if (role === "engineer") {
      document.body.classList.add("has-bottom-nav");
    } else {
      document.body.classList.remove("has-bottom-nav");
    }
    return () => document.body.classList.remove("has-bottom-nav");
  }, [role]);

  const visibleLinks = useMemo(() => {
    if (!authenticated) return [];
    const items = links.filter(
      (link) => link.roles.includes(role) && (link.href !== "/platform" || isPlatformAdmin)
    );
    if (role === "engineer") {
      return sortEngineerLinks(items);
    }
    return items;
  }, [authenticated, isPlatformAdmin, role]);

  return (
    <>
      <div className="topbar container" style={{ marginBottom: 0, paddingTop: 4 }}>
        {!authenticated && <Link href="/login">Sign in</Link>}
        {authenticated && (
          <button
            type="button"
            onClick={() => {
              clearOfflineSession();
              window.localStorage.removeItem("opf_access_token");
              window.localStorage.removeItem("opf_role");
              window.localStorage.removeItem("opf_user_id");
              window.location.href = "/login";
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
