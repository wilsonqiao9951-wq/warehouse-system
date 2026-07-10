"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { EngineerDashboard, User } from "@/types";
import { AppRole, getCurrentRole } from "@/lib/role";
import ManagerShell from "@/components/manager-shell";

export default function EmployeesPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [performance, setPerformance] = useState<Record<number, EngineerDashboard>>({});
  const [role, setRole] = useState<AppRole>("admin");

  useEffect(() => {
    setRole(getCurrentRole());
  }, []);

  useEffect(() => {
    if (role !== "manager" && role !== "admin") return;
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
        { label: "Engineers", value: users.filter((u) => u.role === "engineer").length }
      ]}
    >
    <section className="card">
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
