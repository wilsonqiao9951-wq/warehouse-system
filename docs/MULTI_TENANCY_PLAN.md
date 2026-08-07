# Multi-tenancy implementation status

OpenPartsFlow now enforces tenant ownership at the API, ORM, and PostgreSQL
database layers. Multi-customer operation is no longer dependent on callers
remembering to add an `organization_id` filter.

## Active controls

- `organizations` is the tenant root and every tenant model has a non-null
  `organization_id` foreign key.
- Formal Cookie/Bearer authentication resolves the user from server-owned
  records and verifies the signed organization and revocable auth version.
- Every authenticated session is narrowed to the resolved organization before
  business queries run. API-key requests are narrowed after the key owner is
  resolved.
- ORM reads receive tenant loader criteria and ORM writes inherit or validate
  the active organization.
- Cross-organization object references are rejected in operational,
  inventory, integration, billing, backup, and knowledge workflows.
- PostgreSQL revision `20260807_0053` enables and forces one read/write RLS
  policy on every tenant model. A contract test requires the migration table
  list to remain identical to the ORM tenant model registry.
- Transaction-local PostgreSQL settings carry the tenant scope and are cleared
  automatically on commit/rollback before a pooled connection can be reused.
- Platform-wide access is opened only for authentication/bootstrap resolution,
  verified platform-administrator operations, and explicitly reviewed
  cross-tenant workers.
- Production uses separate migration-owner and restricted application roles;
  the application role is `NOSUPERUSER NOBYPASSRLS NOINHERIT`.
- Warehouse names and codes are unique within an organization, not globally,
  so separate customers may use the same operational naming convention.

## Defense model

```text
authenticated identity / API key
  -> application authorization and ownership checks
  -> ORM tenant read/write scope
  -> transaction-local PostgreSQL RLS context
  -> forced database read/write policy
```

Frontend capability flags remain usability hints only. Work-order ownership,
registered-device, claim-version, completion-password, role, permission, and
tenant checks are all enforced server-side in addition to RLS.

Operational setup, verification, upgrade, and rollback requirements are in
[`POSTGRES_RLS.md`](POSTGRES_RLS.md).

## Ongoing change rule

Any new model containing `organization_id` must be added to `TENANT_MODELS` and
the next PostgreSQL migration must add the forced policy before release. CI
fails when the model and migration coverage sets differ. New platform-wide or
background access paths must use the reviewed scope helpers and include
cross-tenant denial tests.

Migration/model alignment is enforced on both SQLite and PostgreSQL as
documented in [`SCHEMA_CONTRACT.md`](SCHEMA_CONTRACT.md).
