"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

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

  useEffect(() => {
    const saved = window.localStorage.getItem("opf_role");
    const savedUserId = window.localStorage.getItem("opf_user_id");
    if (saved) {
      setRole(saved);
    }
    if (savedUserId) {
      setUserId(savedUserId);
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
    const items = links.filter((link) => link.roles.includes(role));
    if (role === "engineer") {
      return sortEngineerLinks(items);
    }
    return items;
  }, [role]);

  return (
    <>
      <div className="topbar container" style={{ marginBottom: 0, paddingTop: 4 }}>
        <select
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
        </select>
        <input
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
        />
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
