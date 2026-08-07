from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select, union_all
from sqlalchemy.orm import Session

from app.models import (
    InventoryRegion,
    InventoryTransaction,
    Part,
    User,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)
from app.schemas import (
    AnalyticsDataQualityRead,
    AnalyticsEngineerRowRead,
    AnalyticsFilterOption,
    AnalyticsFilterRead,
    AnalyticsJobTypeRowRead,
    AnalyticsKpiRead,
    AnalyticsPeriodRead,
    AnalyticsRegionRowRead,
    AnalyticsSourceFreshnessRead,
    AnalyticsTrendPointRead,
    EnterpriseAnalyticsRead,
)


@dataclass
class AnalyticsBundle:
    dashboard: EnterpriseAnalyticsRead
    detail_rows: list[dict[str, Any]]


@dataclass
class _Aggregate:
    created: int = 0
    completed: int = 0
    first_time_fix_labeled: int = 0
    first_time_fix_success: int = 0
    rework: int = 0
    duration_labeled: int = 0
    duration_minutes: int = 0
    revenue: float = 0.0
    labor_cost: float = 0.0
    parts_cost: float = 0.0

    @property
    def first_time_fix_rate(self) -> float | None:
        if not self.first_time_fix_labeled:
            return None
        return self.first_time_fix_success / self.first_time_fix_labeled

    @property
    def first_time_fix_coverage(self) -> float:
        return self.first_time_fix_labeled / self.completed if self.completed else 0.0

    @property
    def rework_rate(self) -> float:
        return self.rework / self.completed if self.completed else 0.0

    @property
    def average_repair_minutes(self) -> float | None:
        if not self.duration_labeled:
            return None
        return self.duration_minutes / self.duration_labeled

    @property
    def contribution(self) -> float:
        return self.revenue - self.labor_cost - self.parts_cost


def _utc_naive_start(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _dimension_conditions(
    organization_id: int,
    engineer_id: int | None,
    job_type: str | None,
) -> list[Any]:
    conditions: list[Any] = [WorkOrder.organization_id == organization_id]
    if engineer_id is not None:
        conditions.append(
            func.coalesce(
                WorkOrder.completed_by_id,
                WorkOrder.engineer_id,
                WorkOrder.assigned_user_id,
            )
            == engineer_id
        )
    if job_type:
        conditions.append(func.lower(WorkOrder.job_type) == job_type.lower())
    return conditions


def _validate_filters(
    db: Session,
    organization_id: int,
    from_date: date,
    to_date: date,
    engineer_id: int | None,
    job_type: str | None,
) -> str | None:
    if to_date < from_date:
        raise HTTPException(status_code=422, detail="to_date must be on or after from_date")
    if (to_date - from_date).days + 1 > 366:
        raise HTTPException(status_code=422, detail="Analytics range cannot exceed 366 days")
    if engineer_id is not None:
        engineer = db.get(User, engineer_id)
        if not engineer or engineer.organization_id != organization_id or engineer.role != UserRole.ENGINEER:
            raise HTTPException(status_code=404, detail="Engineer not found")
    normalized_job_type = job_type.strip() if job_type else None
    return normalized_job_type or None


def _parts_costs(db: Session, work_order_ids: list[int]) -> dict[int, float]:
    if not work_order_ids:
        return {}
    return {
        work_order_id: float(total or 0.0)
        for work_order_id, total in db.execute(
            select(WorkOrderPart.work_order_id, func.sum(WorkOrderPart.total_cost))
            .where(WorkOrderPart.work_order_id.in_(work_order_ids))
            .group_by(WorkOrderPart.work_order_id)
        ).all()
    }


def _aggregate_completed(
    rows: list[WorkOrder],
    parts_costs: dict[int, float],
) -> _Aggregate:
    result = _Aggregate(completed=len(rows))
    for row in rows:
        if row.first_time_fix is not None:
            result.first_time_fix_labeled += 1
            result.first_time_fix_success += int(row.first_time_fix is True)
        result.rework += int(row.is_rework)
        if row.repair_duration_minutes is not None:
            result.duration_labeled += 1
            result.duration_minutes += row.repair_duration_minutes
        result.revenue += float(row.revenue or 0.0)
        result.labor_cost += float(row.labor_cost or 0.0)
        result.parts_cost += parts_costs.get(row.id, 0.0)
    return result


def _delta_percent(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return ((current - previous) / abs(previous)) * 100


def _kpi(
    code: str,
    label: str,
    value: float | None,
    unit: str,
    previous_value: float | None,
    definition: str,
) -> AnalyticsKpiRead:
    return AnalyticsKpiRead(
        code=code,
        label=label,
        value=value,
        unit=unit,
        previous_value=previous_value,
        delta_percent=_delta_percent(value, previous_value),
        definition=definition,
    )


def _bucket_start(value: date, grain: str) -> date:
    if grain == "day":
        return value
    if grain == "week":
        return value - timedelta(days=value.weekday())
    return value.replace(day=1)


def _next_bucket(value: date, grain: str) -> date:
    if grain == "day":
        return value + timedelta(days=1)
    if grain == "week":
        return value + timedelta(days=7)
    return (value.replace(day=28) + timedelta(days=4)).replace(day=1)


def _bucket_label(value: date, grain: str) -> str:
    if grain == "month":
        return value.strftime("%b %Y")
    if grain == "week":
        return f"Week of {value.strftime('%b %d')}"
    return value.strftime("%b %d")


def _trend(
    from_date: date,
    to_date: date,
    grain: str,
    created_rows: list[WorkOrder],
    completed_rows: list[WorkOrder],
    parts_costs: dict[int, float],
) -> list[AnalyticsTrendPointRead]:
    buckets: dict[date, _Aggregate] = {}
    cursor = _bucket_start(from_date, grain)
    last = _bucket_start(to_date, grain)
    while cursor <= last:
        buckets[cursor] = _Aggregate()
        cursor = _next_bucket(cursor, grain)
    for row in created_rows:
        bucket = buckets[_bucket_start(row.created_at.date(), grain)]
        bucket.created += 1
    completed_by_bucket: dict[date, list[WorkOrder]] = defaultdict(list)
    for row in completed_rows:
        if row.completed_at:
            completed_by_bucket[_bucket_start(row.completed_at.date(), grain)].append(row)
    for bucket_start, rows in completed_by_bucket.items():
        completed = _aggregate_completed(rows, parts_costs)
        completed.created = buckets[bucket_start].created
        buckets[bucket_start] = completed
    return [
        AnalyticsTrendPointRead(
            bucket_start=bucket_start,
            label=_bucket_label(bucket_start, grain),
            created_count=aggregate.created,
            completed_count=aggregate.completed,
            first_time_fix_rate=aggregate.first_time_fix_rate,
            rework_rate=aggregate.rework_rate,
            average_repair_minutes=aggregate.average_repair_minutes,
            revenue=round(aggregate.revenue, 2),
            contribution=round(aggregate.contribution, 2),
        )
        for bucket_start, aggregate in sorted(buckets.items())
    ]


def _engineer_rows(
    completed_rows: list[WorkOrder],
    costs: dict[int, float],
    users: dict[int, User],
) -> list[AnalyticsEngineerRowRead]:
    grouped: dict[int | None, list[WorkOrder]] = defaultdict(list)
    for row in completed_rows:
        grouped[row.completed_by_id or row.engineer_id or row.assigned_user_id].append(row)
    results: list[AnalyticsEngineerRowRead] = []
    for engineer_id, rows in grouped.items():
        aggregate = _aggregate_completed(rows, costs)
        user = users.get(engineer_id) if engineer_id is not None else None
        results.append(
            AnalyticsEngineerRowRead(
                engineer_id=engineer_id,
                engineer_name=user.name if user else "Unattributed",
                completed_count=aggregate.completed,
                first_time_fix_rate=aggregate.first_time_fix_rate,
                first_time_fix_coverage=aggregate.first_time_fix_coverage,
                rework_rate=aggregate.rework_rate,
                average_repair_minutes=aggregate.average_repair_minutes,
                parts_cost=round(aggregate.parts_cost, 2),
                revenue=round(aggregate.revenue, 2),
                contribution=round(aggregate.contribution, 2),
            )
        )
    return sorted(results, key=lambda row: (-row.completed_count, row.engineer_name.lower()))


def _job_type_rows(
    completed_rows: list[WorkOrder],
    costs: dict[int, float],
) -> list[AnalyticsJobTypeRowRead]:
    grouped: dict[str, list[WorkOrder]] = defaultdict(list)
    for row in completed_rows:
        grouped[(row.job_type or "Unclassified").strip() or "Unclassified"].append(row)
    results = []
    for job_type, rows in grouped.items():
        aggregate = _aggregate_completed(rows, costs)
        results.append(
            AnalyticsJobTypeRowRead(
                job_type=job_type,
                completed_count=aggregate.completed,
                first_time_fix_rate=aggregate.first_time_fix_rate,
                rework_rate=aggregate.rework_rate,
                average_repair_minutes=aggregate.average_repair_minutes,
                contribution=round(aggregate.contribution, 2),
            )
        )
    return sorted(results, key=lambda row: (-row.completed_count, row.job_type.lower()))


def _region_rows(
    db: Session,
    organization_id: int,
    completed_ids: list[int],
) -> list[AnalyticsRegionRowRead]:
    regions = db.scalars(
        select(InventoryRegion).where(InventoryRegion.organization_id == organization_id)
    ).all()
    if not regions:
        return []
    default_region = next((region for region in regions if region.is_default), regions[0])
    warehouses = db.scalars(
        select(Warehouse).where(Warehouse.organization_id == organization_id)
    ).all()
    warehouse_region = {
        warehouse.id: warehouse.region_id or default_region.id for warehouse in warehouses
    }
    parts = db.scalars(select(Part).where(Part.organization_id == organization_id)).all()
    part_by_id = {part.id: part for part in parts}

    inbound = select(
        InventoryTransaction.to_warehouse_id.label("warehouse_id"),
        InventoryTransaction.part_id.label("part_id"),
        InventoryTransaction.quantity.label("quantity"),
    ).where(
        InventoryTransaction.organization_id == organization_id,
        InventoryTransaction.to_warehouse_id.is_not(None),
    )
    outbound = select(
        InventoryTransaction.from_warehouse_id.label("warehouse_id"),
        InventoryTransaction.part_id.label("part_id"),
        (-InventoryTransaction.quantity).label("quantity"),
    ).where(
        InventoryTransaction.organization_id == organization_id,
        InventoryTransaction.from_warehouse_id.is_not(None),
    )
    movements = union_all(inbound, outbound).subquery()
    balances = db.execute(
        select(
            movements.c.warehouse_id,
            movements.c.part_id,
            func.sum(movements.c.quantity),
        ).group_by(movements.c.warehouse_id, movements.c.part_id)
    ).all()

    warehouse_counts: dict[int, int] = defaultdict(int)
    stock_quantity: dict[int, int] = defaultdict(int)
    stock_value: dict[int, float] = defaultdict(float)
    low_stock: dict[int, int] = defaultdict(int)
    for warehouse in warehouses:
        warehouse_counts[warehouse_region[warehouse.id]] += 1
        low_stock[warehouse_region[warehouse.id]] += len(parts)
    for warehouse_id, part_id, quantity_value in balances:
        region_id = warehouse_region.get(warehouse_id, default_region.id)
        part = part_by_id.get(part_id)
        if not part:
            continue
        quantity = int(quantity_value or 0)
        stock_quantity[region_id] += quantity
        stock_value[region_id] += quantity * float(part.default_cost or 0.0)
        if quantity > max(part.safety_stock, part.min_stock):
            low_stock[region_id] -= 1

    consumed_quantity: dict[int, int] = defaultdict(int)
    consumed_cost: dict[int, float] = defaultdict(float)
    consumed_work_orders: dict[int, set[int]] = defaultdict(set)
    if completed_ids:
        usage_rows = db.execute(
            select(
                WorkOrderPart.work_order_id,
                WorkOrderPart.warehouse_id,
                WorkOrderPart.quantity,
                WorkOrderPart.total_cost,
            ).where(
                WorkOrderPart.organization_id == organization_id,
                WorkOrderPart.work_order_id.in_(completed_ids),
            )
        ).all()
        for work_order_id, warehouse_id, quantity, total_cost in usage_rows:
            region_id = warehouse_region.get(warehouse_id, default_region.id)
            consumed_quantity[region_id] += int(quantity or 0)
            consumed_cost[region_id] += float(total_cost or 0.0)
            consumed_work_orders[region_id].add(work_order_id)

    return [
        AnalyticsRegionRowRead(
            region_id=region.id,
            region_code=region.code,
            region_name=region.name,
            warehouse_count=warehouse_counts[region.id],
            stock_quantity=stock_quantity[region.id],
            stock_value=round(stock_value[region.id], 2),
            low_stock_sku_count=max(0, low_stock[region.id]),
            completed_work_orders_with_usage=len(consumed_work_orders[region.id]),
            consumed_quantity=consumed_quantity[region.id],
            consumed_parts_cost=round(consumed_cost[region.id], 2),
        )
        for region in sorted(regions, key=lambda item: (not item.is_default, item.name.lower()))
    ]


def build_enterprise_analytics(
    db: Session,
    organization_id: int,
    *,
    from_date: date,
    to_date: date,
    engineer_id: int | None = None,
    job_type: str | None = None,
) -> AnalyticsBundle:
    job_type = _validate_filters(
        db,
        organization_id,
        from_date,
        to_date,
        engineer_id,
        job_type,
    )
    period_days = (to_date - from_date).days + 1
    previous_to_date = from_date - timedelta(days=1)
    previous_from_date = previous_to_date - timedelta(days=period_days - 1)
    current_start = _utc_naive_start(from_date)
    current_end = _utc_naive_start(to_date + timedelta(days=1))
    previous_start = _utc_naive_start(previous_from_date)
    conditions = _dimension_conditions(organization_id, engineer_id, job_type)

    created_rows = list(
        db.scalars(
            select(WorkOrder).where(
                *conditions,
                WorkOrder.created_at >= current_start,
                WorkOrder.created_at < current_end,
            )
        ).all()
    )
    completed_rows = list(
        db.scalars(
            select(WorkOrder).where(
                *conditions,
                WorkOrder.completed_at >= current_start,
                WorkOrder.completed_at < current_end,
            )
        ).all()
    )
    previous_created_rows = list(
        db.scalars(
            select(WorkOrder).where(
                *conditions,
                WorkOrder.created_at >= previous_start,
                WorkOrder.created_at < current_start,
            )
        ).all()
    )
    previous_completed_rows = list(
        db.scalars(
            select(WorkOrder).where(
                *conditions,
                WorkOrder.completed_at >= previous_start,
                WorkOrder.completed_at < current_start,
            )
        ).all()
    )
    current_ids = [row.id for row in completed_rows]
    previous_ids = [row.id for row in previous_completed_rows]
    current_costs = _parts_costs(db, current_ids)
    previous_costs = _parts_costs(db, previous_ids)
    current = _aggregate_completed(completed_rows, current_costs)
    current.created = len(created_rows)
    previous = _aggregate_completed(previous_completed_rows, previous_costs)
    previous.created = len(previous_created_rows)

    backlog_conditions = [
        *conditions,
        WorkOrder.created_at < current_end,
        or_(WorkOrder.completed_at.is_(None), WorkOrder.completed_at >= current_end),
        func.lower(WorkOrder.status).notin_({"cancelled", "canceled"}),
    ]
    previous_backlog_conditions = [
        *conditions,
        WorkOrder.created_at < current_start,
        or_(WorkOrder.completed_at.is_(None), WorkOrder.completed_at >= current_start),
        func.lower(WorkOrder.status).notin_({"cancelled", "canceled"}),
    ]
    backlog = int(db.scalar(select(func.count(WorkOrder.id)).where(*backlog_conditions)) or 0)
    previous_backlog = int(
        db.scalar(select(func.count(WorkOrder.id)).where(*previous_backlog_conditions)) or 0
    )

    range_days = period_days
    grain = "day" if range_days <= 31 else "week" if range_days <= 180 else "month"
    user_rows = db.scalars(
        select(User).where(User.organization_id == organization_id).order_by(User.name)
    ).all()
    users = {user.id: user for user in user_rows}
    engineer_options = [
        AnalyticsFilterOption(value=str(user.id), label=user.name)
        for user in user_rows
        if user.role == UserRole.ENGINEER
    ]
    job_type_values = sorted(
        {
            value.strip()
            for value in db.scalars(
                select(WorkOrder.job_type).where(
                    WorkOrder.organization_id == organization_id,
                    WorkOrder.job_type.is_not(None),
                )
            ).all()
            if value and value.strip()
        },
        key=str.lower,
    )

    first_time_fix_percent = (
        current.first_time_fix_rate * 100 if current.first_time_fix_rate is not None else None
    )
    previous_first_time_fix_percent = (
        previous.first_time_fix_rate * 100 if previous.first_time_fix_rate is not None else None
    )
    kpis = [
        _kpi(
            "work_orders_created",
            "Work orders created",
            float(current.created),
            "count",
            float(previous.created),
            "Work orders with created_at inside the selected UTC date range.",
        ),
        _kpi(
            "completed_work_orders",
            "Completed work orders",
            float(current.completed),
            "count",
            float(previous.completed),
            "Work orders with completed_at inside the selected UTC date range.",
        ),
        _kpi(
            "period_end_backlog",
            "Period-end backlog",
            float(backlog),
            "count",
            float(previous_backlog),
            "Non-cancelled work orders created before period end and not completed by period end.",
        ),
        _kpi(
            "first_time_fix_rate",
            "First-time fix rate",
            first_time_fix_percent,
            "percent",
            previous_first_time_fix_percent,
            "first_time_fix=true divided by completed work orders with a first-time-fix label.",
        ),
        _kpi(
            "rework_rate",
            "Rework rate",
            current.rework_rate * 100,
            "percent",
            previous.rework_rate * 100,
            "Completed work orders marked is_rework divided by all completed work orders.",
        ),
        _kpi(
            "average_repair_hours",
            "Average repair hours",
            current.average_repair_minutes / 60 if current.average_repair_minutes is not None else None,
            "hours",
            previous.average_repair_minutes / 60 if previous.average_repair_minutes is not None else None,
            "Average repair_duration_minutes among completed work orders with duration evidence.",
        ),
        _kpi(
            "gross_contribution",
            "Gross contribution",
            round(current.contribution, 2),
            "currency",
            round(previous.contribution, 2),
            "Completed-work-order revenue minus labor cost and recorded work-order parts cost.",
        ),
    ]

    completed_count = current.completed
    attributed = sum(
        1
        for row in completed_rows
        if (row.completed_by_id or row.engineer_id or row.assigned_user_id) is not None
    )
    duration_coverage = current.duration_labeled / completed_count if completed_count else 0.0
    attribution_coverage = attributed / completed_count if completed_count else 0.0
    warnings: list[str] = []
    if completed_count and current.first_time_fix_coverage < 0.8:
        warnings.append("First-time-fix coverage is below 80%; interpret the rate cautiously.")
    if completed_count and duration_coverage < 0.8:
        warnings.append("Repair-duration coverage is below 80%; averages may be biased.")
    if completed_count and attribution_coverage < 0.95:
        warnings.append("Engineer attribution coverage is below 95%.")

    detail_rows = []
    for row in sorted(completed_rows, key=lambda item: (item.completed_at or datetime.min, item.id)):
        resolved_engineer_id = row.completed_by_id or row.engineer_id or row.assigned_user_id
        engineer = users.get(resolved_engineer_id) if resolved_engineer_id else None
        parts_cost = current_costs.get(row.id, 0.0)
        detail_rows.append(
            {
                "work_order_id": row.id,
                "ticket_number": row.ticket_number,
                "completed_at": row.completed_at,
                "engineer_id": resolved_engineer_id,
                "engineer_name": engineer.name if engineer else "Unattributed",
                "job_type": row.job_type or "Unclassified",
                "first_time_fix": row.first_time_fix,
                "is_rework": row.is_rework,
                "repair_duration_minutes": row.repair_duration_minutes,
                "revenue": float(row.revenue or 0.0),
                "labor_cost": float(row.labor_cost or 0.0),
                "parts_cost": parts_cost,
                "contribution": float(row.revenue or 0.0)
                - float(row.labor_cost or 0.0)
                - parts_cost,
            }
        )

    generated_at = datetime.now(timezone.utc)
    dashboard = EnterpriseAnalyticsRead(
        generated_at=generated_at,
        period=AnalyticsPeriodRead(
            from_date=from_date,
            to_date=to_date,
            previous_from_date=previous_from_date,
            previous_to_date=previous_to_date,
            days=period_days,
            grain=grain,
        ),
        filters=AnalyticsFilterRead(
            engineer_id=engineer_id,
            job_type=job_type,
            engineers=engineer_options,
            job_types=[AnalyticsFilterOption(value=value, label=value) for value in job_type_values],
        ),
        kpis=kpis,
        trend=_trend(from_date, to_date, grain, created_rows, completed_rows, current_costs),
        engineers=_engineer_rows(completed_rows, current_costs, users),
        job_types=_job_type_rows(completed_rows, current_costs),
        regions=_region_rows(db, organization_id, current_ids),
        data_quality=AnalyticsDataQualityRead(
            completed_work_orders=completed_count,
            first_time_fix_labeled=current.first_time_fix_labeled,
            first_time_fix_coverage=current.first_time_fix_coverage,
            repair_duration_labeled=current.duration_labeled,
            repair_duration_coverage=duration_coverage,
            engineer_attributed=attributed,
            engineer_attribution_coverage=attribution_coverage,
            warnings=warnings,
        ),
        source_freshness=AnalyticsSourceFreshnessRead(
            work_orders_updated_at=db.scalar(
                select(func.max(WorkOrder.updated_at)).where(
                    WorkOrder.organization_id == organization_id
                )
            ),
            work_order_parts_updated_at=db.scalar(
                select(func.max(WorkOrderPart.updated_at)).where(
                    WorkOrderPart.organization_id == organization_id
                )
            ),
            inventory_transactions_updated_at=db.scalar(
                select(func.max(InventoryTransaction.updated_at)).where(
                    InventoryTransaction.organization_id == organization_id
                )
            ),
        ),
    )
    return AnalyticsBundle(dashboard=dashboard, detail_rows=detail_rows)
