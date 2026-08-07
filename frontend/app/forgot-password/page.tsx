"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { PasswordResetConfiguration } from "@/types";

export default function ForgotPasswordPage() {
  const [configuration, setConfiguration] = useState<PasswordResetConfiguration | null>(null);
  const [email, setEmail] = useState("");
  const [message, setMessage] = useState("");
  const [debugUrl, setDebugUrl] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getPasswordResetConfiguration()
      .then(setConfiguration)
      .catch((caught: Error) => setError(caught.message));
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    setDebugUrl(null);
    try {
      const result = await api.requestPasswordReset(email.trim());
      setMessage(result.message);
      setDebugUrl(result.reset_url || null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Unable to request a password reset");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ maxWidth: 520, margin: "64px auto", padding: 28 }}>
      <h1 style={{ marginTop: 0 }}>Reset password</h1>
      <p className="muted">
        Enter your account email. The response is intentionally identical whether or not an eligible account exists.
      </p>
      {configuration && !configuration.available ? (
        <div className="notice">Password reset delivery is not configured. Contact your organization administrator.</div>
      ) : (
        <form onSubmit={submit} style={{ display: "grid", gap: 14 }}>
          <label>Email<input type="email" autoComplete="email" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <button type="submit" disabled={busy || !configuration?.available}>{busy ? "Requesting…" : "Send reset instructions"}</button>
        </form>
      )}
      {message && <div className="success" style={{ marginTop: 14 }}>{message}</div>}
      {debugUrl && <div className="notice" style={{ marginTop: 14 }}>Local development link: <a href={debugUrl}>continue reset</a></div>}
      {error && <div className="error" style={{ marginTop: 14 }}>{error}</div>}
      <p style={{ marginBottom: 0 }}><Link href="/login">Return to sign in</Link></p>
    </section>
  );
}
