# Database schema contract

OpenPartsFlow treats the Alembic migration chain as the deployed database
history and SQLAlchemy metadata as the current application contract. Both must
describe the same columns, nullability, constraints, and indexes after every
release.

## Automated gate

CI now creates both databases from an empty state and runs:

```bash
alembic upgrade head
alembic check
```

The backend job checks SQLite compatibility and the private-deployment job
checks PostgreSQL 16. A pull request fails if SQLAlchemy autogeneration can find
any unapplied model operation. PostgreSQL RLS policies are migration-owned
database security objects and remain covered separately by
`scripts.verify_postgres_rls`.

## Revision 20260807_0054

The reconciliation migration resolves all previously detected drift:

- removes model declarations for five redundant primary-key indexes that never
  existed in deployed databases;
- records the existing knowledge-origin, restore-retention, work-order
  customer/equipment history, and work-order claim indexes in model metadata;
- backfills missing knowledge/recognition timestamps and makes the eight
  application-required timestamp columns non-null;
- replaces the legacy global warehouse-name uniqueness rule with
  `(organization_id, name)`, matching the existing tenant-scoped warehouse code
  rule and allowing separate customers to use the same operational name.

The downgrade refuses to restore global warehouse-name uniqueness if different
organizations have already used the same name. This check runs before any
schema mutation, leaving revision `0054` intact on refusal.

## Change procedure

For every future schema change:

1. update the SQLAlchemy model contract;
2. add an explicit Alembic revision with upgrade and safe downgrade behavior;
3. backfill before adding non-null constraints;
4. preserve or explicitly remove production query indexes;
5. add tenant and data-preservation tests;
6. run empty-database upgrade, downgrade/re-upgrade, and `alembic check` on
   SQLite and PostgreSQL;
7. extend portable-restore revision compatibility when record format remains
   compatible;
8. record the migration and verification evidence before deployment.

Do not use `alembic stamp` to hide drift. A database with business tables and
unknown history must use the legacy adoption workflow, and a production
database must be backed up before any migration.
