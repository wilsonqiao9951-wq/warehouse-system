"use client";

import { FormEvent, useState } from "react";
import { api } from "@/lib/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setBusy(true);
      setError("");
      const result = await api.login(email.trim(), password);
      window.localStorage.setItem("opf_access_token", result.access_token);
      window.localStorage.setItem("opf_role", result.user.role);
      window.localStorage.setItem("opf_user_id", String(result.user.id));
      window.location.href = "/";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to sign in.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="card" style={{ maxWidth: 480, margin: "64px auto", padding: 28 }}>
      <div className="app-header-badge" style={{ display: "inline-block", marginBottom: 14 }}>OPERATIONS PLATFORM</div>
      <h1 style={{ fontSize: "2rem", letterSpacing: "-0.04em", margin: "0 0 8px" }}>Welcome back</h1>
      <p className="muted" style={{ marginTop: 0, lineHeight: 1.6 }}>Sign in to manage inventory, field work and customer operations in one place.</p>
      <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
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
        {error && <div className="error">{error}</div>}
        <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Continue to workspace"}</button>
      </form>
    </section>
  );
}
