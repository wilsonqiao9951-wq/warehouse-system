"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";

export default function ResetPasswordPage() {
  const [token, setToken] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [complete, setComplete] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setToken(new URLSearchParams(window.location.search).get("token") || "");
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!token) return setError("Password reset token is missing.");
    if (password !== confirmation) return setError("Passwords do not match.");
    setBusy(true);
    setError("");
    try {
      await api.completePasswordReset(token, password);
      setComplete(true);
      setPassword("");
      setConfirmation("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to reset password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ maxWidth: 520, margin: "64px auto", padding: 28 }}>
      <h1 style={{ marginTop: 0 }}>Choose a new password</h1>
      {complete ? (
        <div className="success">Password changed and all previous sessions revoked. <Link href="/login">Sign in again</Link>.</div>
      ) : (
        <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
          <label>New password<input type="password" minLength={10} maxLength={128} autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          <label>Confirm new password<input type="password" minLength={10} maxLength={128} autoComplete="new-password" value={confirmation} onChange={(event) => setConfirmation(event.target.value)} required /></label>
          {error && <div className="error">{error}</div>}
          <button type="submit" disabled={busy || password.length < 10 || confirmation.length < 10}>{busy ? "Resetting…" : "Reset password"}</button>
        </form>
      )}
    </section>
  );
}
