"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/lib/api";

const links = [
  { href: "/", label: "Dashboard", roles: ["manager", "admin"] },
  { href: "/work-orders", label: "Work Orders", roles: ["manager", "admin"] },
  { href: "/calendar", label: "Calendar", roles: ["manager", "admin"] },
  { href: "/map", label: "Map", roles: ["manager", "admin", "engineer"] },
  { href: "/inventory", label: "Inventory", roles: ["warehouse", "manager", "admin"] },
  { href: "/employees", label: "Employees", roles: ["manager", "admin"] },
  { href: "/reports", label: "Reports", roles: ["manager", "admin"] },
  { href: "/pilot-checklist", label: "Pilot Checklist", roles: ["manager", "admin"] },
  { href: "/settings", label: "Settings", roles: ["manager", "admin"] },
  { href: "/parts-usage", label: "Parts Usage", roles: ["warehouse", "admin"] },
  { href: "/work-order-details", label: "WO Details", roles: ["admin"] },
  { href: "/today", label: "Today", roles: ["engineer"] },
  { href: "/my-jobs", label: "My Jobs", roles: ["engineer"] },
  { href: "/my-van-inventory", label: "My Van", roles: ["engineer"] },
  { href: "/profile", label: "Profile", roles: ["engineer"] }
];

function sortEngineerLinks(items: typeof links) {
  const order = ["/today", "/map", "/my-jobs", "/my-van-inventory", "/profile"];
  return [...items].sort((a, b) => order.indexOf(a.href) - order.indexOf(b.href));
}

export default function Nav() {
  const pathname = usePathname();
  const [role, setRole] = useState("admin");
  const [userId, setUserId] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const legacyAuth = process.env.NEXT_PUBLIC_LEGACY_AUTH === "true";

  useEffect(() => {
    const saved = window.localStorage.getItem("opf_role");
    const savedUserId = window.localStorage.getItem("opf_user_id");
    const token = window.localStorage.getItem("opf_access_token");
    if (saved) {
      setRole(saved);
    }
    if (savedUserId) {
      setUserId(savedUserId);
    }
    if (token) {
      api.getMe()
        .then((user) => {
          setAuthenticated(true);
          setRole(user.role);
          setUserId(String(user.id));
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
    if (!authenticated && !legacyAuth) return [];
    const items = links.filter((link) => link.roles.includes(role));
    if (role === "engineer") {
      return sortEngineerLinks(items);
    }
    return items;
  }, [authenticated, legacyAuth, role]);

  return (
    <>
      <div className="topbar container" style={{ marginBottom: 0, paddingTop: 4 }}>
        {legacyAuth && !authenticated && <select
          value={role}
          onChange={(e) => {
            setRole(e.target.value);
            window.localStorage.setItem("opf_role", e.target.value);
          }}
          style={{ maxWidth: 200 }}
          aria-label="Role"
        >
          <option value="engineer">technician</option>
          <option value="warehouse">warehouse</option>
          <option value="manager">manager</option>
          <option value="admin">admin</option>
        </select>}
        {legacyAuth && !authenticated && <input
          placeholder="X-User-Id"
          value={userId}
          onChange={(e) => {
            const value = e.target.value.replace(/[^\d]/g, "");
            setUserId(value);
            if (value) {
              window.localStorage.setItem("opf_user_id", value);
            } else {
              window.localStorage.removeItem("opf_user_id");
            }
          }}
          style={{ maxWidth: 160 }}
          inputMode="numeric"
          aria-label="User id for API"
        />}
        {!authenticated && !legacyAuth && <Link href="/login">Sign in</Link>}
        {authenticated && (
          <button
            type="button"
            onClick={() => {
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
