from __future__ import annotations

from datetime import datetime
import json
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, set_tenant_database_scope
from app.core.permissions import INTEGRATIONS_MANAGE, INTEGRATIONS_READ
from app.core.rbac import Actor, get_current_actor, require_permission
from app.core.security import verify_password
from app.models import (
    AuditLog,
    ExternalIntegration,
    ExternalSyncLog,
    ExternalWorkOrderLink,
    IntegrationAdapterConfiguration,
    IntegrationConnectionTest,
    IntegrationParallelReconciliation,
    IntegrationParityContract,
    Organization,
    Part,
    Warehouse,
    WorkOrder,
    User,
)
from app.schemas import (
    ExternalInventoryBalanceRead,
    ExternalIntegrationCreate,
    ExternalIntegrationRead,
    ExternalIntegrationRotate,
    ExternalIntegrationSecretRead,
    ExternalIntegrationUpdate,
    IntegrationAdapterConfigurationRead,
    IntegrationAdapterConfigurationUpsert,
    IntegrationAdapterConnectionTestRequest,
    IntegrationConnectionTestRead,
    IntegrationParallelReconciliationCreate,
    IntegrationParallelReconciliationRead,
    IntegrationParityContractRead,
    IntegrationParityContractUpsert,
    ExternalPartRecommendationRead,
    ExternalSyncLogRead,
    ExternalWorkOrderRead,
    ExternalWorkOrderUpsert,
    ExternalWorkOrderUpsertRead,
)
from app.services.integrations import (
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    integration_read,
    sync_log_read,
    upsert_external_work_order,
    validate_field_mapping,
    validate_subscribed_events,
    validate_webhook_url,
)
from app.services.inventory import get_available_stock_quantity, get_stock_balances
from app.services.commercial import consume_monthly_usage, require_subscription_access
from app.services.integration_parity import (
    apply_parity_contract,
    assess_parity_contract,
    parity_contract_read,
    stored_parity_payload,
)
from app.services.integration_reconciliation import (
    reconciliation_read,
    run_parallel_reconciliation,
)
from app.services.integration_adapters import (
    IntegrationCredentialConfigurationError,
    adapter_configuration_read,
    connection_evidence_fingerprint,
    connection_test_read,
    decrypt_integration_credential,
    encrypt_integration_credential,
    normalize_adapter_base_url,
    normalize_api_key_header,
    normalize_health_path,
    probe_adapter_connection,
)
from app.services.recommendations import build_part_recommendations


router = APIRouter()


def _require_account_reauthentication(
    db: Session,
    actor: Actor,
    password: str | None,
) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method not in {"bearer", "cookie"} or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated session required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _integration_or_404(db: Session, integration_id: int) -> ExternalIntegration:
    integration = db.get(ExternalIntegration, integration_id)
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    return integration


def _adapter_integration_or_422(
    db: Session, integration_id: int
) -> ExternalIntegration:
    integration = _integration_or_404(db, integration_id)
    if integration.provider not in {"erp", "wms"}:
        raise HTTPException(
            status_code=422,
            detail="Adapter connections are available only for ERP and WMS integrations",
        )
    return integration


def _latest_connection_test(
    db: Session,
    integration_id: int,
) -> IntegrationConnectionTest | None:
    return db.scalar(
        select(IntegrationConnectionTest)
        .where(IntegrationConnectionTest.integration_id == integration_id)
        .order_by(
            IntegrationConnectionTest.tested_at.desc(),
            IntegrationConnectionTest.id.desc(),
        )
        .limit(1)
    )


def _audit_integration(
    db: Session,
    actor: Actor,
    action: str,
    integration: ExternalIntegration,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=actor.organization_id,
            user_id=actor.user_id,
            action=action,
            entity_type="external_integration",
            entity_id=integration.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "provider": integration.provider,
                    **(metadata or {}),
                },
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def get_external_integration(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> ExternalIntegration:
    provided_key = x_api_key or ""
    if len(provided_key) > 200:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    prefix = api_key_prefix(provided_key)
    candidate = (
        db.scalar(
            select(ExternalIntegration).where(
                ExternalIntegration.key_prefix == prefix,
            )
        )
        if prefix
        else None
    )
    expected_hash = candidate.api_key_hash if candidate else "0" * 64
    key_matches = secrets.compare_digest(hash_api_key(provided_key), expected_hash)
    if not candidate or not key_matches or not candidate.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive API key")
    organization = db.get(Organization, candidate.organization_id)
    require_subscription_access(organization)
    set_tenant_database_scope(db, candidate.organization_id)
    return candidate


@router.get(
    "/integrations",
    response_model=list[ExternalIntegrationRead],
)
def list_integrations(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    rows = db.scalars(
        select(ExternalIntegration).order_by(
            ExternalIntegration.is_active.desc(),
            ExternalIntegration.name,
            ExternalIntegration.id,
        )
    ).all()
    return [integration_read(row) for row in rows]


@router.post(
    "/integrations",
    response_model=ExternalIntegrationSecretRead,
)
def create_integration(
    payload: ExternalIntegrationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    mapping = validate_field_mapping(payload.field_mapping)
    webhook_url = validate_webhook_url(payload.webhook_url)
    subscribed_events = validate_subscribed_events(payload.subscribed_events)
    if subscribed_events and not webhook_url:
        raise HTTPException(
            status_code=422,
            detail="A webhook URL is required when outbound events are subscribed",
        )
    raw_key, prefix, key_hash = generate_api_key()
    integration = ExternalIntegration(
        organization_id=actor.organization_id,
        name=payload.name.strip(),
        provider=payload.provider,
        key_prefix=prefix,
        api_key_hash=key_hash,
        field_mapping_json=json.dumps(mapping, separators=(",", ":")),
        webhook_url=webhook_url,
        subscribed_events_json=json.dumps(subscribed_events, separators=(",", ":")),
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(integration)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    _audit_integration(db, actor, "create_external_integration", integration)
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.patch(
    "/integrations/{integration_id}",
    response_model=ExternalIntegrationRead,
)
def update_integration(
    integration_id: int,
    payload: ExternalIntegrationUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    changed_fields: list[str] = []
    if payload.name is not None:
        integration.name = payload.name.strip()
        changed_fields.append("name")
    if payload.field_mapping is not None:
        integration.field_mapping_json = json.dumps(
            validate_field_mapping(payload.field_mapping),
            separators=(",", ":"),
        )
        changed_fields.append("field_mapping")
    webhook_url = integration.webhook_url
    if "webhook_url" in payload.model_fields_set:
        webhook_url = validate_webhook_url(payload.webhook_url)
    subscribed_events = json.loads(integration.subscribed_events_json or "[]")
    if payload.subscribed_events is not None:
        subscribed_events = validate_subscribed_events(payload.subscribed_events)
    if subscribed_events and not webhook_url:
        raise HTTPException(
            status_code=422,
            detail="A webhook URL is required when outbound events are subscribed",
        )
    if "webhook_url" in payload.model_fields_set:
        integration.webhook_url = webhook_url
        changed_fields.append("webhook_url")
    if payload.subscribed_events is not None:
        integration.subscribed_events_json = json.dumps(
            subscribed_events,
            separators=(",", ":"),
        )
        changed_fields.append("subscribed_events")
    if payload.is_active is not None:
        integration.is_active = payload.is_active
        changed_fields.append("is_active")
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    if integration.parity_contract and set(changed_fields).intersection(
        {"field_mapping", "webhook_url", "subscribed_events", "is_active"}
    ):
        parity_payload = stored_parity_payload(integration.parity_contract)
        parity_assessment = assess_parity_contract(integration, parity_payload)
        integration.parity_contract.version += 1
        apply_parity_contract(
            integration.parity_contract,
            parity_payload,
            parity_assessment,
            actor_id=actor.user_id,
        )
        db.add(integration.parity_contract)
        changed_fields.append("parity_readiness")
    _audit_integration(
        db,
        actor,
        "update_external_integration",
        integration,
        {
            "changed_fields": sorted(changed_fields),
            "new_version": integration.version,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="An integration with this name already exists",
        ) from exc
    db.refresh(integration)
    return integration_read(integration)


@router.get(
    "/integrations/{integration_id}/parity-contract",
    response_model=IntegrationParityContractRead,
)
def get_integration_parity_contract(
    integration_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    integration = _integration_or_404(db, integration_id)
    contract = db.scalar(
        select(IntegrationParityContract).where(
            IntegrationParityContract.integration_id == integration.id,
        )
    )
    return parity_contract_read(integration, contract)


@router.put(
    "/integrations/{integration_id}/parity-contract",
    response_model=IntegrationParityContractRead,
)
def save_integration_parity_contract(
    integration_id: int,
    payload: IntegrationParityContractUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    integration = db.scalar(
        select(ExternalIntegration)
        .where(ExternalIntegration.id == integration_id)
        .with_for_update()
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    contract = db.scalar(
        select(IntegrationParityContract).where(
            IntegrationParityContract.integration_id == integration.id,
        )
    )
    if contract is None:
        if payload.expected_version != 0:
            raise HTTPException(status_code=409, detail="Parity contract version is stale")
        assessment = assess_parity_contract(integration, payload)
        contract = IntegrationParityContract(
            organization_id=actor.organization_id,
            integration_id=integration.id,
            source_fingerprint=assessment.source_fingerprint,
            created_by=actor.user_id,
            updated_by=actor.user_id,
            validated_at=datetime.utcnow(),
        )
        apply_parity_contract(
            contract,
            payload,
            assessment,
            actor_id=actor.user_id,
        )
        db.add(contract)
        action = "create_integration_parity_contract"
    else:
        if contract.version != payload.expected_version:
            raise HTTPException(status_code=409, detail="Parity contract version is stale")
        assessment = assess_parity_contract(integration, payload)
        if contract.source_fingerprint == assessment.source_fingerprint:
            return parity_contract_read(integration, contract)
        contract.version += 1
        apply_parity_contract(
            contract,
            payload,
            assessment,
            actor_id=actor.user_id,
        )
        db.add(contract)
        action = "update_integration_parity_contract"
    db.flush()
    _audit_integration(
        db,
        actor,
        action,
        integration,
        {
            "parity_contract_id": contract.id,
            "new_version": contract.version,
            "readiness_status": contract.readiness_status,
            "readiness_score": contract.readiness_score,
            "source_fingerprint": contract.source_fingerprint,
        },
    )
    db.commit()
    db.refresh(contract)
    return parity_contract_read(integration, contract)


@router.post(
    "/integrations/{integration_id}/parallel-reconciliations",
    response_model=IntegrationParallelReconciliationRead,
)
def create_integration_parallel_reconciliation(
    integration_id: int,
    payload: IntegrationParallelReconciliationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    integration = db.scalar(
        select(ExternalIntegration).where(
            ExternalIntegration.id == integration_id,
            ExternalIntegration.organization_id == actor.organization_id,
        )
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    contract = db.scalar(
        select(IntegrationParityContract).where(
            IntegrationParityContract.organization_id == actor.organization_id,
            IntegrationParityContract.integration_id == integration.id,
        )
    )
    if not contract:
        raise HTTPException(status_code=409, detail="A persisted parity contract is required")
    _require_account_reauthentication(db, actor, payload.account_password)
    row, created = run_parallel_reconciliation(
        db,
        integration,
        contract,
        payload,
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
    )
    if created:
        _audit_integration(
            db,
            actor,
            "create_integration_parallel_reconciliation",
            integration,
            {
                "reconciliation_id": row.id,
                "status": row.status,
                "input_record_count": row.input_record_count,
                "matched_record_count": row.matched_record_count,
                "discrepancy_count": row.discrepancy_count,
                "contract_fingerprint": row.contract_fingerprint,
                "snapshot_fingerprint": row.snapshot_fingerprint,
                "evidence_fingerprint": row.evidence_fingerprint,
                "truncated": row.truncated,
            },
        )
        db.commit()
        db.refresh(row)
    return reconciliation_read(row)


@router.get(
    "/integrations/{integration_id}/parallel-reconciliations",
    response_model=list[IntegrationParallelReconciliationRead],
)
def list_integration_parallel_reconciliations(
    integration_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    integration = db.scalar(
        select(ExternalIntegration).where(
            ExternalIntegration.id == integration_id,
            ExternalIntegration.organization_id == actor.organization_id,
        )
    )
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")
    rows = db.scalars(
        select(IntegrationParallelReconciliation)
        .where(
            IntegrationParallelReconciliation.organization_id == actor.organization_id,
            IntegrationParallelReconciliation.integration_id == integration.id,
        )
        .order_by(
            IntegrationParallelReconciliation.created_at.desc(),
            IntegrationParallelReconciliation.id.desc(),
        )
        .limit(limit)
    ).all()
    return [reconciliation_read(row) for row in rows]


@router.get(
    "/integrations/{integration_id}/parallel-reconciliations/{reconciliation_id}",
    response_model=IntegrationParallelReconciliationRead,
)
def get_integration_parallel_reconciliation(
    integration_id: int,
    reconciliation_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    row = db.scalar(
        select(IntegrationParallelReconciliation).where(
            IntegrationParallelReconciliation.id == reconciliation_id,
            IntegrationParallelReconciliation.integration_id == integration_id,
            IntegrationParallelReconciliation.organization_id == actor.organization_id,
        )
    )
    if not row:
        raise HTTPException(status_code=404, detail="Parallel reconciliation not found")
    return reconciliation_read(row)


@router.get(
    "/integrations/{integration_id}/adapter",
    response_model=IntegrationAdapterConfigurationRead,
)
def get_integration_adapter_configuration(
    integration_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    integration = _adapter_integration_or_422(db, integration_id)
    configuration = db.scalar(
        select(IntegrationAdapterConfiguration).where(
            IntegrationAdapterConfiguration.integration_id == integration.id
        )
    )
    if configuration is None:
        return IntegrationAdapterConfigurationRead(
            persisted=False,
            organization_id=actor.organization_id,
            integration_id=integration.id,
            protocol="rest_json",
            base_url="",
            health_path="/",
            auth_type="none",
            has_credentials=False,
            timeout_seconds=settings.integration_connection_timeout_seconds,
            version=0,
        )
    return adapter_configuration_read(
        configuration,
        _latest_connection_test(db, integration.id),
    )


@router.put(
    "/integrations/{integration_id}/adapter",
    response_model=IntegrationAdapterConfigurationRead,
)
def save_integration_adapter_configuration(
    integration_id: int,
    payload: IntegrationAdapterConfigurationUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    _require_account_reauthentication(db, actor, payload.account_password)
    integration = db.scalar(
        select(ExternalIntegration)
        .where(ExternalIntegration.id == integration_id)
        .with_for_update()
    )
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    if integration.provider not in {"erp", "wms"}:
        raise HTTPException(
            status_code=422,
            detail="Adapter connections are available only for ERP and WMS integrations",
        )
    if payload.timeout_seconds > settings.integration_connection_timeout_seconds:
        raise HTTPException(
            status_code=422,
            detail="Adapter timeout exceeds the deployment connection-timeout limit",
        )
    configuration = db.scalar(
        select(IntegrationAdapterConfiguration).where(
            IntegrationAdapterConfiguration.integration_id == integration.id
        )
    )
    previous_auth_type = configuration.auth_type if configuration else None
    if configuration is None:
        if payload.expected_version != 0:
            raise HTTPException(status_code=409, detail="Adapter configuration version is stale")
        configuration = IntegrationAdapterConfiguration(
            organization_id=actor.organization_id,
            integration_id=integration.id,
            protocol=payload.protocol,
            base_url=normalize_adapter_base_url(payload.base_url),
            health_path=normalize_health_path(payload.health_path),
            auth_type=payload.auth_type,
            timeout_seconds=payload.timeout_seconds,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        db.add(configuration)
        action = "create_integration_adapter_configuration"
    else:
        if configuration.version != payload.expected_version:
            raise HTTPException(status_code=409, detail="Adapter configuration version is stale")
        configuration.version += 1
        configuration.protocol = payload.protocol
        configuration.base_url = normalize_adapter_base_url(payload.base_url)
        configuration.health_path = normalize_health_path(payload.health_path)
        configuration.auth_type = payload.auth_type
        configuration.timeout_seconds = payload.timeout_seconds
        configuration.updated_by = actor.user_id
        action = "update_integration_adapter_configuration"

    configuration.auth_username = (
        payload.auth_username.strip() if payload.auth_username else None
    )
    configuration.api_key_header = normalize_api_key_header(payload.api_key_header)
    if payload.auth_type == "none":
        configuration.credential_ciphertext = None
        configuration.credential_updated_at = None
    elif payload.credential_secret is not None:
        try:
            configuration.credential_ciphertext = encrypt_integration_credential(
                payload.credential_secret,
                organization_id=actor.organization_id,
                integration_id=integration.id,
                auth_type=payload.auth_type,
            )
        except IntegrationCredentialConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail="Integration credential protection is not configured",
            ) from exc
        configuration.credential_updated_at = datetime.utcnow()
    elif not configuration.credential_ciphertext or previous_auth_type != payload.auth_type:
        raise HTTPException(
            status_code=422,
            detail="A new credential is required for the selected authentication type",
        )
    db.add(configuration)
    db.flush()
    _audit_integration(
        db,
        actor,
        action,
        integration,
        {
            "adapter_configuration_id": configuration.id,
            "protocol": configuration.protocol,
            "auth_type": configuration.auth_type,
            "credential_rotated": payload.credential_secret is not None,
            "new_version": configuration.version,
        },
    )
    db.commit()
    db.refresh(configuration)
    return adapter_configuration_read(
        configuration,
        _latest_connection_test(db, integration.id),
    )


@router.post(
    "/integrations/{integration_id}/adapter/test",
    response_model=IntegrationConnectionTestRead,
)
def test_integration_adapter_connection(
    integration_id: int,
    payload: IntegrationAdapterConnectionTestRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    _require_account_reauthentication(db, actor, payload.account_password)
    integration = _adapter_integration_or_422(db, integration_id)
    if not integration.is_active:
        raise HTTPException(status_code=409, detail="Inactive integrations cannot be tested")
    configuration = db.scalar(
        select(IntegrationAdapterConfiguration).where(
            IntegrationAdapterConfiguration.integration_id == integration.id
        )
    )
    if configuration is None:
        raise HTTPException(status_code=404, detail="Adapter configuration not found")
    if configuration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Adapter configuration version is stale")
    credential: str | None = None
    if configuration.auth_type != "none":
        if not configuration.credential_ciphertext:
            raise HTTPException(status_code=422, detail="Adapter credentials are not configured")
        try:
            credential = decrypt_integration_credential(
                configuration.credential_ciphertext,
                organization_id=configuration.organization_id,
                integration_id=configuration.integration_id,
                auth_type=configuration.auth_type,
            )
        except IntegrationCredentialConfigurationError as exc:
            raise HTTPException(
                status_code=503,
                detail="Integration credentials are unavailable",
            ) from exc
    result = probe_adapter_connection(configuration, credential)

    current_configuration = db.scalar(
        select(IntegrationAdapterConfiguration)
        .where(IntegrationAdapterConfiguration.id == configuration.id)
        .with_for_update()
    )
    if (
        current_configuration is None
        or current_configuration.version != payload.expected_version
    ):
        raise HTTPException(status_code=409, detail="Adapter configuration changed during testing")
    tested_at = datetime.utcnow()
    row = IntegrationConnectionTest(
        organization_id=actor.organization_id,
        integration_id=integration.id,
        configuration_id=current_configuration.id,
        configuration_version=current_configuration.version,
        status=result.status,
        response_status_code=result.response_status_code,
        latency_ms=result.latency_ms,
        protocol_confirmed=result.protocol_confirmed,
        protocol_signal=result.protocol_signal,
        error_code=result.error_code,
        evidence_fingerprint=connection_evidence_fingerprint(
            current_configuration,
            result,
            tested_at,
            actor.user_id,
        ),
        tested_by=actor.user_id,
        tested_at=tested_at,
    )
    db.add(row)
    db.flush()
    _audit_integration(
        db,
        actor,
        "test_integration_adapter_connection",
        integration,
        {
            "adapter_configuration_id": current_configuration.id,
            "configuration_version": current_configuration.version,
            "connection_test_id": row.id,
            "status": row.status,
            "response_status_code": row.response_status_code,
            "latency_ms": row.latency_ms,
            "protocol_confirmed": row.protocol_confirmed,
            "protocol_signal": row.protocol_signal,
            "error_code": row.error_code,
            "evidence_fingerprint": row.evidence_fingerprint,
        },
    )
    db.commit()
    db.refresh(row)
    return connection_test_read(row, current_version=current_configuration.version)


@router.get(
    "/integrations/{integration_id}/adapter/tests",
    response_model=list[IntegrationConnectionTestRead],
)
def list_integration_adapter_connection_tests(
    integration_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    integration = _adapter_integration_or_422(db, integration_id)
    configuration = db.scalar(
        select(IntegrationAdapterConfiguration).where(
            IntegrationAdapterConfiguration.integration_id == integration.id
        )
    )
    current_version = configuration.version if configuration else None
    rows = db.scalars(
        select(IntegrationConnectionTest)
        .where(IntegrationConnectionTest.integration_id == integration.id)
        .order_by(
            IntegrationConnectionTest.tested_at.desc(),
            IntegrationConnectionTest.id.desc(),
        )
        .limit(limit)
    ).all()
    return [
        connection_test_read(row, current_version=current_version)
        for row in rows
    ]


@router.post(
    "/integrations/{integration_id}/rotate-key",
    response_model=ExternalIntegrationSecretRead,
)
def rotate_integration_key(
    integration_id: int,
    payload: ExternalIntegrationRotate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    integration = _integration_or_404(db, integration_id)
    if integration.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Integration version is stale")
    raw_key, prefix, key_hash = generate_api_key()
    previous_prefix = integration.key_prefix
    integration.key_prefix = prefix
    integration.api_key_hash = key_hash
    integration.version += 1
    integration.updated_by = actor.user_id
    db.add(integration)
    _audit_integration(
        db,
        actor,
        "rotate_external_integration_key",
        integration,
        {
            "previous_key_prefix": previous_prefix,
            "new_key_prefix": prefix,
            "new_version": integration.version,
        },
    )
    db.commit()
    db.refresh(integration)
    return ExternalIntegrationSecretRead(
        integration=integration_read(integration),
        api_key=raw_key,
    )


@router.get(
    "/integrations/{integration_id}/sync-logs",
    response_model=list[ExternalSyncLogRead],
)
def list_integration_sync_logs(
    integration_id: int,
    status: str | None = Query(
        default=None,
        pattern="^(pending|processing|processed|failed)$",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_READ)
    _integration_or_404(db, integration_id)
    stmt = select(ExternalSyncLog).where(
        ExternalSyncLog.integration_id == integration_id
    )
    if status:
        stmt = stmt.where(ExternalSyncLog.status == status)
    rows = db.scalars(
        stmt.order_by(
            ExternalSyncLog.created_at.desc(),
            ExternalSyncLog.id.desc(),
        ).limit(limit)
    ).all()
    return [sync_log_read(row) for row in rows]


@router.post(
    "/integrations/{integration_id}/sync-logs/{log_id}/retry",
    response_model=ExternalSyncLogRead,
)
def retry_integration_delivery(
    integration_id: int,
    log_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, INTEGRATIONS_MANAGE)
    _integration_or_404(db, integration_id)
    log = db.get(ExternalSyncLog, log_id)
    if (
        not log
        or log.integration_id != integration_id
        or log.direction != "outbound"
    ):
        raise HTTPException(status_code=404, detail="Outbound delivery not found")
    if log.status == "processed":
        raise HTTPException(status_code=409, detail="Delivery already succeeded")
    log.status = "pending"
    log.response_status_code = None
    log.response_json = None
    log.error_message = None
    log.next_retry_at = datetime.utcnow()
    log.last_attempt_at = None
    log.processed_at = None
    db.add(log)
    _audit_integration(
        db,
        actor,
        "retry_external_delivery",
        log.integration,
        {"sync_log_id": log.id, "event_type": log.event_type},
    )
    db.commit()
    db.refresh(log)
    return sync_log_read(log)


def _external_work_order(
    db: Session,
    integration: ExternalIntegration,
    external_id: str,
) -> tuple[ExternalWorkOrderLink, WorkOrder]:
    link = db.scalar(
        select(ExternalWorkOrderLink).where(
            ExternalWorkOrderLink.integration_id == integration.id,
            ExternalWorkOrderLink.external_id == external_id,
        )
    )
    work_order = db.get(WorkOrder, link.work_order_id) if link else None
    if not link or not work_order:
        raise HTTPException(status_code=404, detail="External work order not found")
    return link, work_order


def _reserve_external_request(
    db: Session,
    integration: ExternalIntegration,
    *,
    includes_ai: bool = False,
) -> None:
    consume_monthly_usage(
        db,
        integration.organization_id,
        ai_requests=1 if includes_ai else 0,
        api_requests=1,
    )
    integration.last_used_at = datetime.utcnow()
    db.add(integration)


@router.get(
    "/external/v1/inventory",
    response_model=list[ExternalInventoryBalanceRead],
)
def external_inventory(
    part_number: str | None = Query(default=None, max_length=120),
    warehouse_code: str | None = Query(default=None, max_length=50),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    _reserve_external_request(db, integration)
    parts = {
        row.id: row
        for row in db.scalars(select(Part).where(Part.is_active.is_(True))).all()
    }
    warehouses = {
        row.id: row
        for row in db.scalars(select(Warehouse).where(Warehouse.is_active.is_(True))).all()
    }
    part_filter = (part_number or "").strip().casefold()
    warehouse_filter = (warehouse_code or "").strip().casefold()
    rows: list[ExternalInventoryBalanceRead] = []
    for balance in get_stock_balances(db):
        part = parts.get(balance.part_id)
        warehouse = warehouses.get(balance.warehouse_id)
        if not part or not warehouse:
            continue
        if part_filter and part.part_number.casefold() != part_filter:
            continue
        if warehouse_filter and warehouse.code.casefold() != warehouse_filter:
            continue
        rows.append(
            ExternalInventoryBalanceRead(
                part_number=part.part_number,
                part_name=part.name,
                warehouse_code=warehouse.code,
                warehouse_name=warehouse.name,
                quantity=balance.quantity,
                available_quantity=get_available_stock_quantity(
                    db,
                    part.id,
                    warehouse.id,
                ),
                unit=part.unit,
                is_low_stock=balance.is_low_stock,
            )
        )
        if len(rows) >= limit:
            break
    db.commit()
    return rows


@router.get(
    "/external/v1/work-orders/{external_id}",
    response_model=ExternalWorkOrderRead,
)
def external_work_order_status(
    external_id: str,
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    link, work_order = _external_work_order(db, integration, external_id)
    _reserve_external_request(db, integration)
    result = ExternalWorkOrderRead(
        external_id=link.external_id,
        work_order_id=work_order.id,
        ticket_number=work_order.ticket_number,
        status=work_order.status,
        assigned_engineer_id=work_order.engineer_id or work_order.assigned_user_id,
        claimed=work_order.claimed_by_id is not None,
        started_at=work_order.started_at,
        paused_at=work_order.paused_at,
        completed_at=work_order.completed_at,
        final_outcome=work_order.final_outcome,
        updated_at=work_order.updated_at,
    )
    db.commit()
    return result


@router.get(
    "/external/v1/work-orders/{external_id}/recommendations",
    response_model=list[ExternalPartRecommendationRead],
)
def external_work_order_recommendations(
    external_id: str,
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    _, work_order = _external_work_order(db, integration, external_id)
    _reserve_external_request(db, integration, includes_ai=True)
    result = [
        ExternalPartRecommendationRead(
            part_number=row.part.part_number,
            part_name=row.part.name,
            recommended_quantity=row.recommended_quantity,
            historical_usage_count=row.usage_count,
            success_rate=row.success_rate,
            average_repair_minutes=row.average_repair_minutes,
            available_quantity=row.available_quantity,
            inventory_location=row.inventory_location,
            confidence=row.confidence,
            reason=row.reason,
        )
        for row in build_part_recommendations(db, work_order)
    ]
    db.commit()
    return result


@router.post(
    "/external/v1/work-orders",
    response_model=ExternalWorkOrderUpsertRead,
)
def external_work_order_upsert(
    payload: ExternalWorkOrderUpsert,
    idempotency_key: str = Header(
        min_length=8,
        max_length=160,
        alias="X-Idempotency-Key",
    ),
    db: Session = Depends(get_db),
    integration: ExternalIntegration = Depends(get_external_integration),
):
    cleaned_idempotency_key = idempotency_key.strip()
    if len(cleaned_idempotency_key) < 8:
        raise HTTPException(
            status_code=422,
            detail="X-Idempotency-Key must contain at least 8 non-space characters",
        )
    return upsert_external_work_order(
        db,
        integration,
        payload,
        cleaned_idempotency_key,
    )
