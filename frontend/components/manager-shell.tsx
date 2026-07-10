"use client";

type Metric = { label: string; value: string | number };

export default function ManagerShell({
  title,
  subtitle,
  metrics,
  children
}: {
  title: string;
  subtitle?: string;
  metrics?: Metric[];
  children: React.ReactNode;
}) {
  return (
    <section>
      {metrics && metrics.length > 0 && (
        <div className="grid" style={{ marginBottom: 12 }}>
          {metrics.map((m) => (
            <div className="card" key={m.label} style={{ marginBottom: 0 }}>
              <div className="muted">{m.label}</div>
              <div className="metric">{m.value}</div>
            </div>
          ))}
        </div>
      )}
      <div className="card">
        <h2 style={{ marginTop: 0, marginBottom: 6 }}>{title}</h2>
        {subtitle && (
          <p className="muted" style={{ marginTop: 0 }}>
            {subtitle}
          </p>
        )}
        <div className="two-col" style={{ marginTop: 8 }}>
          <input placeholder="Search…" />
          <select defaultValue="">
            <option value="">All Status</option>
            <option value="open">open</option>
            <option value="in_progress">in_progress</option>
            <option value="completed">completed</option>
          </select>
        </div>
      </div>
      {children}
    </section>
  );
}
