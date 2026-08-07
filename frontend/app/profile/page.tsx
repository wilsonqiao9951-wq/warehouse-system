"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, clearOfflineSession } from "@/lib/api";
import { AuthSecurityEvent, MfaEnrollment, MfaStatus, User } from "@/types";

const outcomeLabel: Record<AuthSecurityEvent["outcome"], string> = {
  success: "Signed in",
  invalid_credentials: "Invalid credentials",
  rate_limited: "Rate limited",
  subscription_denied: "Subscription denied",
  device_rejected: "Device rejected",
  sessions_revoked: "Sessions revoked",
  reset_requested: "Reset requested",
  reset_request_ignored: "Reset request ignored",
  reset_delivered: "Reset email delivered",
  reset_delivery_failed: "Reset delivery failed",
  reset_completed: "Password reset completed",
  reset_rejected: "Reset token rejected",
  mfa_challenge_required: "MFA challenge required",
  mfa_success: "MFA verified",
  mfa_invalid: "MFA rejected",
  mfa_recovery_used: "Recovery code used",
  mfa_enrolled: "MFA enabled",
  mfa_disabled: "MFA disabled",
  mfa_recovery_regenerated: "Recovery codes replaced"
};

function signOut(reason: string) {
  clearOfflineSession();
  window.localStorage.removeItem("opf_access_token");
  window.localStorage.removeItem("opf_role");
  window.localStorage.removeItem("opf_user_id");
  window.location.href = `/login?reason=${encodeURIComponent(reason)}`;
}

export default function ProfilePage() {
  const [user, setUser] = useState<User | null>(null);
  const [events, setEvents] = useState<AuthSecurityEvent[]>([]);
  const [password, setPassword] = useState("");
  const [mfaStatus, setMfaStatus] = useState<MfaStatus | null>(null);
  const [mfaEnrollment, setMfaEnrollment] = useState<MfaEnrollment | null>(null);
  const [mfaPassword, setMfaPassword] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);
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
        void api.getMfaStatus().then(setMfaStatus).catch(() => setMfaStatus(null));
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
      signOut("sessions-revoked");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to revoke sessions");
      setBusy(false);
    }
  }

  async function startMfa(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const enrollment = await api.startMfaEnrollment(mfaPassword);
      setMfaEnrollment(enrollment);
      setMfaCode("");
      setRecoveryCodes([]);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to start MFA enrollment");
    } finally {
      setBusy(false);
    }
  }

  async function confirmMfa(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const result = await api.confirmMfaEnrollment(mfaCode);
      setRecoveryCodes(result.recovery_codes);
      setMfaEnrollment(null);
      setMfaStatus((current) => current ? { ...current, enabled: true, enrollment_pending: false } : current);
      setMfaPassword("");
      setMfaCode("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to confirm MFA enrollment");
    } finally {
      setBusy(false);
    }
  }

  async function disableMfa() {
    setBusy(true);
    setError("");
    try {
      await api.disableMfa(mfaPassword, mfaCode);
      signOut("mfa-disabled");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to disable MFA");
      setBusy(false);
    }
  }

  async function regenerateRecoveryCodes() {
    setBusy(true);
    setError("");
    try {
      const result = await api.regenerateMfaRecoveryCodes(mfaPassword, mfaCode);
      setRecoveryCodes(result.recovery_codes);
      setMfaPassword("");
      setMfaCode("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to replace recovery codes");
    } finally {
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
            {busy ? "Working…" : "Revoke all sessions and sign out"}
          </button>
        </form>
      </section>

      {mfaStatus?.eligible && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Administrator multi-factor authentication</h3>
          <p className="muted">
            Protect this administrator account with a standards-compatible authenticator app. Every enable, disable, or recovery-code replacement revokes existing sessions.
          </p>
          {!mfaStatus.available && (
            <p className="notice-warn">MFA is unavailable until the server encryption key is configured.</p>
          )}
          {recoveryCodes.length > 0 && (
            <div className="notice-warn">
              <b>Save these one-time recovery codes now. They will not be shown again.</b>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: 8, marginTop: 12 }}>
                {recoveryCodes.map((code) => <code key={code}>{code}</code>)}
              </div>
              <button type="button" style={{ marginTop: 14 }} onClick={() => signOut("mfa-updated")}>I saved the codes — sign in again</button>
            </div>
          )}
          {!mfaStatus.enabled && recoveryCodes.length === 0 && !mfaEnrollment && (
            <form onSubmit={startMfa} style={{ display: "grid", gap: 12 }}>
              <label>
                Current account password
                <input type="password" minLength={10} maxLength={128} autoComplete="current-password" value={mfaPassword} onChange={(event) => setMfaPassword(event.target.value)} required />
              </label>
              <button type="submit" disabled={busy || !mfaStatus.available || mfaPassword.length < 10}>Start MFA enrollment</button>
            </form>
          )}
          {mfaEnrollment && (
            <form onSubmit={confirmMfa} style={{ display: "grid", gap: 12 }}>
              <p className="notice">Add this secret to your authenticator app, then enter its current six-digit code.</p>
              <div style={{ overflowWrap: "anywhere" }}><b>Secret:</b> <code>{mfaEnrollment.secret}</code></div>
              <details><summary>Manual provisioning URI</summary><code style={{ overflowWrap: "anywhere" }}>{mfaEnrollment.provisioning_uri}</code></details>
              <label>
                Authenticator code
                <input inputMode="numeric" autoComplete="one-time-code" minLength={6} maxLength={6} value={mfaCode} onChange={(event) => setMfaCode(event.target.value)} required />
              </label>
              <button type="submit" disabled={busy || mfaCode.length !== 6}>Verify and enable MFA</button>
            </form>
          )}
          {mfaStatus.enabled && recoveryCodes.length === 0 && (
            <div style={{ display: "grid", gap: 12 }}>
              <p className="notice-success">MFA is enabled{mfaStatus.enabled_at ? ` since ${new Date(mfaStatus.enabled_at).toLocaleString()}` : ""}.</p>
              <label>
                Current account password
                <input type="password" minLength={10} maxLength={128} autoComplete="current-password" value={mfaPassword} onChange={(event) => setMfaPassword(event.target.value)} required />
              </label>
              <label>
                Authenticator or unused recovery code
                <input autoComplete="one-time-code" minLength={6} maxLength={32} value={mfaCode} onChange={(event) => setMfaCode(event.target.value)} required />
              </label>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <button type="button" disabled={busy || mfaPassword.length < 10 || mfaCode.length < 6} onClick={regenerateRecoveryCodes}>Replace recovery codes</button>
                <button type="button" className="danger" disabled={busy || mfaPassword.length < 10 || mfaCode.length < 6} onClick={disableMfa}>Disable MFA</button>
              </div>
            </div>
          )}
        </section>
      )}

      {user?.role === "admin" && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Recent authentication events</h3>
          <p className="muted">
            Tenant-scoped outcomes only. Email, IP address, passwords, tokens, device secrets, MFA secrets, and recovery codes are never displayed or retained here.
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th>Time</th><th>Account</th><th>Event</th><th>Outcome</th></tr></thead>
              <tbody>
                {events.map((item) => (
                  <tr key={item.id}>
                    <td>{new Date(item.occurred_at).toLocaleString()}</td>
                    <td>{item.user_id || "Unknown"}</td>
                    <td>{item.event_type === "login" ? "Login" : item.event_type === "password_reset" ? "Password reset" : item.event_type === "mfa" ? "MFA" : "Session control"}</td>
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
