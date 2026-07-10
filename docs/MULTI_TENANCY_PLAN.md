# Multi-tenancy implementation plan

OpenPartsFlow is being migrated from a single-company application to a tenant-aware SaaS platform.

## Current foundation

- `organizations` is the tenant root entity.
- Core operational records carry a non-null `organization_id` foreign key.
- Existing records are assigned to organization `1` (`default`) during migration.
- API response models expose `organization_id` for verification and support diagnostics.
- Global uniqueness rules remain in place during this compatibility phase.

## Required next phase

The schema foundation alone does not enforce tenant isolation. Before onboarding more than one customer:

1. Derive `organization_id` from an authenticated user, never from an untrusted request body.
2. Apply organization predicates to every query and ownership checks to every referenced entity.
3. Replace global unique constraints with organization-scoped composite constraints where appropriate.
4. Add cross-organization denial tests for every API domain.
5. Enable PostgreSQL Row-Level Security as defense in depth.

Until those steps are complete, production must continue to operate as a single organization.
