"use client";

import { FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { InvitationInfo } from "@/types";

export default function AcceptInvitationPage() {
  const params = useSearchParams();
  const token = params.get("token") || "";
  const [info, setInfo] = useState<InvitationInfo | null>(null);
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [complete, setComplete] = useState(false);

  useEffect(() => {
    if (!token) { setError("Invitation token is missing."); return; }
    api.getInvitation(token).then(setInfo).catch((e: Error) => setError(e.message));
  }, [token]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      setError("");
      await api.acceptInvitation(token, password);
      setComplete(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unable to accept invitation.");
    }
  };

  return <section className="card" style={{ maxWidth: 520, margin: "48px auto" }}>
    <h1>Accept invitation</h1>
    {info && <p>You are joining <strong>{info.organization_name}</strong> as {info.role}. Account: {info.email}</p>}
    {error && <div className="error">{error}</div>}
    {complete ? <div className="success">Account created. <a href="/login">Sign in</a></div> : info && <form onSubmit={submit} style={{ display: "grid", gap: 12 }}>
      <label>Create password<input type="password" minLength={10} value={password} onChange={(e) => setPassword(e.target.value)} required /></label>
      <button type="submit">Create account</button>
    </form>}
  </section>;
}
