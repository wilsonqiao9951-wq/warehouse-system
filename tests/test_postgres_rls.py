from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

from app.core.database import (
    _apply_postgres_rls_scope,
    set_platform_database_scope,
    set_tenant_database_scope,
)
from app.core.rbac import TENANT_MODELS


class _FakeConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self):
        self.calls = []

    def execute(self, statement, parameters):
        self.calls.append((str(statement), parameters))


class _FakeSession:
    def __init__(self):
        self.info = {"rls_platform_access": True}
        self.connection_value = _FakeConnection()
        self.transaction_active = False

    def in_transaction(self):
        return self.transaction_active

    def connection(self):
        return self.connection_value


def _migration_module(filename: str, module_name: str):
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / filename
    )
    spec = spec_from_file_location(module_name, path)
    module = module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_postgres_rls_migration_covers_every_tenant_model():
    baseline = _migration_module(
        "20260807_0053_postgres_row_level_security.py",
        "openpartsflow_rls_baseline_migration",
    )
    profit_snapshots = _migration_module(
        "20260807_0061_add_profit_snapshots.py",
        "openpartsflow_profit_snapshot_migration",
    )
    low_stock_rules = _migration_module(
        "20260807_0062_add_low_stock_rules.py",
        "openpartsflow_low_stock_rule_migration",
    )
    part_usage_reviews = _migration_module(
        "20260808_0063_add_part_usage_reviews.py",
        "openpartsflow_part_usage_review_migration",
    )
    model_tables = {model.__tablename__ for model in TENANT_MODELS}
    secured_tables = set(baseline.TENANT_TABLES) | {
        profit_snapshots.TABLE_NAME,
        low_stock_rules.RULE_TABLE,
        *part_usage_reviews.TENANT_TABLES,
    }
    assert secured_tables == model_tables
    assert len(secured_tables) == len(model_tables)
    for migration in (baseline, profit_snapshots, low_stock_rules, part_usage_reviews):
        assert "platform_access" in migration.POLICY_EXPRESSION
        assert "organization_id" in migration.POLICY_EXPRESSION


def test_postgres_scope_uses_transaction_local_settings():
    connection = _FakeConnection()
    session = SimpleNamespace(
        info={"organization_id": 42, "rls_platform_access": False}
    )
    _apply_postgres_rls_scope(session, connection)
    assert len(connection.calls) == 1
    statement, parameters = connection.calls[0]
    assert "set_config" in statement
    assert parameters == {"organization_id": "42", "platform_access": "off"}


def test_database_scope_switches_platform_and_tenant_without_pool_state():
    session = _FakeSession()
    set_tenant_database_scope(session, 7)
    assert session.info == {
        "organization_id": 7,
        "rls_platform_access": False,
    }
    assert session.connection_value.calls == []

    session.transaction_active = True
    set_platform_database_scope(session)
    assert session.info == {"rls_platform_access": True}
    assert session.connection_value.calls[-1][1] == {
        "organization_id": "",
        "platform_access": "on",
    }

    set_tenant_database_scope(session, 9)
    assert session.connection_value.calls[-1][1] == {
        "organization_id": "9",
        "platform_access": "off",
    }
