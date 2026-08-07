"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EngineerDashboard, InvitationCreated, OrganizationSettings, PermissionEffect, User, UserPermissionMatrix, UserRole } from "@/types";
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
  const [effectivePermissions, setEffectivePermissions] = useState<string[] | null>(null);
  const [permissionUser, setPermissionUser] = useState<User | null>(null);
  const [permissionMatrix, setPermissionMatrix] = useState<UserPermissionMatrix | null>(null);
  const [permissionReason, setPermissionReason] = useState("Administrative access adjustment");
  const [permissionError, setPermissionError] = useState("");
  const [permissionNotice, setPermissionNotice] = useState("");
  const [permissionSaving, setPermissionSaving] = useState("");

  useEffect(() => {
    const currentRole = getCurrentRole();
    setRole(currentRole);
    api.getMyPermissions()
      .then((matrix) => setEffectivePermissions(matrix.effective_permissions))
      .catch(() => setEffectivePermissions(
        currentRole === "admin" || currentRole === "manager" ? ["users.read"] : []
      ));
  }, []);

  useEffect(() => {
    if (!effectivePermissions?.includes("users.read")) return;
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
  }, [effectivePermissions]);

  async function openPermissions(user: User) {
    setPermissionUser(user);
    setPermissionMatrix(null);
    setPermissionError("");
    setPermissionNotice("");
    try {
      setPermissionMatrix(await api.getUserPermissions(user.id));
    } catch (error) {
      setPermissionError(error instanceof Error ? error.message : "Unable to load permissions");
    }
  }

  async function changePermission(permissionCode: string, effect: PermissionEffect) {
    if (!permissionUser || permissionReason.trim().length < 3) {
      setPermissionError("Enter a reason with at least 3 characters.");
      return;
    }
    setPermissionSaving(permissionCode);
    setPermissionError("");
    setPermissionNotice("");
    try {
      const matrix = await api.setUserPermission(
        permissionUser.id,
        permissionCode,
        effect,
        permissionReason.trim()
      );
      setPermissionMatrix(matrix);
      setPermissionNotice(`Updated ${permissionCode}. The change is recorded in the audit log.`);
    } catch (error) {
      setPermissionError(error instanceof Error ? error.message : "Unable to update permission");
    } finally {
      setPermissionSaving("");
    }
  }

  if (effectivePermissions === null) {
    return <section className="card">Loading access policy…</section>;
  }

  if (!effectivePermissions.includes("users.read")) {
    return <section className="card">Your current access policy does not allow the employee directory.</section>;
  }

  return (
    <ManagerShell
      title="Employees"
      subtitle="Role, effective access policy, and technician performance overview."
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
          {createdInvite && (
            <div className="success" style={{ marginTop: 12 }}>
              {createdInvite.invitation_url ? (
                <>Local development invitation link (shown once): <a href={createdInvite.invitation_url}>{createdInvite.invitation_url}</a></>
              ) : (
                <>Invitation email queued for {createdInvite.email}. For account security, the sign-up link is sent only to the invited employee.</>
              )}
            </div>
          )}
        </div>
      )}
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Role</th>
            <th>Open Jobs</th>
            <th>Completed Jobs</th>
            {role === "admin" && <th>Access policy</th>}
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
                {role === "admin" && (
                  <td><button type="button" onClick={() => void openPermissions(u)}>Permissions</button></td>
                )}
              </tr>
            );
          })}
        </tbody>
      </table>
      {role === "admin" && permissionUser && (
        <div className="card" style={{ marginTop: 24 }}>
          <h2>Access policy · {permissionUser.name}</h2>
          <p className="muted">
            Role defaults remain active unless an explicit allow or deny is selected. Deny takes priority.
            Every change records the administrator, target, reason, previous value, and new value.
          </p>
          {permissionUser.role === "admin" ? (
            <p>Administrator permissions are role-controlled and cannot be overridden.</p>
          ) : (
            <>
              <label>
                Change reason
                <input
                  value={permissionReason}
                  minLength={3}
                  maxLength={500}
                  onChange={(event) => setPermissionReason(event.target.value)}
                />
              </label>
              {permissionMatrix && (
                <table style={{ marginTop: 16 }}>
                  <thead><tr><th>Permission</th><th>Role default</th><th>Effective</th><th>Override</th></tr></thead>
                  <tbody>
                    {permissionMatrix.definitions.map((definition) => {
                      const override = permissionMatrix.overrides.find(
                        (item) => item.permission_code === definition.code
                      );
                      const effective = permissionMatrix.effective_permissions.includes(definition.code);
                      return (
                        <tr key={definition.code}>
                          <td>
                            <strong>{definition.name}</strong>
                            <div className="muted">{definition.code} · {definition.description}</div>
                          </td>
                          <td>{permissionMatrix.role_permissions.includes(definition.code) ? "Allowed" : "Not allowed"}</td>
                          <td>{effective ? "Allowed" : "Denied"}</td>
                          <td>
                            <select
                              value={override?.effect ?? "inherit"}
                              disabled={permissionSaving === definition.code}
                              onChange={(event) => void changePermission(
                                definition.code,
                                event.target.value as PermissionEffect
                              )}
                            >
                              <option value="inherit">Inherit role</option>
                              <option value="allow">Explicit allow</option>
                              <option value="deny">Explicit deny</option>
                            </select>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </>
          )}
          {permissionError && <div className="error" style={{ marginTop: 12 }}>{permissionError}</div>}
          {permissionNotice && <div className="success" style={{ marginTop: 12 }}>{permissionNotice}</div>}
        </div>
      )}
    </section>
    </ManagerShell>
  );
}
