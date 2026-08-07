from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError

from app.core.config import settings


VERIFY_ROLE = "openpartsflow_rls_verifier"


def main() -> int:
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    if engine.dialect.name != "postgresql":
        print("PostgreSQL RLS verification skipped for non-PostgreSQL database.")
        return 0

    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE ROLE "{VERIFY_ROLE}" NOLOGIN NOBYPASSRLS'))
            connection.execute(
                text(f'GRANT USAGE ON SCHEMA public TO "{VERIFY_ROLE}"')
            )
            connection.execute(
                text(
                    f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES '
                    f'IN SCHEMA public TO "{VERIFY_ROLE}"'
                )
            )
            connection.execute(
                text(
                    f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public '
                    f'TO "{VERIFY_ROLE}"'
                )
            )
            first_organization = connection.scalar(
                text("SELECT COALESCE(MAX(id), 0) + 1000 FROM organizations")
            )
            second_organization = first_organization + 1
            first_part = connection.scalar(
                text("SELECT COALESCE(MAX(id), 0) + 1000 FROM parts")
            )
            connection.execute(
                text(
                    "INSERT INTO organizations (id, name, slug) VALUES "
                    "(:first_org, 'RLS Verify One', 'rls-verify-one'), "
                    "(:second_org, 'RLS Verify Two', 'rls-verify-two')"
                ),
                {
                    "first_org": first_organization,
                    "second_org": second_organization,
                },
            )
            connection.execute(
                text(
                    "INSERT INTO parts (id, organization_id, part_number, name) "
                    "VALUES (:first_part, :first_org, 'RLS-ONE', 'RLS part one'), "
                    "(:second_part, :second_org, 'RLS-TWO', 'RLS part two')"
                ),
                {
                    "first_part": first_part,
                    "second_part": first_part + 1,
                    "first_org": first_organization,
                    "second_org": second_organization,
                },
            )

            connection.execute(text(f'SET LOCAL ROLE "{VERIFY_ROLE}"'))
            connection.execute(
                text(
                    "SELECT set_config('openpartsflow.organization_id', '', true), "
                    "set_config('openpartsflow.platform_access', 'off', true)"
                )
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM parts")) == 0

            connection.execute(
                text(
                    "SELECT set_config('openpartsflow.organization_id', :org, true)"
                ),
                {"org": str(first_organization)},
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM parts")) == 1
            assert connection.scalar(
                text("SELECT part_number FROM parts")
            ) == "RLS-ONE"

            savepoint = connection.begin_nested()
            try:
                connection.execute(
                    text(
                        "INSERT INTO parts (organization_id, part_number, name) "
                        "VALUES (:other_org, 'RLS-BLOCKED', 'Blocked cross-tenant part')"
                    ),
                    {"other_org": second_organization},
                )
            except DBAPIError:
                savepoint.rollback()
            else:
                savepoint.rollback()
                raise AssertionError("PostgreSQL RLS allowed a cross-tenant insert")

            connection.execute(
                text(
                    "SELECT set_config('openpartsflow.organization_id', '', true), "
                    "set_config('openpartsflow.platform_access', 'on', true)"
                )
            )
            assert connection.scalar(text("SELECT COUNT(*) FROM parts")) == 2
            print("PostgreSQL tenant RLS read/write/platform verification passed.")
            return 0
        finally:
            transaction.rollback()


if __name__ == "__main__":
    raise SystemExit(main())
