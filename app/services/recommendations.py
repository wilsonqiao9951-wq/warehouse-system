from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from math import log2
import re
import unicodedata

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    InventoryTransaction,
    Part,
    ReplenishmentRequest,
    StorageLocation,
    VehicleReturnRequest,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
    WorkOrderPartMemory,
)
from app.schemas import PartRead, WorkOrderPartRecommendation


_SUCCESS_OUTCOMES = {"fixed", "repaired", "resolved", "successful", "success"}


@dataclass(frozen=True)
class _HistoryMatch:
    work_order: WorkOrder
    score: float
    factors: tuple[str, ...]


@dataclass(frozen=True)
class _InventoryPosition:
    available_quantity: int
    label: str | None
    warehouse_id: int | None
    location_id: int | None


def _normalize(value: str | None) -> str:
    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _description_tokens(item: WorkOrder) -> set[str]:
    text = _normalize(" ".join(filter(None, (item.problem_description, item.description))))
    return {token for token in re.findall(r"[^\W_]+", text) if len(token) > 1}


def _history_similarity(target: WorkOrder, historical: WorkOrder) -> tuple[float, tuple[str, ...]]:
    score = 0.0
    factors: list[str] = []

    machine_match = bool(_normalize(target.machine_type)) and (
        _normalize(target.machine_type) == _normalize(historical.machine_type)
    )
    job_match = bool(_normalize(target.job_type)) and (
        _normalize(target.job_type) == _normalize(historical.job_type)
    )
    if machine_match:
        score += 38
        factors.append("same machine")
    if job_match:
        score += 24
        factors.append("same job type")
    if machine_match and job_match:
        score += 18

    if bool(_normalize(target.fault_type)) and (
        _normalize(target.fault_type) == _normalize(historical.fault_type)
    ):
        score += 20
        factors.append("same fault type")
    if bool(_normalize(target.error_code)) and (
        _normalize(target.error_code) == _normalize(historical.error_code)
    ):
        score += 12
        factors.append("same error code")

    target_tokens = _description_tokens(target)
    historical_tokens = _description_tokens(historical)
    if target_tokens and historical_tokens:
        overlap = len(target_tokens & historical_tokens) / len(target_tokens | historical_tokens)
        if overlap >= 0.2:
            score += 10 + overlap * 20
            factors.append("similar symptoms")

    return min(100.0, score), tuple(factors)


def _inventory_positions(
    db: Session,
    part_ids: set[int],
    preferred_user_id: int | None,
) -> dict[int, _InventoryPosition]:
    if not part_ids:
        return {}

    warehouses = db.scalars(
        select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.id)
    ).all()
    locations = db.scalars(
        select(StorageLocation)
        .where(StorageLocation.is_active.is_(True))
        .order_by(StorageLocation.code)
    ).all()
    transactions = db.scalars(
        select(InventoryTransaction).where(InventoryTransaction.part_id.in_(part_ids))
    ).all()

    warehouse_quantities: dict[tuple[int, int], int] = defaultdict(int)
    location_quantities: dict[tuple[int, int], int] = defaultdict(int)
    for transaction in transactions:
        if transaction.to_warehouse_id:
            warehouse_quantities[(transaction.part_id, transaction.to_warehouse_id)] += transaction.quantity
        if transaction.from_warehouse_id:
            warehouse_quantities[(transaction.part_id, transaction.from_warehouse_id)] -= transaction.quantity
        if transaction.to_location_id:
            location_quantities[(transaction.part_id, transaction.to_location_id)] += transaction.quantity
        if transaction.from_location_id:
            location_quantities[(transaction.part_id, transaction.from_location_id)] -= transaction.quantity

    reservations: dict[tuple[int, int], int] = defaultdict(int)
    for request in db.scalars(
        select(ReplenishmentRequest).where(
            ReplenishmentRequest.part_id.in_(part_ids),
            ReplenishmentRequest.status == "picking",
        )
    ).all():
        if request.source_warehouse_id:
            reservations[(request.part_id, request.source_warehouse_id)] += request.quantity
    for request in db.scalars(
        select(VehicleReturnRequest).where(
            VehicleReturnRequest.part_id.in_(part_ids),
            VehicleReturnRequest.status == "approved",
        )
    ).all():
        reservations[(request.part_id, request.source_warehouse_id)] += request.quantity

    locations_by_warehouse: dict[int, list[StorageLocation]] = defaultdict(list)
    for location in locations:
        locations_by_warehouse[location.warehouse_id].append(location)

    results: dict[int, _InventoryPosition] = {}
    for part_id in part_ids:
        positions: list[tuple[int, int, Warehouse]] = []
        total_available = 0
        for warehouse in warehouses:
            available = max(
                0,
                warehouse_quantities[(part_id, warehouse.id)]
                - reservations[(part_id, warehouse.id)],
            )
            total_available += available
            if available:
                preferred = int(
                    preferred_user_id is not None
                    and warehouse.assigned_user_id == preferred_user_id
                )
                positions.append((preferred, available, warehouse))

        if not positions:
            results[part_id] = _InventoryPosition(0, None, None, None)
            continue

        _, _, best_warehouse = max(positions, key=lambda row: (row[0], row[1], -row[2].id))
        best_location = max(
            locations_by_warehouse.get(best_warehouse.id, []),
            key=lambda location: location_quantities[(part_id, location.id)],
            default=None,
        )
        if best_location and location_quantities[(part_id, best_location.id)] > 0:
            label = f"{best_warehouse.name} / {best_location.code}"
            location_id = best_location.id
        else:
            label = best_warehouse.name
            location_id = None
        results[part_id] = _InventoryPosition(
            total_available,
            label,
            best_warehouse.id,
            location_id,
        )
    return results


def _success_rate(matches: list[tuple[_HistoryMatch, int]]) -> float | None:
    labeled = [
        match.work_order
        for match, _ in matches
        if match.work_order.final_outcome and match.work_order.first_time_fix is not None
    ]
    if not labeled:
        return None
    successful = sum(
        1
        for item in labeled
        if _normalize(item.final_outcome) in _SUCCESS_OUTCOMES
        and item.first_time_fix is True
        and not item.is_rework
    )
    return round(successful / len(labeled), 3)


def _reason(
    factors: tuple[str, ...],
    usage_count: int,
    recommended_quantity: int,
    success_rate: float | None,
    average_repair_minutes: float | None,
    inventory: _InventoryPosition,
) -> str:
    basis = ", ".join(factors) if factors else "similar completed work"
    statements = [
        f"Matched by {basis}",
        (
            f"used on {usage_count} similar completed job"
            f"{'s' if usage_count != 1 else ''} (average {recommended_quantity} per job)"
        ),
    ]
    if success_rate is None:
        statements.append("first-time repair outcome is not yet labeled")
    else:
        statements.append(f"{round(success_rate * 100)}% first-time repair success")
    if average_repair_minutes is not None:
        statements.append(f"average repair time {round(average_repair_minutes)} minutes")
    if inventory.label:
        statements.append(f"{inventory.available_quantity} available; best location {inventory.label}")
    else:
        statements.append("currently out of stock")
    return "; ".join(statements) + "."


def _learned_recommendations(
    db: Session,
    target: WorkOrder,
) -> list[WorkOrderPartRecommendation]:
    history = db.scalars(
        select(WorkOrder)
        .where(
            WorkOrder.id != target.id,
            func.upper(WorkOrder.status) == "COMPLETED",
        )
        .order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc())
        .limit(500)
    ).all()
    matches_by_id: dict[int, _HistoryMatch] = {}
    for historical in history:
        score, factors = _history_similarity(target, historical)
        if score >= 18:
            matches_by_id[historical.id] = _HistoryMatch(historical, score, factors)
    if not matches_by_id:
        return []

    usage_rows = db.scalars(
        select(WorkOrderPart).where(WorkOrderPart.work_order_id.in_(matches_by_id))
    ).all()
    quantity_by_order_part: dict[tuple[int, int], int] = defaultdict(int)
    for usage in usage_rows:
        quantity_by_order_part[(usage.work_order_id, usage.part_id)] += usage.quantity

    matches_by_part: dict[int, list[tuple[_HistoryMatch, int]]] = defaultdict(list)
    for (work_order_id, part_id), quantity in quantity_by_order_part.items():
        matches_by_part[part_id].append((matches_by_id[work_order_id], quantity))
    if not matches_by_part:
        return []

    inventories = _inventory_positions(
        db,
        set(matches_by_part),
        target.claimed_by_id or target.engineer_id or target.assigned_user_id,
    )
    parts = {
        item.id: item
        for item in db.scalars(select(Part).where(Part.id.in_(matches_by_part))).all()
    }
    ranked: list[tuple[float, WorkOrderPartRecommendation]] = []
    for part_id, matches in matches_by_part.items():
        part = parts.get(part_id)
        if not part or not part.is_active:
            continue
        usage_count = len(matches)
        total_quantity = sum(quantity for _, quantity in matches)
        recommended_quantity = max(1, round(total_quantity / usage_count))
        success_rate = _success_rate(matches)
        repair_durations = [
            match.work_order.repair_duration_minutes
            for match, _ in matches
            if match.work_order.repair_duration_minutes is not None
        ]
        average_repair_minutes = (
            round(sum(repair_durations) / len(repair_durations), 1)
            if repair_durations
            else None
        )
        best_match = max(matches, key=lambda row: row[0].score)[0]
        average_similarity = sum(match.score for match, _ in matches) / usage_count
        evidence = min(1.0, log2(usage_count + 1) / 3)
        outcome_signal = success_rate if success_rate is not None else 0.5
        inventory = inventories[part_id]
        confidence = round(
            min(
                0.99,
                best_match.score / 100 * 0.55
                + average_similarity / 100 * 0.15
                + evidence * 0.15
                + outcome_signal * 0.10
                + (0.05 if inventory.available_quantity else 0),
            ),
            3,
        )
        rank_score = (
            best_match.score * 1.5
            + average_similarity * 0.5
            + evidence * 20
            + outcome_signal * 10
            + (5 if inventory.available_quantity else 0)
        )
        ranked.append(
            (
                rank_score,
                WorkOrderPartRecommendation(
                    part=PartRead.model_validate(part),
                    recommended_quantity=recommended_quantity,
                    usage_count=usage_count,
                    total_quantity=total_quantity,
                    success_rate=success_rate,
                    average_repair_minutes=average_repair_minutes,
                    available_quantity=inventory.available_quantity,
                    inventory_location=inventory.label,
                    inventory_warehouse_id=inventory.warehouse_id,
                    inventory_location_id=inventory.location_id,
                    confidence=confidence,
                    reason=_reason(
                        best_match.factors,
                        usage_count,
                        recommended_quantity,
                        success_rate,
                        average_repair_minutes,
                        inventory,
                    ),
                ),
            )
        )
    ranked.sort(key=lambda row: (-row[0], row[1].part.part_number))
    return [item for _, item in ranked[:20]]


def _legacy_recommendations(
    db: Session,
    target: WorkOrder,
) -> list[WorkOrderPartRecommendation]:
    memories = db.scalars(
        select(WorkOrderPartMemory).order_by(
            WorkOrderPartMemory.usage_count.desc(),
            WorkOrderPartMemory.total_quantity.desc(),
        )
    ).all()
    best_by_part: dict[int, tuple[float, WorkOrderPartMemory, tuple[str, ...]]] = {}
    for memory in memories:
        score = 0.0
        factors: list[str] = []
        machine_match = bool(_normalize(target.machine_type)) and (
            _normalize(target.machine_type) == _normalize(memory.machine_type)
        )
        job_match = bool(_normalize(target.job_type)) and (
            _normalize(target.job_type) == _normalize(memory.job_type)
        )
        if machine_match:
            score += 38
            factors.append("same machine")
        if job_match:
            score += 24
            factors.append("same job type")
        if machine_match and job_match:
            score += 18
        if score < 18:
            continue
        current = best_by_part.get(memory.part_id)
        if current is None or score > current[0]:
            best_by_part[memory.part_id] = (score, memory, tuple(factors))
    if not best_by_part:
        return []

    inventories = _inventory_positions(
        db,
        set(best_by_part),
        target.claimed_by_id or target.engineer_id or target.assigned_user_id,
    )
    parts = {
        item.id: item
        for item in db.scalars(select(Part).where(Part.id.in_(best_by_part))).all()
    }
    ranked: list[tuple[float, WorkOrderPartRecommendation]] = []
    for part_id, (score, memory, factors) in best_by_part.items():
        part = parts.get(part_id)
        if not part or not part.is_active:
            continue
        recommended_quantity = max(1, round(memory.total_quantity / memory.usage_count))
        inventory = inventories[part_id]
        confidence = round(
            min(
                0.69,
                score / 100 * 0.55
                + min(1.0, log2(memory.usage_count + 1) / 3) * 0.1
                + (0.05 if inventory.available_quantity else 0),
            ),
            3,
        )
        location_text = (
            f" {inventory.available_quantity} available; best location {inventory.label}."
            if inventory.label
            else " Currently out of stock."
        )
        ranked.append(
            (
                score + memory.usage_count,
                WorkOrderPartRecommendation(
                    part=PartRead.model_validate(part),
                    recommended_quantity=recommended_quantity,
                    usage_count=memory.usage_count,
                    total_quantity=memory.total_quantity,
                    success_rate=None,
                    average_repair_minutes=None,
                    available_quantity=inventory.available_quantity,
                    inventory_location=inventory.label,
                    inventory_warehouse_id=inventory.warehouse_id,
                    inventory_location_id=inventory.location_id,
                    confidence=confidence,
                    reason=(
                        f"Legacy aggregate matched by {', '.join(factors)}; used on "
                        f"{memory.usage_count} recorded job"
                        f"{'s' if memory.usage_count != 1 else ''} "
                        f"(average {recommended_quantity} per job). "
                        f"First-time repair outcome is not yet labeled."
                        f"{location_text}"
                    ),
                ),
            )
        )
    ranked.sort(key=lambda row: (-row[0], row[1].part.part_number))
    return [item for _, item in ranked[:20]]


def build_part_recommendations(
    db: Session,
    target: WorkOrder,
) -> list[WorkOrderPartRecommendation]:
    learned = _learned_recommendations(db, target)
    return learned if learned else _legacy_recommendations(db, target)
