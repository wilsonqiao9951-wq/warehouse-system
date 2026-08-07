# Enterprise data residency controls

OpenPartsFlow can pin an Enterprise organization to the deployment region that
is allowed to serve and process it. This is an enforcement boundary, not an
automatic data-movement feature.

## Deployment identity

Every staging and production runtime must declare one normalized region code:

```env
DEPLOYMENT_REGION=us-east-1
```

Codes use 2-64 lowercase letters, numbers, and single hyphens. `local`, blank,
mixed-case, and free-form values fail production validation. Local development
defaults to `local` and organizations remain unpinned unless explicitly
configured.

Before starting workers or serving traffic, production and staging query the
database for pinned organizations. If any organization belongs to another
region, startup fails closed. Operators must correct the deployment setting or
complete a controlled migration while the deployment remains offline.

## Organization policy

Only a platform administrator can set or clear `data_residency_region`, and the
organization must be on the Enterprise plan. A new assignment must exactly
match the current deployment's region. Changing the policy requires the
platform administrator's current account password and the organization's
current `settings_version`.

The platform response exposes:

- `data_residency_region`: contractual region, or `null` when unpinned;
- `data_residency_enforced_at`: when the current assignment was established;
- `deployment_region`: this running data plane;
- `data_residency_status`: `unrestricted`, `compliant`, or `blocked`.

Every change creates organization-scoped audit evidence containing the actor,
old/new region, enforcement timestamp, and settings version. Passwords and
session credentials are never included.

## Runtime enforcement

If a pinned organization and runtime region do not match, OpenPartsFlow blocks:

- password and MFA-completed login;
- existing Cookie and Bearer sessions;
- invitation viewing and acceptance;
- external API keys;
- public slug/domain branding lookup.

The startup database guard additionally prevents integration and billing
workers from running against a mismatched database. Platform administrators can
still inspect the mismatch only in development/test recovery contexts; a real
production runtime will not start until the database is region-consistent.

## Moving an organization

Changing a label does not move PostgreSQL rows, evidence volumes, backups,
logs, or provider data. A cross-region move requires a maintenance window:

1. stop user writes and background workers in the source region;
2. create and verify encrypted database and evidence-volume recovery points;
3. use the governed organization export/restore evidence where applicable;
4. restore and validate the target data plane in isolation;
5. set the organization policy on the target deployment with password-confirmed
   platform administration;
6. verify schema head, RLS, checksums, tenant access, and readiness;
7. redirect traffic only after the target is compliant;
8. retain or destroy the source copy according to the customer's contract and
   record the decision outside the application.

OpenPartsFlow does not claim that a shared database containing an out-of-region
copy is compliant. Infrastructure backups, object storage, centralized logs,
SMTP, billing providers, AI providers, and external integrations need their own
contractual residency review.

## Migration and rollback

Alembic revision `20260807_0055` adds the nullable region, enforcement
timestamp, consistency constraint, and platform query index. Existing
organizations remain unpinned. Downgrade is refused while any organization has
residency evidence, preventing silent removal of an active contractual control.
