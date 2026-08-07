"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, clearOfflineSession } from "@/lib/api";
import { AuthSecurityEvent, User } from "@/types";

const outcomeLabel: Record<AuthSecurityEvent["outcome"], string> = {
  success: "Signed in",
  invalid_credentials: "Invalid credentials",
  rate_limited: "Rate limited",
  subscription_denied: "Subscription denied",
  device_rejected: "Device rejected",
  sessions_revoked: "Sessions revoked"
};

export default function ProfilePage() {
  const [user, setUser] = useState<User | null>(null);
  const [events, setEvents] = useState<AuthSecurityEvent[]>([]);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const apiBaseUrl = useMemo(
    () => process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000/api",
    []
  );

  useEffect(() => {
    api.getMe()
      .then((current) => {
        setUser(current);
        if (current.role === "admin") {
          void api.listAuthSecurityEvents().then(setEvents).catch(() => setEvents([]));
        }
      })
      .catch((caught: Error) => setError(caught.message));
  }, []);

  async function revokeSessions(event: FormEvent) {
    event.preventDefault();
    if (password.length < 10) return;
    setBusy(true);
    setError("");
    try {
      await api.revokeAllSessions(password);
      clearOfflineSession();
      window.localStorage.removeItem("opf_access_token");
      window.localStorage.removeItem("opf_role");
      window.localStorage.removeItem("opf_user_id");
      window.location.href = "/login?reason=sessions-revoked";
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to revoke sessions");
      setBusy(false);
    }
  }

  return (
    <section>
      <section className="card">
        <h2 style={{ marginTop: 0 }}>Account security</h2>
        <p className="muted">
          Session identity is enforced by the server. Revoking sessions immediately invalidates every existing access token for this account.
        </p>
        {error && <p className="error">{error}</p>}
        <div className="two-col">
          <div><b>Name:</b> {user?.name || "—"}</div>
          <div><b>Email:</b> {user?.email || "—"}</div>
          <div><b>Role:</b> {user?.role || "—"}</div>
          <div><b>Account ID:</b> {user?.id || "—"}</div>
        </div>
        <form onSubmit={revokeSessions} style={{ marginTop: 18 }}>
          <label>
            Current account password
            <input
              type="password"
              minLength={10}
              maxLength={128}
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              required
            />
          </label>
          <p className="muted">
            Use this after a lost phone, shared credential, or suspicious sign-in. Registered phone records remain, but every bearer session must sign in again.
          </p>
          <button type="submit" disabled={busy || password.length < 10}>
            {busy ? "Revoking…" : "Revoke all sessions and sign out"}
          </button>
        </form>
      </section>

      {user?.role === "admin" && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Recent authentication events</h3>
          <p className="muted">
            Tenant-scoped outcomes only. Email, IP address, passwords, tokens, and device secrets are never displayed or retained here.
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Account</th><th>Event</th><th>Outcome</th></tr></thead>
              <tbody>
                {events.map((item) => (
                  <tr key={item.id}>
                    <td>{new Date(item.occurred_at).toLocaleString()}</td>
                    <td>{item.user_id || "Unknown"}</td>
                    <td>{item.event_type === "login" ? "Login" : "Session control"}</td>
                    <td>{outcomeLabel[item.outcome]}</td>
                  </tr>
                ))}
                {events.length === 0 && <tr><td colSpan={4}>No tenant authentication events recorded.</td></tr>}
              </tbody>
            </table>
          </div>
        </section>
      )}

      <section className="card">
        <h3 style={{ marginTop: 0 }}>Connection diagnostics</h3>
        <p className="muted">Account identity comes only from the authenticated server session.</p>
        <div style={{ wordBreak: "break-all", fontSize: 14 }}>
          <b>API base URL:</b> {apiBaseUrl}
        </div>
      </section>
    </section>
  );
}
