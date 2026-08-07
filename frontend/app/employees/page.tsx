"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EngineerDashboard, InvitationCreated, OrganizationSettings, User, UserRole } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function EmployeesPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [performance, setPerformance] = useState<Record<number, EngineerDashboard>>({});
  const [role, setRole] = useState<AppRole>("admin");
  const [invite, setInvite] = useState({ name: "", email: "", role: "engineer" as UserRole });
  const [createdInvite, setCreatedInvite] = useState<InvitationCreated | null>(null);
  const [inviteError, setInviteError] = useState("");
  const [organization, setOrganization] = useState<OrganizationSettings | null>(null);

  useEffect(() => {
    setRole(getCurrentRole());
  }, []);

  useEffect(() => {
    if (role !== "manager" && role !== "admin") return;
    api.getOrganizationSettings().then(setOrganization).catch(() => setOrganization(null));
    api.listUsers().then(async (allUsers) => {
      setUsers(allUsers);
      const engineers = allUsers.filter((u) => u.role === "engineer");
      const dashboards = await Promise.all(engineers.map((u) => api.getEngineerDashboard(u.id).catch(() => null)));
      const map: Record<number, EngineerDashboard> = {};
      dashboards.forEach((item) => {
        if (item) map[item.user_id] = item;
      });
      setPerformance(map);
    });
  }, [role]);

  if (role !== "manager" && role !== "admin") {
    return <section className="card">Employee performance is available to manager/admin role only.</section>;
  }

  return (
    <ManagerShell
      title="Employees"
      subtitle="Role and technician performance overview."
      metrics={[
        { label: "Employees", value: users.length },
        { label: "Engineers", value: users.filter((u) => u.role === "engineer").length },
        {
          label: "Plan seats",
          value: organization
            ? `${organization.active_users + organization.pending_invitations}/${organization.max_users ?? "Unlimited"}`
            : "—"
        }
      ]}
    >
    <section className="card">
      {role === "admin" && (
        <div style={{ marginBottom: 24 }}>
          <h2>Invite employee</h2>
          <div className="two-col">
            <input placeholder="Employee name" value={invite.name} onChange={(e) => setInvite({ ...invite, name: e.target.value })} />
            <input type="email" placeholder="Employee email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
            <select value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value as UserRole })}>
              <option value="engineer">Technician</option><option value="warehouse">Warehouse</option><option value="manager">Manager</option><option value="admin">Admin</option>
            </select>
            <button type="button" onClick={() => {
              setInviteError(""); setCreatedInvite(null);
              api.createInvitation(invite).then((created) => {
                setCreatedInvite(created);
                void api.getOrganizationSettings().then(setOrganization).catch(() => undefined);
              }).catch((e: Error) => setInviteError(e.message));
            }}>Create invitation</button>
          </div>
          {organization && (
            <p className="muted">
              {organization.plan_code} plan: {organization.active_users} active users and {organization.pending_invitations} open invitations use {organization.max_users ?? "unlimited"} seats.
            </p>
          )}
          {inviteError && <div className="error">{inviteError}</div>}
          {createdInvite && <div className="success" style={{ marginTop: 12 }}>Invitation link (shown once): <a href={createdInvite.invitation_url}>{createdInvite.invitation_url}</a></div>}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Open Jobs</th>
            <th>Completed Jobs</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => {
            const perf = performance[u.id];
            return (
              <tr key={u.id}>
                <td>{u.name}</td>
                <td>{u.role}</td>
                <td>{perf?.open_work_orders ?? "-"}</td>
                <td>{perf?.completed_work_orders ?? "-"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
    </ManagerShell>
  );
}
