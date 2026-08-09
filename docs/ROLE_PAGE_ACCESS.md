# Role page access

OpenPartsFlow resolves access in three layers:

1. the signed-in organization role provides the default workspace;
2. effective enterprise permissions can allow or deny delegated employee,
   report, audit, Agent, or integration pages;
3. the API repeats the authoritative role, tenant, work-order ownership,
   registered-device, claim-version, inventory-custody, and reauthentication
   checks.

The navigation and direct-route guard share one fail-closed policy. Hiding a
navigation item is not treated as authorization; an unavailable direct URL is
blocked in the application shell and its API remains independently protected.

## Default workspaces

| Area | Manager | Warehouse | Technician | Organization admin |
| --- | --- | --- | --- | --- |
| Dashboard, calendar, team map | Allow | Deny | Map only | Allow |
| Organization work-order pool | Manage/create; execution writes denied | Deny | Team read-only; own claimed job executes on bound phone | Manage/create/correct with audit |
| Inventory balances, ledger, reconciliation, van planning, regions | Allow | Allow | Own van only | Allow |
| Scan, service knowledge, photo memory, sync, profile | Allow | Allow | Allow | Allow |
| Warehouse tasks, stock rules, counts, form actions | Allow | Allow | Deny | Allow |
| Employee directory | `users.read` default | Deny by default | Deny by default | Allow |
| Reports, analytics, profit and usage review | `reports.read` default | Deny by default | Own performance only | Allow |
| Operations Agent | `agent.use` default | Deny by default | Deny by default | Allow |
| Audit logs | `audit.read` default | Deny by default | Deny by default | Allow |
| Integrations and parallel run | `integrations.read` default | Deny by default | Deny by default | Allow |
| Settings and job forms | Read/operational scope | Deny | Deny | Full tenant administration |
| Imports | Allow | Allow | Deny | Allow |
| Backups and sync conflict decisions | Deny | Deny | Deny | Allow |
| Platform customer/operations pages | Deny | Deny | Deny | Platform admin only |

The assistant role has profile-only page access.

## Technician visibility and ownership

Technicians can open **Work Orders** to see the organization-wide pool,
claimant, completion attribution, and progress. The overview contains no edit
or save control for a technician. Field changes continue through the work-order
detail workflow and require the same authenticated technician, registered
device, and current claim generation that owns the job. Other technicians'
jobs remain read-only. Financial fields, customer signature data, and device
record identifiers remain server-redacted.

## Individual overrides

An organization administrator can apply audited `allow`, `deny`, or `inherit`
overrides from **Employees** for the enterprise permission catalog. An explicit
deny removes the corresponding navigation entry and direct page access as soon
as the current permission matrix is refreshed. Administrator permissions and
the non-delegable ownership/custody controls cannot be overridden.
