# PostgreSQL row-level security

Revision `20260807_0053` adds database-level tenant isolation to every current
OpenPartsFlow tenant table. It is defense in depth behind authenticated API
authorization and the existing ORM tenant filter; it does not replace either.

## Policy contract

Each tenant table has RLS enabled and forced with the policy
`openpartsflow_tenant_isolation`. Reads and writes are accepted only when one
of these transaction-local conditions is true:

- `openpartsflow.organization_id` exactly matches the row's
  `organization_id`; or
- `openpartsflow.platform_access` is `on` for a reviewed platform operation.

OpenPartsFlow writes both settings with PostgreSQL `set_config(..., true)`.
The final `true` makes the setting transaction-local, so commit or rollback
clears it before SQLAlchemy returns the connection to the pool. Tenant identity
resolution uses a temporary bootstrap scope, then immediately narrows the same
transaction to the authenticated user's or API key's organization. Verified
platform administrators and reviewed cross-tenant workers must switch scope
explicitly through the database helpers.

The migration's table list is intentionally static so schema review shows
exactly which tables changed. `tests/test_postgres_rls.py` compares it with the
live `TENANT_MODELS` registry and fails if a future tenant model is omitted.

## Required database roles

Never run the API as the PostgreSQL initialization user, table owner,
superuser, or a role with `BYPASSRLS`. Production uses two independent
credentials:

| Role | Used by | Required capability |
| --- | --- | --- |
| `POSTGRES_OWNER_USER` | one-shot Alembic migrator | owns/changes schema; never used by API |
| `POSTGRES_APP_USER` | API and in-process workers | login, schema usage, table DML, sequence use; `NOSUPERUSER NOBYPASSRLS NOINHERIT` |

Use different high-entropy passwords in `POSTGRES_PASSWORD` and
`POSTGRES_APP_PASSWORD`. `MIGRATION_DATABASE_URL` contains the owner credential;
`DATABASE_URL` contains only the restricted application credential.

For a fresh Compose volume,
`deploy/postgres/init-app-role.sh` creates the restricted role and grants both
existing and owner-default object privileges before Alembic runs. The script is
idempotent and may be rerun to rotate the application password or repair grants.

## Existing-volume upgrade

Take and verify the database plus evidence-volume recovery point first. Add the
new owner/app variables and split URLs from `.env.production.example`, then:

```bash
export OPENPARTSFLOW_ENV_FILE=.env.production
docker compose --env-file .env.production -f docker-compose.production.yml up -d db
docker compose --env-file .env.production -f docker-compose.production.yml exec db \
  /docker-entrypoint-initdb.d/10-openpartsflow-app-role.sh
docker compose --env-file .env.production -f docker-compose.production.yml run --rm migrate
docker compose --env-file .env.production -f docker-compose.production.yml up -d --force-recreate api web
```

Do not switch `DATABASE_URL` to the restricted role before the bootstrap script
succeeds. Do not put the owner URL into the API service as a workaround.

## Verification

Run the integration verifier with the migration-owner URL in an isolated or
maintenance environment:

```bash
DATABASE_URL="$MIGRATION_DATABASE_URL" python -m scripts.verify_postgres_rls
```

The verifier runs inside one rolled-back transaction. It creates a temporary
`NOBYPASSRLS` role, proves an empty scope reads no tenant rows, proves one tenant
cannot read or write another tenant's rows, and proves the explicit platform
scope can read both. CI runs it against PostgreSQL 16 after every migration.

Also verify the runtime role flags:

```sql
SELECT rolname, rolsuper, rolbypassrls, rolinherit
FROM pg_roles
WHERE rolname = 'openpartsflow_app';
```

Expected values are `false`, `false`, and `false` for the three capability
columns. Confirm all current tenant tables have the named policy before opening
traffic.

## Rollback

Application rollback must use a complete pre-change recovery point unless a
downgrade was rehearsed for that exact release. Revision `0053` downgrade drops
the policies and disables/unwraps RLS; it does not remove the restricted role.
Keep the API stopped during a downgrade, use the owner URL, verify the target
schema, and never point older code at a newer schema.
