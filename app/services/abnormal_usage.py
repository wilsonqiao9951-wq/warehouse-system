from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from math import ceil
from statistics import fmean, pstdev
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    InventoryRegion,
    Part,
    PartUsageBaseline,
    PartUsageReview,
    User,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)
from app.schemas import AbnormalUsageRow, PartUsageBaselineRead


EVALUATION_VERSION = "usage-anomaly-v1"
LOOKBACK_DAYS = 365
MAX_HISTORY_WORK_ORDERS = 10_000
MIN_QUANTITY_SAMPLES = 3
MIN_COMBINATION_WORK_ORDERS = 5
RARE_COMBINATION_RATIO = 0.20
OFF_HOURS_END = 6
OFF_HOURS_START = 22

SCOPE_DIMENSIONS = (
    ("job_machine_store", ("job_type", "machine_type", "store")),
    ("job_machine", ("job_type", "machine_type")),
    ("machine", ("machine_type",)),
    ("job", ("job_type",)),
    ("organization", ()),
)


@dataclass(frozen=True)
class EvaluationOutcome:
    review: PartUsageReview | None
    created: bool
    already_evaluated: bool


def _utcnow_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _key(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _segment(work_order: WorkOrder) -> dict[str, str]:
    return {
        "job_type": _key(work_order.job_type),
        "machine_type": _key(work_order.machine_type),
        "store": _key(work_order.store_name or work_order.outlet_name),
    }


def _scope_keys(scope: str, dimensions: tuple[str, ...], current: dict[str, str]) -> dict[str, str]:
    enabled = set(dimensions)
    return {
        "scope": scope,
        "job_type_key": current["job_type"] if "job_type" in enabled else "",
        "machine_type_key": current["machine_type"] if "machine_type" in enabled else "",
        "store_key": current["store"] if "store" in enabled else "",
    }


def _matches_scope(candidate: dict[str, str], dimensions: tuple[str, ...], current: dict[str, str]) -> bool:
    return all(candidate[name] == current[name] for name in dimensions)


def _percentile_nearest_rank(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, ceil(percentile * len(ordered)))
    return float(ordered[min(len(ordered), rank) - 1])


def _fingerprint(payload: dict) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _historical_evidence(
    db: Session,
    organization_id: int,
    before: datetime,
) -> tuple[list[WorkOrder], list[WorkOrderPart]]:
    start = before - timedelta(days=LOOKBACK_DAYS)
    order_query = (
        select(WorkOrder)
        .where(
            WorkOrder.organization_id == organization_id,
            WorkOrder.is_locked.is_(True),
            WorkOrder.completed_at.is_not(None),
            WorkOrder.completed_at >= start,
            WorkOrder.completed_at < before,
        )
        .order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc())
        .limit(MAX_HISTORY_WORK_ORDERS)
    )
    orders = db.scalars(order_query).all()
    if not orders:
        return [], []
    oldest_completion = min(row.completed_at for row in orders if row.completed_at is not None)
    usage_rows = db.scalars(
        select(WorkOrderPart)
        .join(WorkOrder, WorkOrder.id == WorkOrderPart.work_order_id)
        .where(
            WorkOrderPart.organization_id == organization_id,
            WorkOrder.organization_id == organization_id,
            WorkOrder.is_locked.is_(True),
            WorkOrder.completed_at.is_not(None),
            WorkOrder.completed_at >= oldest_completion,
            WorkOrder.completed_at < before,
            WorkOrderPart.created_at < before,
        )
        .order_by(WorkOrderPart.created_at.asc(), WorkOrderPart.id.asc())
    ).all()
    allowed = {row.id for row in orders}
    return orders, [row for row in usage_rows if row.work_order_id in allowed]


def _upsert_baseline(
    db: Session,
    *,
    organization_id: int,
    part_id: int,
    scope: str,
    dimensions: tuple[str, ...],
    current_segment: dict[str, str],
    history_orders: list[WorkOrder],
    history_usage: list[WorkOrderPart],
) -> PartUsageBaseline:
    keys = _scope_keys(scope, dimensions, current_segment)
    matching_orders = [
        row for row in history_orders if _matches_scope(_segment(row), dimensions, current_segment)
    ]
    matching_order_ids = {row.id for row in matching_orders}
    part_rows = [
        row
        for row in history_usage
        if row.part_id == part_id and row.work_order_id in matching_order_ids
    ]
    quantity_by_work_order: dict[int, int] = {}
    for row in part_rows:
        quantity_by_work_order[row.work_order_id] = quantity_by_work_order.get(row.work_order_id, 0) + row.quantity
    quantities = list(quantity_by_work_order.values())
    mean_quantity = fmean(quantities) if quantities else 0.0
    stddev_quantity = pstdev(quantities) if len(quantities) > 1 else 0.0
    p90_quantity = _percentile_nearest_rank(quantities, 0.9)
    spike_threshold = max(p90_quantity, mean_quantity * 1.8, mean_quantity + 2 * stddev_quantity)
    support_ratio = len(quantity_by_work_order) / len(matching_orders) if matching_orders else 0.0
    evidence_fingerprint = _fingerprint(
        {
            "version": EVALUATION_VERSION,
            "part_id": part_id,
            **keys,
            "orders": [
                (row.id, row.completed_at.isoformat() if row.completed_at else None)
                for row in matching_orders
            ],
            "usage": [(row.id, row.work_order_id, row.quantity) for row in part_rows],
        }
    )
    baseline = db.scalar(
        select(PartUsageBaseline)
        .where(
            PartUsageBaseline.organization_id == organization_id,
            PartUsageBaseline.part_id == part_id,
            PartUsageBaseline.scope == scope,
            PartUsageBaseline.job_type_key == keys["job_type_key"],
            PartUsageBaseline.machine_type_key == keys["machine_type_key"],
            PartUsageBaseline.store_key == keys["store_key"],
        )
        .with_for_update()
    )
    now = _utcnow_naive()
    values = {
        "sample_work_orders": len(quantity_by_work_order),
        "sample_usage_rows": len(part_rows),
        "segment_work_orders": len(matching_orders),
        "total_quantity": sum(quantities),
        "mean_quantity": float(mean_quantity),
        "stddev_quantity": float(stddev_quantity),
        "p90_quantity": p90_quantity,
        "spike_threshold": float(spike_threshold),
        "support_ratio": float(support_ratio),
        "first_observed_at": min((row.created_at for row in part_rows), default=None),
        "last_observed_at": max((row.created_at for row in part_rows), default=None),
        "source_fingerprint": evidence_fingerprint,
        "computed_at": now,
        "updated_at": now,
    }
    if baseline is None:
        baseline = PartUsageBaseline(
            organization_id=organization_id,
            part_id=part_id,
            **keys,
            **values,
            version=0,
            created_at=now,
        )
        db.add(baseline)
        db.flush()
        return baseline
    if baseline.source_fingerprint == evidence_fingerprint:
        return baseline
    for name, value in values.items():
        setattr(baseline, name, value)
    baseline.version += 1
    db.flush()
    return baseline


def _usage_timezone(db: Session, warehouse: Warehouse) -> str:
    if warehouse.region and warehouse.region.timezone:
        return warehouse.region.timezone
    default_region = db.scalar(
        select(InventoryRegion).where(
            InventoryRegion.organization_id == warehouse.organization_id,
            InventoryRegion.is_default.is_(True),
        )
    )
    return default_region.timezone if default_region else "UTC"


def _local_hour(used_at: datetime, timezone_name: str) -> int:
    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        zone = timezone.utc
    instant = used_at.replace(tzinfo=timezone.utc) if used_at.tzinfo is None else used_at.astimezone(timezone.utc)
    return instant.astimezone(zone).hour


def evaluate_part_usage(
    db: Session,
    organization_id: int,
    usage: WorkOrderPart,
) -> EvaluationOutcome:
    existing = db.scalar(
        select(PartUsageReview).where(
            PartUsageReview.organization_id == organization_id,
            PartUsageReview.work_order_part_id == usage.id,
        )
    )
    if existing is not None:
        return EvaluationOutcome(review=existing, created=False, already_evaluated=True)

    work_order = db.scalar(
        select(WorkOrder).where(
            WorkOrder.id == usage.work_order_id,
            WorkOrder.organization_id == organization_id,
        )
    )
    part = db.scalar(
        select(Part)
        .where(Part.id == usage.part_id, Part.organization_id == organization_id)
        .with_for_update()
    )
    warehouse = db.scalar(
        select(Warehouse).where(
            Warehouse.id == usage.warehouse_id,
            Warehouse.organization_id == organization_id,
        )
    )
    if work_order is None or part is None or warehouse is None:
        return EvaluationOutcome(review=None, created=False, already_evaluated=False)

    history_orders, history_usage = _historical_evidence(db, organization_id, usage.created_at)
    current_segment = _segment(work_order)
    baselines = [
        _upsert_baseline(
            db,
            organization_id=organization_id,
            part_id=part.id,
            scope=scope,
            dimensions=dimensions,
            current_segment=current_segment,
            history_orders=history_orders,
            history_usage=history_usage,
        )
        for scope, dimensions in SCOPE_DIMENSIONS
    ]
    exact = baselines[0]
    selected = next(
        (row for row in baselines if row.sample_work_orders >= MIN_QUANTITY_SAMPLES),
        None,
    )
    reason_codes: list[str] = []
    explanations: list[str] = []
    if selected and usage.quantity > selected.spike_threshold:
        reason_codes.append("quantity_spike")
        explanations.append(
            f"Quantity {usage.quantity} exceeds the {selected.scope} baseline threshold "
            f"{selected.spike_threshold:.2f} from {selected.sample_work_orders} prior work orders."
        )
    if (
        exact.segment_work_orders >= MIN_COMBINATION_WORK_ORDERS
        and exact.support_ratio < RARE_COMBINATION_RATIO
    ):
        reason_codes.append("unusual_part_combination")
        explanations.append(
            f"This part appeared in {exact.support_ratio:.0%} of {exact.segment_work_orders} prior "
            "work orders with the same job type, machine, and store context."
        )
    timezone_name = _usage_timezone(db, warehouse)
    local_hour = _local_hour(usage.created_at, timezone_name)
    if local_hour < OFF_HOURS_END or local_hour >= OFF_HOURS_START:
        reason_codes.append("off_hour_usage")
        explanations.append(
            f"Usage was recorded at local hour {local_hour:02d}:00 in {timezone_name}; "
            f"review hours are {OFF_HOURS_END:02d}:00-{OFF_HOURS_START:02d}:00."
        )
    if not reason_codes:
        return EvaluationOutcome(review=None, created=False, already_evaluated=False)

    if "quantity_spike" in reason_codes and selected and usage.quantity >= selected.spike_threshold * 2:
        severity = "high"
    elif len(reason_codes) >= 2:
        severity = "high"
    elif "quantity_spike" in reason_codes or "unusual_part_combination" in reason_codes:
        severity = "medium"
    else:
        severity = "low"
    evidence = {
        "evaluation_version": EVALUATION_VERSION,
        "organization_id": organization_id,
        "work_order_id": work_order.id,
        "work_order_part_id": usage.id,
        "part_id": part.id,
        "warehouse_id": warehouse.id,
        "observed_quantity": usage.quantity,
        "observed_parts_cost": usage.total_cost,
        "reason_codes": reason_codes,
        "baseline_id": selected.id if selected else None,
        "baseline_fingerprint": selected.source_fingerprint if selected else None,
        "exact_segment_fingerprint": exact.source_fingerprint,
        "usage_timezone": timezone_name,
        "usage_local_hour": local_hour,
    }
    now = _utcnow_naive()
    review = PartUsageReview(
        organization_id=organization_id,
        work_order_id=work_order.id,
        work_order_part_id=usage.id,
        part_id=part.id,
        warehouse_id=warehouse.id,
        engineer_id=(
            work_order.completed_by_id
            or work_order.claimed_by_id
            or work_order.engineer_id
            or usage.user_id
        ),
        baseline_id=selected.id if selected else None,
        status="pending",
        severity=severity,
        reason_codes_json=json.dumps(reason_codes, separators=(",", ":")),
        explanation_json=json.dumps(explanations, separators=(",", ":")),
        observed_quantity=usage.quantity,
        observed_parts_cost=usage.total_cost,
        baseline_scope=selected.scope if selected else None,
        baseline_sample_size=selected.sample_work_orders if selected else 0,
        baseline_mean_quantity=selected.mean_quantity if selected else 0.0,
        baseline_p90_quantity=selected.p90_quantity if selected else 0.0,
        baseline_spike_threshold=selected.spike_threshold if selected else 0.0,
        segment_work_order_count=exact.segment_work_orders,
        combination_support_ratio=exact.support_ratio,
        usage_timezone=timezone_name,
        usage_local_hour=local_hour,
        evaluation_version=EVALUATION_VERSION,
        source_fingerprint=_fingerprint(evidence),
        version=0,
        created_at=now,
        updated_at=now,
    )
    db.add(review)
    db.flush()
    return EvaluationOutcome(review=review, created=True, already_evaluated=False)


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def part_usage_review_read(
    db: Session,
    row: PartUsageReview,
    *,
    work_order_parts_cost: float | None = None,
) -> AbnormalUsageRow:
    work_order = db.get(WorkOrder, row.work_order_id)
    part = db.get(Part, row.part_id)
    warehouse = db.get(Warehouse, row.warehouse_id)
    engineer = db.get(User, row.engineer_id) if row.engineer_id else None
    acknowledger = db.get(User, row.acknowledged_by) if row.acknowledged_by else None
    reviewer = db.get(User, row.reviewed_by) if row.reviewed_by else None
    explanations = _json_list(row.explanation_json)
    if work_order_parts_cost is None:
        work_order_parts_cost = float(
            db.scalar(
                select(func.coalesce(func.sum(WorkOrderPart.total_cost), 0)).where(
                    WorkOrderPart.organization_id == row.organization_id,
                    WorkOrderPart.work_order_id == row.work_order_id,
                )
            )
            or 0
        )
    return AbnormalUsageRow(
        id=row.id,
        work_order_id=row.work_order_id,
        work_order_part_id=row.work_order_part_id,
        ticket_number=work_order.ticket_number if work_order else f"WO-{row.work_order_id}",
        engineer_id=row.engineer_id,
        engineer_name=engineer.name if engineer else None,
        part_id=row.part_id,
        part_number=part.part_number if part else f"PART-{row.part_id}",
        part_name=part.name if part else "Unavailable part",
        warehouse_id=row.warehouse_id,
        warehouse_name=warehouse.name if warehouse else "Unavailable warehouse",
        observed_quantity=row.observed_quantity,
        observed_parts_cost=row.observed_parts_cost,
        parts_cost=work_order_parts_cost,
        revenue=work_order.revenue if work_order else 0.0,
        status=row.status,
        severity=row.severity,
        reason_codes=_json_list(row.reason_codes_json),
        explanations=explanations,
        reason="; ".join(explanations),
        baseline_id=row.baseline_id,
        baseline_scope=row.baseline_scope,
        baseline_sample_size=row.baseline_sample_size,
        baseline_mean_quantity=row.baseline_mean_quantity,
        baseline_p90_quantity=row.baseline_p90_quantity,
        baseline_spike_threshold=row.baseline_spike_threshold,
        segment_work_order_count=row.segment_work_order_count,
        combination_support_ratio=row.combination_support_ratio,
        usage_timezone=row.usage_timezone,
        usage_local_hour=row.usage_local_hour,
        evaluation_version=row.evaluation_version,
        source_fingerprint=row.source_fingerprint,
        version=row.version,
        acknowledged_by=row.acknowledged_by,
        acknowledged_by_name=acknowledger.name if acknowledger else None,
        acknowledged_at=row.acknowledged_at,
        acknowledgement_note=row.acknowledgement_note,
        reviewed_by=row.reviewed_by,
        reviewed_by_name=reviewer.name if reviewer else None,
        reviewed_at=row.reviewed_at,
        decision_reason=row.decision_reason,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def part_usage_review_reads(
    db: Session,
    rows: list[PartUsageReview],
) -> list[AbnormalUsageRow]:
    if not rows:
        return []
    work_order_ids = {row.work_order_id for row in rows}
    cost_by_work_order = {
        work_order_id: float(total_cost or 0)
        for work_order_id, total_cost in db.execute(
            select(
                WorkOrderPart.work_order_id,
                func.coalesce(func.sum(WorkOrderPart.total_cost), 0),
            )
            .where(
                WorkOrderPart.organization_id == rows[0].organization_id,
                WorkOrderPart.work_order_id.in_(work_order_ids),
            )
            .group_by(WorkOrderPart.work_order_id)
        )
    }
    return [
        part_usage_review_read(
            db,
            row,
            work_order_parts_cost=cost_by_work_order.get(row.work_order_id, 0.0),
        )
        for row in rows
    ]


def part_usage_baseline_read(db: Session, row: PartUsageBaseline) -> PartUsageBaselineRead:
    part = db.get(Part, row.part_id)
    return PartUsageBaselineRead(
        id=row.id,
        part_id=row.part_id,
        part_number=part.part_number if part else f"PART-{row.part_id}",
        part_name=part.name if part else "Unavailable part",
        scope=row.scope,
        job_type_key=row.job_type_key,
        machine_type_key=row.machine_type_key,
        store_key=row.store_key,
        sample_work_orders=row.sample_work_orders,
        sample_usage_rows=row.sample_usage_rows,
        segment_work_orders=row.segment_work_orders,
        mean_quantity=row.mean_quantity,
        stddev_quantity=row.stddev_quantity,
        p90_quantity=row.p90_quantity,
        spike_threshold=row.spike_threshold,
        support_ratio=row.support_ratio,
        source_fingerprint=row.source_fingerprint,
        version=row.version,
        computed_at=row.computed_at,
    )
