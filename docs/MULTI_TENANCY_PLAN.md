# Multi-tenancy implementation plan

OpenPartsFlow is being migrated from a single-company application to a tenant-aware SaaS platform.

## Current foundation

- `organizations` is the tenant root entity.
- Core operational records carry a non-null `organization_id` foreign key.
- Existing records are assigned to organization `1` (`default`) during migration.
- API response models expose `organization_id` for verification and support diagnostics.
- Authenticated `X-User-Id` actors derive their organization from the server-side user record.
- ORM reads are automatically scoped to the actor's organization.
- New tenant-owned records automatically inherit the actor's organization.
- Cross-organization object references are rejected in core operational flows.
- Global uniqueness rules remain in place during this compatibility phase.

## Required next phase

The core isolation layer is now active, but the temporary `X-User-Id` authentication mechanism is not suitable for selling the product. Before onboarding more than one production customer:

1. Replace `X-User-Id` with formal authentication and account lifecycle management.
2. Complete cross-organization denial tests for every API and import/export domain.
3. Replace global unique constraints with organization-scoped composite constraints where appropriate.
4. Enable PostgreSQL Row-Level Security as defense in depth.
5. Add a platform-admin control plane for creating, suspending and supporting organizations.

Until those steps are complete, production must continue to operate as a single organization.
