"use client";

import ManagerShell from "@/components/manager-shell";

export default function SettingsPage() {
  return (
    <ManagerShell title="Settings" subtitle="Manager/Admin settings and policy controls." metrics={[{ label: "Modules", value: 1 }]}>
      <section className="card">
        <div className="notice notice-success">Settings framework page is ready for next configuration modules.</div>
      </section>
    </ManagerShell>
  );
}
