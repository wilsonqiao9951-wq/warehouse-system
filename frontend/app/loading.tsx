export default function Loading() {
  return (
    <section className="card">
      <p style={{ marginTop: 0 }}>Loading…</p>
      <div style={{ display: "grid", gap: 10 }}>
        <div className="skeleton" style={{ width: "40%" }} />
        <div className="skeleton" style={{ width: "88%" }} />
        <div className="skeleton" style={{ width: "72%" }} />
      </div>
      <p className="muted" style={{ fontSize: 14, marginBottom: 0 }}>
        If you are offline, open cached pages when available; API actions need a connection.
      </p>
    </section>
  );
}
