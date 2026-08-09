from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from app.models import (
    ExternalIntegration,
    ExternalWorkOrderLink,
    IntegrationParallelReconciliation,
    IntegrationParityContract,
    InventoryTransaction,
    Part,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
)
from app.schemas import (
    IntegrationParallelReconciliationCreate,
    IntegrationParallelReconciliationRead,
)


MAX_STORED_DISCREPANCIES = 500


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _hash(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _unique_map(rows, key_builder, value_builder, label: str) -> dict[str, str | int]:
    result: dict[str, str | int] = {}
    for row in rows:
        key = key_builder(row)
        if key in result:
            raise HTTPException(
                status_code=422,
                detail=f"Parallel-run {label} snapshot contains duplicate key: {key}",
            )
        result[key] = value_builder(row)
    return result


def _external_maps(payload: IntegrationParallelReconciliationCreate) -> dict[str, dict[str, str | int]]:
    work_orders = _unique_map(
        payload.work_orders,
        lambda row: row.external_id,
        lambda row: row.status.casefold(),
        "work-order",
    )
    part_usage = _unique_map(
        payload.part_usage,
        lambda row: f"{row.external_work_order_id}|{row.part_number.upper()}",
        lambda row: row.quantity,
        "part-usage",
    )
    inventory = _unique_map(
        payload.inventory,
        lambda row: f"{row.warehouse_code.upper()}|{row.part_number.upper()}",
        lambda row: row.quantity,
        "inventory",
    )
    if any(value == 0 for value in inventory.values()):
        raise HTTPException(
            status_code=422,
            detail="Parallel-run inventory snapshots must omit zero balances",
        )
    return {
        "work_orders": work_orders,
        "part_usage": part_usage,
        "inventory": inventory,
    }


def _openpartsflow_maps(
    db: Session,
    integration: ExternalIntegration,
    *,
    organization_id: int,
    observed_from: datetime,
    observed_to: datetime,
) -> dict[str, dict[str, str | int]]:
    work_orders = {
        external_id: (status or "").strip().casefold()
        for external_id, status in db.execute(
            select(ExternalWorkOrderLink.external_id, WorkOrder.status)
            .join(WorkOrder, WorkOrder.id == ExternalWorkOrderLink.work_order_id)
            .where(
                ExternalWorkOrderLink.organization_id == organization_id,
                WorkOrder.organization_id == organization_id,
                ExternalWorkOrderLink.integration_id == integration.id,
                WorkOrder.updated_at >= observed_from,
                WorkOrder.updated_at <= observed_to,
            )
        ).all()
    }

    part_usage = {
        f"{external_id}|{part_number.upper()}": int(quantity or 0)
        for external_id, part_number, quantity in db.execute(
            select(
                ExternalWorkOrderLink.external_id,
                Part.part_number,
                func.sum(WorkOrderPart.quantity),
            )
            .join(
                WorkOrderPart,
                WorkOrderPart.work_order_id == ExternalWorkOrderLink.work_order_id,
            )
            .join(Part, Part.id == WorkOrderPart.part_id)
            .where(
                ExternalWorkOrderLink.organization_id == organization_id,
                WorkOrderPart.organization_id == organization_id,
                Part.organization_id == organization_id,
                ExternalWorkOrderLink.integration_id == integration.id,
                WorkOrderPart.updated_at >= observed_from,
                WorkOrderPart.updated_at <= observed_to,
            )
            .group_by(ExternalWorkOrderLink.external_id, Part.part_number)
        ).all()
    }

    from_warehouse = aliased(Warehouse)
    to_warehouse = aliased(Warehouse)
    inventory: dict[str, int] = {}
    inventory_rows = db.execute(
        select(
            Part.part_number,
            InventoryTransaction.quantity,
            from_warehouse.code,
            to_warehouse.code,
        )
        .join(Part, Part.id == InventoryTransaction.part_id)
        .outerjoin(
            from_warehouse,
            from_warehouse.id == InventoryTransaction.from_warehouse_id,
        )
        .outerjoin(
            to_warehouse,
            to_warehouse.id == InventoryTransaction.to_warehouse_id,
        )
        .where(
            InventoryTransaction.organization_id == organization_id,
            Part.organization_id == organization_id,
        )
    ).all()
    for part_number, quantity, from_code, to_code in inventory_rows:
        if to_code:
            key = f"{to_code.upper()}|{part_number.upper()}"
            inventory[key] = inventory.get(key, 0) + int(quantity)
        if from_code:
            key = f"{from_code.upper()}|{part_number.upper()}"
            inventory[key] = inventory.get(key, 0) - int(quantity)
    inventory = {key: value for key, value in inventory.items() if value != 0}
    return {
        "work_orders": work_orders,
        "part_usage": part_usage,
        "inventory": inventory,
    }


def _compare_maps(
    external: dict[str, dict[str, str | int]],
    internal: dict[str, dict[str, str | int]],
) -> tuple[dict[str, dict[str, int]], list[dict], int, int]:
    object_settings = {
        "work_orders": ("work_order", "status"),
        "part_usage": ("part_usage", "quantity"),
        "inventory": ("inventory", "quantity"),
    }
    counts: dict[str, dict[str, int]] = {}
    discrepancies: list[dict] = []
    total_matched = 0
    total_discrepancies = 0
    for collection, (object_type, field) in object_settings.items():
        external_rows = external[collection]
        internal_rows = internal[collection]
        matched = 0
        object_discrepancies = 0
        for key in sorted(set(external_rows) | set(internal_rows)):
            external_value = external_rows.get(key)
            internal_value = internal_rows.get(key)
            reason = None
            if key not in external_rows:
                reason = "missing_external"
            elif key not in internal_rows:
                reason = "missing_openpartsflow"
            elif external_value != internal_value:
                reason = "value_mismatch"
            else:
                matched += 1
                continue
            object_discrepancies += 1
            total_discrepancies += 1
            if len(discrepancies) < MAX_STORED_DISCREPANCIES:
                discrepancies.append(
                    {
                        "object_type": object_type,
                        "key": key,
                        "field": field,
                        "openpartsflow_value": internal_value,
                        "external_value": external_value,
                        "reason": reason,
                    }
                )
        counts[collection] = {
            "external": len(external_rows),
            "openpartsflow": len(internal_rows),
            "matched": matched,
            "discrepancies": object_discrepancies,
        }
        total_matched += matched
    return counts, discrepancies, total_matched, total_discrepancies


def reconciliation_read(
    row: IntegrationParallelReconciliation,
) -> IntegrationParallelReconciliationRead:
    try:
        object_counts = json.loads(row.object_counts_json)
    except (TypeError, json.JSONDecodeError):
        object_counts = {}
    try:
        discrepancies = json.loads(row.discrepancies_json)
    except (TypeError, json.JSONDecodeError):
        discrepancies = []
    return IntegrationParallelReconciliationRead(
        id=row.id,
        organization_id=row.organization_id,
        integration_id=row.integration_id,
        contract_id=row.contract_id,
        source_revision=row.source_revision,
        contract_fingerprint=row.contract_fingerprint,
        snapshot_fingerprint=row.snapshot_fingerprint,
        evidence_fingerprint=row.evidence_fingerprint,
        observed_from=row.observed_from,
        observed_to=row.observed_to,
        status=row.status,
        input_record_count=row.input_record_count,
        matched_record_count=row.matched_record_count,
        discrepancy_count=row.discrepancy_count,
        object_counts=object_counts,
        discrepancies=discrepancies,
        truncated=row.truncated,
        reason=row.reason,
        created_by=row.created_by,
        created_at=row.created_at,
    )


def run_parallel_reconciliation(
    db: Session,
    integration: ExternalIntegration,
    contract: IntegrationParityContract,
    payload: IntegrationParallelReconciliationCreate,
    *,
    organization_id: int,
    actor_id: int | None,
) -> tuple[IntegrationParallelReconciliation, bool]:
    if integration.provider not in {"appsheet", "google_sheets"}:
        raise HTTPException(
            status_code=422,
            detail="Parallel reconciliation is available only for AppSheet and Google Sheets integrations",
        )
    if not integration.is_active:
        raise HTTPException(status_code=409, detail="Inactive integrations cannot be reconciled")
    if contract.readiness_status != "ready":
        raise HTTPException(status_code=409, detail="A ready parity contract is required")
    if payload.source_revision != contract.source_revision:
        raise HTTPException(
            status_code=409,
            detail="Snapshot source revision does not match the ready parity contract",
        )

    observed_from = _utc_naive(payload.observed_from)
    observed_to = _utc_naive(payload.observed_to)
    external = _external_maps(payload)
    internal = _openpartsflow_maps(
        db,
        integration,
        organization_id=organization_id,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    snapshot_document = {
        "source_revision": payload.source_revision,
        "observed_from": observed_from.isoformat(timespec="microseconds"),
        "observed_to": observed_to.isoformat(timespec="microseconds"),
        "objects": external,
    }
    snapshot_fingerprint = _hash(snapshot_document)
    evidence_fingerprint = _hash(
        {
            "contract_fingerprint": contract.source_fingerprint,
            "snapshot_fingerprint": snapshot_fingerprint,
            "openpartsflow": internal,
        }
    )
    existing = db.scalar(
        select(IntegrationParallelReconciliation).where(
            IntegrationParallelReconciliation.organization_id == organization_id,
            IntegrationParallelReconciliation.integration_id == integration.id,
            IntegrationParallelReconciliation.evidence_fingerprint == evidence_fingerprint,
        )
    )
    if existing:
        return existing, False

    counts, discrepancies, matched_count, discrepancy_count = _compare_maps(
        external,
        internal,
    )
    row = IntegrationParallelReconciliation(
        organization_id=organization_id,
        integration_id=integration.id,
        contract_id=contract.id,
        source_revision=payload.source_revision,
        contract_fingerprint=contract.source_fingerprint,
        snapshot_fingerprint=snapshot_fingerprint,
        evidence_fingerprint=evidence_fingerprint,
        observed_from=observed_from,
        observed_to=observed_to,
        status="matched" if discrepancy_count == 0 else "differences",
        input_record_count=sum(len(rows) for rows in external.values()),
        matched_record_count=matched_count,
        discrepancy_count=discrepancy_count,
        object_counts_json=_canonical_json(counts),
        discrepancies_json=_canonical_json(discrepancies),
        truncated=discrepancy_count > len(discrepancies),
        reason=payload.reason,
        created_by=actor_id,
        created_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # A concurrent exact retry may win the unique evidence insert after
        # the pre-check. Roll back this no-side-effect attempt and return the
        # winner instead of surfacing a spurious conflict.
        db.rollback()
        existing = db.scalar(
            select(IntegrationParallelReconciliation).where(
                IntegrationParallelReconciliation.organization_id == organization_id,
                IntegrationParallelReconciliation.integration_id == integration.id,
                IntegrationParallelReconciliation.evidence_fingerprint == evidence_fingerprint,
            )
        )
        if existing:
            return existing, False
        raise
    return row, True
