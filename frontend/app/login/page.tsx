"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { OrganizationBranding } from "@/types";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [challengeToken, setChallengeToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [branding, setBranding] = useState<OrganizationBranding | null>(null);

  useEffect(() => {
    const slug = new URLSearchParams(window.location.search).get("organization");
    if (slug) {
      api.getPublicOrganizationBranding(slug).then(setBranding).catch(() => setBranding(null));
      return;
    }
    const hostname = window.location.hostname.toLowerCase();
    const isLocal = hostname === "localhost"
      || hostname === "127.0.0.1"
      || hostname === "::1"
      || hostname.endsWith(".localhost");
    if (!isLocal) {
      api.getPublicOrganizationBrandingByDomain(hostname)
        .then(setBranding)
        .catch(() => setBranding(null));
    }
  }, []);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      const result = challengeToken
        ? await api.completeMfaLogin(challengeToken, mfaCode)
        : await api.login(email.trim(), password);
      if ("mfa_required" in result) {
        setChallengeToken(result.challenge_token);
        setPassword("");
        return;
      }
      window.localStorage.setItem("opf_access_token", result.access_token);
      window.localStorage.setItem("opf_role", result.user.role);
      window.localStorage.setItem("opf_user_id", String(result.user.id));
      window.location.href = result.user.role === "engineer" ? "/today" : "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ maxWidth: 480, margin: "64px auto", padding: 28 }}>
      <div className="app-header-badge" style={{ display: "inline-block", marginBottom: 14 }}>
        {branding ? `${branding.name.toUpperCase()} PORTAL` : "OPERATIONS PLATFORM"}
      </div>
      <h1 style={{ fontSize: "2rem", letterSpacing: "-0.04em", margin: "0 0 8px" }}>
        {challengeToken ? "Verify your identity" : branding?.brand_login_headline || "Welcome back"}
      </h1>
      <p className="muted" style={{ marginTop: 0, lineHeight: 1.6 }}>
        {challengeToken
          ? "Enter the current code from your authenticator app or one unused recovery code."
          : "Sign in to manage inventory, field work and customer operations in one place."}
      </p>
      {!challengeToken && (
        <p className="notice" style={{ lineHeight: 1.5 }}>
          Engineer sign-in securely registers this phone. Claimed work orders can only be changed by the same account on the registered device.
        </p>
      )}
      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
        {!challengeToken && (
          <>
            <label>
              Email
              <input
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label>
              Password
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={10}
                required
              />
            </label>
          </>
        )}
        {challengeToken && (
          <label>
            Authenticator or recovery code
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value)}
              minLength={6}
              maxLength={32}
              autoFocus
              required
            />
          </label>
        )}
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy}>
          {busy ? "Signing in…" : challengeToken ? "Verify and continue" : "Continue to workspace"}
        </button>
        {challengeToken ? (
          <button
            type="button"
            className="secondary"
            onClick={() => { setChallengeToken(""); setMfaCode(""); setError(""); }}
          >
            Restart sign-in
          </button>
        ) : (
          <Link href="/forgot-password" style={{ textAlign: "center" }}>Forgot your password?</Link>
        )}
      </form>
    </section>
  );
}
