from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from math import ceil
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    InventoryTransaction,
    Part,
    ReplenishmentRequest,
    TransactionType,
    User,
    UserRole,
    VehicleReturnRequest,
    Warehouse,
)
from app.schemas import (
    VanConsumptionDayRead,
    VanEngineerConsumptionRead,
    VanPlanningRead,
    VanPlanningSummaryRead,
    VanRebalanceRecommendationRead,
)


router = APIRouter(prefix="/inventory", tags=["van-inventory-planning"])

MAX_VEHICLES = 100
MAX_PARTS = 500
ACTIVE_REPLENISHMENT_STATUSES = ("requested", "picking", "shipped")
ACTIVE_RETURN_STATUSES = ("requested", "approved")


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _balance_map(
    db: Session,
    organization_id: int,
    warehouse_ids: list[int],
    part_ids: list[int],
) -> dict[tuple[int, int], int]:
    balances: dict[tuple[int, int], int] = defaultdict(int)
    if not warehouse_ids or not part_ids:
        return balances
    inbound = db.execute(
        select(
            InventoryTransaction.to_warehouse_id,
            InventoryTransaction.part_id,
            func.coalesce(func.sum(InventoryTransaction.quantity), 0),
        )
        .where(
            InventoryTransaction.organization_id == organization_id,
            InventoryTransaction.to_warehouse_id.in_(warehouse_ids),
            InventoryTransaction.part_id.in_(part_ids),
        )
        .group_by(
            InventoryTransaction.to_warehouse_id,
            InventoryTransaction.part_id,
        )
    ).all()
    outbound = db.execute(
        select(
            InventoryTransaction.from_warehouse_id,
            InventoryTransaction.part_id,
            func.coalesce(func.sum(InventoryTransaction.quantity), 0),
        )
        .where(
            InventoryTransaction.organization_id == organization_id,
            InventoryTransaction.from_warehouse_id.in_(warehouse_ids),
            InventoryTransaction.part_id.in_(part_ids),
        )
        .group_by(
            InventoryTransaction.from_warehouse_id,
            InventoryTransaction.part_id,
        )
    ).all()
    for warehouse_id, part_id, quantity in inbound:
        balances[(warehouse_id, part_id)] += int(quantity or 0)
    for warehouse_id, part_id, quantity in outbound:
        balances[(warehouse_id, part_id)] -= int(quantity or 0)
    return balances


def _quantity_map(rows: list[tuple]) -> dict[tuple[int, int], int]:
    return {
        (int(warehouse_id), int(part_id)): max(0, int(quantity or 0))
        for warehouse_id, part_id, quantity in rows
    }


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


@router.get("/van-planning", response_model=VanPlanningRead)
def van_inventory_planning(
    response: Response,
    lookback_days: int = Query(default=30, ge=1, le=366),
    coverage_days: int = Query(default=14, ge=1, le=90),
    engineer_id: int | None = Query(default=None, ge=1),
    part_id: int | None = Query(default=None, ge=1),
    action: Literal["replenish", "return", "balanced"] | None = Query(default=None),
    include_balanced: bool = Query(default=False),
    limit: int = Query(default=200, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    response.headers["Cache-Control"] = "no-store"

    if engineer_id is not None:
        engineer = db.scalar(
            select(User).where(
                User.id == engineer_id,
                User.organization_id == actor.organization_id,
                User.role == UserRole.ENGINEER,
            )
        )
        if engineer is None:
            raise HTTPException(status_code=404, detail="Engineer not found")

    vehicle_query = (
        select(Warehouse, User)
        .join(
            User,
            (User.id == Warehouse.assigned_user_id)
            & (User.organization_id == actor.organization_id),
        )
        .where(
            Warehouse.organization_id == actor.organization_id,
            Warehouse.is_active.is_(True),
            User.role == UserRole.ENGINEER,
            User.is_active.is_(True),
        )
        .order_by(User.name.asc(), Warehouse.code.asc(), Warehouse.id.asc())
    )
    if engineer_id is not None:
        vehicle_query = vehicle_query.where(User.id == engineer_id)
    vehicle_rows = db.execute(vehicle_query.limit(MAX_VEHICLES + 1)).all()
    vehicle_truncated = len(vehicle_rows) > MAX_VEHICLES
    vehicle_rows = vehicle_rows[:MAX_VEHICLES]
    vehicle_ids = [warehouse.id for warehouse, _engineer in vehicle_rows]

    part_query = select(Part).where(Part.organization_id == actor.organization_id)
    if part_id is not None:
        part_query = part_query.where(Part.id == part_id)
    parts = list(
        db.scalars(
            part_query.order_by(Part.part_number.asc(), Part.id.asc()).limit(MAX_PARTS + 1)
        ).all()
    )
    if part_id is not None and not parts:
        raise HTTPException(status_code=404, detail="Part not found")
    part_truncated = len(parts) > MAX_PARTS
    parts = parts[:MAX_PARTS]
    part_ids = [part.id for part in parts]

    start_at = _utcnow_naive() - timedelta(days=lookback_days)
    balances = _balance_map(
        db, actor.organization_id, vehicle_ids, part_ids
    )
    usage_rows = db.execute(
        select(
            InventoryTransaction.from_warehouse_id,
            InventoryTransaction.part_id,
            func.coalesce(func.sum(func.abs(InventoryTransaction.quantity)), 0),
            func.count(func.distinct(InventoryTransaction.work_order_id)),
        )
        .where(
            InventoryTransaction.organization_id == actor.organization_id,
            InventoryTransaction.transaction_type == TransactionType.WORK_ORDER_USED,
            InventoryTransaction.from_warehouse_id.in_(vehicle_ids or [-1]),
            InventoryTransaction.part_id.in_(part_ids or [-1]),
            InventoryTransaction.created_at >= start_at,
        )
        .group_by(
            InventoryTransaction.from_warehouse_id,
            InventoryTransaction.part_id,
        )
    ).all()
    usage_by_vehicle_part = {
        (int(warehouse_id), int(used_part_id)): (
            max(0, int(quantity or 0)),
            max(0, int(work_orders or 0)),
        )
        for warehouse_id, used_part_id, quantity, work_orders in usage_rows
    }
    work_order_counts = {
        int(warehouse_id): max(0, int(work_orders or 0))
        for warehouse_id, work_orders in db.execute(
            select(
                InventoryTransaction.from_warehouse_id,
                func.count(func.distinct(InventoryTransaction.work_order_id)),
            )
            .where(
                InventoryTransaction.organization_id == actor.organization_id,
                InventoryTransaction.transaction_type == TransactionType.WORK_ORDER_USED,
                InventoryTransaction.from_warehouse_id.in_(vehicle_ids or [-1]),
                InventoryTransaction.part_id.in_(part_ids or [-1]),
                InventoryTransaction.created_at >= start_at,
                InventoryTransaction.work_order_id.is_not(None),
            )
            .group_by(InventoryTransaction.from_warehouse_id)
        ).all()
    }

    trend_rows = db.execute(
        select(
            InventoryTransaction.from_warehouse_id,
            func.date(InventoryTransaction.created_at),
            func.coalesce(func.sum(func.abs(InventoryTransaction.quantity)), 0),
        )
        .where(
            InventoryTransaction.organization_id == actor.organization_id,
            InventoryTransaction.transaction_type == TransactionType.WORK_ORDER_USED,
            InventoryTransaction.from_warehouse_id.in_(vehicle_ids or [-1]),
            InventoryTransaction.part_id.in_(part_ids or [-1]),
            InventoryTransaction.created_at >= start_at,
        )
        .group_by(
            InventoryTransaction.from_warehouse_id,
            func.date(InventoryTransaction.created_at),
        )
        .order_by(
            InventoryTransaction.from_warehouse_id.asc(),
            func.date(InventoryTransaction.created_at).asc(),
        )
    ).all()
    trends: dict[int, list[VanConsumptionDayRead]] = defaultdict(list)
    for warehouse_id, usage_date, quantity in trend_rows:
        trends[int(warehouse_id)].append(
            VanConsumptionDayRead(
                date=_as_date(usage_date),
                quantity=max(0, int(quantity or 0)),
            )
        )

    pending_inbound = _quantity_map(
        db.execute(
            select(
                ReplenishmentRequest.destination_warehouse_id,
                ReplenishmentRequest.part_id,
                func.coalesce(func.sum(ReplenishmentRequest.quantity), 0),
            )
            .where(
                ReplenishmentRequest.organization_id == actor.organization_id,
                ReplenishmentRequest.destination_warehouse_id.in_(vehicle_ids or [-1]),
                ReplenishmentRequest.part_id.in_(part_ids or [-1]),
                ReplenishmentRequest.status.in_(ACTIVE_REPLENISHMENT_STATUSES),
                ReplenishmentRequest.requires_reconciliation.is_(False),
            )
            .group_by(
                ReplenishmentRequest.destination_warehouse_id,
                ReplenishmentRequest.part_id,
            )
        ).all()
    )
    pending_outbound = _quantity_map(
        db.execute(
            select(
                VehicleReturnRequest.source_warehouse_id,
                VehicleReturnRequest.part_id,
                func.coalesce(func.sum(VehicleReturnRequest.quantity), 0),
            )
            .where(
                VehicleReturnRequest.organization_id == actor.organization_id,
                VehicleReturnRequest.source_warehouse_id.in_(vehicle_ids or [-1]),
                VehicleReturnRequest.part_id.in_(part_ids or [-1]),
                VehicleReturnRequest.status.in_(ACTIVE_RETURN_STATUSES),
            )
            .group_by(
                VehicleReturnRequest.source_warehouse_id,
                VehicleReturnRequest.part_id,
            )
        ).all()
    )

    organization_users = {
        user.id: user
        for user in db.scalars(
            select(User).where(User.organization_id == actor.organization_id)
        ).all()
    }
    candidate_warehouses = list(
        db.scalars(
            select(Warehouse)
            .where(
                Warehouse.organization_id == actor.organization_id,
                Warehouse.is_active.is_(True),
            )
            .order_by(Warehouse.code.asc(), Warehouse.id.asc())
        ).all()
    )
    source_warehouses = [
        warehouse
        for warehouse in candidate_warehouses
        if (warehouse.warehouse_type or "").lower() != "van"
        and not (
            warehouse.assigned_user_id
            and organization_users.get(warehouse.assigned_user_id)
            and organization_users[warehouse.assigned_user_id].role == UserRole.ENGINEER
        )
    ]
    source_ids = [warehouse.id for warehouse in source_warehouses]
    source_balances = _balance_map(
        db, actor.organization_id, source_ids, part_ids
    )
    reserved_source = _quantity_map(
        db.execute(
            select(
                ReplenishmentRequest.source_warehouse_id,
                ReplenishmentRequest.part_id,
                func.coalesce(func.sum(ReplenishmentRequest.quantity), 0),
            )
            .where(
                ReplenishmentRequest.organization_id == actor.organization_id,
                ReplenishmentRequest.source_warehouse_id.in_(source_ids or [-1]),
                ReplenishmentRequest.part_id.in_(part_ids or [-1]),
                ReplenishmentRequest.status == "picking",
                ReplenishmentRequest.requires_reconciliation.is_(False),
            )
            .group_by(
                ReplenishmentRequest.source_warehouse_id,
                ReplenishmentRequest.part_id,
            )
        ).all()
    )

    def suggested_warehouse(
        vehicle: Warehouse,
        selected_part_id: int,
        selected_action: str,
    ) -> tuple[Warehouse | None, int | None]:
        ranked: list[tuple[int, int, int, Warehouse]] = []
        for warehouse in source_warehouses:
            same_region = int(
                vehicle.region_id is not None
                and warehouse.region_id == vehicle.region_id
            )
            available = max(
                0,
                source_balances.get((warehouse.id, selected_part_id), 0)
                - reserved_source.get((warehouse.id, selected_part_id), 0),
            )
            ranked.append((same_region, available, -warehouse.id, warehouse))
        if not ranked:
            return None, None
        if selected_action == "replenish":
            _region, available, _stable, warehouse = max(ranked)
            return warehouse, available
        same_region_rows = [row for row in ranked if row[0]]
        _region, available, _stable, warehouse = max(
            same_region_rows or ranked,
            key=lambda row: (row[0], -row[3].id),
        )
        return warehouse, available

    engineer_summaries: list[VanEngineerConsumptionRead] = []
    all_recommendations: list[VanRebalanceRecommendationRead] = []
    action_counts = {"replenish": 0, "return": 0, "balanced": 0}
    replenish_quantity = 0
    return_quantity = 0
    total_consumed = 0
    total_work_orders = 0

    for vehicle, engineer in vehicle_rows:
        vehicle_consumed = sum(
            usage_by_vehicle_part.get((vehicle.id, candidate_part.id), (0, 0))[0]
            for candidate_part in parts
        )
        vehicle_work_orders = work_order_counts.get(vehicle.id, 0)
        total_consumed += vehicle_consumed
        total_work_orders += vehicle_work_orders
        engineer_summaries.append(
            VanEngineerConsumptionRead(
                engineer_id=engineer.id,
                engineer_name=engineer.name,
                warehouse_id=vehicle.id,
                warehouse_code=vehicle.code,
                warehouse_name=vehicle.name,
                region_id=vehicle.region_id,
                consumed_quantity=vehicle_consumed,
                work_order_count=vehicle_work_orders,
                average_daily_usage=round(vehicle_consumed / lookback_days, 3),
                trend=trends.get(vehicle.id, []),
            )
        )

        for candidate_part in parts:
            consumed, _work_orders = usage_by_vehicle_part.get(
                (vehicle.id, candidate_part.id), (0, 0)
            )
            average_daily = consumed / lookback_days
            forecast = ceil(average_daily * coverage_days)
            threshold = max(0, candidate_part.safety_stock or 0, candidate_part.min_stock or 0)
            target = max(threshold, forecast)
            current = balances.get((vehicle.id, candidate_part.id), 0)
            inbound = pending_inbound.get((vehicle.id, candidate_part.id), 0)
            outbound = pending_outbound.get((vehicle.id, candidate_part.id), 0)
            projected = current + inbound - outbound
            if projected < target:
                recommended_action = "replenish"
                recommended_quantity = target - projected
                replenish_quantity += recommended_quantity
                reason = (
                    f"Projected stock {projected} is {recommended_quantity} below target {target}; "
                    f"target combines threshold {threshold} with {coverage_days}-day forecast {forecast}."
                )
            elif projected > target:
                recommended_action = "return"
                recommended_quantity = projected - target
                return_quantity += recommended_quantity
                reason = (
                    f"Projected stock {projected} is {recommended_quantity} above target {target}; "
                    "use the authenticated vehicle-return custody workflow."
                )
            else:
                recommended_action = "balanced"
                recommended_quantity = 0
                reason = (
                    f"Projected stock matches target {target} after pending custody movements."
                )
            action_counts[recommended_action] += 1
            suggested, available = suggested_warehouse(
                vehicle, candidate_part.id, recommended_action
            )
            all_recommendations.append(
                VanRebalanceRecommendationRead(
                    engineer_id=engineer.id,
                    engineer_name=engineer.name,
                    warehouse_id=vehicle.id,
                    warehouse_code=vehicle.code,
                    warehouse_name=vehicle.name,
                    region_id=vehicle.region_id,
                    part_id=candidate_part.id,
                    part_number=candidate_part.part_number,
                    part_name=candidate_part.name,
                    current_quantity=current,
                    threshold_quantity=threshold,
                    consumed_quantity=consumed,
                    average_daily_usage=round(average_daily, 3),
                    forecast_quantity=forecast,
                    target_quantity=target,
                    pending_inbound_quantity=inbound,
                    pending_outbound_quantity=outbound,
                    projected_quantity=projected,
                    recommended_action=recommended_action,
                    recommended_quantity=recommended_quantity,
                    suggested_warehouse_id=suggested.id if suggested else None,
                    suggested_warehouse_code=suggested.code if suggested else None,
                    suggested_warehouse_name=suggested.name if suggested else None,
                    suggested_warehouse_available_quantity=available,
                    source_can_fulfill=bool(
                        recommended_action != "replenish"
                        or (available is not None and available >= recommended_quantity)
                    ),
                    reason=reason,
                )
            )

    action_order = {"replenish": 0, "return": 1, "balanced": 2}
    all_recommendations.sort(
        key=lambda item: (
            action_order[item.recommended_action],
            -item.recommended_quantity,
            item.engineer_name.lower(),
            item.part_number.lower(),
            item.warehouse_id,
            item.part_id,
        )
    )
    filtered = [
        item
        for item in all_recommendations
        if (action is None or item.recommended_action == action)
        and (
            include_balanced
            or action == "balanced"
            or item.recommended_action != "balanced"
        )
    ]
    result_truncated = len(filtered) > limit
    return VanPlanningRead(
        generated_at=_utcnow_naive(),
        lookback_days=lookback_days,
        coverage_days=coverage_days,
        summary=VanPlanningSummaryRead(
            vehicle_count=len(vehicle_rows),
            engineer_count=len({engineer.id for _vehicle, engineer in vehicle_rows}),
            consumed_quantity=total_consumed,
            work_order_count=total_work_orders,
            replenish_count=action_counts["replenish"],
            return_count=action_counts["return"],
            balanced_count=action_counts["balanced"],
            recommended_replenish_quantity=replenish_quantity,
            recommended_return_quantity=return_quantity,
        ),
        engineers=engineer_summaries,
        recommendations=filtered[:limit],
        truncated=vehicle_truncated or part_truncated or result_truncated,
    )
