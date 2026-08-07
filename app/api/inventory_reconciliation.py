from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, aliased

from app.core.database import get_db
from app.core.rbac import Actor, get_current_actor, require_roles
from app.models import (
    InventoryCountLine,
    InventoryCountSession,
    InventoryTransaction,
    Part,
    ReplenishmentRequest,
    StorageLocation,
    TransactionType,
    UserRole,
    VehicleReturnRequest,
    Warehouse,
)
from app.schemas import (
    InventoryReconciliationExceptionRead,
    InventoryReconciliationPageRead,
)


router = APIRouter(prefix="/inventory", tags=["inventory-reconciliation"])

CANDIDATE_SCAN_LIMIT = 500


def _transaction_map(
    db: Session,
    actor: Actor,
    transaction_ids: set[int],
) -> dict[int, InventoryTransaction]:
    if not transaction_ids:
        return {}
    rows: dict[int, InventoryTransaction] = {}
    ordered_ids = sorted(transaction_ids)
    # Keep the IN clause below conservative SQLite and proxy parameter limits.
    for offset in range(0, len(ordered_ids), 400):
        chunk = ordered_ids[offset : offset + 400]
        for row in db.scalars(
            select(InventoryTransaction).where(
                InventoryTransaction.organization_id == actor.organization_id,
                InventoryTransaction.id.in_(chunk),
            )
        ).all():
            rows[row.id] = row
    return rows


def _warehouse_route(
    source_code: str | None,
    source_name: str | None,
    destination_code: str | None,
    destination_name: str | None,
) -> str | None:
    source = source_code or source_name
    destination = destination_code or destination_name
    if source and destination:
        return f"{source} -> {destination}"
    return source or destination


def _replenishment_errors(
    item: ReplenishmentRequest,
    transactions: dict[int, InventoryTransaction],
) -> list[str]:
    errors: list[str] = []
    shipment_required = item.status in {"shipped", "received", "completed"}
    receipt_required = item.status in {"received", "completed"}
    shipment = transactions.get(item.shipment_transaction_id or 0)
    receipt = transactions.get(item.receipt_transaction_id or 0)

    if shipment_required and shipment is None:
        errors.append("shipment transaction is missing")
    if item.shipment_transaction_id is not None and not shipment_required:
        errors.append(f"status {item.status} must not retain a shipment transaction")
    if shipment is not None and (
        shipment.replenishment_request_id != item.id
        or shipment.movement_stage != "ship"
        or shipment.transaction_type != TransactionType.OUTBOUND
        or shipment.part_id != item.part_id
        or shipment.quantity != item.quantity
        or shipment.from_warehouse_id != item.source_warehouse_id
    ):
        errors.append("shipment transaction does not match custody evidence")

    if receipt_required and receipt is None:
        errors.append("receipt transaction is missing")
    if item.receipt_transaction_id is not None and not receipt_required:
        errors.append(f"status {item.status} must not retain a receipt transaction")
    if receipt is not None and (
        receipt.replenishment_request_id != item.id
        or receipt.movement_stage != "receive"
        or receipt.transaction_type != TransactionType.INBOUND
        or receipt.part_id != item.part_id
        or receipt.quantity != item.quantity
        or receipt.to_warehouse_id != item.destination_warehouse_id
    ):
        errors.append("receipt transaction does not match custody evidence")
    return errors


def _vehicle_return_errors(
    item: VehicleReturnRequest,
    transactions: dict[int, InventoryTransaction],
) -> list[str]:
    errors: list[str] = []
    shipment_required = item.status in {"shipped", "received"}
    receipt_required = item.status == "received"
    shipment = transactions.get(item.shipment_transaction_id or 0)
    receipt = transactions.get(item.receipt_transaction_id or 0)

    if shipment_required and shipment is None:
        errors.append("handover transaction is missing")
    if item.shipment_transaction_id is not None and not shipment_required:
        errors.append(f"status {item.status} must not retain a handover transaction")
    if shipment is not None and (
        shipment.vehicle_return_request_id != item.id
        or shipment.movement_stage != "return_ship"
        or shipment.transaction_type != TransactionType.OUTBOUND
        or shipment.part_id != item.part_id
        or shipment.quantity != item.quantity
        or shipment.from_warehouse_id != item.source_warehouse_id
    ):
        errors.append("handover transaction does not match return evidence")

    if receipt_required and receipt is None:
        errors.append("warehouse receipt transaction is missing")
    if item.receipt_transaction_id is not None and not receipt_required:
        errors.append(f"status {item.status} must not retain a receipt transaction")
    if receipt is not None and (
        receipt.vehicle_return_request_id != item.id
        or receipt.movement_stage != "return_receive"
        or receipt.transaction_type != TransactionType.INBOUND
        or receipt.part_id != item.part_id
        or receipt.quantity != item.quantity
        or receipt.to_warehouse_id != item.destination_warehouse_id
    ):
        errors.append("receipt transaction does not match return evidence")
    return errors


def _count_adjustment_errors(
    item: InventoryCountSession,
    line: InventoryCountLine,
    variance: int,
    transaction: InventoryTransaction | None,
) -> list[str]:
    if transaction is None:
        return ["adjustment transaction is missing"]
    errors: list[str] = []
    if (
        transaction.transaction_type != TransactionType.ADJUSTMENT
        or transaction.inventory_count_line_id != line.id
        or transaction.part_id != line.part_id
        or transaction.quantity != abs(variance)
    ):
        errors.append("adjustment transaction does not match count evidence")
    if variance > 0 and (
        transaction.to_warehouse_id != item.warehouse_id
        or transaction.to_location_id != item.location_id
        or transaction.from_warehouse_id is not None
        or transaction.from_location_id is not None
    ):
        errors.append("positive variance is not posted to the counted location")
    if variance < 0 and (
        transaction.from_warehouse_id != item.warehouse_id
        or transaction.from_location_id != item.location_id
        or transaction.to_warehouse_id is not None
        or transaction.to_location_id is not None
    ):
        errors.append("negative variance is not posted from the counted location")
    return errors


def _replenishment_exceptions(
    db: Session,
    actor: Actor,
) -> tuple[list[InventoryReconciliationExceptionRead], bool]:
    source = aliased(Warehouse)
    destination = aliased(Warehouse)
    rows = db.execute(
        select(
            ReplenishmentRequest,
            Part.part_number,
            Part.name,
            source.code,
            source.name,
            destination.code,
            destination.name,
        )
        .join(
            Part,
            (Part.id == ReplenishmentRequest.part_id)
            & (Part.organization_id == actor.organization_id),
        )
        .outerjoin(
            source,
            (source.id == ReplenishmentRequest.source_warehouse_id)
            & (source.organization_id == actor.organization_id),
        )
        .outerjoin(
            destination,
            (destination.id == ReplenishmentRequest.destination_warehouse_id)
            & (destination.organization_id == actor.organization_id),
        )
        .where(
            ReplenishmentRequest.organization_id == actor.organization_id,
            or_(
                ReplenishmentRequest.requires_reconciliation.is_(True),
                ReplenishmentRequest.status.in_(("shipped", "received", "completed")),
                ReplenishmentRequest.shipment_transaction_id.is_not(None),
                ReplenishmentRequest.receipt_transaction_id.is_not(None),
            ),
        )
        .order_by(ReplenishmentRequest.updated_at.desc(), ReplenishmentRequest.id.desc())
        .limit(CANDIDATE_SCAN_LIMIT + 1)
    ).all()
    truncated = len(rows) > CANDIDATE_SCAN_LIMIT
    rows = rows[:CANDIDATE_SCAN_LIMIT]
    transaction_ids = {
        transaction_id
        for values in rows
        for transaction_id in (values[0].shipment_transaction_id, values[0].receipt_transaction_id)
        if transaction_id is not None
    }
    transactions = _transaction_map(db, actor, transaction_ids)
    exceptions: list[InventoryReconciliationExceptionRead] = []
    for (
        item,
        part_number,
        part_name,
        source_code,
        source_name,
        destination_code,
        destination_name,
    ) in rows:
        warehouse_label = _warehouse_route(
            source_code,
            source_name,
            destination_code,
            destination_name,
        )
        if item.requires_reconciliation:
            linked = bool(item.shipment_transaction_id or item.receipt_transaction_id)
            detail = (
                "Legacy custody is marked for reconciliation and already has linked stock movements; "
                "inspect the evidence before any correction."
                if linked
                else "Legacy custody has no trustworthy linked movements; an administrator must reset "
                "or explicitly accept the historical record."
            )
            exceptions.append(
                InventoryReconciliationExceptionRead(
                    id=f"replenishment:{item.id}:legacy",
                    source="replenishment",
                    kind="legacy_reconciliation",
                    severity="critical" if linked else "warning",
                    entity_type="replenishment_request",
                    entity_id=item.id,
                    status=item.status,
                    title=f"Replenishment #{item.id} needs historical reconciliation",
                    detail=detail,
                    part_id=item.part_id,
                    part_number=part_number,
                    part_name=part_name,
                    warehouse_label=warehouse_label,
                    quantity=item.quantity,
                    shipment_transaction_id=item.shipment_transaction_id,
                    receipt_transaction_id=item.receipt_transaction_id,
                    action_route=f"/warehouse-tasks#replenishment-{item.id}",
                    action_label="Review replenishment",
                    updated_at=item.updated_at or item.created_at,
                )
            )
            continue
        errors = _replenishment_errors(item, transactions)
        if errors:
            exceptions.append(
                InventoryReconciliationExceptionRead(
                    id=f"replenishment:{item.id}:ledger",
                    source="replenishment",
                    kind="custody_ledger_mismatch",
                    severity="critical",
                    entity_type="replenishment_request",
                    entity_id=item.id,
                    status=item.status,
                    title=f"Replenishment #{item.id} has inconsistent ledger evidence",
                    detail="; ".join(errors),
                    part_id=item.part_id,
                    part_number=part_number,
                    part_name=part_name,
                    warehouse_label=warehouse_label,
                    quantity=item.quantity,
                    shipment_transaction_id=item.shipment_transaction_id,
                    receipt_transaction_id=item.receipt_transaction_id,
                    action_route=f"/warehouse-tasks#replenishment-{item.id}",
                    action_label="Inspect custody",
                    updated_at=item.updated_at or item.created_at,
                )
            )
    return exceptions, truncated


def _vehicle_return_exceptions(
    db: Session,
    actor: Actor,
) -> tuple[list[InventoryReconciliationExceptionRead], bool]:
    source = aliased(Warehouse)
    destination = aliased(Warehouse)
    rows = db.execute(
        select(
            VehicleReturnRequest,
            Part.part_number,
            Part.name,
            source.code,
            source.name,
            destination.code,
            destination.name,
        )
        .join(
            Part,
            (Part.id == VehicleReturnRequest.part_id)
            & (Part.organization_id == actor.organization_id),
        )
        .join(
            source,
            (source.id == VehicleReturnRequest.source_warehouse_id)
            & (source.organization_id == actor.organization_id),
        )
        .join(
            destination,
            (destination.id == VehicleReturnRequest.destination_warehouse_id)
            & (destination.organization_id == actor.organization_id),
        )
        .where(
            VehicleReturnRequest.organization_id == actor.organization_id,
            or_(
                VehicleReturnRequest.status.in_(("shipped", "received")),
                VehicleReturnRequest.shipment_transaction_id.is_not(None),
                VehicleReturnRequest.receipt_transaction_id.is_not(None),
            ),
        )
        .order_by(VehicleReturnRequest.updated_at.desc(), VehicleReturnRequest.id.desc())
        .limit(CANDIDATE_SCAN_LIMIT + 1)
    ).all()
    truncated = len(rows) > CANDIDATE_SCAN_LIMIT
    rows = rows[:CANDIDATE_SCAN_LIMIT]
    transaction_ids = {
        transaction_id
        for values in rows
        for transaction_id in (values[0].shipment_transaction_id, values[0].receipt_transaction_id)
        if transaction_id is not None
    }
    transactions = _transaction_map(db, actor, transaction_ids)
    exceptions: list[InventoryReconciliationExceptionRead] = []
    for (
        item,
        part_number,
        part_name,
        source_code,
        source_name,
        destination_code,
        destination_name,
    ) in rows:
        errors = _vehicle_return_errors(item, transactions)
        if not errors:
            continue
        exceptions.append(
            InventoryReconciliationExceptionRead(
                id=f"vehicle-return:{item.id}:ledger",
                source="vehicle_return",
                kind="custody_ledger_mismatch",
                severity="critical",
                entity_type="vehicle_return_request",
                entity_id=item.id,
                status=item.status,
                title=f"Vehicle return #{item.id} has inconsistent ledger evidence",
                detail="; ".join(errors),
                part_id=item.part_id,
                part_number=part_number,
                part_name=part_name,
                warehouse_label=_warehouse_route(
                    source_code,
                    source_name,
                    destination_code,
                    destination_name,
                ),
                quantity=item.quantity,
                shipment_transaction_id=item.shipment_transaction_id,
                receipt_transaction_id=item.receipt_transaction_id,
                action_route=f"/warehouse-tasks#vehicle-return-{item.id}",
                action_label="Inspect vehicle return",
                updated_at=item.updated_at or item.created_at,
            )
        )
    return exceptions, truncated


def _inventory_count_exceptions(
    db: Session,
    actor: Actor,
) -> tuple[list[InventoryReconciliationExceptionRead], bool]:
    rows = db.execute(
        select(
            InventoryCountSession,
            InventoryCountLine,
            Part.part_number,
            Part.name,
            Warehouse.code,
            Warehouse.name,
            StorageLocation.code,
        )
        .join(
            InventoryCountLine,
            (InventoryCountLine.session_id == InventoryCountSession.id)
            & (InventoryCountLine.organization_id == actor.organization_id),
        )
        .join(
            Part,
            (Part.id == InventoryCountLine.part_id)
            & (Part.organization_id == actor.organization_id),
        )
        .join(
            Warehouse,
            (Warehouse.id == InventoryCountSession.warehouse_id)
            & (Warehouse.organization_id == actor.organization_id),
        )
        .outerjoin(
            StorageLocation,
            (StorageLocation.id == InventoryCountSession.location_id)
            & (StorageLocation.organization_id == actor.organization_id),
        )
        .where(
            InventoryCountSession.organization_id == actor.organization_id,
            or_(
                InventoryCountSession.status.in_(("submitted", "approved")),
                InventoryCountLine.adjustment_transaction_id.is_not(None),
            ),
        )
        .order_by(InventoryCountSession.updated_at.desc(), InventoryCountLine.id.desc())
        .limit(CANDIDATE_SCAN_LIMIT + 1)
    ).all()
    truncated = len(rows) > CANDIDATE_SCAN_LIMIT
    rows = rows[:CANDIDATE_SCAN_LIMIT]
    adjustment_ids = {
        values[1].adjustment_transaction_id
        for values in rows
        if values[1].adjustment_transaction_id is not None
    }
    transactions = _transaction_map(db, actor, adjustment_ids)
    exceptions: list[InventoryReconciliationExceptionRead] = []
    for item, line, part_number, part_name, warehouse_code, warehouse_name, location_code in rows:
        warehouse_label = warehouse_code or warehouse_name
        if location_code:
            warehouse_label = f"{warehouse_label} / {location_code}"
        severity: Literal["critical", "warning"] | None = None
        kind: Literal[
            "count_pending_variance",
            "count_ledger_mismatch",
        ] | None = None
        detail = ""
        variance: int | None = None

        if item.status == "submitted":
            if line.adjustment_transaction_id is not None:
                severity, kind = "critical", "count_ledger_mismatch"
                detail = "Submitted count already has an adjustment transaction before approval."
            elif line.submitted_book_quantity is None:
                severity, kind = "critical", "count_ledger_mismatch"
                detail = "Submitted count is missing its immutable book-quantity snapshot."
            else:
                variance = line.counted_quantity - line.submitted_book_quantity
                if variance:
                    severity, kind = "warning", "count_pending_variance"
                    detail = (
                        f"Physical count differs from the submission snapshot by {variance:+d}; "
                        "administrator approval will recalculate the live variance before posting."
                    )
        elif item.status == "approved":
            if line.approved_book_quantity is None or line.variance_quantity is None:
                severity, kind = "critical", "count_ledger_mismatch"
                detail = "Approved count is missing book-quantity or variance evidence."
            else:
                variance = line.counted_quantity - line.approved_book_quantity
                errors: list[str] = []
                if line.variance_quantity != variance:
                    errors.append("stored variance does not match approved count evidence")
                if variance == 0 and line.adjustment_transaction_id is not None:
                    errors.append("zero variance must not have an adjustment transaction")
                if variance != 0:
                    errors.extend(
                        _count_adjustment_errors(
                            item,
                            line,
                            variance,
                            transactions.get(line.adjustment_transaction_id or 0),
                        )
                    )
                if errors:
                    severity, kind = "critical", "count_ledger_mismatch"
                    detail = "; ".join(errors)
        elif line.adjustment_transaction_id is not None:
            severity, kind = "critical", "count_ledger_mismatch"
            detail = f"Count status {item.status} must not retain an adjustment transaction."

        if severity is None or kind is None:
            continue
        exceptions.append(
            InventoryReconciliationExceptionRead(
                id=f"inventory-count:{item.id}:{line.id}",
                source="inventory_count",
                kind=kind,
                severity=severity,
                entity_type="inventory_count",
                entity_id=item.id,
                line_id=line.id,
                status=item.status,
                title=(
                    f"Inventory count #{item.id} has a pending variance"
                    if kind == "count_pending_variance"
                    else f"Inventory count #{item.id} has inconsistent ledger evidence"
                ),
                detail=detail,
                part_id=line.part_id,
                part_number=part_number,
                part_name=part_name,
                warehouse_label=warehouse_label,
                quantity=line.counted_quantity,
                variance_quantity=variance,
                adjustment_transaction_id=line.adjustment_transaction_id,
                action_route=f"/inventory-counts#count-{item.id}",
                action_label="Review inventory count",
                updated_at=item.updated_at or item.created_at,
            )
        )
    return exceptions, truncated


@router.get(
    "/reconciliation-exceptions",
    response_model=InventoryReconciliationPageRead,
)
def inventory_reconciliation_exceptions(
    response: Response,
    source: Literal["replenishment", "vehicle_return", "inventory_count"] | None = Query(default=None),
    severity: Literal["critical", "warning"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    response.headers["Cache-Control"] = "no-store"

    exceptions: list[InventoryReconciliationExceptionRead] = []
    truncated = False
    if source in {None, "replenishment"}:
        rows, source_truncated = _replenishment_exceptions(db, actor)
        exceptions.extend(rows)
        truncated = truncated or source_truncated
    if source in {None, "vehicle_return"}:
        rows, source_truncated = _vehicle_return_exceptions(db, actor)
        exceptions.extend(rows)
        truncated = truncated or source_truncated
    if source in {None, "inventory_count"}:
        rows, source_truncated = _inventory_count_exceptions(db, actor)
        exceptions.extend(rows)
        truncated = truncated or source_truncated

    if severity is not None:
        exceptions = [row for row in exceptions if row.severity == severity]
    exceptions.sort(key=lambda row: (row.updated_at, row.id), reverse=True)
    exceptions.sort(key=lambda row: 0 if row.severity == "critical" else 1)
    total = len(exceptions)
    critical = sum(row.severity == "critical" for row in exceptions)
    warning = total - critical
    return InventoryReconciliationPageRead(
        items=exceptions[:limit],
        total=total,
        critical=critical,
        warning=warning,
        replenishment=sum(row.source == "replenishment" for row in exceptions),
        vehicle_return=sum(row.source == "vehicle_return" for row in exceptions),
        inventory_count=sum(row.source == "inventory_count" for row in exceptions),
        truncated=truncated or total > limit,
        candidate_scan_limit=CANDIDATE_SCAN_LIMIT,
    )
