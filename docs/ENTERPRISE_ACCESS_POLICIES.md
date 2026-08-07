# Enterprise Access Policies

OpenPartsFlow combines stable role defaults with administrator-controlled user
overrides. The API remains authoritative; navigation visibility is only a user
experience aid.

## Resolution order

1. An organization administrator always receives every catalog permission.
   Administrator permissions cannot be overridden, preventing tenant lockout.
2. A non-administrator starts with the defaults for their role.
3. An explicit `allow` adds one catalog permission.
4. An explicit `deny` removes one catalog permission, even when the role would
   normally allow it.
5. `inherit` deletes the override and immediately restores the role default.

Unknown permission codes are ignored during authentication and rejected by the
management API. An override never changes work-order ownership, claim, device,
claim-version, password, inventory-custody, or tenant-isolation checks.

## Initial catalog

| Permission | Default role(s) | Protected capability |
| --- | --- | --- |
| `users.read` | admin, manager | Tenant employee directory |
| `audit.read` | admin, manager | Audit search and summaries |
| `audit.export` | admin | Password-confirmed audit CSV export |
| `reports.read` | admin, manager | Performance, warehouse, abnormal-usage, profit, and work-order export reports |
| `integrations.read` | admin, manager | Integration configuration and delivery-log reads |
| `integrations.manage` | admin | Integration creation, mutation, key rotation, and delivery retry |

The catalog is deliberately allowlisted in application code. Arbitrary database
strings cannot create new capabilities.

## API

- `GET /api/permissions/catalog` returns the allowlisted definitions.
- `GET /api/permissions/me` returns role defaults, overrides, and effective
  permissions for the authenticated user.
- `GET /api/users/{user_id}/permissions` is organization-admin-only.
- `PUT /api/users/{user_id}/permissions/{permission_code}` is
  organization-admin-only and accepts `allow`, `deny`, or `inherit` plus a
  required reason.

The target must belong to the administrator's active organization. Attempts to
inspect another tenant return `404`. Non-administrators cannot grant permissions
even if they hold every delegable permission.

## Audit and secret handling

Every management call records `change_user_permission` with the administrator,
target user, catalog code/name, previous effect, new effect, and reason. It does
not record passwords, bearer tokens, device secrets, integration keys, or other
credentials.

The Employees page exposes the matrix only to administrators. Effective
permissions also drive the Employees, Reports, Audit Logs, and Integrations
navigation entries, including explicit role-default denials.

## Deployment

Alembic revision `20260807_0042` creates `user_permission_grants` with tenant,
user, and permission uniqueness plus tenant/user lookup indexes. Apply it before
starting this application version:

```text
alembic upgrade head
```

The permission rows participate in the same ORM tenant read/write filters as
other customer data. Portable exports retain them as tenant evidence, while
controlled restores treat access policy and other authentication/security
records as protected rather than overwriting live authorization state.
