from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import engine
from app.models import InventoryRegion, Organization, Part, User, UserRole, Warehouse


class ScaleVerificationError(RuntimeError):
    pass


_SCALE_ID_TABLES = frozenset(
    {
        "organizations",
        "users",
        "inventory_regions",
        "warehouses",
        "parts",
        "work_orders",
        "work_order_parts",
        "inventory_transactions",
    }
)
_REQUIRED_SCALE_INDEXES = frozenset(
    {
        "ix_work_orders_org_id",
        "ix_work_orders_org_schedule_id",
        "ix_inventory_transactions_org_id",
        "ix_work_order_parts_org_id",
        "ix_work_order_parts_org_user_id",
    }
)


def _next_id(session: Session, table: str) -> int:
    if table not in _SCALE_ID_TABLES:
        raise ScaleVerificationError(f"Unsupported scale seed table: {table}")
    return int(
        session.execute(
            text(f"SELECT COALESCE(MAX(id), 0) + 1 FROM {table}")
        ).scalar_one()
    )


def _missing_required_indexes(available: set[str]) -> list[str]:
    return sorted(_REQUIRED_SCALE_INDEXES - available)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        raise ScaleVerificationError("No latency samples were collected")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _plan_nodes(plan: dict) -> list[dict]:
    nodes = [plan]
    for child in plan.get("Plans", []):
        nodes.extend(_plan_nodes(child))
    return nodes


def _explain(session: Session, sql: str, parameters: dict) -> tuple[list[str], list[str]]:
    raw = session.execute(
        text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {sql}"), parameters
    ).scalar_one()
    payload = raw if isinstance(raw, list) else json.loads(raw)
    nodes = _plan_nodes(payload[0]["Plan"])
    node_types = sorted({str(node.get("Node Type", "unknown")) for node in nodes})
    indexes = sorted(
        {str(node["Index Name"]) for node in nodes if node.get("Index Name")}
    )
    return node_types, indexes


def _time_query(
    session: Session,
    sql: str,
    parameters: dict,
    *,
    warmups: int,
    samples: int,
) -> tuple[list[float], int]:
    row_count = 0
    for _ in range(warmups):
        session.execute(text(sql), parameters).all()
    durations: list[float] = []
    for _ in range(samples):
        started = time.perf_counter()
        rows = session.execute(text(sql), parameters).all()
        durations.append((time.perf_counter() - started) * 1000)
        row_count = len(rows)
    return durations, row_count


def _assert_local_postgres() -> None:
    normalized = settings.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"postgresql", "postgres"}:
        raise ScaleVerificationError("Scale verification requires PostgreSQL")
    if (parsed.hostname or "").lower() not in {"127.0.0.1", "localhost", "::1"}:
        raise ScaleVerificationError(
            "Scale verification is destructive test-only work and requires a loopback database"
        )


def _seed(session: Session, work_orders: int, transactions: int) -> dict[str, int]:
    suffix = uuid4().hex[:12]
    organization_id = _next_id(session, "organizations")
    primary = Organization(
        id=organization_id,
        name="Scale verification primary",
        slug=f"scale-primary-{suffix}",
        max_users=max(50, 100),
        max_warehouses=20,
    )
    noise = Organization(
        id=organization_id + 1,
        name="Scale verification noise",
        slug=f"scale-noise-{suffix}",
        max_users=max(50, 100),
        max_warehouses=20,
    )
    session.add_all([primary, noise])
    session.flush()
    engineer = User(
        id=_next_id(session, "users"),
        organization_id=primary.id,
        name="Scale engineer",
        email=f"scale-engineer-{suffix}@example.invalid",
        role=UserRole.ENGINEER,
    )
    region = InventoryRegion(
        id=_next_id(session, "inventory_regions"),
        organization_id=primary.id,
        code="PRIMARY",
        name="Primary",
        timezone="UTC",
        is_default=True,
    )
    session.add_all([engineer, region])
    session.flush()
    warehouse = Warehouse(
        id=_next_id(session, "warehouses"),
        organization_id=primary.id,
        code="SCALE",
        name="Scale warehouse",
        region_id=region.id,
    )
    part = Part(
        id=_next_id(session, "parts"),
        organization_id=primary.id,
        part_number=f"SCALE-{suffix}",
        name="Scale verification part",
        default_cost=1.0,
    )
    session.add_all([warehouse, part])
    session.flush()

    work_order_start = _next_id(session, "work_orders")
    work_order_part_start = _next_id(session, "work_order_parts")
    inventory_transaction_start = _next_id(session, "inventory_transactions")
    common_columns = """
        id, organization_id, form_version, form_data_json, claim_version,
        ticket_number, schedule_date, job_type, machine_type,
        assigned_user_id, engineer_id, completed_by_id,
        revenue, labor_cost, status, completed_at, final_outcome,
        first_time_fix, is_rework, repair_duration_minutes, is_locked,
        created_at, updated_at
    """
    session.execute(
        text(
            f"""
            INSERT INTO work_orders ({common_columns})
            SELECT :work_order_start + value - 1, :organization_id, 0, '{{}}', 0,
                   :prefix || '-' || value::text,
                   CURRENT_DATE - ((value % 180)::int),
                   CASE WHEN value % 2 = 0 THEN 'preventive' ELSE 'repair' END,
                   CASE WHEN value % 3 = 0 THEN 'ACME-9000' ELSE 'ACME-7000' END,
                   :engineer_id, :engineer_id, :engineer_id,
                   200.0, 50.0, 'completed',
                   CURRENT_TIMESTAMP - ((value % 180)::int * INTERVAL '1 day'),
                   'fixed', true, false, 60, true,
                   CURRENT_TIMESTAMP - ((value % 180)::int * INTERVAL '1 day'),
                   CURRENT_TIMESTAMP
            FROM generate_series(1, :work_orders) AS value
            """
        ),
        {
            "organization_id": primary.id,
            "work_order_start": work_order_start,
            "engineer_id": engineer.id,
            "prefix": f"SCALE-{suffix}",
            "work_orders": work_orders,
        },
    )
    session.execute(
        text(
            f"""
            INSERT INTO work_orders ({common_columns})
            SELECT :work_order_start + :work_orders + value - 1,
                   :organization_id, 0, '{{}}', 0,
                   :prefix || '-' || value::text,
                   CURRENT_DATE - ((value % 180)::int),
                   'noise', 'NOISE', NULL, NULL, NULL,
                   0.0, 0.0, 'open', NULL, NULL, NULL, false, NULL, false,
                   CURRENT_TIMESTAMP - ((value % 180)::int * INTERVAL '1 day'),
                   CURRENT_TIMESTAMP
            FROM generate_series(1, :work_orders) AS value
            """
        ),
        {
            "organization_id": noise.id,
            "work_order_start": work_order_start,
            "prefix": f"NOISE-{suffix}",
            "work_orders": work_orders,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO work_order_parts (
                id, organization_id, work_order_id, part_id, warehouse_id, user_id,
                quantity, unit_cost, total_cost, installed, old_part_returned,
                created_at, updated_at
            )
            SELECT :work_order_part_start
                       + ROW_NUMBER() OVER (ORDER BY wo.id, series.value) - 1,
                   wo.organization_id, wo.id, :part_id, :warehouse_id, :engineer_id,
                   1, 1.0, 1.0, 'yes', 'no', wo.created_at, CURRENT_TIMESTAMP
            FROM work_orders AS wo
            CROSS JOIN generate_series(1, 2) AS series(value)
            WHERE wo.organization_id = :organization_id
            """
        ),
        {
            "organization_id": primary.id,
            "work_order_part_start": work_order_part_start,
            "part_id": part.id,
            "warehouse_id": warehouse.id,
            "engineer_id": engineer.id,
        },
    )
    per_work_order = max(1, math.ceil(transactions / work_orders))
    session.execute(
        text(
            """
            INSERT INTO inventory_transactions (
                id, organization_id, part_id, transaction_type, quantity,
                from_warehouse_id, work_order_id, user_id, unit_cost,
                created_at, updated_at
            )
            SELECT :inventory_transaction_start
                       + ROW_NUMBER() OVER (ORDER BY wo.id, series.value) - 1,
                   wo.organization_id, :part_id, 'WORK_ORDER_USED', -1,
                   :warehouse_id, wo.id, :engineer_id, 1.0,
                   wo.created_at + (series.value * INTERVAL '1 second'), CURRENT_TIMESTAMP
            FROM work_orders AS wo
            CROSS JOIN generate_series(1, :per_work_order) AS series(value)
            WHERE wo.organization_id = :organization_id
            LIMIT :transactions
            """
        ),
        {
            "organization_id": primary.id,
            "inventory_transaction_start": inventory_transaction_start,
            "part_id": part.id,
            "warehouse_id": warehouse.id,
            "engineer_id": engineer.id,
            "per_work_order": per_work_order,
            "transactions": transactions,
        },
    )
    session.flush()
    session.execute(text("ANALYZE work_orders"))
    session.execute(text("ANALYZE work_order_parts"))
    session.execute(text("ANALYZE inventory_transactions"))
    return {
        "organization_id": primary.id,
        "engineer_id": engineer.id,
        "part_id": part.id,
        "work_orders": work_orders,
        "noise_work_orders": work_orders,
        "work_order_parts": work_orders * 2,
        "inventory_transactions": transactions,
    }


def verify_scale(
    *,
    work_orders: int,
    transactions: int,
    samples: int,
    p95_budget_ms: float,
) -> dict:
    _assert_local_postgres()
    started_at = datetime.now(timezone.utc)
    results: list[dict] = []
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(
            bind=connection,
            join_transaction_mode="create_savepoint",
            info={"rls_platform_access": True},
        )
        try:
            seed = _seed(session, work_orders, transactions)
            available_indexes = set(
                session.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = current_schema()"
                    )
                )
                .scalars()
                .all()
            )
            missing_indexes = _missing_required_indexes(available_indexes)
            if missing_indexes:
                raise ScaleVerificationError(
                    "Required scale indexes are missing: " + ", ".join(missing_indexes)
                )
            queries = (
                (
                    "recent_work_orders",
                    "SELECT id FROM work_orders WHERE organization_id = :organization_id "
                    "ORDER BY id DESC LIMIT 100",
                    {"organization_id": seed["organization_id"]},
                    "work_orders",
                ),
                (
                    "scheduled_work_orders",
                    "SELECT id FROM work_orders WHERE organization_id = :organization_id "
                    "AND schedule_date BETWEEN CURRENT_DATE - 30 AND CURRENT_DATE "
                    "ORDER BY schedule_date DESC, id DESC LIMIT 100",
                    {"organization_id": seed["organization_id"]},
                    "work_orders",
                ),
                (
                    "inventory_ledger_page",
                    "SELECT id FROM inventory_transactions "
                    "WHERE organization_id = :organization_id ORDER BY id DESC LIMIT 200",
                    {"organization_id": seed["organization_id"]},
                    "inventory_transactions",
                ),
                (
                    "engineer_parts_page",
                    "SELECT id FROM work_order_parts WHERE organization_id = :organization_id "
                    "AND user_id = :engineer_id ORDER BY id DESC LIMIT 100",
                    {
                        "organization_id": seed["organization_id"],
                        "engineer_id": seed["engineer_id"],
                    },
                    "work_order_parts",
                ),
                (
                    "parts_cost_aggregate",
                    "SELECT work_order_id, SUM(total_cost) FROM work_order_parts "
                    "WHERE organization_id = :organization_id "
                    "AND work_order_id IN (SELECT id FROM work_orders "
                    "WHERE organization_id = :organization_id ORDER BY id DESC LIMIT 100) "
                    "GROUP BY work_order_id",
                    {"organization_id": seed["organization_id"]},
                    "work_order_parts",
                ),
            )
            for name, sql, parameters, protected_table in queries:
                node_types, indexes = _explain(session, sql, parameters)
                durations, row_count = _time_query(
                    session,
                    sql,
                    parameters,
                    warmups=2,
                    samples=samples,
                )
                p95 = _percentile(durations, 0.95)
                plan_text = " ".join(node_types)
                if "Seq Scan" in node_types and protected_table:
                    raise ScaleVerificationError(
                        f"{name} regressed to a sequential scan on {protected_table}"
                    )
                if not indexes:
                    raise ScaleVerificationError(
                        f"{name} did not use an index; plan={plan_text}"
                    )
                if p95 > p95_budget_ms:
                    raise ScaleVerificationError(
                        f"{name} p95 {p95:.3f}ms exceeded {p95_budget_ms:.3f}ms"
                    )
                results.append(
                    {
                        "query": name,
                        "rows_returned": row_count,
                        "p50_ms": round(_percentile(durations, 0.50), 3),
                        "p95_ms": round(p95, 3),
                        "plan_nodes": node_types,
                        "indexes": indexes,
                    }
                )
        finally:
            session.close()
            transaction.rollback()
    completed_at = datetime.now(timezone.utc)
    return {
        "format": "opf-scale-verification-v1",
        "status": "passed",
        "database": "postgresql",
        "required_indexes": sorted(_REQUIRED_SCALE_INDEXES),
        "seed": {
            key: value
            for key, value in seed.items()
            if key
            in {
                "work_orders",
                "noise_work_orders",
                "work_order_parts",
                "inventory_transactions",
            }
        },
        "samples_per_query": samples,
        "p95_budget_ms": p95_budget_ms,
        "queries": results,
        "duration_seconds": round((completed_at - started_at).total_seconds(), 3),
        "transaction_rolled_back": True,
        "scope": "regression gate; not a production capacity or contractual SLA claim",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify production query plans at repeatable scale.")
    parser.add_argument("--confirm-isolated-ci", action="store_true")
    parser.add_argument("--work-orders", type=int, default=20_000)
    parser.add_argument("--transactions", type=int, default=80_000)
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--p95-budget-ms", type=float, default=750.0)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.confirm_isolated_ci:
        print(json.dumps({"status": "failed", "error": "isolated CI confirmation is required"}))
        return 1
    if args.work_orders < 10_000 or args.transactions < args.work_orders or args.samples < 3:
        print(json.dumps({"status": "failed", "error": "scale inputs are below the verification floor"}))
        return 1
    try:
        report = verify_scale(
            work_orders=args.work_orders,
            transactions=args.transactions,
            samples=args.samples,
            p95_budget_ms=args.p95_budget_ms,
        )
    except ScaleVerificationError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    if args.report:
        args.report.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
