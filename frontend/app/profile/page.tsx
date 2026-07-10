"use client";

import { useEffect, useMemo, useState } from "react";

export default function ProfilePage() {
  const [role, setRole] = useState("engineer");
  const [userId, setUserId] = useState("");

  const apiBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api",
    []
  );

  useEffect(() => {
    setRole(window.localStorage.getItem("opf_role") || "engineer");
    setUserId(window.localStorage.getItem("opf_user_id") || "");
  }, []);

  return (
    <section className="card">
      <h3>Profile</h3>
      <div>
        <b>Role:</b> {role}
      </div>
      <div>
        <b>X-User-Id:</b> {userId || "—"}
      </div>
      <section className="card" style={{ marginTop: 14, marginBottom: 0, background: "#f9fafb" }}>
        <h4 className="section-title" style={{ marginTop: 0 }}>
          Developer / public test
        </h4>
        <p className="muted" style={{ marginTop: 0, fontSize: 13 }}>
          Values below help verify phone and Cloudflare setup. Change role and X-User-Id in the top bar.
        </p>
        <div style={{ wordBreak: "break-all", fontSize: 14 }}>
          <b>API base URL:</b> {apiBaseUrl}
        </div>
      </section>
      <p className="muted" style={{ marginTop: 8 }}>
        For public phone testing, this URL must be reachable from the phone (not localhost). See{" "}
        <code style={{ fontSize: 13 }}>docs/ENVIRONMENT_SETUP.md</code>.
      </p>
    </section>
  );
}
