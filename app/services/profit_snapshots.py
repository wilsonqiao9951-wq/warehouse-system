from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    InventoryRegion,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
    WorkOrderProfitSnapshot,
)
from app.schemas import (
    ProfitSnapshotDailyRead,
    ProfitSnapshotDashboardRead,
    ProfitSnapshotRankingRead,
    ProfitSnapshotSummaryRead,
)


class ProfitSnapshotConflict(RuntimeError):
    pass


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _attribution(
    db: Session,
    work_order: WorkOrder,
    engineer_id: int | None,
) -> tuple[InventoryRegion | None, Warehouse | None, str]:
    usage = db.execute(
        select(
            Warehouse,
            InventoryRegion,
            func.coalesce(func.sum(func.abs(WorkOrderPart.total_cost)), 0),
            func.coalesce(func.sum(func.abs(WorkOrderPart.quantity)), 0),
        )
        .join(
            WorkOrderPart,
            (WorkOrderPart.warehouse_id == Warehouse.id)
            & (WorkOrderPart.organization_id == work_order.organization_id),
        )
        .join(
            InventoryRegion,
            (InventoryRegion.id == Warehouse.region_id)
            & (InventoryRegion.organization_id == work_order.organization_id),
        )
        .where(
            Warehouse.organization_id == work_order.organization_id,
            WorkOrderPart.work_order_id == work_order.id,
        )
        .group_by(Warehouse.id, InventoryRegion.id)
        .order_by(
            func.sum(func.abs(WorkOrderPart.total_cost)).desc(),
            func.sum(func.abs(WorkOrderPart.quantity)).desc(),
            Warehouse.id.asc(),
        )
        .limit(1)
    ).first()
    if usage:
        warehouse, region, _cost, _quantity = usage
        return region, warehouse, "parts_usage_region"

    if engineer_id is not None:
        engineer_vehicle = db.execute(
            select(Warehouse, InventoryRegion)
            .join(
                InventoryRegion,
                (InventoryRegion.id == Warehouse.region_id)
                & (InventoryRegion.organization_id == work_order.organization_id),
            )
            .where(
                Warehouse.organization_id == work_order.organization_id,
                Warehouse.assigned_user_id == engineer_id,
                Warehouse.is_active.is_(True),
            )
            .order_by(Warehouse.id.asc())
            .limit(1)
        ).first()
        if engineer_vehicle:
            warehouse, region = engineer_vehicle
            return region, warehouse, "engineer_vehicle_region"

    default_region = db.scalar(
        select(InventoryRegion)
        .where(
            InventoryRegion.organization_id == work_order.organization_id,
            InventoryRegion.is_active.is_(True),
        )
        .order_by(InventoryRegion.is_default.desc(), InventoryRegion.id.asc())
        .limit(1)
    )
    if default_region:
        return default_region, None, "default_region"
    return None, None, "unattributed"


def snapshot_values(db: Session, work_order: WorkOrder) -> dict:
    if work_order.completed_at is None or str(work_order.status).upper() != "COMPLETED":
        raise ValueError("Only completed work orders can be snapshotted")
    parts_cost = float(
        db.scalar(
            select(func.coalesce(func.sum(WorkOrderPart.total_cost), 0)).where(
                WorkOrderPart.organization_id == work_order.organization_id,
                WorkOrderPart.work_order_id == work_order.id,
            )
        )
        or 0.0
    )
    engineer_id = (
        work_order.completed_by_id
        or work_order.claimed_by_id
        or work_order.engineer_id
        or work_order.assigned_user_id
    )
    engineer = None
    if engineer_id is not None:
        engineer = db.scalar(
            select(User).where(
                User.id == engineer_id,
                User.organization_id == work_order.organization_id,
            )
        )
    if engineer is None:
        engineer_id = None
    region, warehouse, method = _attribution(db, work_order, engineer_id)
    revenue = round(float(work_order.revenue or 0.0), 2)
    labor_cost = round(float(work_order.labor_cost or 0.0), 2)
    parts_cost = round(parts_cost, 2)
    profit = round(revenue - labor_cost - parts_cost, 2)
    values = {
        "organization_id": work_order.organization_id,
        "work_order_id": work_order.id,
        "snapshot_date": work_order.completed_at.date(),
        "completed_at": work_order.completed_at,
        "ticket_number": work_order.ticket_number,
        "engineer_id": engineer_id,
        "engineer_name": engineer.name if engineer else "Unattributed",
        "region_id": region.id if region else None,
        "region_code": region.code if region else None,
        "region_name": region.name if region else None,
        "attribution_warehouse_id": warehouse.id if warehouse else None,
        "attribution_method": method,
        "machine_type": (work_order.machine_type or "Unclassified").strip() or "Unclassified",
        "revenue": revenue,
        "labor_cost": labor_cost,
        "parts_cost": parts_cost,
        "profit": profit,
    }
    evidence = {
        key: value.isoformat(timespec="microseconds") if isinstance(value, datetime) else str(value)
        for key, value in values.items()
    }
    values["source_fingerprint"] = sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return values


def capture_profit_snapshot(
    db: Session,
    work_order: WorkOrder,
) -> tuple[WorkOrderProfitSnapshot, bool]:
    values = snapshot_values(db, work_order)
    existing = db.scalar(
        select(WorkOrderProfitSnapshot).where(
            WorkOrderProfitSnapshot.organization_id == work_order.organization_id,
            WorkOrderProfitSnapshot.work_order_id == work_order.id,
        )
    )
    if existing:
        if existing.source_fingerprint != values["source_fingerprint"]:
            raise ProfitSnapshotConflict(
                f"Profit snapshot source changed for work order {work_order.id}"
            )
        return existing, False
    now = _utcnow_naive()
    row = WorkOrderProfitSnapshot(
        **values,
        captured_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    db.flush()
    return row, True


def _margin(profit: float, revenue: float) -> float | None:
    return round(profit / revenue, 4) if revenue else None


def build_profit_snapshot_dashboard(
    db: Session,
    organization_id: int,
    *,
    from_date: date,
    to_date: date,
    ranking_limit: int,
) -> ProfitSnapshotDashboardRead:
    if to_date < from_date:
        raise ValueError("to_date must be on or after from_date")
    if (to_date - from_date).days + 1 > 366:
        raise ValueError("Profit snapshot range cannot exceed 366 days")
    common = (
        WorkOrderProfitSnapshot.organization_id == organization_id,
        WorkOrderProfitSnapshot.snapshot_date >= from_date,
        WorkOrderProfitSnapshot.snapshot_date <= to_date,
    )
    summary_row = db.execute(
        select(
            func.count(WorkOrderProfitSnapshot.id),
            func.coalesce(func.sum(WorkOrderProfitSnapshot.revenue), 0),
            func.coalesce(func.sum(WorkOrderProfitSnapshot.labor_cost), 0),
            func.coalesce(func.sum(WorkOrderProfitSnapshot.parts_cost), 0),
            func.coalesce(func.sum(WorkOrderProfitSnapshot.profit), 0),
            func.max(WorkOrderProfitSnapshot.captured_at),
        ).where(*common)
    ).one()
    snapshot_count = int(summary_row[0] or 0)
    completed_count = int(
        db.scalar(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.organization_id == organization_id,
                WorkOrder.status == "COMPLETED",
                WorkOrder.completed_at >= datetime.combine(from_date, time.min),
                WorkOrder.completed_at < datetime.combine(to_date + timedelta(days=1), time.min),
            )
        )
        or 0
    )
    revenue = round(float(summary_row[1] or 0), 2)
    labor_cost = round(float(summary_row[2] or 0), 2)
    parts_cost = round(float(summary_row[3] or 0), 2)
    profit = round(float(summary_row[4] or 0), 2)

    daily_values = {
        row_date: (
            int(count or 0),
            round(float(day_revenue or 0), 2),
            round(float(day_labor or 0), 2),
            round(float(day_parts or 0), 2),
            round(float(day_profit or 0), 2),
        )
        for row_date, count, day_revenue, day_labor, day_parts, day_profit in db.execute(
            select(
                WorkOrderProfitSnapshot.snapshot_date,
                func.count(WorkOrderProfitSnapshot.id),
                func.sum(WorkOrderProfitSnapshot.revenue),
                func.sum(WorkOrderProfitSnapshot.labor_cost),
                func.sum(WorkOrderProfitSnapshot.parts_cost),
                func.sum(WorkOrderProfitSnapshot.profit),
            )
            .where(*common)
            .group_by(WorkOrderProfitSnapshot.snapshot_date)
            .order_by(WorkOrderProfitSnapshot.snapshot_date.asc())
        ).all()
    }
    daily = []
    cursor = from_date
    while cursor <= to_date:
        count, day_revenue, day_labor, day_parts, day_profit = daily_values.get(
            cursor, (0, 0.0, 0.0, 0.0, 0.0)
        )
        daily.append(
            ProfitSnapshotDailyRead(
                snapshot_date=cursor,
                completed_count=count,
                revenue=day_revenue,
                labor_cost=day_labor,
                parts_cost=day_parts,
                profit=day_profit,
            )
        )
        cursor += timedelta(days=1)

    def rankings(dimension: str) -> list[ProfitSnapshotRankingRead]:
        if dimension == "engineer":
            key_column = WorkOrderProfitSnapshot.engineer_id
            label_column = WorkOrderProfitSnapshot.engineer_name
        elif dimension == "region":
            key_column = WorkOrderProfitSnapshot.region_id
            label_column = WorkOrderProfitSnapshot.region_name
        else:
            key_column = WorkOrderProfitSnapshot.machine_type
            label_column = WorkOrderProfitSnapshot.machine_type
        rows = db.execute(
            select(
                key_column,
                label_column,
                func.count(WorkOrderProfitSnapshot.id),
                func.sum(WorkOrderProfitSnapshot.revenue),
                func.sum(WorkOrderProfitSnapshot.labor_cost),
                func.sum(WorkOrderProfitSnapshot.parts_cost),
                func.sum(WorkOrderProfitSnapshot.profit).label("rank_profit"),
            )
            .where(*common)
            .group_by(key_column, label_column)
            .order_by(
                func.sum(WorkOrderProfitSnapshot.profit).desc(),
                func.count(WorkOrderProfitSnapshot.id).desc(),
                label_column.asc(),
            )
            .limit(ranking_limit)
        ).all()
        result = []
        for key, label, count, rank_revenue, rank_labor, rank_parts, rank_profit in rows:
            safe_revenue = round(float(rank_revenue or 0), 2)
            safe_profit = round(float(rank_profit or 0), 2)
            result.append(
                ProfitSnapshotRankingRead(
                    dimension=dimension,
                    key=str(key) if key is not None else "unattributed",
                    label=str(label or "Unattributed"),
                    completed_count=int(count or 0),
                    revenue=safe_revenue,
                    labor_cost=round(float(rank_labor or 0), 2),
                    parts_cost=round(float(rank_parts or 0), 2),
                    profit=safe_profit,
                    margin_rate=_margin(safe_profit, safe_revenue),
                )
            )
        return result

    return ProfitSnapshotDashboardRead(
        generated_at=_utcnow_naive(),
        from_date=from_date,
        to_date=to_date,
        summary=ProfitSnapshotSummaryRead(
            completed_work_orders=completed_count,
            snapshot_count=snapshot_count,
            missing_snapshot_count=max(0, completed_count - snapshot_count),
            coverage_rate=(snapshot_count / completed_count if completed_count else 1.0),
            revenue=revenue,
            labor_cost=labor_cost,
            parts_cost=parts_cost,
            profit=profit,
            margin_rate=_margin(profit, revenue),
        ),
        daily=daily,
        engineers=rankings("engineer"),
        regions=rankings("region"),
        machine_types=rankings("machine_type"),
        last_captured_at=summary_row[5],
    )


def backfill_profit_snapshots(
    db: Session,
    organization_id: int,
    *,
    from_date: date,
    to_date: date,
    after_work_order_id: int | None,
    limit: int,
) -> tuple[int, int, int, int, int | None]:
    query = (
        select(WorkOrder)
        .where(
            WorkOrder.organization_id == organization_id,
            WorkOrder.status == "COMPLETED",
            WorkOrder.completed_at >= datetime.combine(from_date, time.min),
            WorkOrder.completed_at < datetime.combine(to_date + timedelta(days=1), time.min),
        )
        .order_by(WorkOrder.id.asc())
        .limit(limit + 1)
    )
    if after_work_order_id is not None:
        query = query.where(WorkOrder.id > after_work_order_id)
    rows = list(db.scalars(query).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    created = existing = conflicts = 0
    for work_order in rows:
        try:
            _snapshot, was_created = capture_profit_snapshot(db, work_order)
        except ProfitSnapshotConflict:
            conflicts += 1
        else:
            if was_created:
                created += 1
            else:
                existing += 1
    next_id = rows[-1].id if has_more and rows else None
    return len(rows), created, existing, conflicts, next_id
