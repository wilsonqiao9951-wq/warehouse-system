from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json

from fastapi import HTTPException

from app.models import ExternalIntegration, IntegrationParityContract
from app.schemas import (
    IntegrationParityAutomation,
    IntegrationParityColumn,
    IntegrationParityContractRead,
    IntegrationParityContractUpsert,
    IntegrationParityGapRead,
    IntegrationParityTable,
)
from app.services.integrations import integration_mapping, integration_subscribed_events


CAPABILITIES = (
    "work_order_intake",
    "work_order_status_read",
    "inventory_read",
    "recommendations_read",
    "status_callback",
    "completion_callback",
    "part_usage_callback",
)

_CANONICAL_FIELDS: dict[str, dict[str, set[str]]] = {
    "work_orders": {
        "work_order.external_id": {"inbound", "outbound", "read"},
        "work_order.ticket_number": {"inbound", "outbound", "read"},
        "work_order.wo_number": {"inbound", "outbound", "read"},
        "work_order.schedule_date": {"inbound", "outbound", "read"},
        "work_order.outlet_name": {"inbound", "outbound", "read"},
        "work_order.store_name": {"inbound", "outbound", "read"},
        "work_order.job_type": {"inbound", "outbound", "read"},
        "work_order.description": {"inbound", "outbound", "read"},
        "work_order.problem_description": {"inbound", "outbound", "read"},
        "work_order.address": {"inbound", "outbound", "read"},
        "work_order.city": {"inbound", "outbound", "read"},
        "work_order.state": {"inbound", "outbound", "read"},
        "work_order.zip": {"inbound", "outbound", "read"},
        "work_order.contact_phone": {"inbound", "outbound", "read"},
        "work_order.machine_type": {"inbound", "outbound", "read"},
        "work_order.status": {"inbound", "outbound", "read"},
        "work_order.claimed": {"outbound", "read"},
        "work_order.completed_at": {"outbound", "read"},
        "work_order.completed_by_id": {"outbound", "read"},
        "work_order.final_outcome": {"outbound", "read"},
        "work_order.first_time_fix": {"outbound", "read"},
    },
    "part_usage": {
        "part_usage.external_id": {"outbound", "read"},
        "part_usage.work_order_external_id": {"outbound", "read"},
        "part_usage.part_number": {"outbound", "read"},
        "part_usage.quantity": {"outbound", "read"},
        "part_usage.warehouse_code": {"outbound", "read"},
        "part_usage.used_by_id": {"outbound", "read"},
        "part_usage.used_at": {"outbound", "read"},
    },
    "inventory": {
        "inventory.part_number": {"read"},
        "inventory.part_name": {"read"},
        "inventory.warehouse_code": {"read"},
        "inventory.warehouse_name": {"read"},
        "inventory.quantity": {"read"},
        "inventory.available_quantity": {"read"},
        "inventory.unit": {"read"},
        "inventory.is_low_stock": {"read"},
    },
    "recommendations": {
        "recommendation.part_number": {"read"},
        "recommendation.part_name": {"read"},
        "recommendation.recommended_quantity": {"read"},
        "recommendation.historical_usage_count": {"read"},
        "recommendation.available_quantity": {"read"},
        "recommendation.reason": {"read"},
        "recommendation.confidence": {"read"},
    },
}

_CALLBACK_EVENTS = {
    "status_callback": "work_order.status_changed",
    "completion_callback": "work_order.completed",
    "part_usage_callback": "work_order.part_used",
}


@dataclass(frozen=True)
class ParityAssessment:
    covered_capabilities: list[str]
    gaps: list[IntegrationParityGapRead]
    readiness_status: str
    readiness_score: int
    source_fingerprint: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _direction_supports(actual: str, needed: str) -> bool:
    return actual == needed or actual == "bidirectional"


def _normalized_payload(payload: IntegrationParityContractUpsert) -> dict:
    required = sorted(set(payload.required_capabilities), key=CAPABILITIES.index)
    tables = [table.model_dump(mode="json") for table in payload.tables]
    automations = [automation.model_dump(mode="json") for automation in payload.automations]
    tables.sort(key=lambda row: (row["canonical_object"], row["external_name"].casefold()))
    automations.sort(key=lambda row: row["name"].casefold())
    return {
        "source_revision": payload.source_revision.strip(),
        "required_capabilities": required,
        "tables": tables,
        "automations": automations,
    }


def validate_parity_contract(payload: IntegrationParityContractUpsert) -> dict:
    normalized = _normalized_payload(payload)
    if len(_canonical_json(normalized).encode("utf-8")) > 1_048_576:
        raise HTTPException(status_code=422, detail="Parity contract cannot exceed 1 MiB")
    if len(normalized["required_capabilities"]) != len(payload.required_capabilities):
        raise HTTPException(status_code=422, detail="Required capabilities cannot repeat")

    table_names: set[str] = set()
    for table in payload.tables:
        table_name = table.external_name.casefold()
        if table_name in table_names:
            raise HTTPException(status_code=422, detail="External table names cannot repeat")
        table_names.add(table_name)
        external_names: set[str] = set()
        canonical_names: set[str] = set()
        for column in table.columns:
            external_name = column.external_name.casefold()
            if external_name in external_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"External columns cannot repeat in {table.external_name}",
                )
            external_names.add(external_name)
            canonical = column.canonical_field
            if not canonical:
                continue
            if canonical in canonical_names:
                raise HTTPException(
                    status_code=422,
                    detail=f"Canonical fields cannot repeat in {table.external_name}",
                )
            canonical_names.add(canonical)
            allowed_directions = _CANONICAL_FIELDS[table.canonical_object].get(canonical)
            if not allowed_directions:
                raise HTTPException(
                    status_code=422,
                    detail=f"Unsupported canonical field for {table.canonical_object}: {canonical}",
                )
            if column.direction == "bidirectional":
                if not {"inbound", "outbound"}.issubset(allowed_directions):
                    raise HTTPException(
                        status_code=422,
                        detail=f"{canonical} cannot be bidirectional",
                    )
            elif column.direction not in allowed_directions:
                raise HTTPException(
                    status_code=422,
                    detail=f"{canonical} does not support {column.direction} access",
                )
        if table.key_column.casefold() not in external_names:
            raise HTTPException(
                status_code=422,
                detail=f"Key column for {table.external_name} must exist in its columns",
            )

    automation_names: set[str] = set()
    for automation in payload.automations:
        key = automation.name.casefold()
        if key in automation_names:
            raise HTTPException(status_code=422, detail="Automation names cannot repeat")
        automation_names.add(key)
        callback = automation.capability in _CALLBACK_EVENTS
        if callback and automation.direction != "outbound":
            raise HTTPException(
                status_code=422,
                detail=f"{automation.capability} must be an outbound automation",
            )
        if automation.capability == "work_order_intake" and automation.direction != "inbound":
            raise HTTPException(
                status_code=422,
                detail="work_order_intake must be an inbound automation",
            )
    return normalized


def _has_fields(
    tables: list[IntegrationParityTable],
    canonical_object: str,
    required: list[tuple[str, str]],
) -> bool:
    for table in tables:
        if table.canonical_object != canonical_object:
            continue
        indexed = {
            column.canonical_field: column
            for column in table.columns
            if column.canonical_field
        }
        if all(
            field in indexed and _direction_supports(indexed[field].direction, direction)
            for field, direction in required
        ):
            return True
    return False


def _has_any_field(
    tables: list[IntegrationParityTable],
    canonical_object: str,
    fields: list[str],
    direction: str,
) -> bool:
    return any(
        table.canonical_object == canonical_object
        and any(
            column.canonical_field in fields
            and _direction_supports(column.direction, direction)
            for column in table.columns
        )
        for table in tables
    )


def assess_parity_contract(
    integration: ExternalIntegration,
    payload: IntegrationParityContractUpsert,
) -> ParityAssessment:
    normalized = validate_parity_contract(payload)
    covered: set[str] = set()
    gaps: list[IntegrationParityGapRead] = []
    tables = payload.tables

    intake_core = _has_fields(
        tables,
        "work_orders",
        [("work_order.external_id", "inbound")],
    ) and _has_any_field(
        tables,
        "work_orders",
        ["work_order.ticket_number", "work_order.wo_number"],
        "inbound",
    )
    mapping_matches = True
    work_order_columns = [
        column
        for table in tables
        if table.canonical_object == "work_orders"
        for column in table.columns
    ]
    for canonical, external_name in integration_mapping(integration).items():
        expected = f"work_order.{canonical}"
        if not any(
            column.canonical_field == expected
            and column.external_name == external_name
            and _direction_supports(column.direction, "inbound")
            for column in work_order_columns
        ):
            mapping_matches = False
            gaps.append(
                IntegrationParityGapRead(
                    code="field_mapping_mismatch",
                    severity="error",
                    capability="work_order_intake",
                    message=(
                        f"Configured field mapping {canonical} → {external_name} is not represented "
                        "as an inbound work-order contract column."
                    ),
                )
            )
    intake_automation = any(
        automation.enabled
        and automation.capability == "work_order_intake"
        and automation.direction == "inbound"
        for automation in payload.automations
    )
    if intake_core and mapping_matches and intake_automation:
        covered.add("work_order_intake")

    if _has_fields(
        tables,
        "work_orders",
        [("work_order.external_id", "read"), ("work_order.status", "read")],
    ):
        covered.add("work_order_status_read")
    if _has_fields(
        tables,
        "inventory",
        [("inventory.part_number", "read"), ("inventory.warehouse_code", "read")],
    ) and _has_any_field(
        tables,
        "inventory",
        ["inventory.quantity", "inventory.available_quantity"],
        "read",
    ):
        covered.add("inventory_read")
    if _has_fields(
        tables,
        "recommendations",
        [
            ("recommendation.part_number", "read"),
            ("recommendation.recommended_quantity", "read"),
            ("recommendation.reason", "read"),
        ],
    ):
        covered.add("recommendations_read")

    enabled_automations = {
        automation.capability
        for automation in payload.automations
        if automation.enabled and automation.direction == "outbound"
    }
    subscribed = set(integration_subscribed_events(integration))
    callback_fields = {
        "status_callback": (
            "work_orders",
            [("work_order.external_id", "outbound"), ("work_order.status", "outbound")],
        ),
        "completion_callback": (
            "work_orders",
            [
                ("work_order.external_id", "outbound"),
                ("work_order.completed_at", "outbound"),
                ("work_order.final_outcome", "outbound"),
            ],
        ),
        "part_usage_callback": (
            "part_usage",
            [
                ("part_usage.work_order_external_id", "outbound"),
                ("part_usage.part_number", "outbound"),
                ("part_usage.quantity", "outbound"),
            ],
        ),
    }
    for capability, event_name in _CALLBACK_EVENTS.items():
        object_name, fields = callback_fields[capability]
        if (
            integration.is_active
            and integration.webhook_url
            and event_name in subscribed
            and capability in enabled_automations
            and _has_fields(tables, object_name, fields)
        ):
            covered.add(capability)

    required = normalized["required_capabilities"]
    if not integration.is_active:
        covered.clear()
        gaps.append(
            IntegrationParityGapRead(
                code="integration_inactive",
                severity="error",
                message="The integration API key is inactive, so parallel-run capabilities are unavailable.",
            )
        )
    for capability in required:
        if capability not in covered and not any(
            gap.capability == capability and gap.severity == "error" for gap in gaps
        ):
            gaps.append(
                IntegrationParityGapRead(
                    code="capability_not_covered",
                    severity="error",
                    capability=capability,
                    message=f"Required capability {capability} is not fully mapped or configured.",
                )
            )
    if not payload.source_revision.strip():
        gaps.append(
            IntegrationParityGapRead(
                code="source_revision_missing",
                severity="warning",
                message="Record the AppSheet version, sheet revision, or discovery date before UAT.",
            )
        )
    unmapped_count = sum(
        1 for table in tables for column in table.columns if not column.canonical_field
    )
    if unmapped_count:
        gaps.append(
            IntegrationParityGapRead(
                code="external_columns_unmapped",
                severity="warning",
                message=f"{unmapped_count} external columns are documented but not mapped to OpenPartsFlow.",
            )
        )

    covered_required = len(set(required).intersection(covered))
    score = round(covered_required * 100 / len(required))
    status = "ready" if score == 100 and not any(gap.severity == "error" for gap in gaps) else "blocked"
    fingerprint = sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()
    return ParityAssessment(
        covered_capabilities=sorted(covered, key=CAPABILITIES.index),
        gaps=gaps,
        readiness_status=status,
        readiness_score=score,
        source_fingerprint=fingerprint,
    )


def default_parity_payload(integration: ExternalIntegration) -> IntegrationParityContractUpsert:
    mapping = integration_mapping(integration)
    work_order_columns = [
        IntegrationParityColumn(
            external_name="Row ID",
            canonical_field="work_order.external_id",
            data_type="text",
            direction="bidirectional",
            required=True,
            notes="Stable AppSheet key or Google Sheets row identifier.",
        )
    ]
    for canonical, external_name in sorted(mapping.items()):
        work_order_columns.append(
            IntegrationParityColumn(
                external_name=external_name,
                canonical_field=f"work_order.{canonical}",
                data_type="date" if canonical == "schedule_date" else "text",
                direction="bidirectional" if canonical == "status" else "inbound",
                required=canonical in {"ticket_number", "wo_number"},
            )
        )
    if not any(column.canonical_field == "work_order.status" for column in work_order_columns):
        work_order_columns.append(
            IntegrationParityColumn(
                external_name="Status",
                canonical_field="work_order.status",
                data_type="enum",
                direction="bidirectional",
            )
        )
    work_order_columns.extend(
        [
            IntegrationParityColumn(
                external_name="Completed At",
                canonical_field="work_order.completed_at",
                data_type="datetime",
                direction="outbound",
            ),
            IntegrationParityColumn(
                external_name="Final Outcome",
                canonical_field="work_order.final_outcome",
                data_type="text",
                direction="outbound",
            ),
        ]
    )
    tables = [
        IntegrationParityTable(
            external_name="Work Orders",
            canonical_object="work_orders",
            key_column="Row ID",
            description="Inbound dispatch plus safe status and completion return fields.",
            columns=work_order_columns,
        ),
        IntegrationParityTable(
            external_name="Parts Usage",
            canonical_object="part_usage",
            key_column="Event ID",
            columns=[
                IntegrationParityColumn(external_name="Event ID", canonical_field="part_usage.external_id", direction="outbound", required=True),
                IntegrationParityColumn(external_name="Work Order Row ID", canonical_field="part_usage.work_order_external_id", direction="outbound", required=True),
                IntegrationParityColumn(external_name="Part Number", canonical_field="part_usage.part_number", direction="outbound", required=True),
                IntegrationParityColumn(external_name="Quantity", canonical_field="part_usage.quantity", data_type="number", direction="outbound", required=True),
                IntegrationParityColumn(external_name="Warehouse", canonical_field="part_usage.warehouse_code", direction="outbound"),
            ],
        ),
        IntegrationParityTable(
            external_name="Inventory",
            canonical_object="inventory",
            key_column="Part Number",
            columns=[
                IntegrationParityColumn(external_name="Part Number", canonical_field="inventory.part_number", direction="read", required=True),
                IntegrationParityColumn(external_name="Warehouse", canonical_field="inventory.warehouse_code", direction="read", required=True),
                IntegrationParityColumn(external_name="Quantity", canonical_field="inventory.quantity", data_type="number", direction="read", required=True),
                IntegrationParityColumn(external_name="Available", canonical_field="inventory.available_quantity", data_type="number", direction="read"),
                IntegrationParityColumn(external_name="Low Stock", canonical_field="inventory.is_low_stock", data_type="boolean", direction="read"),
            ],
        ),
        IntegrationParityTable(
            external_name="Recommendations",
            canonical_object="recommendations",
            key_column="Part Number",
            columns=[
                IntegrationParityColumn(external_name="Part Number", canonical_field="recommendation.part_number", direction="read", required=True),
                IntegrationParityColumn(external_name="Recommended Quantity", canonical_field="recommendation.recommended_quantity", data_type="number", direction="read", required=True),
                IntegrationParityColumn(external_name="Reason", canonical_field="recommendation.reason", direction="read", required=True),
                IntegrationParityColumn(external_name="Confidence", canonical_field="recommendation.confidence", data_type="number", direction="read"),
            ],
        ),
    ]
    automations = [
        IntegrationParityAutomation(
            name="Import new and updated work orders",
            trigger="row_added",
            direction="inbound",
            capability="work_order_intake",
            external_action="POST the row to /api/external/v1/work-orders with an idempotency key.",
        ),
        IntegrationParityAutomation(
            name="Apply work-order status callback",
            trigger="webhook",
            direction="outbound",
            capability="status_callback",
            external_action="Verify the signature and update the linked row status.",
        ),
        IntegrationParityAutomation(
            name="Apply completion callback",
            trigger="webhook",
            direction="outbound",
            capability="completion_callback",
            external_action="Verify the signature and write completion evidence to the linked row.",
        ),
        IntegrationParityAutomation(
            name="Append used part callback",
            trigger="webhook",
            direction="outbound",
            capability="part_usage_callback",
            external_action="Verify the signature and append the idempotent parts-usage event.",
        ),
    ]
    return IntegrationParityContractUpsert(
        expected_version=0,
        source_revision="",
        required_capabilities=list(CAPABILITIES),
        tables=tables,
        automations=automations,
    )


def _load_json(value: str, fallback: object) -> object:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def parity_contract_read(
    integration: ExternalIntegration,
    contract: IntegrationParityContract | None,
) -> IntegrationParityContractRead:
    if contract is None:
        payload = default_parity_payload(integration)
        assessment = assess_parity_contract(integration, payload)
        return IntegrationParityContractRead(
            persisted=False,
            organization_id=integration.organization_id,
            integration_id=integration.id,
            provider=integration.provider,
            source_revision=payload.source_revision,
            required_capabilities=payload.required_capabilities,
            covered_capabilities=assessment.covered_capabilities,
            tables=payload.tables,
            automations=payload.automations,
            readiness_status="draft",
            readiness_score=assessment.readiness_score,
            gaps=assessment.gaps,
            source_fingerprint=assessment.source_fingerprint,
            version=0,
        )
    return IntegrationParityContractRead(
        id=contract.id,
        persisted=True,
        organization_id=contract.organization_id,
        integration_id=contract.integration_id,
        provider=integration.provider,
        source_revision=contract.source_revision,
        required_capabilities=_load_json(contract.required_capabilities_json, []),
        covered_capabilities=_load_json(contract.covered_capabilities_json, []),
        tables=_load_json(contract.tables_json, []),
        automations=_load_json(contract.automations_json, []),
        readiness_status=contract.readiness_status,
        readiness_score=contract.readiness_score,
        gaps=_load_json(contract.gaps_json, []),
        source_fingerprint=contract.source_fingerprint,
        version=contract.version,
        created_by=contract.created_by,
        updated_by=contract.updated_by,
        validated_at=contract.validated_at,
        created_at=contract.created_at,
        updated_at=contract.updated_at,
    )


def stored_parity_payload(
    contract: IntegrationParityContract,
) -> IntegrationParityContractUpsert:
    return IntegrationParityContractUpsert(
        expected_version=contract.version,
        source_revision=contract.source_revision,
        required_capabilities=_load_json(contract.required_capabilities_json, []),
        tables=_load_json(contract.tables_json, []),
        automations=_load_json(contract.automations_json, []),
    )


def apply_parity_contract(
    contract: IntegrationParityContract,
    payload: IntegrationParityContractUpsert,
    assessment: ParityAssessment,
    *,
    actor_id: int,
) -> None:
    normalized = validate_parity_contract(payload)
    now = datetime.utcnow()
    contract.source_revision = normalized["source_revision"]
    contract.required_capabilities_json = _canonical_json(normalized["required_capabilities"])
    contract.covered_capabilities_json = _canonical_json(assessment.covered_capabilities)
    contract.tables_json = _canonical_json(normalized["tables"])
    contract.automations_json = _canonical_json(normalized["automations"])
    contract.gaps_json = _canonical_json([gap.model_dump(mode="json") for gap in assessment.gaps])
    contract.readiness_status = assessment.readiness_status
    contract.readiness_score = assessment.readiness_score
    contract.source_fingerprint = assessment.source_fingerprint
    contract.updated_by = actor_id
    contract.validated_at = now
    contract.updated_at = now
