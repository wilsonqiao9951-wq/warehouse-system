from datetime import date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
import json
import secrets
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.responses import FileResponse, StreamingResponse
from openpyxl import Workbook, load_workbook
from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import settings
from app.core.operations import operations_monitor
from app.core.permissions import REPORTS_READ, USERS_READ
from app.core.rbac import (
    Actor,
    get_current_actor,
    require_bound_device,
    require_platform_admin,
    require_permission,
    require_roles,
    require_work_order_execution_scope,
    require_work_order_owner_scope,
    require_work_order_scope,
    require_work_order_write_scope,
)
from app.core.security import create_access_token, hash_password, verify_password
from app.models import (
    AuditLog,
    CompletionPolicy,
    Customer,
    Equipment,
    InventoryTransaction,
    InventoryNotification,
    InventoryCountLine,
    InventoryCountSession,
    InventoryRegion,
    ReplenishmentRequest,
    VehicleReturnRequest,
    ImportBatch,
    JobStatus,
    MachineKnowledgeEntry,
    MachineKnowledgeProfile,
    Organization,
    OrganizationDomain,
    Part,
    PartMachineAssociation,
    PartRecognitionCandidate,
    PartRecognitionObservation,
    QCPicture,
    ReturnEquipment,
    StorageLocation,
    TransactionType,
    User,
    UserDevice,
    UserInvitation,
    UserRole,
    Warehouse,
    WorkOrder,
    WorkOrderPart,
    WorkOrderVoiceNote,
)
from app.schemas import (
    AbnormalUsageRow,
    CustomerCreate,
    CustomerRead,
    EquipmentCreate,
    EquipmentRead,
    CompletionPolicyRead,
    CompletionPolicyUpsert,
    JobStatusCreate,
    JobStatusRead,
    QCPictureCreate,
    QCPictureRead,
    ReturnEquipmentCreate,
    ReturnEquipmentRead,
    InventoryTransactionCreate,
    InventoryCountAction,
    InventoryCountCreate,
    InventoryCountLineUpsert,
    InventoryCountRead,
    InventoryCountLineRead,
    LowStockAlert,
    LocationStockBalance,
    InventoryScanRequest,
    InventoryScanRead,
    InventoryLocationScanRequest,
    InventoryLocationScanRead,
    InventoryLocationLabelRead,
    MachineKnowledgeEntryAction,
    MachineKnowledgeEntryCreate,
    MachineKnowledgeEntryRead,
    MachineKnowledgeEntryUpdate,
    MachineKnowledgeDraftGenerate,
    MachineKnowledgeDraftGenerationRead,
    MachineKnowledgeEvidenceRead,
    MachineKnowledgePartRead,
    MachineKnowledgeProfileCreate,
    MachineKnowledgeProfileRead,
    MachineKnowledgeProfileUpdate,
    WorkOrderFlowAction,
    InventoryTransactionRead,
    ImportBatchRead,
    InvitationAccept,
    InvitationCreate,
    InvitationCreated,
    InvitationInfo,
    AdminWarehouseDashboard,
    EngineerDashboard,
    PartCreate,
    PartRead,
    PartMachineAssociationRead,
    PartRecognitionCandidateAction,
    PartRecognitionCandidateRead,
    PartRecognitionObservationRead,
    WorkOrderPartRecommendation,
    InventoryNotificationRead,
    ReplenishmentRequestRead,
    ReplenishmentRequestAction,
    ReplenishmentRequestCreate,
    ReplenishmentRequestReconcile,
    VehicleReturnRequestAction,
    VehicleReturnRequestCreate,
    VehicleReturnRequestRead,
    OrganizationCreate,
    OrganizationBrandingRead,
    OrganizationBrandingUpdate,
    OrganizationDomainAction,
    OrganizationDomainRead,
    OrganizationDomainUpsert,
    OrganizationEmailIdentityUpdate,
    OrganizationRead,
    OrganizationSettingsRead,
    OrganizationUpdate,
    PasswordSet,
    StockBalance,
    StorageLocationCreate,
    StorageLocationRead,
    TokenResponse,
    UserCreate,
    UserRead,
    WarehouseCreate,
    WarehouseRead,
    WorkOrderCreate,
    WorkOrderClaimRelease,
    WorkOrderPartCreate,
    WorkOrderPartRead,
    WorkOrderProfit,
    WorkOrderRead,
    WorkOrderUpdate,
    WorkOrderServiceContext,
    WorkOrderServiceIntelligence,
    WorkOrderVoiceNoteRead,
    WarehouseSummary,
)
from app.services.inventory import (
    create_transaction,
    get_employee_van_inventory,
    get_stock_quantity,
    get_available_stock_quantity,
    get_stock_balances,
    get_location_stock_balances,
    get_location_stock_quantity,
    get_work_order_parts_cost,
    use_part_on_work_order,
    warehouse_is_vehicle,
    begin_inventory_write,
)
from app.services.integration_delivery import enqueue_work_order_event
from app.services.regions import ensure_default_region
from app.services.commercial import (
    PLAN_DEFAULTS,
    apply_plan_defaults,
    consume_monthly_usage,
    enforce_user_capacity,
    enforce_warehouse_capacity,
    lock_organization,
    organization_usage,
    require_subscription_access,
)
from app.services.recommendations import build_part_recommendations
from app.services.service_intelligence import build_service_intelligence
from app.services.visual_recognition import generate_visual_part_candidates
from app.services.domains import lookup_txt_records, normalize_custom_domain
from app.services.work_order_forms import (
    snapshot_template,
    template_for_assignment,
    validate_work_order_form_completion,
    work_order_form_requires_approval,
)

router = APIRouter()

PART_IMPORT_FIELDS = {
    "part_number",
    "name",
    "category",
    "barcode",
    "item_type",
    "tracking_mode",
    "is_active",
    "english_name",
    "machine_type",
    "unit",
    "default_cost",
    "safety_stock",
    "min_stock",
    "supplier",
    "image_url",
    "notes",
}


def _import_batch_read(batch: ImportBatch) -> ImportBatchRead:
    payload = json.loads(batch.payload_json or "[]")
    return ImportBatchRead(
        id=batch.id,
        organization_id=batch.organization_id,
        import_type=batch.import_type,
        filename=batch.filename,
        file_sha256=batch.file_sha256,
        status=batch.status,
        total_rows=batch.total_rows,
        valid_rows=batch.valid_rows,
        error_rows=batch.error_rows,
        created_count=batch.created_count,
        updated_count=batch.updated_count,
        errors=json.loads(batch.errors_json or "[]"),
        preview_rows=payload[:20],
        created_by=batch.created_by,
        committed_at=batch.committed_at,
        created_at=batch.created_at,
    )


def _normalize_import_header(value) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _parse_non_negative_number(value, cast, field_name: str):
    if value in (None, ""):
        return cast(0)
    number = cast(value)
    if number < 0:
        raise ValueError(f"{field_name} cannot be negative")
    return number


@router.post("/auth/login", response_model=TokenResponse)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
    x_device_id: str | None = Header(default=None, alias="X-Device-Id"),
    x_device_token: str | None = Header(default=None, alias="X-Device-Token"),
    x_device_name: str | None = Header(default=None, alias="X-Device-Name"),
):
    user = db.scalar(select(User).where(func.lower(User.email) == form.username.strip().lower()))
    organization = db.get(Organization, user.organization_id) if user else None
    if (
        not user
        or not user.is_active
        or (
            not user.is_platform_admin
            and (not organization or not organization.is_active)
        )
        or not verify_password(form.password, user.password_hash)
    ):
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    require_subscription_access(
        organization,
        platform_admin=user.is_platform_admin,
    )
    device_id = None
    if x_device_id or x_device_token:
        if not x_device_id or not x_device_token or not (16 <= len(x_device_id) <= 128) or len(x_device_token) < 32:
            raise HTTPException(status_code=400, detail="Valid device id and device token are required together")
        if any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for character in x_device_id):
            raise HTTPException(status_code=400, detail="Device id contains invalid characters")
        token_hash = sha256(x_device_token.encode("utf-8")).hexdigest()
        device = db.scalar(select(UserDevice).where(
            UserDevice.organization_id == user.organization_id, UserDevice.device_id == x_device_id
        ))
        if device and device.user_id != user.id:
            raise HTTPException(status_code=409, detail="This device is bound to another account")
        if device and (not device.is_active or device.revoked_at is not None):
            raise HTTPException(status_code=401, detail="This device registration has been revoked")
        if device and not secrets.compare_digest(device.device_token_hash, token_hash):
            raise HTTPException(status_code=401, detail="Device authentication failed")
        if not device:
            device = UserDevice(
                organization_id=user.organization_id,
                user_id=user.id,
                device_id=x_device_id,
                device_token_hash=token_hash,
                device_name=(x_device_name or "Registered device")[:255],
            )
            db.add(device)
        else:
            device.device_name = (x_device_name or device.device_name or "Registered device")[:255]
            device.last_seen_at = datetime.utcnow()
        db.commit()
        device_id = x_device_id
    token, expires_in = create_access_token(user.id, user.organization_id, device_id=device_id)
    return TokenResponse(access_token=token, expires_in=expires_in, user=user, device_id=device_id)


@router.get("/auth/me", response_model=UserRead)
def auth_me(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    if actor.user_id is None:
        raise HTTPException(status_code=401, detail="Authenticated user required")
    user = db.get(User, actor.user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


@router.post("/users/invitations", response_model=InvitationCreated)
def create_user_invitation(
    payload: InvitationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    email = payload.email.strip().lower()
    organization = lock_organization(db, actor.organization_id)
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    enforce_user_capacity(
        db,
        organization,
        include_pending=True,
        replacing_email=email,
    )
    now = datetime.utcnow()
    pending = db.scalars(
        select(UserInvitation).where(
            func.lower(UserInvitation.email) == email,
            UserInvitation.used_at.is_(None),
        )
    ).all()
    for invitation in pending:
        invitation.used_at = now
    raw_token = secrets.token_urlsafe(32)
    invitation = UserInvitation(
        email=email,
        name=payload.name.strip(),
        role=payload.role,
        token_hash=sha256(raw_token.encode()).hexdigest(),
        invited_by=actor.user_id,
        expires_at=now + timedelta(hours=settings.invitation_expire_hours),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    base_url = settings.frontend_public_url.rstrip("/")
    return InvitationCreated(
        id=invitation.id,
        email=invitation.email,
        name=invitation.name,
        role=invitation.role,
        expires_at=invitation.expires_at,
        invitation_url=f"{base_url}/accept-invitation?token={raw_token}",
    )


def _valid_invitation(db: Session, raw_token: str) -> UserInvitation:
    token_hash = sha256(raw_token.encode()).hexdigest()
    invitation = db.scalar(select(UserInvitation).where(UserInvitation.token_hash == token_hash))
    if not invitation or invitation.used_at is not None or invitation.expires_at <= datetime.utcnow():
        raise HTTPException(status_code=400, detail="Invitation is invalid or expired")
    organization = db.get(Organization, invitation.organization_id)
    try:
        require_subscription_access(organization)
    except HTTPException as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return invitation


@router.get("/auth/invitations/{token}", response_model=InvitationInfo)
def invitation_info(token: str, db: Session = Depends(get_db)):
    invitation = _valid_invitation(db, token)
    organization = db.get(Organization, invitation.organization_id)
    return InvitationInfo(
        email=invitation.email,
        name=invitation.name,
        role=invitation.role,
        organization_name=organization.name,
        expires_at=invitation.expires_at,
    )


@router.post("/auth/invitations/accept", response_model=UserRead)
def accept_invitation(payload: InvitationAccept, db: Session = Depends(get_db)):
    invitation = _valid_invitation(db, payload.token)
    organization = lock_organization(db, invitation.organization_id)
    db.refresh(invitation)
    if (
        invitation.used_at is not None
        or invitation.expires_at <= datetime.utcnow()
    ):
        raise HTTPException(
            status_code=400,
            detail="Invitation is invalid or expired",
        )
    try:
        require_subscription_access(organization)
    except HTTPException as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    if db.scalar(select(User.id).where(func.lower(User.email) == invitation.email.lower())):
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    enforce_user_capacity(
        db,
        organization,
        include_pending=False,
    )
    user = User(
        organization_id=invitation.organization_id,
        name=invitation.name,
        email=invitation.email,
        role=invitation.role,
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    invitation.used_at = datetime.utcnow()
    db.add_all([user, invitation])
    db.commit()
    db.refresh(user)
    return user


def _organization_branding_read(
    organization: Organization,
) -> OrganizationBrandingRead:
    return OrganizationBrandingRead(
        name=organization.name,
        slug=organization.slug,
        brand_logo_url=organization.brand_logo_url,
        brand_primary_color=organization.brand_primary_color,
        brand_login_headline=organization.brand_login_headline,
    )


def _organization_settings_read(
    db: Session,
    organization: Organization,
) -> OrganizationSettingsRead:
    usage = organization_usage(db, organization.id)
    return OrganizationSettingsRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        is_active=organization.is_active,
        brand_logo_url=organization.brand_logo_url,
        brand_primary_color=organization.brand_primary_color,
        brand_login_headline=organization.brand_login_headline,
        plan_code=organization.plan_code,
        subscription_status=organization.subscription_status,
        trial_ends_at=organization.trial_ends_at,
        max_users=organization.max_users,
        max_warehouses=organization.max_warehouses,
        max_vehicle_warehouses=organization.max_vehicle_warehouses,
        ai_monthly_limit=organization.ai_monthly_limit,
        api_monthly_limit=organization.api_monthly_limit,
        settings_version=organization.settings_version,
        **usage,
    )


def _organization_read(db: Session, organization: Organization) -> OrganizationRead:
    settings_read = _organization_settings_read(db, organization)
    domain = db.scalar(
        select(OrganizationDomain).where(
            OrganizationDomain.organization_id == organization.id
        )
    )
    email_sender_address = None
    if (
        domain
        and domain.status == "verified"
        and domain.email_identity_enabled
        and domain.email_from_local_part
    ):
        email_sender_address = f"{domain.email_from_local_part}@{domain.domain}"
    return OrganizationRead(
        **settings_read.model_dump(),
        total_users=db.scalar(
            select(func.count(User.id)).where(
                User.organization_id == organization.id
            )
        )
        or 0,
        total_parts=db.scalar(
            select(func.count(Part.id)).where(
                Part.organization_id == organization.id
            )
        )
        or 0,
        total_work_orders=db.scalar(
            select(func.count(WorkOrder.id)).where(
                WorkOrder.organization_id == organization.id
            )
        )
        or 0,
        custom_domain=domain.domain if domain else None,
        custom_domain_status=domain.status if domain else None,
        email_sender_address=email_sender_address,
        created_at=organization.created_at,
    )


def _platform_audit(
    db: Session,
    actor: Actor,
    organization: Organization,
    action: str,
    metadata: dict,
) -> None:
    db.add(
        AuditLog(
            organization_id=organization.id,
            user_id=actor.user_id,
            action=action,
            entity_type="organization",
            entity_id=organization.id,
            metadata_json=json.dumps(
                {
                    "actor_role": actor.role.value,
                    "auth_method": actor.auth_method,
                    "device_id": actor.device_id,
                    **metadata,
                },
                default=str,
                separators=(",", ":"),
            ),
            timestamp=datetime.utcnow(),
        )
    )


def _require_custom_domain_feature(organization: Organization) -> None:
    if organization.plan_code == "starter":
        raise HTTPException(
            status_code=403,
            detail="Custom domains are not included in the Starter plan.",
        )


def _new_domain_challenge(domain: str) -> tuple[str, str, str]:
    token = secrets.token_urlsafe(24)
    return (
        token,
        f"_openpartsflow-challenge.{domain}",
        f"openpartsflow-verification={token}",
    )


def _organization_domain_read(row: OrganizationDomain) -> OrganizationDomainRead:
    sender_address = None
    if (
        row.status == "verified"
        and row.email_identity_enabled
        and row.email_from_local_part
    ):
        sender_address = f"{row.email_from_local_part}@{row.domain}"
    return OrganizationDomainRead(
        id=row.id,
        organization_id=row.organization_id,
        domain=row.domain,
        status=row.status,
        verification_name=row.verification_name,
        verification_value=row.verification_value,
        last_checked_at=row.last_checked_at,
        verification_error=row.verification_error,
        verified_at=row.verified_at,
        email_from_name=row.email_from_name,
        email_from_local_part=row.email_from_local_part,
        email_identity_enabled=row.email_identity_enabled,
        email_sender_address=sender_address,
        login_url=f"https://{row.domain}/login" if row.status == "verified" else None,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _organization_domain_or_404(db: Session) -> OrganizationDomain:
    row = db.scalar(select(OrganizationDomain))
    if not row:
        raise HTTPException(status_code=404, detail="Custom domain is not configured")
    return row


@router.get(
    "/auth/organization-branding/{slug}",
    response_model=OrganizationBrandingRead,
)
def public_organization_branding(
    slug: str,
    db: Session = Depends(get_db),
):
    organization = db.scalar(
        select(Organization).where(
            Organization.slug == slug.strip().lower(),
            Organization.is_active.is_(True),
        )
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _organization_branding_read(organization)


@router.get(
    "/auth/organization-branding/by-domain/{domain}",
    response_model=OrganizationBrandingRead,
)
def public_organization_branding_by_domain(
    domain: str,
    db: Session = Depends(get_db),
):
    try:
        normalized = normalize_custom_domain(domain)
    except ValueError:
        raise HTTPException(status_code=404, detail="Organization not found") from None
    organization = db.scalar(
        select(Organization)
        .join(
            OrganizationDomain,
            OrganizationDomain.organization_id == Organization.id,
        )
        .where(
            OrganizationDomain.domain == normalized,
            OrganizationDomain.status == "verified",
            Organization.is_active.is_(True),
            Organization.plan_code.in_(("professional", "enterprise")),
        )
    )
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _organization_branding_read(organization)


@router.get("/organization/settings", response_model=OrganizationSettingsRead)
def get_organization_settings(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    return _organization_settings_read(db, organization)


@router.patch(
    "/organization/settings/branding",
    response_model=OrganizationSettingsRead,
)
def update_organization_branding(
    payload: OrganizationBrandingUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = lock_organization(db, actor.organization_id)
    if organization.settings_version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Organization settings changed; refresh before saving.",
        )
    fields = payload.model_fields_set - {"expected_version"}
    if (
        "brand_primary_color" in fields
        and payload.brand_primary_color is None
    ):
        raise HTTPException(
            status_code=422,
            detail="Brand primary color cannot be empty",
        )
    for field_name in fields:
        setattr(organization, field_name, getattr(payload, field_name))
    organization.settings_version += 1
    db.add(organization)
    _audit(
        db,
        actor,
        "organization_branding_updated",
        "organization",
        organization.id,
        {
            "changed_fields": sorted(fields),
            "settings_version": organization.settings_version,
        },
    )
    db.commit()
    db.refresh(organization)
    return _organization_settings_read(db, organization)


@router.get(
    "/organization/domain",
    response_model=OrganizationDomainRead | None,
)
def get_organization_domain(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_custom_domain_feature(organization)
    row = db.scalar(select(OrganizationDomain))
    return _organization_domain_read(row) if row else None


@router.put(
    "/organization/domain",
    response_model=OrganizationDomainRead,
)
def put_organization_domain(
    payload: OrganizationDomainUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = lock_organization(db, actor.organization_id)
    _require_custom_domain_feature(organization)
    row = db.scalar(select(OrganizationDomain).with_for_update())
    now = datetime.utcnow()
    created = row is None
    if row:
        if payload.expected_version is None or row.version != payload.expected_version:
            raise HTTPException(
                status_code=409,
                detail="Custom domain changed; refresh before saving.",
            )
        if row.domain == payload.domain:
            db.commit()
            return _organization_domain_read(row)
        token, name, value = _new_domain_challenge(payload.domain)
        row.domain = payload.domain
        row.status = "pending"
        row.verification_token = token
        row.verification_name = name
        row.verification_value = value
        row.last_checked_at = None
        row.verification_error = None
        row.verified_at = None
        row.email_identity_enabled = False
        row.updated_by = actor.user_id
        row.version += 1
    else:
        if payload.expected_version not in {None, 0}:
            raise HTTPException(status_code=409, detail="Custom domain does not exist")
        token, name, value = _new_domain_challenge(payload.domain)
        row = OrganizationDomain(
            organization_id=actor.organization_id,
            domain=payload.domain,
            status="pending",
            verification_token=token,
            verification_name=name,
            verification_value=value,
            created_by=actor.user_id,
            updated_by=actor.user_id,
        )
        db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="This custom domain is already assigned to another organization.",
        ) from exc
    _audit(
        db,
        actor,
        "organization_domain_created" if created else "organization_domain_changed",
        "organization_domain",
        row.id,
        {"domain": row.domain, "version": row.version, "timestamp": now},
    )
    db.commit()
    db.refresh(row)
    return _organization_domain_read(row)


@router.post(
    "/organization/domain/verify",
    response_model=OrganizationDomainRead,
)
async def verify_organization_domain(
    payload: OrganizationDomainAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    organization = db.get(Organization, actor.organization_id)
    if not organization:
        raise HTTPException(status_code=404, detail="Organization not found")
    _require_custom_domain_feature(organization)
    row = _organization_domain_or_404(db)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Custom domain version is stale")
    now = datetime.utcnow()
    cooldown = max(1, settings.custom_domain_verification_cooldown_seconds)
    if row.last_checked_at and now - row.last_checked_at < timedelta(seconds=cooldown):
        raise HTTPException(
            status_code=429,
            detail=f"Wait {cooldown} seconds between DNS verification checks.",
        )
    expected_name = row.verification_name
    expected_value = row.verification_value
    records, resolver_error = await lookup_txt_records(expected_name)

    lock_organization(db, actor.organization_id)
    row = _organization_domain_or_404(db)
    if (
        row.version != payload.expected_version
        or row.verification_name != expected_name
        or row.verification_value != expected_value
    ):
        raise HTTPException(status_code=409, detail="Custom domain changed during verification")
    matched = any(
        secrets.compare_digest(record, expected_value)
        for record in records
    )
    row.last_checked_at = now
    if matched:
        row.status = "verified"
        row.verified_at = row.verified_at or now
        row.verification_error = None
    else:
        row.verification_error = resolver_error or (
            "Required TXT verification value was not found yet."
        )
    row.updated_by = actor.user_id
    row.version += 1
    db.add(row)
    _audit(
        db,
        actor,
        "organization_domain_verification_checked",
        "organization_domain",
        row.id,
        {
            "domain": row.domain,
            "verified": matched,
            "resolver_available": resolver_error is None,
            "version": row.version,
        },
    )
    db.commit()
    db.refresh(row)
    return _organization_domain_read(row)


@router.post(
    "/organization/domain/rotate-challenge",
    response_model=OrganizationDomainRead,
)
def rotate_organization_domain_challenge(
    payload: OrganizationDomainAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = lock_organization(db, actor.organization_id)
    _require_custom_domain_feature(organization)
    row = _organization_domain_or_404(db)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Custom domain version is stale")
    token, name, value = _new_domain_challenge(row.domain)
    row.verification_token = token
    row.verification_name = name
    row.verification_value = value
    row.status = "pending"
    row.last_checked_at = None
    row.verification_error = None
    row.verified_at = None
    row.email_identity_enabled = False
    row.updated_by = actor.user_id
    row.version += 1
    db.add(row)
    _audit(
        db,
        actor,
        "organization_domain_challenge_rotated",
        "organization_domain",
        row.id,
        {"domain": row.domain, "version": row.version},
    )
    db.commit()
    db.refresh(row)
    return _organization_domain_read(row)


@router.patch(
    "/organization/domain/email-identity",
    response_model=OrganizationDomainRead,
)
def update_organization_email_identity(
    payload: OrganizationEmailIdentityUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = lock_organization(db, actor.organization_id)
    _require_custom_domain_feature(organization)
    row = _organization_domain_or_404(db)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Custom domain version is stale")
    if payload.enabled and row.status != "verified":
        raise HTTPException(
            status_code=409,
            detail="Verify domain ownership before enabling its email identity.",
        )
    row.email_from_name = payload.from_name
    row.email_from_local_part = payload.local_part
    row.email_identity_enabled = payload.enabled
    row.updated_by = actor.user_id
    row.version += 1
    db.add(row)
    _audit(
        db,
        actor,
        "organization_email_identity_updated",
        "organization_domain",
        row.id,
        {
            "domain": row.domain,
            "enabled": row.email_identity_enabled,
            "version": row.version,
        },
    )
    db.commit()
    db.refresh(row)
    return _organization_domain_read(row)


@router.delete(
    "/organization/domain",
    status_code=204,
)
def delete_organization_domain(
    payload: OrganizationDomainAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    _require_account_reauthentication(db, actor, payload.account_password)
    organization = lock_organization(db, actor.organization_id)
    _require_custom_domain_feature(organization)
    row = _organization_domain_or_404(db)
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Custom domain version is stale")
    row_id = row.id
    row_domain = row.domain
    _audit(
        db,
        actor,
        "organization_domain_removed",
        "organization_domain",
        row_id,
        {"domain": row_domain, "version": row.version},
    )
    db.delete(row)
    db.commit()
    return None


@router.get("/platform/organizations", response_model=list[OrganizationRead])
def list_organizations(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    organizations = db.scalars(select(Organization).order_by(Organization.id.asc())).all()
    return [_organization_read(db, organization) for organization in organizations]


@router.post("/platform/organizations", response_model=OrganizationRead)
def create_organization(
    payload: OrganizationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    slug = payload.slug.strip().lower()
    email = payload.admin_email.strip().lower()
    if db.scalar(select(Organization.id).where(Organization.slug == slug)):
        raise HTTPException(status_code=409, detail="Organization slug already exists")
    if db.scalar(select(User.id).where(func.lower(User.email) == email)):
        raise HTTPException(status_code=409, detail="Administrator email already exists")

    organization = Organization(name=payload.name.strip(), slug=slug)
    apply_plan_defaults(organization, payload.plan_code)
    if payload.trial_days:
        organization.subscription_status = "trialing"
        organization.trial_ends_at = datetime.utcnow() + timedelta(
            days=payload.trial_days
        )
    else:
        organization.subscription_status = "active"
        organization.trial_ends_at = None
    db.add(organization)
    db.flush()
    administrator = User(
        organization_id=organization.id,
        name=payload.admin_name.strip(),
        email=email,
        role=UserRole.ADMIN,
        password_hash=hash_password(payload.admin_password),
        is_active=True,
        is_platform_admin=False,
    )
    db.add(administrator)
    db.flush()
    _platform_audit(
        db,
        actor,
        organization,
        "organization_created",
        {
            "plan_code": organization.plan_code,
            "subscription_status": organization.subscription_status,
            "trial_ends_at": organization.trial_ends_at,
            "administrator_user_id": administrator.id,
        },
    )
    db.commit()
    db.refresh(organization)
    return _organization_read(db, organization)


@router.patch("/platform/organizations/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: int,
    payload: OrganizationUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_platform_admin(actor)
    db.info.pop("organization_id", None)
    organization = lock_organization(db, organization_id)
    if organization.settings_version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Organization settings changed; refresh before saving.",
        )
    fields = payload.model_fields_set - {"expected_version"}
    audit_fields = set(fields)
    if payload.plan_code is not None:
        audit_fields.update(PLAN_DEFAULTS[payload.plan_code])
    before = {
        field_name: getattr(organization, field_name)
        for field_name in audit_fields
    }
    if payload.plan_code is not None:
        apply_plan_defaults(organization, payload.plan_code)
    for field_name in fields - {"plan_code"}:
        setattr(organization, field_name, getattr(payload, field_name))
    if (
        organization.subscription_status == "trialing"
        and (
            organization.trial_ends_at is None
            or organization.trial_ends_at <= datetime.utcnow()
        )
    ):
        raise HTTPException(
            status_code=422,
            detail="A trialing organization requires a future trial end.",
        )
    organization.settings_version += 1
    db.add(organization)
    _platform_audit(
        db,
        actor,
        organization,
        "organization_subscription_updated",
        {
            "changed_fields": sorted(audit_fields),
            "before": before,
            "after": {
                field_name: getattr(organization, field_name)
                for field_name in audit_fields
            },
            "settings_version": organization.settings_version,
        },
    )
    db.commit()
    db.refresh(organization)
    return _organization_read(db, organization)


def _require_tenant_user(db: Session, user_id: int | None, field_name: str) -> None:
    if user_id is not None and not db.get(User, user_id):
        raise HTTPException(status_code=400, detail=f"{field_name} must reference a user in the current organization")


def _audit(
    db: Session,
    actor: Actor,
    action: str,
    entity_type: str,
    entity_id: int | None = None,
    metadata: dict | None = None,
):
    audit_metadata = {
        "actor_role": actor.role.value,
        "auth_method": actor.auth_method,
        "device_id": actor.device_id,
        "device_record_id": actor.device_record_id,
        "claim_version": actor.claim_version,
        **(metadata or {}),
    }
    db.add(
        AuditLog(
            user_id=actor.user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata_json=json.dumps(audit_metadata, default=str, separators=(",", ":")),
            timestamp=datetime.utcnow(),
        )
    )


def _require_account_reauthentication(db: Session, actor: Actor, password: str | None) -> None:
    if actor.auth_method == "test":
        return
    if actor.auth_method != "bearer" or actor.user_id is None:
        raise HTTPException(status_code=401, detail="Bearer authentication required")
    user = db.get(User, actor.user_id)
    if not password or not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Account password verification failed")


def _work_order_read_for_actor(db: Session, actor: Actor, item: WorkOrder) -> WorkOrderRead:
    payload = WorkOrderRead.model_validate(item).model_dump()
    claimant = db.get(User, item.claimed_by_id) if item.claimed_by_id else None
    completed_by = db.get(User, item.completed_by_id) if item.completed_by_id else None
    completed_device = db.get(UserDevice, item.completed_device_id) if item.completed_device_id else None
    is_test_actor = actor.auth_method == "test"
    is_engineer_owner = bool(
        actor.role == UserRole.ENGINEER
        and actor.user_id == item.claimed_by_id
        and actor.device_verified
        and actor.device_record_id == item.claimed_device_id
    )
    execution_open = not item.is_locked and item.status.upper() != "PENDING_APPROVAL"
    payload.update(
        claimed_by_name=claimant.name if claimant else None,
        completed_by_name=completed_by.name if completed_by else None,
        completed_device_name=(
            completed_device.device_name
            if completed_device and (is_engineer_owner or actor.role in {UserRole.ADMIN, UserRole.MANAGER})
            else None
        ),
        can_claim=bool(
            actor.role == UserRole.ENGINEER
            and actor.device_verified
            and item.claimed_by_id is None
            and execution_open
            and item.status.upper() != "COMPLETED"
        ),
        can_edit=bool((is_engineer_owner or actor.role == UserRole.ADMIN or is_test_actor) and execution_open),
        can_complete=bool((is_engineer_owner or is_test_actor) and execution_open),
    )
    if actor.role not in {UserRole.ADMIN, UserRole.MANAGER} and not is_engineer_owner and not is_test_actor:
        payload["revenue"] = 0.0
        payload["labor_cost"] = 0.0
        payload["customer_signature_name"] = None
        payload["customer_signature_data"] = None
        payload["customer_signed_at"] = None
        payload["claimed_device_id"] = None
        payload["completed_device_id"] = None
    return WorkOrderRead(**payload)


def _image_extension(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in {
        b"heic", b"heix", b"hevc", b"hevx", b"mif1",
    }:
        return ".heic"
    return None


def _knowledge_media_file_type(data: bytes) -> tuple[str, str, str] | None:
    image_extension = _image_extension(data)
    if image_extension:
        image_mime_types = {
            ".jpg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".heic": "image/heic",
        }
        return "photo", image_extension, image_mime_types[image_extension]
    if data.startswith(b"\x1aE\xdf\xa3"):
        return "video", ".webm", "video/webm"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand == b"qt  ":
            return "video", ".mov", "video/quicktime"
        if brand in {
            b"isom",
            b"iso2",
            b"mp41",
            b"mp42",
            b"avc1",
            b"M4V ",
            b"MSNV",
        }:
            return "video", ".mp4", "video/mp4"
    return None


@router.post("/uploads/work-order-parts")
async def upload_work_order_part_photo(
    work_order_id: int = Form(..., ge=1),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    work_order = require_work_order_execution_scope(db, actor, work_order_id)
    if not work_order or work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Work order cannot accept uploads in its current state")

    data = await file.read(settings.max_image_upload_bytes + 1)
    if len(data) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit")
    ext = _image_extension(data)
    if not ext:
        raise HTTPException(status_code=400, detail="Unsupported or invalid image file")

    target_dir = Path("uploads/work-order-parts")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{ext}"
    target_path = target_dir / filename

    target_path.write_bytes(data)
    _audit(
        db,
        actor,
        "upload_work_order_photo",
        "work_order",
        work_order_id,
        {"url": f"/uploads/work-order-parts/{filename}"},
    )
    db.commit()
    return {"url": f"/uploads/work-order-parts/{filename}"}


def _audio_extension(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x1aE\xdf\xa3"):
        return ".webm", "audio/webm"
    if data.startswith(b"OggS"):
        return ".ogg", "audio/ogg"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WAVE":
        return ".wav", "audio/wav"
    if len(data) >= 12 and data[4:8] == b"ftyp":
        return ".m4a", "audio/mp4"
    if data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0):
        return ".mp3", "audio/mpeg"
    return None


@router.post("/work-orders/{work_order_id}/voice-notes", response_model=WorkOrderVoiceNoteRead)
async def create_work_order_voice_note(
    work_order_id: int,
    file: UploadFile = File(...),
    duration_seconds: float | None = Form(None, ge=0, le=7200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    work_order = require_work_order_execution_scope(db, actor, work_order_id)
    if not work_order or work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail="Voice notes cannot be added to this work order")
    data = await file.read(settings.max_audio_upload_bytes + 1)
    if len(data) > settings.max_audio_upload_bytes:
        raise HTTPException(status_code=413, detail="Audio exceeds the configured upload limit")
    audio_type = _audio_extension(data)
    if not audio_type:
        raise HTTPException(status_code=400, detail="Unsupported or invalid audio file")
    extension, mime_type = audio_type
    target_dir = Path("uploads/work-order-voice-notes")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    (target_dir / filename).write_bytes(data)
    note = WorkOrderVoiceNote(
        organization_id=actor.organization_id,
        work_order_id=work_order_id,
        created_by=actor.user_id,
        audio_url=f"/uploads/work-order-voice-notes/{filename}",
        mime_type=mime_type,
        duration_seconds=duration_seconds,
    )
    db.add(note)
    _audit(db, actor, "create_voice_note", "work_order_voice_note", None, {"work_order_id": work_order_id})
    db.commit()
    db.refresh(note)
    return note


@router.get("/work-orders/{work_order_id}/voice-notes", response_model=list[WorkOrderVoiceNoteRead])
def list_work_order_voice_notes(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    return db.scalars(
        select(WorkOrderVoiceNote)
        .where(
            WorkOrderVoiceNote.organization_id == actor.organization_id,
            WorkOrderVoiceNote.work_order_id == work_order_id,
        )
        .order_by(WorkOrderVoiceNote.id.desc())
    ).all()


@router.post("/users", response_model=UserRead)
def create_user(payload: UserCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN)
    email = (payload.email or "").strip().lower() or None
    organization = lock_organization(db, actor.organization_id)
    enforce_user_capacity(
        db,
        organization,
        include_pending=True,
        replacing_email=email,
    )
    data = payload.model_dump(exclude={"password"})
    data["email"] = email
    item = User(**data, password_hash=hash_password(payload.password) if payload.password else None)
    db.add(item)
    db.flush()
    if email:
        now = datetime.utcnow()
        pending = db.scalars(
            select(UserInvitation).where(
                UserInvitation.organization_id == actor.organization_id,
                func.lower(UserInvitation.email) == email,
                UserInvitation.used_at.is_(None),
                UserInvitation.expires_at > now,
            )
        ).all()
        for invitation in pending:
            invitation.used_at = now
            db.add(invitation)
    db.commit()
    db.refresh(item)
    return item


@router.post("/users/{user_id}/set-password", status_code=204)
def set_user_password(
    user_id: int,
    payload: PasswordSet,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.password_hash = hash_password(payload.password)
    db.add(user)
    db.commit()


@router.get("/users", response_model=list[UserRead])
def list_users(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, USERS_READ)
    return db.scalars(select(User).order_by(User.id.desc()).offset(skip).limit(limit)).all()


@router.post("/warehouses", response_model=WarehouseRead)
def create_warehouse(payload: WarehouseCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    _require_tenant_user(db, payload.assigned_user_id, "assigned_user_id")
    values = payload.model_dump()
    values["warehouse_type"] = (payload.warehouse_type or "main").strip().lower()
    owner = db.get(User, payload.assigned_user_id) if payload.assigned_user_id else None
    if owner and owner.role == UserRole.ENGINEER and values["warehouse_type"] == "main":
        values["warehouse_type"] = "van"
    if values["warehouse_type"] not in {"main", "van"}:
        raise HTTPException(status_code=422, detail="warehouse_type must be main or van")
    if values["warehouse_type"] == "van" and (
        not owner or not owner.is_active or owner.role != UserRole.ENGINEER
    ):
        raise HTTPException(status_code=422, detail="A van warehouse must be assigned to an active engineer")
    organization = lock_organization(db, actor.organization_id)
    if values["is_active"]:
        enforce_warehouse_capacity(
            db,
            organization,
            values["warehouse_type"],
        )
    values["code"] = (payload.code or payload.name).strip().upper().replace(" ", "-")
    values["region_id"] = ensure_default_region(db, actor.organization_id).id
    item = Warehouse(**values)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/warehouses", response_model=list[WarehouseRead])
def list_warehouses(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    return db.scalars(select(Warehouse).order_by(Warehouse.id.desc()).offset(skip).limit(limit)).all()


@router.post("/storage-locations", response_model=StorageLocationRead)
def create_storage_location(
    payload: StorageLocationCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if not db.get(Warehouse, payload.warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    item = StorageLocation(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/storage-locations", response_model=list[StorageLocationRead])
def list_storage_locations(
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    query = select(StorageLocation).order_by(StorageLocation.code.asc())
    if warehouse_id is not None:
        if not db.get(Warehouse, warehouse_id):
            raise HTTPException(status_code=404, detail="Warehouse not found")
        query = query.where(StorageLocation.warehouse_id == warehouse_id)
    return db.scalars(query).all()


def _knowledge_model_key(value: str) -> str:
    key = value.strip().casefold()
    if not key:
        raise HTTPException(status_code=422, detail="Machine model is required")
    return key


def _knowledge_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


def _knowledge_media_url(value: str | None) -> str | None:
    cleaned = _knowledge_optional_text(value)
    if cleaned and not cleaned.lower().startswith(("https://", "http://", "/uploads/")):
        raise HTTPException(
            status_code=422,
            detail="Knowledge media URL must use http(s) or an uploaded /uploads/ path",
        )
    return cleaned


def _knowledge_part_read(
    part: Part,
    association: PartMachineAssociation | None = None,
) -> MachineKnowledgePartRead:
    return MachineKnowledgePartRead(
        id=part.id,
        part_number=part.part_number,
        name=part.name,
        image_url=part.image_url,
        recognition_source=association.recognition_source if association else None,
        confidence=association.confidence if association else None,
        confirmed_count=association.confirmed_count if association else None,
    )


def _knowledge_entry_read(
    db: Session,
    actor: Actor,
    entry: MachineKnowledgeEntry,
) -> MachineKnowledgeEntryRead:
    curator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    related_part = db.get(Part, entry.related_part_id) if entry.related_part_id else None
    alternative_for_part = (
        db.get(Part, entry.alternative_for_part_id)
        if entry.alternative_for_part_id
        else None
    )
    return MachineKnowledgeEntryRead(
        id=entry.id,
        organization_id=entry.organization_id,
        profile_id=entry.profile_id,
        entry_type=entry.entry_type,
        title=entry.title,
        content=entry.content,
        fault_code=entry.fault_code,
        related_part=_knowledge_part_read(related_part) if related_part else None,
        related_part_role=entry.related_part_role,
        alternative_for_part=(
            _knowledge_part_read(alternative_for_part)
            if alternative_for_part
            else None
        ),
        installation_location=entry.installation_location,
        source_work_order_id=entry.source_work_order_id,
        media_url=entry.media_url,
        media_mime_type=entry.media_mime_type,
        media_size_bytes=entry.media_size_bytes,
        sort_order=entry.sort_order,
        status=entry.status,
        version=entry.version,
        created_by=entry.created_by,
        updated_by=entry.updated_by,
        published_by=entry.published_by,
        published_at=entry.published_at,
        archived_by=entry.archived_by,
        archived_at=entry.archived_at,
        can_edit=curator and entry.status == "draft",
        can_publish=actor.role == UserRole.ADMIN and entry.status == "draft",
        can_archive=actor.role == UserRole.ADMIN and entry.status in {"draft", "published"},
        can_reopen=actor.role == UserRole.ADMIN and entry.status == "archived",
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _machine_knowledge_profile_read(
    db: Session,
    actor: Actor,
    profile: MachineKnowledgeProfile,
) -> MachineKnowledgeProfileRead:
    curator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    entries_stmt = select(MachineKnowledgeEntry).where(
        MachineKnowledgeEntry.profile_id == profile.id
    )
    if not curator:
        entries_stmt = entries_stmt.where(MachineKnowledgeEntry.status == "published")
    entries = db.scalars(
        entries_stmt.order_by(
            MachineKnowledgeEntry.entry_type,
            MachineKnowledgeEntry.sort_order,
            MachineKnowledgeEntry.id,
        )
    ).all()

    associations = db.execute(
        select(PartMachineAssociation, Part)
        .join(Part, Part.id == PartMachineAssociation.part_id)
        .where(
            func.lower(func.trim(PartMachineAssociation.machine_model))
            == profile.model_key
        )
        .order_by(
            PartMachineAssociation.confidence.desc(),
            PartMachineAssociation.confirmed_count.desc(),
            Part.part_number,
        )
    ).all()

    evidence = db.execute(
        select(
            func.count(WorkOrder.id),
            func.count(WorkOrder.first_time_fix),
            func.coalesce(
                func.sum(case((WorkOrder.first_time_fix.is_(True), 1), else_=0)),
                0,
            ),
            func.avg(WorkOrder.repair_duration_minutes),
            func.max(WorkOrder.completed_at),
        ).where(
            WorkOrder.is_locked.is_(True),
            WorkOrder.completed_at.is_not(None),
            func.lower(func.trim(WorkOrder.machine_type)) == profile.model_key,
        )
    ).one()
    completed_count = int(evidence[0] or 0)
    labeled_count = int(evidence[1] or 0)
    success_count = int(evidence[2] or 0)

    return MachineKnowledgeProfileRead(
        id=profile.id,
        organization_id=profile.organization_id,
        manufacturer=profile.manufacturer,
        model=profile.model,
        equipment_type=profile.equipment_type,
        summary=profile.summary,
        version=profile.version,
        is_active=profile.is_active,
        created_by=profile.created_by,
        updated_by=profile.updated_by,
        can_edit=curator,
        can_add_entry=curator and profile.is_active,
        entries=[_knowledge_entry_read(db, actor, entry) for entry in entries],
        related_parts=[
            _knowledge_part_read(part, association)
            for association, part in associations
        ],
        evidence=MachineKnowledgeEvidenceRead(
            completed_work_orders=completed_count,
            labeled_outcomes=labeled_count,
            first_time_fix_rate=(
                success_count / labeled_count if labeled_count else None
            ),
            average_repair_minutes=(
                float(evidence[3]) if evidence[3] is not None else None
            ),
            latest_completed_at=evidence[4],
        ),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _validate_machine_knowledge_links(
    db: Session,
    profile: MachineKnowledgeProfile,
    *,
    related_part_id: int | None,
    source_work_order_id: int | None,
    related_part_role: str | None = None,
    alternative_for_part_id: int | None = None,
) -> None:
    if related_part_id is not None and not db.get(Part, related_part_id):
        raise HTTPException(
            status_code=400,
            detail="related_part_id is not available in this organization",
        )
    if related_part_role is not None and related_part_id is None:
        raise HTTPException(
            status_code=422,
            detail="A related part is required when a part role is selected",
        )
    if alternative_for_part_id is not None:
        if not db.get(Part, alternative_for_part_id):
            raise HTTPException(
                status_code=400,
                detail="alternative_for_part_id is not available in this organization",
            )
        if related_part_role != "alternative":
            raise HTTPException(
                status_code=422,
                detail="alternative_for_part_id is valid only for an alternative part",
            )
        if alternative_for_part_id == related_part_id:
            raise HTTPException(
                status_code=422,
                detail="An alternative part must differ from the primary part",
            )
    if related_part_role == "alternative" and alternative_for_part_id is None:
        raise HTTPException(
            status_code=422,
            detail="An alternative part must identify the primary part it replaces",
        )
    if source_work_order_id is None:
        return
    work_order = db.get(WorkOrder, source_work_order_id)
    if not work_order:
        raise HTTPException(
            status_code=400,
            detail="source_work_order_id is not available in this organization",
        )
    if not work_order.is_locked or not work_order.completed_at:
        raise HTTPException(
            status_code=409,
            detail="Knowledge evidence must reference a completed work order",
        )
    if _knowledge_model_key(work_order.machine_type or "") != profile.model_key:
        raise HTTPException(
            status_code=409,
            detail="Knowledge evidence work order must use the same machine model",
        )


@router.get(
    "/machine-knowledge",
    response_model=list[MachineKnowledgeProfileRead],
)
def list_machine_knowledge(
    q: str | None = Query(default=None, max_length=255),
    model: str | None = Query(default=None, max_length=255),
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(
        actor,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.WAREHOUSE,
        UserRole.ENGINEER,
    )
    curator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    if include_inactive and not curator:
        raise HTTPException(status_code=403, detail="Inactive knowledge is curator-only")
    stmt = select(MachineKnowledgeProfile)
    if not include_inactive:
        stmt = stmt.where(MachineKnowledgeProfile.is_active.is_(True))
    if not curator:
        stmt = stmt.where(
            MachineKnowledgeProfile.entries.any(
                MachineKnowledgeEntry.status == "published"
            )
        )
    if model:
        stmt = stmt.where(
            MachineKnowledgeProfile.model_key == _knowledge_model_key(model)
        )
    if q and q.strip():
        like = f"%{q.strip().casefold()}%"
        stmt = stmt.where(
            or_(
                func.lower(MachineKnowledgeProfile.model).like(like),
                func.lower(func.coalesce(MachineKnowledgeProfile.manufacturer, "")).like(like),
                func.lower(func.coalesce(MachineKnowledgeProfile.equipment_type, "")).like(like),
                func.lower(func.coalesce(MachineKnowledgeProfile.summary, "")).like(like),
            )
        )
    profiles = db.scalars(
        stmt.order_by(
            MachineKnowledgeProfile.manufacturer,
            MachineKnowledgeProfile.model,
            MachineKnowledgeProfile.id,
        ).limit(limit)
    ).all()
    return [
        _machine_knowledge_profile_read(db, actor, profile)
        for profile in profiles
    ]


@router.get(
    "/machine-knowledge/{profile_id}",
    response_model=MachineKnowledgeProfileRead,
)
def get_machine_knowledge(
    profile_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(
        actor,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.WAREHOUSE,
        UserRole.ENGINEER,
    )
    profile = db.get(MachineKnowledgeProfile, profile_id)
    curator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    if not profile or (not curator and not profile.is_active):
        raise HTTPException(status_code=404, detail="Machine knowledge profile not found")
    if not curator and not db.scalar(
        select(MachineKnowledgeEntry.id).where(
            MachineKnowledgeEntry.profile_id == profile.id,
            MachineKnowledgeEntry.status == "published",
        )
    ):
        raise HTTPException(status_code=404, detail="Machine knowledge profile not found")
    return _machine_knowledge_profile_read(db, actor, profile)


@router.post(
    "/machine-knowledge",
    response_model=MachineKnowledgeProfileRead,
)
def create_machine_knowledge(
    payload: MachineKnowledgeProfileCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    profile = MachineKnowledgeProfile(
        model=payload.model.strip(),
        model_key=_knowledge_model_key(payload.model),
        manufacturer=_knowledge_optional_text(payload.manufacturer),
        equipment_type=_knowledge_optional_text(payload.equipment_type),
        summary=_knowledge_optional_text(payload.summary),
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(profile)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A knowledge profile already exists for this machine model",
        )
    _audit(
        db,
        actor,
        "create_machine_knowledge_profile",
        "machine_knowledge_profile",
        profile.id,
        {"model": profile.model},
    )
    db.commit()
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


@router.patch(
    "/machine-knowledge/{profile_id}",
    response_model=MachineKnowledgeProfileRead,
)
def update_machine_knowledge(
    profile_id: int,
    payload: MachineKnowledgeProfileUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    profile = db.scalar(
        select(MachineKnowledgeProfile)
        .where(MachineKnowledgeProfile.id == profile_id)
        .with_for_update()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="Machine knowledge profile not found")
    if profile.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Machine knowledge profile changed; refresh before editing",
        )
    changes = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if "model" in changes:
        changes["model"] = changes["model"].strip()
        changes["model_key"] = _knowledge_model_key(changes["model"])
    for field in {"manufacturer", "equipment_type", "summary"} & changes.keys():
        changes[field] = _knowledge_optional_text(changes[field])
    for field, value in changes.items():
        setattr(profile, field, value)
    profile.updated_by = actor.user_id
    profile.version += 1
    db.add(profile)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A knowledge profile already exists for this machine model",
        )
    _audit(
        db,
        actor,
        "update_machine_knowledge_profile",
        "machine_knowledge_profile",
        profile.id,
        {"fields": sorted(changes), "version": profile.version},
    )
    db.commit()
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


@router.post(
    "/machine-knowledge/{profile_id}/entries",
    response_model=MachineKnowledgeProfileRead,
)
def create_machine_knowledge_entry(
    profile_id: int,
    payload: MachineKnowledgeEntryCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    profile = db.get(MachineKnowledgeProfile, profile_id)
    if not profile or not profile.is_active:
        raise HTTPException(status_code=404, detail="Active machine knowledge profile not found")
    _validate_machine_knowledge_links(
        db,
        profile,
        related_part_id=payload.related_part_id,
        source_work_order_id=payload.source_work_order_id,
        related_part_role=payload.related_part_role,
        alternative_for_part_id=payload.alternative_for_part_id,
    )
    media_url = _knowledge_media_url(payload.media_url)
    if payload.entry_type in {"photo", "video"} and not media_url:
        raise HTTPException(
            status_code=422,
            detail="Photo and video knowledge entries require a media URL",
        )
    entry = MachineKnowledgeEntry(
        profile_id=profile.id,
        entry_type=payload.entry_type,
        title=payload.title.strip(),
        content=payload.content.strip(),
        fault_code=_knowledge_optional_text(payload.fault_code),
        related_part_id=payload.related_part_id,
        related_part_role=payload.related_part_role,
        alternative_for_part_id=payload.alternative_for_part_id,
        installation_location=_knowledge_optional_text(payload.installation_location),
        source_work_order_id=payload.source_work_order_id,
        media_url=media_url,
        sort_order=payload.sort_order,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(entry)
    db.flush()
    _audit(
        db,
        actor,
        "create_machine_knowledge_entry",
        "machine_knowledge_entry",
        entry.id,
        {
            "profile_id": profile.id,
            "entry_type": entry.entry_type,
            "source_work_order_id": entry.source_work_order_id,
        },
    )
    db.commit()
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


def _work_order_knowledge_specs(
    db: Session,
    work_order: WorkOrder,
) -> list[dict]:
    specs: list[dict] = []
    fault_lines = []
    if work_order.fault_type:
        fault_lines.append(f"Fault type: {work_order.fault_type.strip()}")
    if work_order.error_code:
        fault_lines.append(f"Error code: {work_order.error_code.strip()}")
    if work_order.problem_description:
        fault_lines.append(
            f"Observed problem: {work_order.problem_description.strip()}"
        )
    if work_order.environment_info:
        fault_lines.append(
            f"Field conditions: {work_order.environment_info.strip()}"
        )
    if fault_lines:
        fault_name = (
            _knowledge_optional_text(work_order.fault_type)
            or _knowledge_optional_text(work_order.error_code)
            or _knowledge_optional_text(work_order.job_type)
            or work_order.ticket_number
        )
        specs.append(
            {
                "origin_key": f"work_order:{work_order.id}:fault",
                "entry_type": "fault",
                "title": f"Field fault: {fault_name}"[:255],
                "content": "\n".join(fault_lines)[:20000],
                "fault_code": _knowledge_optional_text(work_order.error_code),
                "sort_order": 100,
            }
        )

    if work_order.repair_result:
        repair_lines = [
            f"Repair performed and verified: {work_order.repair_result.strip()}"
        ]
        if work_order.final_outcome:
            repair_lines.append(f"Final outcome: {work_order.final_outcome.strip()}")
        if work_order.repair_duration_minutes is not None:
            repair_lines.append(
                f"Recorded field duration: {work_order.repair_duration_minutes} minutes"
            )
        repair_lines.append(
            "Review this draft and convert the result into reusable ordered steps before publishing."
        )
        specs.append(
            {
                "origin_key": f"work_order:{work_order.id}:repair",
                "entry_type": "repair_step",
                "title": f"Verified repair from {work_order.ticket_number}"[:255],
                "content": "\n".join(repair_lines)[:20000],
                "sort_order": 200,
            }
        )

    part_rows = db.execute(
        select(WorkOrderPart, Part)
        .join(Part, Part.id == WorkOrderPart.part_id)
        .where(WorkOrderPart.work_order_id == work_order.id)
        .order_by(Part.part_number, WorkOrderPart.id)
    ).all()
    part_totals: dict[int, dict] = {}
    for usage, part in part_rows:
        aggregate = part_totals.setdefault(
            part.id,
            {"part": part, "quantity": 0},
        )
        aggregate["quantity"] += usage.quantity

    successful_repair = bool(
        work_order.first_time_fix is True
        and not work_order.is_rework
        and (work_order.final_outcome or "").strip().casefold()
        in {"repaired", "fixed", "resolved", "success", "successful"}
    )
    for position, aggregate in enumerate(part_totals.values(), start=1):
        part = aggregate["part"]
        quantity = aggregate["quantity"]
        part_role = "recommended" if successful_repair else "reference"
        outcome_note = (
            "This part came from a labeled successful first-time repair."
            if successful_repair
            else "This usage is reference evidence only until a successful outcome is confirmed."
        )
        specs.append(
            {
                "origin_key": f"work_order:{work_order.id}:part:{part.id}",
                "entry_type": "note",
                "title": f"{part.part_number} used on {work_order.ticket_number}"[:255],
                "content": (
                    f"Completed work order recorded {quantity} × {part.name}. "
                    f"{outcome_note}"
                )[:20000],
                "related_part_id": part.id,
                "related_part_role": part_role,
                "sort_order": 300 + position,
            }
        )
    return specs


@router.post(
    "/machine-knowledge/{profile_id}/drafts/from-work-order",
    response_model=MachineKnowledgeDraftGenerationRead,
)
def generate_machine_knowledge_drafts(
    profile_id: int,
    payload: MachineKnowledgeDraftGenerate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    profile = db.scalar(
        select(MachineKnowledgeProfile)
        .where(MachineKnowledgeProfile.id == profile_id)
        .with_for_update()
    )
    if not profile or not profile.is_active:
        raise HTTPException(status_code=404, detail="Active machine knowledge profile not found")
    _validate_machine_knowledge_links(
        db,
        profile,
        related_part_id=None,
        source_work_order_id=payload.work_order_id,
    )
    work_order = db.get(WorkOrder, payload.work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Completed work order not found")
    specs = _work_order_knowledge_specs(db, work_order)
    if not specs:
        raise HTTPException(
            status_code=409,
            detail="Completed work order has no reusable fault, repair, or part evidence",
        )
    origin_keys = [spec["origin_key"] for spec in specs]
    existing_keys = set(
        db.scalars(
            select(MachineKnowledgeEntry.origin_key).where(
                MachineKnowledgeEntry.profile_id == profile.id,
                MachineKnowledgeEntry.origin_key.in_(origin_keys),
            )
        ).all()
    )
    created_count = 0
    for spec in specs:
        if spec["origin_key"] in existing_keys:
            continue
        db.add(
            MachineKnowledgeEntry(
                profile_id=profile.id,
                source_work_order_id=work_order.id,
                created_by=actor.user_id,
                updated_by=actor.user_id,
                **spec,
            )
        )
        created_count += 1
    skipped_count = len(specs) - created_count
    _audit(
        db,
        actor,
        "generate_machine_knowledge_drafts",
        "machine_knowledge_profile",
        profile.id,
        {
            "work_order_id": work_order.id,
            "created_entries": created_count,
            "skipped_entries": skipped_count,
            "origin_keys": origin_keys,
        },
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Knowledge drafts changed concurrently; refresh and retry",
        )
    db.refresh(profile)
    return MachineKnowledgeDraftGenerationRead(
        profile=_machine_knowledge_profile_read(db, actor, profile),
        created_entries=created_count,
        skipped_entries=skipped_count,
    )


@router.post(
    "/machine-knowledge/{profile_id}/media",
    response_model=MachineKnowledgeProfileRead,
)
async def upload_machine_knowledge_media(
    profile_id: int,
    title: str = Form(..., min_length=1, max_length=255),
    description: str = Form(..., min_length=1, max_length=20000),
    file: UploadFile = File(...),
    source_work_order_id: int | None = Form(default=None, ge=1),
    sort_order: int = Form(default=0, ge=0, le=10000),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    profile = db.get(MachineKnowledgeProfile, profile_id)
    if not profile or not profile.is_active:
        raise HTTPException(status_code=404, detail="Active machine knowledge profile not found")
    _validate_machine_knowledge_links(
        db,
        profile,
        related_part_id=None,
        source_work_order_id=source_work_order_id,
    )
    data = await file.read(settings.max_knowledge_media_upload_bytes + 1)
    if len(data) > settings.max_knowledge_media_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail="Knowledge media exceeds the configured upload limit",
        )
    file_type = _knowledge_media_file_type(data)
    if not file_type:
        raise HTTPException(
            status_code=400,
            detail="Unsupported or invalid knowledge photo/video",
        )
    entry_type, extension, mime_type = file_type
    if entry_type == "photo" and len(data) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit")

    filename = f"{uuid4().hex}{extension}"
    storage_key = f"machine-knowledge/{actor.organization_id}/{filename}"
    storage_root = Path("private_uploads")
    target_path = storage_root / storage_key
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_bytes(data)

    entry = MachineKnowledgeEntry(
        profile_id=profile.id,
        entry_type=entry_type,
        title=title.strip(),
        content=description.strip(),
        source_work_order_id=source_work_order_id,
        media_storage_key=storage_key,
        media_mime_type=mime_type,
        media_size_bytes=len(data),
        sort_order=sort_order,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    db.add(entry)
    try:
        db.flush()
        entry.media_url = f"/api/machine-knowledge/media/{entry.id}"
        _audit(
            db,
            actor,
            "upload_machine_knowledge_media",
            "machine_knowledge_entry",
            entry.id,
            {
                "profile_id": profile.id,
                "entry_type": entry_type,
                "mime_type": mime_type,
                "size_bytes": len(data),
                "source_work_order_id": source_work_order_id,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        target_path.unlink(missing_ok=True)
        raise
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


@router.get("/machine-knowledge/media/{entry_id}")
def get_machine_knowledge_media(
    entry_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(
        actor,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.WAREHOUSE,
        UserRole.ENGINEER,
    )
    entry = db.get(MachineKnowledgeEntry, entry_id)
    if not entry or not entry.media_storage_key or not entry.media_mime_type:
        raise HTTPException(status_code=404, detail="Knowledge media not found")
    profile = db.get(MachineKnowledgeProfile, entry.profile_id)
    curator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    if not profile or (
        not curator and (not profile.is_active or entry.status != "published")
    ):
        raise HTTPException(status_code=404, detail="Knowledge media not found")
    storage_root = Path("private_uploads").resolve()
    target_path = (storage_root / entry.media_storage_key).resolve()
    if storage_root not in target_path.parents or not target_path.is_file():
        raise HTTPException(status_code=404, detail="Knowledge media not found")
    return FileResponse(
        target_path,
        media_type=entry.media_mime_type,
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": f'inline; filename="knowledge-{entry.id}{target_path.suffix}"',
        },
    )


@router.patch(
    "/machine-knowledge/entries/{entry_id}",
    response_model=MachineKnowledgeProfileRead,
)
def update_machine_knowledge_entry(
    entry_id: int,
    payload: MachineKnowledgeEntryUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    entry = db.scalar(
        select(MachineKnowledgeEntry)
        .where(MachineKnowledgeEntry.id == entry_id)
        .with_for_update()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Machine knowledge entry not found")
    if entry.status != "draft":
        raise HTTPException(
            status_code=409,
            detail="Published or archived knowledge is immutable; archive and create a new draft",
        )
    if entry.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Machine knowledge entry changed; refresh before editing",
        )
    profile = db.get(MachineKnowledgeProfile, entry.profile_id)
    if not profile or not profile.is_active:
        raise HTTPException(status_code=404, detail="Active machine knowledge profile not found")
    changes = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    related_part_id = changes.get("related_part_id", entry.related_part_id)
    related_part_role = changes.get("related_part_role", entry.related_part_role)
    alternative_for_part_id = changes.get(
        "alternative_for_part_id",
        entry.alternative_for_part_id,
    )
    source_work_order_id = changes.get(
        "source_work_order_id",
        entry.source_work_order_id,
    )
    _validate_machine_knowledge_links(
        db,
        profile,
        related_part_id=related_part_id,
        source_work_order_id=source_work_order_id,
        related_part_role=related_part_role,
        alternative_for_part_id=alternative_for_part_id,
    )
    for field in {
        "title",
        "content",
        "fault_code",
        "installation_location",
    } & changes.keys():
        changes[field] = _knowledge_optional_text(changes[field])
    if changes.get("title") is None and "title" in changes:
        raise HTTPException(status_code=422, detail="Knowledge title is required")
    if changes.get("content") is None and "content" in changes:
        raise HTTPException(status_code=422, detail="Knowledge content is required")
    if entry.media_storage_key and (
        ("entry_type" in changes and changes["entry_type"] != entry.entry_type)
        or (
            "media_url" in changes
            and changes["media_url"] != entry.media_url
        )
    ):
        raise HTTPException(
            status_code=409,
            detail="Uploaded media type and protected URL cannot be replaced in place",
        )
    if entry.media_storage_key:
        changes.pop("media_url", None)
    elif "media_url" in changes:
        changes["media_url"] = _knowledge_media_url(changes["media_url"])
    entry_type = changes.get("entry_type", entry.entry_type)
    media_url = changes.get("media_url", entry.media_url)
    if entry_type in {"photo", "video"} and not media_url:
        raise HTTPException(
            status_code=422,
            detail="Photo and video knowledge entries require a media URL",
        )
    for field, value in changes.items():
        setattr(entry, field, value)
    entry.updated_by = actor.user_id
    entry.version += 1
    db.add(entry)
    _audit(
        db,
        actor,
        "update_machine_knowledge_entry",
        "machine_knowledge_entry",
        entry.id,
        {"fields": sorted(changes), "version": entry.version},
    )
    db.commit()
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


@router.post(
    "/machine-knowledge/entries/{entry_id}/actions",
    response_model=MachineKnowledgeProfileRead,
)
def act_on_machine_knowledge_entry(
    entry_id: int,
    payload: MachineKnowledgeEntryAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN)
    entry = db.scalar(
        select(MachineKnowledgeEntry)
        .where(MachineKnowledgeEntry.id == entry_id)
        .with_for_update()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Machine knowledge entry not found")
    if entry.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Machine knowledge entry changed; refresh before acting",
        )
    profile = db.get(MachineKnowledgeProfile, entry.profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Machine knowledge profile not found")
    now = datetime.utcnow()
    previous_status = entry.status
    if payload.action == "publish":
        if entry.status != "draft" or not profile.is_active:
            raise HTTPException(
                status_code=409,
                detail="Only draft knowledge on an active profile can be published",
            )
        entry.status = "published"
        entry.published_by = actor.user_id
        entry.published_at = now
        entry.archived_by = None
        entry.archived_at = None
    elif payload.action == "archive":
        if entry.status not in {"draft", "published"}:
            raise HTTPException(status_code=409, detail="Knowledge entry is already archived")
        entry.status = "archived"
        entry.archived_by = actor.user_id
        entry.archived_at = now
    elif payload.action == "reopen":
        if entry.status != "archived" or not profile.is_active:
            raise HTTPException(
                status_code=409,
                detail="Only archived knowledge on an active profile can be reopened",
            )
        entry.status = "draft"
        entry.archived_by = None
        entry.archived_at = None
    entry.updated_by = actor.user_id
    entry.version += 1
    db.add(entry)
    _audit(
        db,
        actor,
        f"{payload.action}_machine_knowledge_entry",
        "machine_knowledge_entry",
        entry.id,
        {
            "profile_id": profile.id,
            "previous_status": previous_status,
            "new_status": entry.status,
            "version": entry.version,
        },
    )
    db.commit()
    db.refresh(profile)
    return _machine_knowledge_profile_read(db, actor, profile)


@router.post("/parts", response_model=PartRead)
def create_part(payload: PartCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    item = Part(**payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/parts/recognition/observations", response_model=PartMachineAssociationRead)
async def record_part_observation(
    machine_model: str = Form(..., min_length=1),
    part_id: int | None = Form(None),
    part_number: str | None = Form(None),
    part_name: str | None = Form(None),
    file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    part = db.get(Part, part_id) if part_id else None
    if not part and part_number:
        part = db.scalar(select(Part).where(Part.part_number == part_number.strip()))
    if not part:
        if not part_number or not part_name:
            raise HTTPException(status_code=400, detail="part_id or part_number and part_name are required")
        part = Part(part_number=part_number.strip(), name=part_name.strip(), machine_type=machine_model.strip())
        db.add(part)
        db.flush()
    photo_url = None
    if file:
        data = await file.read(settings.max_image_upload_bytes + 1)
        if len(data) > settings.max_image_upload_bytes:
            raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit")
        ext = _image_extension(data)
        if not ext:
            raise HTTPException(status_code=400, detail="Unsupported or invalid image file")
        target_dir = Path("uploads/part-observations")
        target_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{uuid4().hex}{ext}"
        (target_dir / filename).write_bytes(data)
        photo_url = f"/uploads/part-observations/{filename}"
    association = db.scalar(select(PartMachineAssociation).where(
        PartMachineAssociation.machine_model == machine_model.strip(), PartMachineAssociation.part_id == part.id
    ))
    if association:
        association.confirmed_count += 1
        association.last_confirmed_at = datetime.utcnow()
        association.photo_url = photo_url or association.photo_url
    else:
        association = PartMachineAssociation(machine_model=machine_model.strip(), part_id=part.id, photo_url=photo_url)
        db.add(association)
    _audit(db, actor, "record_part_observation", "part_machine_association", association.id, {"machine_model": machine_model})
    db.commit()
    db.refresh(association)
    return association


@router.get("/parts/recognition/suggestions", response_model=list[PartMachineAssociationRead])
def part_recognition_suggestions(machine_model: str, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    return db.scalars(select(PartMachineAssociation).where(PartMachineAssociation.machine_model.ilike(f"%{machine_model.strip()}%")).order_by(PartMachineAssociation.confirmed_count.desc())).all()


_PART_RECOGNITION_STATUSES = {
    "ai_candidate",
    "employee_confirmed",
    "admin_confirmed",
    "usage_verified",
    "trusted",
    "rejected",
}


def _part_recognition_observation_read(
    db: Session,
    actor: Actor,
    observation: PartRecognitionObservation,
) -> PartRecognitionObservationRead:
    work_order = db.get(WorkOrder, observation.work_order_id) if observation.work_order_id else None
    linked_employee_access = (
        observation.work_order_id is None
        or actor.role == UserRole.ADMIN
        or (
            actor.role == UserRole.ENGINEER
            and work_order is not None
            and work_order.claimed_by_id == actor.user_id
        )
    )
    rows = db.scalars(
        select(PartRecognitionCandidate)
        .where(PartRecognitionCandidate.observation_id == observation.id)
        .order_by(PartRecognitionCandidate.rank, PartRecognitionCandidate.id)
    ).all()
    selected_candidate_id = next(
        (
            row.id
            for row in rows
            if row.status
            in {
                "employee_confirmed",
                "admin_confirmed",
                "usage_verified",
                "trusted",
            }
        ),
        None,
    )
    candidates: list[PartRecognitionCandidateRead] = []
    for row in rows:
        part = db.get(Part, row.part_id)
        if not part:
            continue
        candidates.append(
            PartRecognitionCandidateRead(
                id=row.id,
                organization_id=row.organization_id,
                observation_id=row.observation_id,
                part_id=row.part_id,
                part=PartRead.model_validate(part),
                rank=row.rank,
                confidence=row.confidence,
                reason=row.reason,
                status=row.status,
                version=row.version,
                employee_confirmed_by=row.employee_confirmed_by,
                employee_confirmed_at=row.employee_confirmed_at,
                admin_confirmed_by=row.admin_confirmed_by,
                admin_confirmed_at=row.admin_confirmed_at,
                usage_verified_by=row.usage_verified_by,
                usage_verified_at=row.usage_verified_at,
                trusted_at=row.trusted_at,
                rejected_by=row.rejected_by,
                rejected_at=row.rejected_at,
                rejection_reason=row.rejection_reason,
                can_employee_confirm=(
                    row.status == "ai_candidate"
                    and selected_candidate_id is None
                    and linked_employee_access
                    and actor.role
                    in {
                        UserRole.ADMIN,
                        UserRole.MANAGER,
                        UserRole.WAREHOUSE,
                        UserRole.ENGINEER,
                    }
                ),
                can_admin_confirm=(
                    row.status == "employee_confirmed" and actor.role == UserRole.ADMIN
                ),
                can_verify_usage=(
                    row.status == "admin_confirmed" and actor.role == UserRole.ADMIN
                ),
                can_promote_trusted=(
                    row.status == "usage_verified" and actor.role == UserRole.ADMIN
                ),
                can_reject=(
                    row.status not in {"trusted", "rejected"} and actor.role == UserRole.ADMIN
                ),
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
        )
    return PartRecognitionObservationRead(
        id=observation.id,
        organization_id=observation.organization_id,
        work_order_id=observation.work_order_id,
        machine_model=observation.machine_model,
        label_text=observation.label_text,
        image_url=observation.image_url,
        notes=observation.notes,
        created_by=observation.created_by,
        created_at=observation.created_at,
        updated_at=observation.updated_at,
        candidates=candidates,
    )


@router.post(
    "/parts/recognition/candidates",
    response_model=PartRecognitionObservationRead,
)
async def create_part_recognition_candidates(
    file: UploadFile = File(...),
    machine_model: str | None = Form(default=None, max_length=255),
    label_text: str | None = Form(default=None, max_length=4000),
    work_order_id: int | None = Form(default=None, ge=1),
    notes: str | None = Form(default=None, max_length=4000),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(
        actor,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.WAREHOUSE,
        UserRole.ENGINEER,
    )
    work_order = None
    if work_order_id is not None:
        if actor.role == UserRole.ENGINEER:
            work_order = require_work_order_execution_scope(db, actor, work_order_id)
        elif actor.role == UserRole.ADMIN:
            require_work_order_scope(db, actor, work_order_id)
            work_order = db.get(WorkOrder, work_order_id)
        else:
            raise HTTPException(
                status_code=403,
                detail="Only the claiming engineer or an administrator can attach recognition evidence to a work order",
            )
    machine_value = (machine_model or (work_order.machine_type if work_order else None) or "").strip() or None
    label_value = (label_text or "").strip() or None
    notes_value = (notes or "").strip() or None
    if not machine_value and not label_value and work_order is None:
        raise HTTPException(
            status_code=422,
            detail="Provide a machine model, visible label text, or work-order context",
        )

    data = await file.read(settings.max_image_upload_bytes + 1)
    if len(data) > settings.max_image_upload_bytes:
        raise HTTPException(status_code=413, detail="Image exceeds the configured upload limit")
    extension = _image_extension(data)
    if not extension:
        raise HTTPException(status_code=400, detail="Unsupported or invalid image file")
    consume_monthly_usage(db, actor.organization_id, ai_requests=1)
    target_dir = Path("uploads/part-recognition")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid4().hex}{extension}"
    (target_dir / filename).write_bytes(data)
    image_url = f"/uploads/part-recognition/{filename}"

    observation = PartRecognitionObservation(
        work_order_id=work_order_id,
        machine_model=machine_value,
        label_text=label_value,
        image_url=image_url,
        notes=notes_value,
        created_by=actor.user_id,
    )
    db.add(observation)
    db.flush()
    suggestions = generate_visual_part_candidates(
        db,
        machine_model=machine_value,
        label_text=label_value,
        work_order=work_order,
    )
    for rank, suggestion in enumerate(suggestions, start=1):
        db.add(
            PartRecognitionCandidate(
                observation_id=observation.id,
                part_id=suggestion.part.id,
                rank=rank,
                confidence=suggestion.confidence,
                reason=suggestion.reason,
            )
        )
    _audit(
        db,
        actor,
        "create_part_recognition_candidates",
        "part_recognition_observation",
        observation.id,
        {
            "work_order_id": work_order_id,
            "machine_model": machine_value,
            "candidate_count": len(suggestions),
        },
    )
    db.commit()
    db.refresh(observation)
    return _part_recognition_observation_read(db, actor, observation)


@router.get(
    "/parts/recognition/candidates",
    response_model=list[PartRecognitionObservationRead],
)
def list_part_recognition_candidates(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(
        actor,
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.WAREHOUSE,
        UserRole.ENGINEER,
    )
    if status is not None and status not in _PART_RECOGNITION_STATUSES:
        raise HTTPException(status_code=422, detail="Unknown recognition candidate status")
    query = select(PartRecognitionObservation).order_by(
        PartRecognitionObservation.id.desc()
    )
    if status is not None:
        matching_observations = select(PartRecognitionCandidate.observation_id).where(
            PartRecognitionCandidate.status == status
        )
        query = query.where(PartRecognitionObservation.id.in_(matching_observations))
    observations = db.scalars(query.limit(limit)).all()
    return [
        _part_recognition_observation_read(db, actor, observation)
        for observation in observations
    ]


@router.post(
    "/parts/recognition/candidates/{candidate_id}/actions",
    response_model=PartRecognitionObservationRead,
)
def act_on_part_recognition_candidate(
    candidate_id: int,
    payload: PartRecognitionCandidateAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    candidate = db.scalar(
        select(PartRecognitionCandidate)
        .where(PartRecognitionCandidate.id == candidate_id)
        .with_for_update()
    )
    if not candidate:
        raise HTTPException(status_code=404, detail="Recognition candidate not found")
    observation = db.get(PartRecognitionObservation, candidate.observation_id)
    if not observation:
        raise HTTPException(status_code=404, detail="Recognition observation not found")
    if candidate.version != payload.expected_version:
        raise HTTPException(
            status_code=409,
            detail="Recognition candidate changed; refresh before continuing",
        )
    if payload.work_order_id is not None and payload.work_order_id != observation.work_order_id:
        raise HTTPException(status_code=409, detail="Recognition work-order context does not match")

    previous_status = candidate.status
    now = datetime.utcnow()
    if payload.action == "employee_confirm":
        require_roles(
            actor,
            UserRole.ADMIN,
            UserRole.MANAGER,
            UserRole.WAREHOUSE,
            UserRole.ENGINEER,
        )
        if candidate.status != "ai_candidate":
            raise HTTPException(status_code=409, detail="Only an AI candidate can be employee-confirmed")
        if observation.work_order_id is not None:
            if actor.role == UserRole.ENGINEER:
                if payload.work_order_id is None:
                    raise HTTPException(status_code=422, detail="work_order_id is required")
                require_work_order_execution_scope(db, actor, observation.work_order_id)
            elif actor.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=403,
                    detail="Only the claiming engineer or an administrator can confirm this work-order candidate",
                )
        selected = db.scalar(
            select(PartRecognitionCandidate).where(
                PartRecognitionCandidate.observation_id == observation.id,
                PartRecognitionCandidate.id != candidate.id,
                PartRecognitionCandidate.status.in_(
                    {
                        "employee_confirmed",
                        "admin_confirmed",
                        "usage_verified",
                        "trusted",
                    }
                ),
            )
        )
        if selected:
            raise HTTPException(
                status_code=409,
                detail="Another candidate is already selected for this observation",
            )
        candidate.status = "employee_confirmed"
        candidate.employee_confirmed_by = actor.user_id
        candidate.employee_confirmed_at = now

    elif payload.action == "admin_confirm":
        require_roles(actor, UserRole.ADMIN)
        if candidate.status != "employee_confirmed":
            raise HTTPException(
                status_code=409,
                detail="Administrator confirmation requires employee confirmation first",
            )
        if (
            actor.user_id is not None
            and candidate.employee_confirmed_by == actor.user_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Administrator confirmation must use a different account from employee confirmation",
            )
        candidate.status = "admin_confirmed"
        candidate.admin_confirmed_by = actor.user_id
        candidate.admin_confirmed_at = now

    elif payload.action == "verify_usage":
        require_roles(actor, UserRole.ADMIN)
        if candidate.status != "admin_confirmed":
            raise HTTPException(
                status_code=409,
                detail="Usage verification requires administrator confirmation first",
            )
        if observation.work_order_id is None:
            raise HTTPException(
                status_code=409,
                detail="Usage verification requires a linked work order",
            )
        usage = db.scalar(
            select(WorkOrderPart).where(
                WorkOrderPart.work_order_id == observation.work_order_id,
                WorkOrderPart.part_id == candidate.part_id,
            )
        )
        if not usage:
            raise HTTPException(
                status_code=409,
                detail="The linked work order has not recorded use of this part",
            )
        candidate.status = "usage_verified"
        candidate.usage_verified_by = actor.user_id
        candidate.usage_verified_at = now

    elif payload.action == "promote_trusted":
        require_roles(actor, UserRole.ADMIN)
        if candidate.status != "usage_verified":
            raise HTTPException(
                status_code=409,
                detail="Trusted knowledge requires verified work-order usage",
            )
        if not observation.machine_model:
            raise HTTPException(
                status_code=409,
                detail="A machine model is required before promotion to trusted knowledge",
            )
        association = db.scalar(
            select(PartMachineAssociation).where(
                func.lower(PartMachineAssociation.machine_model)
                == observation.machine_model.casefold(),
                PartMachineAssociation.part_id == candidate.part_id,
            )
        )
        if association:
            association.confirmed_count += 1
            association.last_confirmed_at = now
            association.photo_url = observation.image_url
            association.recognition_source = "verified_visual"
            association.confidence = max(association.confidence, 0.99)
        else:
            db.add(
                PartMachineAssociation(
                    machine_model=observation.machine_model,
                    part_id=candidate.part_id,
                    photo_url=observation.image_url,
                    recognition_source="verified_visual",
                    confidence=0.99,
                    confirmed_count=1,
                    last_confirmed_at=now,
                )
            )
        candidate.status = "trusted"
        candidate.trusted_at = now

    else:
        require_roles(actor, UserRole.ADMIN)
        if candidate.status in {"trusted", "rejected"}:
            raise HTTPException(status_code=409, detail="This candidate can no longer be rejected")
        reason = (payload.reason or "").strip()
        if len(reason) < 3:
            raise HTTPException(
                status_code=422,
                detail="Rejection reason must be at least 3 characters",
            )
        candidate.status = "rejected"
        candidate.rejected_by = actor.user_id
        candidate.rejected_at = now
        candidate.rejection_reason = reason

    candidate.version += 1
    _audit(
        db,
        actor,
        f"part_recognition_{payload.action}",
        "part_recognition_candidate",
        candidate.id,
        {
            "observation_id": observation.id,
            "part_id": candidate.part_id,
            "work_order_id": observation.work_order_id,
            "from_status": previous_status,
            "to_status": candidate.status,
            "previous_version": payload.expected_version,
            "new_version": candidate.version,
        },
    )
    db.commit()
    db.refresh(observation)
    return _part_recognition_observation_read(db, actor, observation)


@router.get("/parts", response_model=list[PartRead])
def list_parts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    return db.scalars(select(Part).order_by(Part.id.desc()).offset(skip).limit(limit)).all()


@router.post("/work-orders", response_model=WorkOrderRead)
def create_work_order(payload: WorkOrderCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    if payload.status.strip().upper() in {"COMPLETED", "PENDING_APPROVAL", "APPROVAL_REJECTED"}:
        raise HTTPException(status_code=400, detail="Terminal work order status requires the completion workflow")
    _require_tenant_user(db, payload.assigned_user_id, "assigned_user_id")
    _require_tenant_user(db, payload.engineer_id, "engineer_id")
    _require_tenant_user(db, payload.assistant_id, "assistant_id")
    data = payload.model_dump()
    customer, equipment = _require_tenant_service_links(db, actor, data.get("customer_id"), data.get("equipment_id"))
    if equipment and not data.get("customer_id"):
        data["customer_id"] = equipment.customer_id
        customer = db.get(Customer, equipment.customer_id) if equipment.customer_id else None
    if customer:
        data["store_name"] = data.get("store_name") or customer.name
        data["outlet_name"] = data.get("outlet_name") or customer.name
        data["contact_phone"] = data.get("contact_phone") or customer.phone
        data["address"] = data.get("address") or customer.address
        data["city"] = data.get("city") or customer.city
        data["state"] = data.get("state") or customer.state
        data["zip"] = data.get("zip") or customer.zip
    if equipment:
        data["machine_type"] = data.get("machine_type") or equipment.model
    if not data.get("ticket_number"):
        data["ticket_number"] = data.get("wo_number")
    if not data.get("wo_number"):
        data["wo_number"] = data.get("ticket_number")
    if not data.get("store_name") and data.get("outlet_name"):
        data["store_name"] = data["outlet_name"]
    if not data.get("outlet_name") and data.get("store_name"):
        data["outlet_name"] = data["store_name"]
    if not data.get("problem_description") and data.get("description"):
        data["problem_description"] = data["description"]
    if not data.get("description") and data.get("problem_description"):
        data["description"] = data["problem_description"]
    if not data.get("engineer_id") and data.get("assigned_user_id"):
        data["engineer_id"] = data["assigned_user_id"]
    if not data.get("assigned_user_id") and data.get("engineer_id"):
        data["assigned_user_id"] = data["engineer_id"]
    if data.get("form_template_id"):
        template = template_for_assignment(
            db,
            template_id=data["form_template_id"],
            machine_type=data.get("machine_type"),
            job_type=data.get("job_type"),
        )
        form_schema_json, form_data_json = snapshot_template(template)
        data["form_template_version"] = template.version
        data["form_schema_json"] = form_schema_json
        data["form_data_json"] = form_data_json
        if "status" not in payload.model_fields_set:
            data["status"] = template.default_work_order_status
    item = WorkOrder(**data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/work-orders", response_model=list[WorkOrderRead])
def list_work_orders(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    technician_id: int | None = Query(default=None, ge=1),
    status: str | None = Query(default=None),
    city: str | None = Query(default=None),
    job_type: str | None = Query(default=None),
    q: str | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    scope: str = Query(default="all", pattern="^(all|mine|available)$"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(WorkOrder).order_by(WorkOrder.id.desc())
    if actor.role == UserRole.ENGINEER and actor.user_id:
        if scope == "mine":
            stmt = stmt.where(WorkOrder.claimed_by_id == actor.user_id)
        elif scope == "available":
            stmt = stmt.where(WorkOrder.claimed_by_id.is_(None), WorkOrder.is_locked.is_(False))
    elif actor.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if technician_id:
        stmt = stmt.where((WorkOrder.assigned_user_id == technician_id) | (WorkOrder.engineer_id == technician_id))
    if status:
        stmt = stmt.where(func.lower(WorkOrder.status) == status.lower())
    if city:
        stmt = stmt.where(func.lower(WorkOrder.city) == city.lower())
    if job_type:
        stmt = stmt.where(func.lower(WorkOrder.job_type) == job_type.lower())
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(
            (func.lower(WorkOrder.ticket_number).like(like))
            | (func.lower(func.coalesce(WorkOrder.wo_number, "")).like(like))
            | (func.lower(func.coalesce(WorkOrder.outlet_name, "")).like(like))
            | (func.lower(func.coalesce(WorkOrder.address, "")).like(like))
        )
    if date_from:
        stmt = stmt.where(WorkOrder.schedule_date >= date_from)
    if date_to:
        stmt = stmt.where(WorkOrder.schedule_date <= date_to)
    rows = db.scalars(stmt.offset(skip).limit(limit)).all()
    return [_work_order_read_for_actor(db, actor, item) for item in rows]


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderRead)
def get_work_order(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    return _work_order_read_for_actor(db, actor, item)


@router.post("/work-orders/{work_order_id}/claim", response_model=WorkOrderRead)
def claim_work_order(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="Only engineers can claim work orders")
    require_bound_device(actor)
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    if item.is_locked or item.status.upper() in {"COMPLETED", "PENDING_APPROVAL"}:
        raise HTTPException(status_code=409, detail="Work order cannot be claimed in its current state")
    if item.claimed_by_id is not None:
        if item.claimed_by_id == actor.user_id and item.claimed_device_id == actor.device_record_id:
            return _work_order_read_for_actor(db, actor, item)
        if item.claimed_by_id == actor.user_id:
            raise HTTPException(status_code=409, detail="Work order is already bound to another registered device")
        raise HTTPException(status_code=409, detail="Work order has already been claimed")

    result = db.execute(
        update(WorkOrder)
        .where(
            WorkOrder.id == work_order_id,
            WorkOrder.organization_id == actor.organization_id,
            WorkOrder.claimed_by_id.is_(None),
            WorkOrder.is_locked.is_(False),
            func.upper(WorkOrder.status).notin_({"COMPLETED", "PENDING_APPROVAL"}),
        )
        .values(
            claimed_by_id=actor.user_id,
            claimed_device_id=actor.device_record_id,
            claimed_at=datetime.utcnow(),
            claim_version=WorkOrder.claim_version + 1,
            assigned_user_id=actor.user_id,
            engineer_id=actor.user_id,
        )
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Work order was claimed by another engineer")
    db.refresh(item)
    _audit(
        db,
        actor,
        "claim_work_order",
        "work_order",
        work_order_id,
        {"claimed_by_id": actor.user_id, "claimed_device_id": actor.device_record_id, "new_claim_version": item.claim_version},
    )
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.post("/work-orders/{work_order_id}/release", response_model=WorkOrderRead)
def release_work_order_claim(
    work_order_id: int,
    payload: WorkOrderClaimRelease,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    require_work_order_scope(db, actor, work_order_id)
    item = db.get(WorkOrder, work_order_id)
    if not item or item.claimed_by_id is None:
        raise HTTPException(status_code=409, detail="Work order is not currently claimed")
    if item.is_locked or item.status.upper() in {"COMPLETED", "PENDING_APPROVAL"}:
        raise HTTPException(status_code=409, detail="Claim cannot be released in the current state")
    previous_user_id = item.claimed_by_id
    previous_device_id = item.claimed_device_id
    if item.assigned_user_id == previous_user_id:
        item.assigned_user_id = None
    if item.engineer_id == previous_user_id:
        item.engineer_id = None
    item.claimed_by_id = None
    item.claimed_device_id = None
    item.claimed_at = None
    item.claim_version += 1
    _audit(
        db,
        actor,
        "release_work_order_claim",
        "work_order",
        work_order_id,
        {
            "reason": payload.reason.strip(),
            "previous_claimed_by_id": previous_user_id,
            "previous_claimed_device_id": previous_device_id,
            "new_claim_version": item.claim_version,
        },
    )
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.get("/work-orders/{work_order_id}/service-context", response_model=WorkOrderServiceContext)
def get_work_order_service_context(
    work_order_id: int,
    history_limit: int = Query(default=5, ge=1, le=20),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    current = db.get(WorkOrder, work_order_id)
    if not current:
        raise HTTPException(status_code=404, detail="Work order not found")
    customer = db.get(Customer, current.customer_id) if current.customer_id else None
    equipment = db.get(Equipment, current.equipment_id) if current.equipment_id else None

    history_stmt = select(WorkOrder).where(
        WorkOrder.organization_id == actor.organization_id,
        WorkOrder.id != current.id,
        func.lower(WorkOrder.status) == "completed",
    )
    if current.equipment_id:
        history_stmt = history_stmt.where(WorkOrder.equipment_id == current.equipment_id)
    elif current.customer_id and current.machine_type:
        history_stmt = history_stmt.where(
            WorkOrder.customer_id == current.customer_id,
            func.lower(func.coalesce(WorkOrder.machine_type, "")) == current.machine_type.lower(),
        )
    elif current.customer_id:
        history_stmt = history_stmt.where(WorkOrder.customer_id == current.customer_id)
    else:
        site_name = (current.outlet_name or current.store_name or "").strip().lower()
        machine = (current.machine_type or "").strip().lower()
        if not site_name or not machine:
            history_rows = []
            history_stmt = None
        else:
            history_stmt = history_stmt.where(
                func.lower(func.coalesce(WorkOrder.machine_type, "")) == machine,
                or_(
                    func.lower(func.coalesce(WorkOrder.outlet_name, "")) == site_name,
                    func.lower(func.coalesce(WorkOrder.store_name, "")) == site_name,
                ),
            )
    if history_stmt is not None:
        history_rows = db.scalars(
            history_stmt.order_by(WorkOrder.completed_at.desc(), WorkOrder.id.desc()).limit(history_limit)
        ).all()

    history = []
    for row in history_rows:
        part_rows = db.execute(
            select(Part.part_number, Part.name, func.sum(WorkOrderPart.quantity))
            .join(WorkOrderPart, WorkOrderPart.part_id == Part.id)
            .where(
                WorkOrderPart.organization_id == actor.organization_id,
                WorkOrderPart.work_order_id == row.id,
            )
            .group_by(Part.part_number, Part.name)
            .order_by(Part.part_number)
        ).all()
        history.append({
            "id": row.id,
            "ticket_number": row.ticket_number,
            "schedule_date": row.schedule_date,
            "job_type": row.job_type,
            "problem_description": row.problem_description,
            "repair_result": row.repair_result,
            "fault_type": row.fault_type,
            "error_code": row.error_code,
            "environment_info": row.environment_info,
            "final_outcome": row.final_outcome,
            "first_time_fix": row.first_time_fix,
            "is_rework": row.is_rework,
            "repair_duration_minutes": row.repair_duration_minutes,
            "status": row.status,
            "completed_at": row.completed_at,
            "engineer_id": row.engineer_id,
            "parts_used": [
                {"part_number": part_number, "name": name, "quantity": int(quantity or 0)}
                for part_number, name, quantity in part_rows
            ],
        })
    return {
        "customer": customer,
        "equipment": equipment,
        "fallback_customer_name": current.outlet_name or current.store_name,
        "fallback_contact_phone": current.contact_phone,
        "fallback_equipment_model": current.machine_type,
        "history": history,
    }


@router.get(
    "/work-orders/{work_order_id}/service-intelligence",
    response_model=WorkOrderServiceIntelligence,
)
def get_work_order_service_intelligence(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    current = db.get(WorkOrder, work_order_id)
    if not current:
        raise HTTPException(status_code=404, detail="Work order not found")
    consume_monthly_usage(db, actor.organization_id, ai_requests=1)
    result = build_service_intelligence(db, current, actor.organization_id)
    db.commit()
    return result


@router.patch("/work-orders/{work_order_id}", response_model=WorkOrderRead)
def update_work_order(
    work_order_id: int,
    payload: WorkOrderUpdate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    item = require_work_order_write_scope(db, actor, work_order_id)
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")
    if item.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Pending completion evidence is frozen until approval or rejection")

    updates = payload.model_dump(exclude_unset=True)
    if actor.role == UserRole.ENGINEER:
        blocked = {"revenue", "labor_cost", "assigned_user_id", "engineer_id", "assistant_id", "customer_id", "equipment_id", "status"}
        for key in blocked:
            updates.pop(key, None)
    if str(updates.get("status", "")).strip().upper() in {"COMPLETED", "PENDING_APPROVAL", "APPROVAL_REJECTED"}:
        raise HTTPException(status_code=400, detail="Terminal work order status requires the completion workflow")
    if "ticket_number" in updates and "wo_number" not in updates:
        updates["wo_number"] = updates["ticket_number"]
    if "wo_number" in updates and "ticket_number" not in updates:
        updates["ticket_number"] = updates["wo_number"]
    if "outlet_name" in updates and "store_name" not in updates:
        updates["store_name"] = updates["outlet_name"]
    if "store_name" in updates and "outlet_name" not in updates:
        updates["outlet_name"] = updates["store_name"]
    if "description" in updates and "problem_description" not in updates:
        updates["problem_description"] = updates["description"]
    if "problem_description" in updates and "description" not in updates:
        updates["description"] = updates["problem_description"]
    if "engineer_id" in updates and "assigned_user_id" not in updates:
        updates["assigned_user_id"] = updates["engineer_id"]
    if "assigned_user_id" in updates and "engineer_id" not in updates:
        updates["engineer_id"] = updates["assigned_user_id"]

    _require_tenant_user(db, updates.get("assigned_user_id"), "assigned_user_id")
    _require_tenant_user(db, updates.get("engineer_id"), "engineer_id")
    _require_tenant_user(db, updates.get("assistant_id"), "assistant_id")
    target_customer_id = updates.get("customer_id", item.customer_id)
    target_equipment_id = updates.get("equipment_id", item.equipment_id)
    if item.claimed_by_id is not None and any(
        field in updates and updates[field] != getattr(item, field)
        for field in {"assigned_user_id", "engineer_id"}
    ):
        raise HTTPException(status_code=409, detail="Release the authenticated claim before reassigning this work order")
    customer, equipment = _require_tenant_service_links(db, actor, target_customer_id, target_equipment_id)
    if equipment and target_customer_id is None:
        updates["customer_id"] = equipment.customer_id
    if customer and equipment and equipment.customer_id not in {None, customer.id}:
        raise HTTPException(status_code=400, detail="Equipment does not belong to the selected customer")

    previous_status = item.status
    for key, value in updates.items():
        setattr(item, key, value)

    db.add(item)
    if item.status != previous_status:
        status_event = JobStatus(
            work_order_id=work_order_id,
            status=item.status,
            timestamp=datetime.utcnow(),
        )
        db.add(status_event)
        db.flush()
        enqueue_work_order_event(
            db,
            item,
            "work_order.status_changed",
            f"work-order:{work_order_id}:job-status:{status_event.id}",
            {"status": item.status},
        )
    _audit(db, actor, "update_work_order", "work_order", work_order_id, {"changed_fields": sorted(updates)})
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.post("/work-orders/{work_order_id}/start", response_model=WorkOrderRead)
def start_work_order(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    item = require_work_order_execution_scope(db, actor, work_order_id)
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be started")
    if item.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Work order is awaiting manager approval")
    item.status = "IN_PROGRESS"
    item.started_at = item.started_at or datetime.utcnow()
    db.add(item)
    status_event = JobStatus(work_order_id=work_order_id, status="IN_PROGRESS", timestamp=datetime.utcnow())
    db.add(status_event)
    db.flush()
    enqueue_work_order_event(
        db,
        item,
        "work_order.status_changed",
        f"work-order:{work_order_id}:job-status:{status_event.id}",
        {"status": item.status},
    )
    _audit(db, actor, "start_job", "work_order", work_order_id)
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.post("/work-orders/{work_order_id}/complete", response_model=WorkOrderRead)
def complete_work_order(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    item = require_work_order_owner_scope(db, actor, work_order_id)
    _require_account_reauthentication(db, actor, payload.account_password)
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Work order already completed")
    _apply_completion_payload(item, payload)
    _capture_repair_duration(item, datetime.utcnow())
    policy = _completion_policy_for_work_order(db, item)
    _validate_completion_evidence(db, item, policy)
    if policy.get("require_manager_approval") and actor.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        item.status = "PENDING_APPROVAL"
        item.completion_requested_by = actor.user_id
        item.completion_requested_at = datetime.utcnow()
        db.add(item)
        status_event = JobStatus(work_order_id=work_order_id, status="PENDING_APPROVAL", timestamp=datetime.utcnow())
        db.add(status_event)
        db.flush()
        enqueue_work_order_event(
            db,
            item,
            "work_order.status_changed",
            f"work-order:{work_order_id}:job-status:{status_event.id}",
            {"status": item.status},
        )
        _audit(db, actor, "request_completion", "work_order", work_order_id, {"policy": policy})
        db.commit()
        db.refresh(item)
        return _work_order_read_for_actor(db, actor, item)
    if policy.get("require_manager_approval"):
        item.completion_approved_by = actor.user_id
        item.completion_approved_at = datetime.utcnow()
    return _finalize_work_order(db, actor, item)


def _normalize_job_type(job_type: str | None) -> str:
    return (job_type or "*").strip().lower() or "*"


def _policy_dict(policy: CompletionPolicy | None, organization_id: int, source: str) -> dict:
    if not policy:
        return {
            "id": None, "organization_id": organization_id, "job_type": None, "source": "legacy_default",
            "require_repair_result": False, "require_customer_signature": False,
            "require_completion_photo": False, "require_all_checklist_items": False,
            "require_parts_usage": False, "require_manager_approval": False,
            "created_at": None, "updated_at": None,
        }
    return {
        "id": policy.id, "organization_id": policy.organization_id,
        "job_type": None if policy.job_type_key == "*" else policy.job_type_key, "source": source,
        "require_repair_result": policy.require_repair_result,
        "require_customer_signature": policy.require_customer_signature,
        "require_completion_photo": policy.require_completion_photo,
        "require_all_checklist_items": policy.require_all_checklist_items,
        "require_parts_usage": policy.require_parts_usage,
        "require_manager_approval": policy.require_manager_approval,
        "created_at": policy.created_at, "updated_at": policy.updated_at,
    }


def _effective_completion_policy(db: Session, organization_id: int, job_type: str | None) -> dict:
    key = _normalize_job_type(job_type)
    policy = None
    source = "organization_default"
    if key != "*":
        policy = db.scalar(select(CompletionPolicy).where(
            CompletionPolicy.organization_id == organization_id, CompletionPolicy.job_type_key == key
        ))
        if policy:
            source = "job_type"
    if not policy:
        policy = db.scalar(select(CompletionPolicy).where(
            CompletionPolicy.organization_id == organization_id, CompletionPolicy.job_type_key == "*"
        ))
    return _policy_dict(policy, organization_id, source)


def _completion_policy_for_work_order(
    db: Session,
    item: WorkOrder,
) -> dict:
    policy = _effective_completion_policy(
        db,
        item.organization_id,
        item.job_type,
    )
    if work_order_form_requires_approval(item):
        policy = {
            **policy,
            "require_manager_approval": True,
        }
    return policy


def _apply_completion_payload(item: WorkOrder, payload: WorkOrderFlowAction) -> None:
    if payload.repair_result is not None:
        item.repair_result = payload.repair_result.strip() or None
    for field in ("fault_type", "error_code", "environment_info", "final_outcome"):
        value = getattr(payload, field)
        if value is not None:
            setattr(item, field, value.strip() or None)
    if payload.first_time_fix is not None:
        item.first_time_fix = payload.first_time_fix
    if payload.is_rework is not None:
        item.is_rework = payload.is_rework
    if payload.checklist_json is not None:
        item.checklist_json = payload.checklist_json
    if payload.customer_signature_name is not None:
        item.customer_signature_name = payload.customer_signature_name.strip() or None
    if payload.customer_signature_data is not None:
        item.customer_signature_data = payload.customer_signature_data
    item.customer_signed_at = datetime.utcnow() if item.customer_signature_name and item.customer_signature_data else None


def _capture_repair_duration(item: WorkOrder, finished_at: datetime) -> None:
    if item.repair_duration_minutes is None and item.started_at:
        item.repair_duration_minutes = max(0, int((finished_at - item.started_at).total_seconds() // 60))
    if not item.final_outcome:
        item.final_outcome = "repaired" if (item.repair_result or "").strip() else "completed"
    if not item.fault_type and item.job_type:
        item.fault_type = item.job_type.strip() or None


def _validate_completion_evidence(db: Session, item: WorkOrder, policy: dict) -> None:
    missing: list[str] = []
    if policy.get("require_repair_result") and not (item.repair_result or "").strip():
        missing.append("repair_result")
    if policy.get("require_customer_signature") and not (item.customer_signature_name and item.customer_signature_data):
        missing.append("customer_signature")
    if policy.get("require_all_checklist_items"):
        try:
            checklist = json.loads(item.checklist_json or "")
        except (TypeError, json.JSONDecodeError):
            checklist = None
        required_keys = {"equipment_safe", "site_clean", "customer_briefed"}
        if (
            not isinstance(checklist, dict)
            or not required_keys.issubset(checklist)
            or not all(type(checklist[key]) is bool and checklist[key] for key in required_keys)
        ):
            missing.append("completed_checklist")
    if policy.get("require_completion_photo") and not db.scalar(
        select(QCPicture.id).where(QCPicture.work_order_id == item.id).limit(1)
    ):
        missing.append("completion_photo")
    if policy.get("require_parts_usage") and not db.scalar(
        select(WorkOrderPart.id).where(WorkOrderPart.work_order_id == item.id).limit(1)
    ):
        missing.append("parts_usage")
    if missing:
        raise HTTPException(status_code=422, detail={"message": "Completion evidence is incomplete", "missing": missing})
    validate_work_order_form_completion(item)


def _finalize_work_order(db: Session, actor: Actor, item: WorkOrder) -> WorkOrderRead:
    work_order_id = item.id
    completed_by_id = item.claimed_by_id
    completed_device_id = item.claimed_device_id
    if actor.auth_method == "test" and completed_by_id is None:
        completed_by_id = actor.user_id
        completed_device_id = actor.device_record_id
    if actor.auth_method != "test" and (completed_by_id is None or completed_device_id is None):
        raise HTTPException(status_code=409, detail="Work order has no authenticated engineer claim")
    finished_at = datetime.utcnow()
    _capture_repair_duration(item, finished_at)
    item.completed_by_id = completed_by_id
    item.completed_device_id = completed_device_id
    item.status = "COMPLETED"
    item.completed_at = finished_at
    item.is_locked = True
    db.add(item)
    status_event = JobStatus(work_order_id=work_order_id, status="COMPLETED", timestamp=datetime.utcnow())
    db.add(status_event)
    db.flush()
    status_event_key = f"work-order:{work_order_id}:job-status:{status_event.id}"
    enqueue_work_order_event(
        db,
        item,
        "work_order.status_changed",
        status_event_key,
        {"status": item.status},
    )
    enqueue_work_order_event(
        db,
        item,
        "work_order.completed",
        f"{status_event_key}:completed",
        {
            "completed_by_id": completed_by_id,
            "completed_device_id": completed_device_id,
            "final_outcome": item.final_outcome,
            "first_time_fix": item.first_time_fix,
            "is_rework": item.is_rework,
            "repair_duration_minutes": item.repair_duration_minutes,
        },
    )
    _audit(
        db,
        actor,
        "complete_job",
        "work_order",
        work_order_id,
        {
            "parts_cost": get_work_order_parts_cost(db, work_order_id),
            "completed_by_id": completed_by_id,
            "completed_device_id": completed_device_id,
            "claim_version": item.claim_version,
            "fault_type": item.fault_type,
            "error_code": item.error_code,
            "final_outcome": item.final_outcome,
            "first_time_fix": item.first_time_fix,
            "is_rework": item.is_rework,
            "repair_duration_minutes": item.repair_duration_minutes,
        },
    )
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


def _require_tenant_service_links(
    db: Session,
    actor: Actor,
    customer_id: int | None,
    equipment_id: int | None,
) -> tuple[Customer | None, Equipment | None]:
    customer = None
    equipment = None
    if customer_id:
        customer = db.scalar(select(Customer).where(Customer.id == customer_id, Customer.organization_id == actor.organization_id))
        if not customer:
            raise HTTPException(status_code=400, detail="customer_id is not available in this organization")
    if equipment_id:
        equipment = db.scalar(select(Equipment).where(Equipment.id == equipment_id, Equipment.organization_id == actor.organization_id))
        if not equipment:
            raise HTTPException(status_code=400, detail="equipment_id is not available in this organization")
    if customer and equipment and equipment.customer_id not in {None, customer.id}:
        raise HTTPException(status_code=400, detail="Equipment does not belong to the selected customer")
    return customer, equipment


@router.post("/customers", response_model=CustomerRead)
def create_customer(payload: CustomerCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    data = payload.model_dump()
    if data.get("account_number") == "":
        data["account_number"] = None
    item = Customer(organization_id=actor.organization_id, **data)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/completion-policies", response_model=list[CompletionPolicyRead])
def list_completion_policies(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    rows = db.scalars(select(CompletionPolicy).where(
        CompletionPolicy.organization_id == actor.organization_id
    ).order_by(CompletionPolicy.job_type_key, CompletionPolicy.id)).all()
    return [_policy_dict(row, actor.organization_id, "organization_default" if row.job_type_key == "*" else "job_type") for row in rows]


@router.post("/completion-policies", response_model=CompletionPolicyRead)
def upsert_completion_policy(
    payload: CompletionPolicyUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    key = _normalize_job_type(payload.job_type)
    item = db.scalar(select(CompletionPolicy).where(
        CompletionPolicy.organization_id == actor.organization_id, CompletionPolicy.job_type_key == key
    ))
    values = payload.model_dump(exclude={"job_type"})
    if item:
        for field, value in values.items():
            setattr(item, field, value)
    else:
        item = CompletionPolicy(organization_id=actor.organization_id, job_type_key=key, **values)
    db.add(item)
    db.flush()
    _audit(db, actor, "upsert_completion_policy", "completion_policy", item.id, {"job_type": key, **values})
    db.commit()
    db.refresh(item)
    return _policy_dict(item, actor.organization_id, "organization_default" if key == "*" else "job_type")


@router.get("/work-orders/{work_order_id}/completion-policy", response_model=CompletionPolicyRead)
def get_work_order_completion_policy(
    work_order_id: int, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_work_order_scope(db, actor, work_order_id)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.ENGINEER)
    item = db.get(WorkOrder, work_order_id)
    if not item:
        raise HTTPException(status_code=404, detail="Work order not found")
    return _completion_policy_for_work_order(db, item)


@router.post("/work-orders/{work_order_id}/request-completion", response_model=WorkOrderRead)
def request_work_order_completion(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    item = require_work_order_owner_scope(db, actor, work_order_id)
    _require_account_reauthentication(db, actor, payload.account_password)
    if not item or item.is_locked:
        raise HTTPException(status_code=400, detail="Work order cannot request completion")
    if item.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Completion approval is already pending")
    policy = _completion_policy_for_work_order(db, item)
    if not policy.get("require_manager_approval"):
        raise HTTPException(status_code=409, detail="This work order does not require manager approval")
    _apply_completion_payload(item, payload)
    _capture_repair_duration(item, datetime.utcnow())
    _validate_completion_evidence(db, item, policy)
    item.status = "PENDING_APPROVAL"
    item.completion_requested_by = actor.user_id
    item.completion_requested_at = datetime.utcnow()
    db.add(item)
    status_event = JobStatus(work_order_id=work_order_id, status="PENDING_APPROVAL", timestamp=datetime.utcnow())
    db.add(status_event)
    db.flush()
    enqueue_work_order_event(
        db,
        item,
        "work_order.status_changed",
        f"work-order:{work_order_id}:job-status:{status_event.id}",
        {"status": item.status},
    )
    _audit(db, actor, "request_completion", "work_order", work_order_id)
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.post("/work-orders/{work_order_id}/approve-completion", response_model=WorkOrderRead)
def approve_work_order_completion(
    work_order_id: int, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_work_order_scope(db, actor, work_order_id)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    item = db.get(WorkOrder, work_order_id)
    if not item or item.status != "PENDING_APPROVAL" or item.is_locked:
        raise HTTPException(status_code=409, detail="Work order is not pending completion approval")
    policy = _completion_policy_for_work_order(db, item)
    _validate_completion_evidence(db, item, policy)
    item.completion_approved_by = actor.user_id
    item.completion_approved_at = datetime.utcnow()
    _audit(db, actor, "approve_completion", "work_order", work_order_id)
    return _finalize_work_order(db, actor, item)


@router.post("/work-orders/{work_order_id}/reject-completion", response_model=WorkOrderRead)
def reject_work_order_completion(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    item = db.get(WorkOrder, work_order_id)
    if not item or item.status != "PENDING_APPROVAL" or item.is_locked:
        raise HTTPException(status_code=409, detail="Work order is not pending completion approval")
    item.status = "APPROVAL_REJECTED"
    item.repair_duration_minutes = None
    db.add(item)
    status_event = JobStatus(work_order_id=work_order_id, status="APPROVAL_REJECTED", timestamp=datetime.utcnow())
    db.add(status_event)
    db.flush()
    enqueue_work_order_event(
        db,
        item,
        "work_order.status_changed",
        f"work-order:{work_order_id}:job-status:{status_event.id}",
        {"status": item.status},
    )
    _audit(db, actor, "reject_completion", "work_order", work_order_id, {"notes": payload.notes})
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.get("/customers", response_model=list[CustomerRead])
def list_customers(
    q: str | None = None,
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    stmt = select(Customer).where(Customer.organization_id == actor.organization_id, Customer.is_active.is_(True))
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(func.lower(Customer.name).like(like) | func.lower(func.coalesce(Customer.account_number, "")).like(like))
    return db.scalars(stmt.order_by(Customer.name, Customer.id).limit(limit)).all()


@router.post("/equipment", response_model=EquipmentRead)
def create_equipment(payload: EquipmentCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    customer, _ = _require_tenant_service_links(db, actor, payload.customer_id, None)
    item = Equipment(organization_id=actor.organization_id, **payload.model_dump())
    if customer:
        item.customer_id = customer.id
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/equipment", response_model=list[EquipmentRead])
def list_equipment(
    customer_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    stmt = select(Equipment).where(Equipment.organization_id == actor.organization_id, Equipment.is_active.is_(True))
    if customer_id:
        stmt = stmt.where(Equipment.customer_id == customer_id)
    return db.scalars(stmt.order_by(Equipment.model, Equipment.id).limit(limit)).all()


@router.post("/work-orders/{work_order_id}/pause", response_model=WorkOrderRead)
def pause_work_order(
    work_order_id: int,
    payload: WorkOrderFlowAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    item = require_work_order_execution_scope(db, actor, work_order_id)
    if item.is_locked:
        raise HTTPException(status_code=400, detail="Completed work order cannot be paused")
    if item.status != "IN_PROGRESS":
        raise HTTPException(status_code=409, detail="Only an in-progress work order can be paused")
    item.status = "PAUSED"
    item.paused_at = datetime.utcnow()
    db.add(item)
    status_event = JobStatus(work_order_id=work_order_id, status="PAUSED", timestamp=datetime.utcnow())
    db.add(status_event)
    db.flush()
    enqueue_work_order_event(
        db,
        item,
        "work_order.status_changed",
        f"work-order:{work_order_id}:job-status:{status_event.id}",
        {"status": item.status},
    )
    _audit(db, actor, "pause_job", "work_order", work_order_id, {"notes": payload.notes})
    db.commit()
    db.refresh(item)
    return _work_order_read_for_actor(db, actor, item)


@router.post("/inventory/transactions", response_model=InventoryTransactionRead)
def add_inventory_transaction(
    payload: InventoryTransactionCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    source_region_id = None
    target_region_id = None
    cross_region = False
    if (
        payload.transaction_type == TransactionType.TRANSFER
        and payload.from_warehouse_id
        and payload.to_warehouse_id
    ):
        source = db.get(Warehouse, payload.from_warehouse_id)
        target = db.get(Warehouse, payload.to_warehouse_id)
        if source and target and not (
            warehouse_is_vehicle(db, source) or warehouse_is_vehicle(db, target)
        ):
            default_region_id = db.scalar(
                select(InventoryRegion.id).where(
                    InventoryRegion.is_default.is_(True)
                )
            )
            source_region_id = source.region_id or default_region_id
            target_region_id = target.region_id or default_region_id
            cross_region = bool(
                source_region_id is not None
                and target_region_id is not None
                and source_region_id != target_region_id
            )
            if cross_region and actor.role not in {UserRole.ADMIN, UserRole.MANAGER}:
                raise HTTPException(
                    status_code=403,
                    detail="Cross-region transfers require administrator or manager access",
                )
    effective_payload = payload.model_copy(update={"user_id": actor.user_id}) if actor.user_id else payload
    tx = create_transaction(db, effective_payload)
    _audit(
        db,
        actor,
        f"inventory_{payload.transaction_type.value}",
        "inventory_transaction",
        tx.id,
        {
            "part_id": payload.part_id,
            "qty": payload.quantity,
            "from": payload.from_warehouse_id,
            "to": payload.to_warehouse_id,
            "from_region_id": source_region_id,
            "to_region_id": target_region_id,
            "cross_region": cross_region,
        },
    )
    db.commit()
    db.refresh(tx)
    return tx


@router.get("/inventory/transactions", response_model=list[InventoryTransactionRead])
def list_inventory_transactions(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    return db.scalars(
        select(InventoryTransaction).order_by(InventoryTransaction.id.desc()).offset(skip).limit(limit)
    ).all()


@router.get("/inventory/balances", response_model=list[StockBalance])
def inventory_balances(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = get_stock_balances(db)
    return rows[skip : skip + limit]


@router.get("/inventory/location-balances", response_model=list[LocationStockBalance])
def inventory_location_balances(
    warehouse_id: int | None = None,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if warehouse_id is not None and not db.get(Warehouse, warehouse_id):
        raise HTTPException(status_code=404, detail="Warehouse not found")
    return get_location_stock_balances(db, warehouse_id)


def _warehouse_label_token(warehouse: Warehouse) -> str:
    return f"OPF:WH:{warehouse.id}:{warehouse.code or ''}"


def _location_label_token(location: StorageLocation) -> str:
    return f"OPF:LOC:{location.id}:{location.code}"


@router.get("/inventory/location-labels", response_model=list[InventoryLocationLabelRead])
def inventory_location_labels(
    warehouse_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    warehouse = db.get(Warehouse, warehouse_id)
    if not warehouse or not warehouse.is_active:
        raise HTTPException(status_code=404, detail="Active warehouse not found")
    rows = [InventoryLocationLabelRead(
        label_token=_warehouse_label_token(warehouse), warehouse_id=warehouse.id,
        warehouse_code=warehouse.code or "", warehouse_name=warehouse.name,
    )]
    locations = db.scalars(select(StorageLocation).where(
        StorageLocation.warehouse_id == warehouse.id,
        StorageLocation.is_active.is_(True),
    ).order_by(StorageLocation.code)).all()
    rows.extend(InventoryLocationLabelRead(
        label_token=_location_label_token(location), warehouse_id=warehouse.id,
        warehouse_code=warehouse.code or "", warehouse_name=warehouse.name,
        location_id=location.id, location_code=location.code, location_name=location.name, zone=location.zone,
    ) for location in locations)
    return rows


@router.post("/inventory/location-scan", response_model=InventoryLocationScanRead)
def scan_inventory_location(
    payload: InventoryLocationScanRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    label = payload.label.strip()
    if not label:
        raise HTTPException(status_code=422, detail="Scan label cannot be blank")
    warehouse: Warehouse | None = None
    location: StorageLocation | None = None
    pieces = label.split(":", 3)
    if len(pieces) == 4 and pieces[0].upper() == "OPF" and pieces[2].isdigit():
        entity_id, printed_code = int(pieces[2]), pieces[3]
        if pieces[1].upper() == "WH":
            warehouse = db.get(Warehouse, entity_id)
            if warehouse and (warehouse.code or "") != printed_code:
                raise HTTPException(status_code=409, detail="Warehouse label is stale or invalid")
        elif pieces[1].upper() == "LOC":
            location = db.get(StorageLocation, entity_id)
            if location and location.code != printed_code:
                raise HTTPException(status_code=409, detail="Location label is stale or invalid")
        else:
            raise HTTPException(status_code=400, detail="Unsupported OpenPartsFlow label type")
    else:
        warehouse = db.scalar(select(Warehouse).where(func.lower(Warehouse.code) == label.lower()))
        if not warehouse:
            location_stmt = select(StorageLocation).where(func.lower(StorageLocation.code) == label.lower())
            if payload.expected_warehouse_id:
                location_stmt = location_stmt.where(StorageLocation.warehouse_id == payload.expected_warehouse_id)
            matches = db.scalars(location_stmt.limit(2)).all()
            if len(matches) > 1:
                raise HTTPException(status_code=409, detail="Location code is ambiguous; scan its warehouse first")
            location = matches[0] if matches else None
    if location:
        warehouse = db.get(Warehouse, location.warehouse_id)
    if not warehouse:
        raise HTTPException(status_code=404, detail="Warehouse or location label not found")
    if not warehouse.is_active or (location and not location.is_active):
        raise HTTPException(status_code=409, detail="Scanned warehouse or location is inactive")
    if payload.expected_warehouse_id and warehouse.id != payload.expected_warehouse_id:
        raise HTTPException(status_code=409, detail="Location belongs to a different warehouse")
    scan_type = "location" if location else "warehouse"
    label_token = _location_label_token(location) if location else _warehouse_label_token(warehouse)
    _audit(db, actor, f"inventory_{scan_type}_scanned", scan_type, location.id if location else warehouse.id, {
        "label_token": label_token, "warehouse_id": warehouse.id,
        "location_id": location.id if location else None,
    })
    db.commit()
    return InventoryLocationScanRead(
        scan_type=scan_type, label_token=label_token, warehouse_id=warehouse.id,
        warehouse_code=warehouse.code or "", warehouse_name=warehouse.name,
        location_id=location.id if location else None, location_code=location.code if location else None,
        location_name=location.name if location else None, zone=location.zone if location else None,
    )


@router.post("/inventory/scan", response_model=InventoryScanRead)
def scan_inventory(
    payload: InventoryScanRequest,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    if not payload.barcode and not payload.part_number:
        raise HTTPException(status_code=400, detail="barcode or part_number is required")
    part = None
    method = "barcode" if payload.barcode else "part_number"
    if payload.barcode:
        part = db.scalar(select(Part).where(Part.barcode == payload.barcode.strip()))
    if not part and payload.part_number:
        part = db.scalar(select(Part).where(Part.part_number == payload.part_number.strip()))
        if part:
            method = "part_number_fallback"
    if not part:
        return InventoryScanRead(
            matched=False, confidence=0.0, recognition_method=method,
            quantity_requested=payload.quantity, warehouse_id=payload.warehouse_id,
            location_id=payload.location_id, feedback="Part label was not recognized. Scan a clear barcode or select the part manually.",
        )
    effective_warehouse_id = payload.warehouse_id
    if payload.location_id:
        location = db.get(StorageLocation, payload.location_id)
        if not location or not location.is_active or (payload.warehouse_id and location.warehouse_id != payload.warehouse_id):
            raise HTTPException(status_code=400, detail="Location does not belong to warehouse")
        effective_warehouse_id = location.warehouse_id
        warehouse = db.get(Warehouse, location.warehouse_id)
        if not warehouse or not warehouse.is_active:
            raise HTTPException(status_code=409, detail="Location warehouse is inactive")
        current = get_location_stock_quantity(db, part.id, payload.location_id)
    elif payload.warehouse_id:
        warehouse = db.get(Warehouse, payload.warehouse_id)
        if not warehouse or not warehouse.is_active:
            raise HTTPException(status_code=404, detail="Active warehouse not found")
        current = get_stock_quantity(db, part.id, payload.warehouse_id)
    else:
        current = None
    if actor.role == UserRole.ENGINEER and effective_warehouse_id is not None:
        warehouse = db.get(Warehouse, effective_warehouse_id)
        if not warehouse or not warehouse_is_vehicle(db, warehouse) or warehouse.assigned_user_id != actor.user_id:
            raise HTTPException(status_code=403, detail="Engineers can only scan stock in their assigned vehicle")
    projected = current - payload.quantity if current is not None else None
    feedback = "Part recognized and the checked quantity is available." if projected is None or projected >= 0 else f"Insufficient stock by {abs(projected)} unit(s)."
    _audit(db, actor, "inventory_scan", "part", part.id, {
        "method": method, "quantity": payload.quantity, "warehouse_id": effective_warehouse_id,
        "location_id": payload.location_id, "current_quantity": current,
    })
    db.commit()
    return InventoryScanRead(
        matched=True, confidence=1.0 if method == "barcode" else 0.95,
        recognition_method=method, part=PartRead.model_validate(part),
        quantity_requested=payload.quantity, warehouse_id=effective_warehouse_id,
        location_id=payload.location_id, current_quantity=current,
        projected_quantity=projected, feedback=feedback,
    )


@router.get("/employees/{user_id}/van-inventory", response_model=list[StockBalance])
def employee_van_inventory(
    user_id: int,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role == UserRole.ENGINEER and actor.user_id != user_id:
        raise HTTPException(status_code=403, detail="Can only view own van inventory")
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.ENGINEER)
    rows = get_employee_van_inventory(db, user_id)
    return rows[skip : skip + limit]


@router.get("/inventory/my-van", response_model=list[StockBalance])
def my_van_inventory(
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ENGINEER or actor.user_id is None:
        raise HTTPException(status_code=403, detail="Engineer access required")
    return get_employee_van_inventory(db, actor.user_id)[:limit]


@router.post(
    "/work-order-parts",
    response_model=WorkOrderPartRead,
    deprecated=True,
    summary="Deprecated: use /work-orders/{work_order_id}/use-part",
)
def add_work_order_part(
    payload: WorkOrderPartCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    begin_inventory_write(db)
    require_work_order_execution_scope(db, actor, payload.work_order_id)
    return use_part_for_work_order(payload.work_order_id, payload, db, actor)


@router.post(
    "/work-orders/{work_order_id}/use-part",
    response_model=WorkOrderPartRead,
    summary="Use a part on work order",
)
def use_part_for_work_order(
    work_order_id: int,
    payload: WorkOrderPartCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    begin_inventory_write(db)
    work_order = require_work_order_execution_scope(db, actor, work_order_id)
    if not work_order or work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=409, detail="Work order cannot accept parts in its current state")
    if payload.work_order_id != work_order_id:
        raise HTTPException(status_code=400, detail="Path work order ID must match payload work_order_id")
    if actor.role == UserRole.ENGINEER:
        source_warehouse = db.get(Warehouse, payload.warehouse_id)
        if (
            not source_warehouse
            or not warehouse_is_vehicle(db, source_warehouse)
            or source_warehouse.assigned_user_id != actor.user_id
        ):
            raise HTTPException(status_code=403, detail="Engineers can only use parts from their own assigned van")
    effective_payload = payload.model_copy(update={"user_id": actor.user_id}) if actor.user_id else payload
    usage = use_part_on_work_order(db, effective_payload)
    part = db.get(Part, payload.part_id)
    warehouse_quantity = get_stock_quantity(db, payload.part_id, payload.warehouse_id)
    threshold = max(part.safety_stock, part.min_stock) if part else 0
    if part and warehouse_quantity <= threshold:
        existing = db.scalar(select(InventoryNotification).where(
            InventoryNotification.part_id == part.id,
            InventoryNotification.warehouse_id == payload.warehouse_id,
            InventoryNotification.status == "open",
        ))
        if not existing:
            db.add(InventoryNotification(
                part_id=part.id, warehouse_id=payload.warehouse_id, work_order_id=work_order_id,
                message=f"{part.part_number} 使用后库存为 {warehouse_quantity}，已达到补货阈值 {threshold}。",
            ))
    source_warehouse = db.get(Warehouse, payload.warehouse_id)
    enqueue_work_order_event(
        db,
        work_order,
        "work_order.part_used",
        f"work-order-part:{usage.id}:created",
        {
            "usage_id": usage.id,
            "part_number": part.part_number if part else None,
            "part_name": part.name if part else None,
            "quantity": usage.quantity,
            "unit": part.unit if part else None,
            "warehouse_code": source_warehouse.code if source_warehouse else None,
            "used_by_id": usage.user_id,
        },
    )
    _audit(db, actor, "use_part", "work_order_part", usage.id, {"work_order_id": work_order_id, "part_id": payload.part_id, "qty": payload.quantity})
    db.commit()
    return usage


@router.get("/inventory/notifications", response_model=list[InventoryNotificationRead])
def inventory_notifications(
    status: str = "open", db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    return db.scalars(select(InventoryNotification).where(InventoryNotification.status == status).order_by(InventoryNotification.id.desc()).limit(100)).all()


@router.patch("/inventory/notifications/{notification_id}", response_model=InventoryNotificationRead)
def update_inventory_notification(
    notification_id: int,
    status: str = Query(..., pattern="^(open|acknowledged|resolved)$"),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    notification = db.get(InventoryNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Inventory notification not found")
    previous_status = notification.status
    notification.status = status
    _audit(
        db,
        actor,
        "inventory_notification_status_changed",
        "inventory_notification",
        notification.id,
        {"from_status": previous_status, "to_status": status},
    )
    db.commit()
    db.refresh(notification)
    return notification


def _replenishment_read_for_actor(
    db: Session,
    actor: Actor,
    item: ReplenishmentRequest,
) -> ReplenishmentRequestRead:
    payload = ReplenishmentRequestRead.model_validate(item).model_dump()
    part = db.get(Part, item.part_id)
    source = db.get(Warehouse, item.source_warehouse_id) if item.source_warehouse_id else None
    destination = db.get(Warehouse, item.destination_warehouse_id)
    target = db.get(User, item.target_user_id) if item.target_user_id else None
    received_device = db.get(UserDevice, item.received_device_id) if item.received_device_id else None
    work_order = db.get(WorkOrder, item.work_order_id) if item.work_order_id else None

    def user_name(user_id: int | None) -> str | None:
        user = db.get(User, user_id) if user_id else None
        return user.name if user else None

    warehouse_operator = actor.role in {UserRole.ADMIN, UserRole.WAREHOUSE}
    can_receive = False
    if item.status == "shipped":
        if item.target_user_id is not None:
            can_receive = bool(
                actor.role == UserRole.ENGINEER
                and actor.user_id == item.target_user_id
                and actor.device_verified
            )
        else:
            can_receive = warehouse_operator
    payload.update(
        part_number=part.part_number if part else None,
        part_name=part.name if part else None,
        source_warehouse_name=source.name if source else None,
        destination_warehouse_name=destination.name if destination else None,
        target_user_name=target.name if target else None,
        requested_by_name=user_name(item.requested_by),
        approved_by_name=user_name(item.approved_by),
        rejected_by_name=user_name(item.rejected_by),
        picking_by_name=user_name(item.picking_by),
        shipped_by_name=user_name(item.shipped_by),
        received_by_name=user_name(item.received_by),
        received_device_name=received_device.device_name if received_device else None,
        completed_by_name=user_name(item.completed_by),
        cancelled_by_name=user_name(item.cancelled_by),
        work_order_ticket_number=work_order.ticket_number if work_order else None,
        source_available_quantity=(
            get_available_stock_quantity(db, item.part_id, item.source_warehouse_id)
            if item.source_warehouse_id
            else None
        ),
        destination_quantity=(
            get_stock_quantity(db, item.part_id, item.destination_warehouse_id)
            if destination
            else 0
        ),
        can_approve=(actor.role in {UserRole.ADMIN, UserRole.MANAGER} and not item.requires_reconciliation
                     and item.status == "requested" and item.approval_status == "pending"),
        can_reject=(actor.role in {UserRole.ADMIN, UserRole.MANAGER} and not item.requires_reconciliation
                    and item.status == "requested" and item.approval_status == "pending"),
        can_start_picking=(warehouse_operator and not item.requires_reconciliation and item.status == "requested"
                           and item.approval_status == "approved"),
        can_ship=warehouse_operator and not item.requires_reconciliation and item.status == "picking",
        can_receive=can_receive and not item.requires_reconciliation,
        can_complete=warehouse_operator and not item.requires_reconciliation and item.status == "received",
        can_cancel=warehouse_operator and not item.requires_reconciliation and item.status in {"requested", "picking"},
        can_reconcile=actor.role == UserRole.ADMIN and item.requires_reconciliation,
    )
    return ReplenishmentRequestRead(**payload)


def _validate_replenishment_destination(
    db: Session,
    destination: Warehouse,
) -> int | None:
    if not destination.is_active:
        raise HTTPException(status_code=409, detail="Destination warehouse is inactive")
    if not warehouse_is_vehicle(db, destination):
        return None
    target = db.get(User, destination.assigned_user_id) if destination.assigned_user_id else None
    if not target or not target.is_active or target.role != UserRole.ENGINEER:
        raise HTTPException(status_code=422, detail="A van destination must be assigned to an active engineer")
    return target.id


def _validate_replenishment_source(
    db: Session,
    source: Warehouse,
    destination: Warehouse,
) -> None:
    if not source.is_active or source.id == destination.id:
        raise HTTPException(status_code=400, detail="Source warehouse must be active and different from destination")
    if warehouse_is_vehicle(db, source):
        raise HTTPException(
            status_code=409,
            detail="A vehicle cannot be used as a replenishment source; use the authenticated return workflow",
        )


@router.post("/inventory/notifications/{notification_id}/create-request", response_model=ReplenishmentRequestRead)
def create_replenishment_request(
    notification_id: int,
    quantity: int = Query(default=1, ge=1),
    source_warehouse_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    notification = db.get(InventoryNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="Inventory notification not found")
    existing = db.scalar(
        select(ReplenishmentRequest).where(ReplenishmentRequest.notification_id == notification_id)
    )
    if existing:
        return _replenishment_read_for_actor(db, actor, existing)
    destination = db.get(Warehouse, notification.warehouse_id)
    if not destination:
        raise HTTPException(status_code=404, detail="Destination warehouse not found")
    target_user_id = _validate_replenishment_destination(db, destination)
    source = db.get(Warehouse, source_warehouse_id) if source_warehouse_id else None
    if source_warehouse_id and not source:
        raise HTTPException(status_code=404, detail="Source warehouse not found")
    if source:
        _validate_replenishment_source(db, source, destination)
    item = ReplenishmentRequest(
        notification_id=notification.id,
        part_id=notification.part_id,
        destination_warehouse_id=notification.warehouse_id,
        source_warehouse_id=source.id if source else None,
        target_user_id=target_user_id,
        quantity=quantity,
        work_order_id=notification.work_order_id,
        requested_by=actor.user_id,
    )
    notification.status = "acknowledged"
    try:
        db.add(item)
        db.flush()
        _audit(
            db,
            actor,
            "replenishment_requested",
            "replenishment_request",
            item.id,
            {
                "notification_id": notification.id,
                "part_id": item.part_id,
                "quantity": item.quantity,
                "source_warehouse_id": item.source_warehouse_id,
                "destination_warehouse_id": item.destination_warehouse_id,
                "target_user_id": item.target_user_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(ReplenishmentRequest).where(ReplenishmentRequest.notification_id == notification_id)
        )
        if existing:
            return _replenishment_read_for_actor(db, actor, existing)
        raise HTTPException(status_code=409, detail="Replenishment request could not be created") from exc
    db.refresh(item)
    return _replenishment_read_for_actor(db, actor, item)


@router.post("/inventory/replenishment-requests", response_model=ReplenishmentRequestRead)
def create_manual_replenishment_request(
    payload: ReplenishmentRequestCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    client_request_id = payload.client_request_id.strip()
    request_reason = payload.reason.strip()
    if len(request_reason) < 3:
        raise HTTPException(status_code=422, detail="Request reason must be at least 3 non-whitespace characters")

    def matches_existing(candidate: ReplenishmentRequest) -> bool:
        return (
            candidate.part_id == payload.part_id
            and candidate.destination_warehouse_id == payload.destination_warehouse_id
            and candidate.source_warehouse_id == payload.source_warehouse_id
            and candidate.quantity == payload.quantity
            and (candidate.request_reason or "") == request_reason
        )

    existing = db.scalar(
        select(ReplenishmentRequest).where(
            ReplenishmentRequest.client_request_id == client_request_id,
        )
    )
    if existing:
        if not matches_existing(existing):
            raise HTTPException(status_code=409, detail="client_request_id was already used for another request")
        return _replenishment_read_for_actor(db, actor, existing)

    part = db.get(Part, payload.part_id)
    destination = db.get(Warehouse, payload.destination_warehouse_id)
    source = db.get(Warehouse, payload.source_warehouse_id) if payload.source_warehouse_id else None
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    if not destination:
        raise HTTPException(status_code=404, detail="Destination warehouse not found")
    target_user_id = _validate_replenishment_destination(db, destination)
    if target_user_id is None:
        raise HTTPException(status_code=422, detail="Manual replenishment destination must be an assigned vehicle")
    if payload.source_warehouse_id and not source:
        raise HTTPException(status_code=404, detail="Source warehouse not found")
    if source:
        _validate_replenishment_source(db, source, destination)

    item = ReplenishmentRequest(
        client_request_id=client_request_id,
        request_reason=request_reason,
        part_id=part.id,
        destination_warehouse_id=destination.id,
        source_warehouse_id=source.id if source else None,
        target_user_id=target_user_id,
        quantity=payload.quantity,
        requested_by=actor.user_id,
    )
    try:
        db.add(item)
        db.flush()
        _audit(
            db,
            actor,
            "replenishment_requested",
            "replenishment_request",
            item.id,
            {
                "origin": "manual",
                "client_request_id": client_request_id,
                "reason": item.request_reason,
                "part_id": item.part_id,
                "quantity": item.quantity,
                "source_warehouse_id": item.source_warehouse_id,
                "destination_warehouse_id": item.destination_warehouse_id,
                "target_user_id": item.target_user_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(ReplenishmentRequest).where(
                ReplenishmentRequest.client_request_id == client_request_id,
            )
        )
        if existing:
            if matches_existing(existing):
                return _replenishment_read_for_actor(db, actor, existing)
            raise HTTPException(status_code=409, detail="client_request_id was already used for another request")
        raise HTTPException(status_code=409, detail="Replenishment request could not be created") from exc
    db.refresh(item)
    return _replenishment_read_for_actor(db, actor, item)


@router.get("/inventory/replenishment-requests", response_model=list[ReplenishmentRequestRead])
def list_replenishment_requests(
    status: str | None = Query(default=None, pattern="^(requested|picking|shipped|received|completed|cancelled|rejected)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    stmt = select(ReplenishmentRequest).order_by(ReplenishmentRequest.id.desc())
    if actor.role == UserRole.ENGINEER:
        stmt = stmt.where(ReplenishmentRequest.target_user_id == actor.user_id)
    if status:
        stmt = stmt.where(ReplenishmentRequest.status == status)
    rows = db.scalars(stmt.limit(limit)).all()
    return [_replenishment_read_for_actor(db, actor, item) for item in rows]


@router.post(
    "/inventory/replenishment-requests/{request_id}/reconcile",
    response_model=ReplenishmentRequestRead,
)
def reconcile_replenishment_request(
    request_id: int,
    payload: ReplenishmentRequestReconcile,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Administrator access required")
    begin_inventory_write(db)
    item = db.scalar(
        select(ReplenishmentRequest)
        .where(
            ReplenishmentRequest.id == request_id,
            ReplenishmentRequest.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Replenishment request not found")
    if not item.requires_reconciliation:
        return _replenishment_read_for_actor(db, actor, item)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Replenishment request changed; refresh before reconciling")
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Reconciliation reason must be at least 3 characters")
    _require_account_reauthentication(db, actor, payload.account_password)
    linked_movements = db.scalars(
        select(InventoryTransaction).where(InventoryTransaction.replenishment_request_id == item.id)
    ).all()
    if linked_movements:
        raise HTTPException(
            status_code=409,
            detail="Linked inventory movements require a dedicated stock correction, not historical reconciliation",
        )
    if payload.resolution == "reset_requested":
        if item.status != "requested":
            raise HTTPException(status_code=409, detail="Only a reopened requested record can use reset_requested")
        if item.notification_id:
            notification = db.get(InventoryNotification, item.notification_id)
            if notification:
                notification.status = "open"
    elif item.status != "completed":
        raise HTTPException(status_code=409, detail="accept_historical is only valid for a legacy completed record")
    elif item.notification_id:
        notification = db.get(InventoryNotification, item.notification_id)
        if notification:
            notification.status = "resolved"

    previous_version = item.version
    item.requires_reconciliation = False
    item.version += 1
    _audit(
        db,
        actor,
        "replenishment_reconciled",
        "replenishment_request",
        item.id,
        {
            "resolution": payload.resolution,
            "reason": reason,
            "previous_version": previous_version,
            "new_version": item.version,
            "status": item.status,
        },
    )
    db.commit()
    db.refresh(item)
    return _replenishment_read_for_actor(db, actor, item)


@router.post("/inventory/replenishment-requests/{request_id}/actions", response_model=ReplenishmentRequestRead)
def act_on_replenishment_request(
    request_id: int,
    payload: ReplenishmentRequestAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    begin_inventory_write(db)
    item = db.scalar(
        select(ReplenishmentRequest)
        .where(
            ReplenishmentRequest.id == request_id,
            ReplenishmentRequest.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Replenishment request not found")
    if item.requires_reconciliation:
        raise HTTPException(
            status_code=409,
            detail="Historical replenishment requires administrator reconciliation before workflow actions",
        )
    target_status = {
        "approve": "requested",
        "reject": "rejected",
        "start_picking": "picking",
        "ship": "shipped",
        "receive": "received",
        "complete": "completed",
        "cancel": "cancelled",
    }[payload.action]
    warehouse_operator = actor.role in {UserRole.ADMIN, UserRole.WAREHOUSE}
    approval_operator = actor.role in {UserRole.ADMIN, UserRole.MANAGER}
    if payload.action in {"approve", "reject"} and not approval_operator:
        raise HTTPException(status_code=403, detail="Manager or administrator approval access required")
    if payload.action in {"start_picking", "ship", "complete", "cancel"} and not warehouse_operator:
        raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
    if payload.action == "receive":
        if item.target_user_id is not None:
            if actor.role != UserRole.ENGINEER or actor.user_id != item.target_user_id:
                raise HTTPException(status_code=403, detail="Only the destination engineer can receive this shipment")
            require_bound_device(actor)
            if item.status == "received" and item.received_device_id != actor.device_record_id:
                raise HTTPException(status_code=403, detail="Shipment was received on another registered device")
        elif not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
    if payload.action == "approve" and item.approval_status == "approved":
        return _replenishment_read_for_actor(db, actor, item)
    if payload.action == "reject" and item.status == "rejected":
        return _replenishment_read_for_actor(db, actor, item)
    if payload.action not in {"approve", "reject"} and item.status == target_status:
        return _replenishment_read_for_actor(db, actor, item)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Replenishment request changed; refresh before continuing")

    previous_status = item.status
    transaction_id: int | None = None
    now = datetime.utcnow()
    if payload.action == "approve":
        if item.status != "requested" or item.approval_status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending replenishment request can be approved")
        item.approval_status = "approved"
        item.approved_by = actor.user_id
        item.approved_at = now

    elif payload.action == "reject":
        if item.status != "requested" or item.approval_status != "pending":
            raise HTTPException(status_code=409, detail="Only a pending replenishment request can be rejected")
        if not payload.reason or len(payload.reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="Rejection reason must be at least 3 characters")
        item.approval_status = "rejected"
        item.rejected_by = actor.user_id
        item.rejected_at = now
        item.rejection_reason = payload.reason.strip()
        if item.notification_id:
            notification = db.get(InventoryNotification, item.notification_id)
            if notification:
                notification.status = "resolved"

    elif payload.action == "start_picking":
        if not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
        if item.status != "requested" or item.approval_status != "approved":
            raise HTTPException(status_code=409, detail="Only an approved replenishment can start picking")
        if (
            item.source_warehouse_id is not None
            and payload.source_warehouse_id is not None
            and payload.source_warehouse_id != item.source_warehouse_id
        ):
            raise HTTPException(
                status_code=409,
                detail="The assigned source warehouse cannot be replaced during picking; cancel and recreate the request",
            )
        source_id = item.source_warehouse_id or payload.source_warehouse_id
        source = db.get(Warehouse, source_id) if source_id else None
        destination = db.get(Warehouse, item.destination_warehouse_id)
        if not source:
            raise HTTPException(status_code=422, detail="Select a source warehouse before picking")
        if not destination:
            raise HTTPException(status_code=404, detail="Destination warehouse not found")
        _validate_replenishment_source(db, source, destination)
        db.scalar(select(Part).where(Part.id == item.part_id).with_for_update())
        if get_available_stock_quantity(db, item.part_id, source.id) < item.quantity:
            raise HTTPException(status_code=409, detail="Insufficient unreserved source stock")
        current_target = _validate_replenishment_destination(db, destination)
        if item.target_user_id not in {None, current_target}:
            raise HTTPException(status_code=409, detail="Destination van ownership changed; cancel and recreate the request")
        item.source_warehouse_id = source.id
        item.target_user_id = current_target
        item.picking_by = actor.user_id
        item.picking_at = now

    elif payload.action == "ship":
        if not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
        if item.status != "picking" or not item.source_warehouse_id:
            raise HTTPException(status_code=409, detail="Only a picking request with a source can be shipped")
        source = db.get(Warehouse, item.source_warehouse_id)
        destination = db.get(Warehouse, item.destination_warehouse_id)
        if not source or not source.is_active:
            raise HTTPException(status_code=409, detail="Source warehouse is no longer active")
        if not destination:
            raise HTTPException(status_code=404, detail="Destination warehouse not found")
        _validate_replenishment_source(db, source, destination)
        current_target = _validate_replenishment_destination(db, destination)
        if current_target != item.target_user_id:
            raise HTTPException(status_code=409, detail="Destination custody changed; cancel and recreate the request")
        part = db.scalar(select(Part).where(Part.id == item.part_id).with_for_update())
        if not part:
            raise HTTPException(status_code=404, detail="Part not found")
        if get_stock_quantity(db, item.part_id, item.source_warehouse_id) < item.quantity:
            raise HTTPException(status_code=409, detail="Source stock is no longer sufficient")
        transaction = InventoryTransaction(
            part_id=item.part_id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=item.quantity,
            from_warehouse_id=item.source_warehouse_id,
            work_order_id=item.work_order_id,
            replenishment_request_id=item.id,
            movement_stage="ship",
            user_id=actor.user_id,
            unit_cost=part.default_cost,
            notes=f"Replenishment #{item.id} shipped",
        )
        db.add(transaction)
        db.flush()
        transaction_id = transaction.id
        item.shipment_transaction_id = transaction.id
        item.shipped_by = actor.user_id
        item.shipped_at = now

    elif payload.action == "receive":
        if item.status != "shipped":
            raise HTTPException(status_code=409, detail="Only shipped replenishments can be received")
        destination = db.get(Warehouse, item.destination_warehouse_id)
        if not destination:
            raise HTTPException(status_code=404, detail="Destination warehouse not found")
        current_target = _validate_replenishment_destination(db, destination)
        if current_target != item.target_user_id:
            raise HTTPException(status_code=409, detail="Destination custody changed after shipment; warehouse reconciliation is required")
        if item.target_user_id is not None:
            if actor.role != UserRole.ENGINEER or actor.user_id != item.target_user_id:
                raise HTTPException(status_code=403, detail="Only the destination engineer can receive this shipment")
            require_bound_device(actor)
            if destination.assigned_user_id != actor.user_id:
                raise HTTPException(status_code=409, detail="Destination van is no longer assigned to this engineer")
            _require_account_reauthentication(db, actor, payload.account_password)
        elif not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
        shipment_transaction = (
            db.get(InventoryTransaction, item.shipment_transaction_id)
            if item.shipment_transaction_id
            else None
        )
        if (
            not shipment_transaction
            or shipment_transaction.replenishment_request_id != item.id
            or shipment_transaction.movement_stage != "ship"
            or shipment_transaction.transaction_type != TransactionType.OUTBOUND
            or shipment_transaction.part_id != item.part_id
            or shipment_transaction.quantity != item.quantity
            or shipment_transaction.from_warehouse_id != item.source_warehouse_id
        ):
            raise HTTPException(status_code=409, detail="Shipment ledger is incomplete; warehouse reconciliation is required")
        part = db.scalar(select(Part).where(Part.id == item.part_id).with_for_update())
        if not part:
            raise HTTPException(status_code=404, detail="Part not found")
        transaction = InventoryTransaction(
            part_id=item.part_id,
            transaction_type=TransactionType.INBOUND,
            quantity=item.quantity,
            to_warehouse_id=item.destination_warehouse_id,
            work_order_id=item.work_order_id,
            replenishment_request_id=item.id,
            movement_stage="receive",
            user_id=actor.user_id,
            unit_cost=shipment_transaction.unit_cost,
            notes=f"Replenishment #{item.id} received",
        )
        db.add(transaction)
        db.flush()
        transaction_id = transaction.id
        item.receipt_transaction_id = transaction.id
        item.received_by = actor.user_id
        item.received_device_id = actor.device_record_id
        item.received_at = now

    elif payload.action == "complete":
        if not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
        if item.status != "received" or item.receipt_transaction_id is None:
            raise HTTPException(status_code=409, detail="Only a received shipment can be completed")
        receipt_transaction = db.get(InventoryTransaction, item.receipt_transaction_id)
        if (
            not receipt_transaction
            or receipt_transaction.replenishment_request_id != item.id
            or receipt_transaction.movement_stage != "receive"
            or receipt_transaction.transaction_type != TransactionType.INBOUND
            or receipt_transaction.part_id != item.part_id
            or receipt_transaction.quantity != item.quantity
            or receipt_transaction.to_warehouse_id != item.destination_warehouse_id
        ):
            raise HTTPException(status_code=409, detail="Receipt ledger is incomplete; warehouse reconciliation is required")
        item.completed_by = actor.user_id
        item.completed_at = now
        if item.notification_id:
            notification = db.get(InventoryNotification, item.notification_id)
            if notification:
                notification.status = "resolved"

    else:
        if not warehouse_operator:
            raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
        if item.status not in {"requested", "picking"}:
            raise HTTPException(status_code=409, detail="Only requested or picking replenishments can be cancelled")
        if not payload.reason or len(payload.reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="Cancellation reason must be at least 3 characters")
        item.cancelled_by = actor.user_id
        item.cancelled_at = now
        item.cancellation_reason = payload.reason.strip()
        if item.notification_id:
            notification = db.get(InventoryNotification, item.notification_id)
            if notification:
                notification.status = "resolved"

    if payload.action == "approve":
        item.status = "requested"
    else:
        item.status = target_status
        item.version += 1
    db.add(item)
    _audit(
        db,
        actor,
        f"replenishment_{payload.action}",
        "replenishment_request",
        item.id,
        {
            "from_status": previous_status,
            "to_status": target_status,
            "previous_version": payload.expected_version,
            "new_version": item.version,
            "part_id": item.part_id,
            "quantity": item.quantity,
            "source_warehouse_id": item.source_warehouse_id,
            "destination_warehouse_id": item.destination_warehouse_id,
            "target_user_id": item.target_user_id,
            "inventory_transaction_id": transaction_id,
            "approval_status": item.approval_status,
            "reason": item.rejection_reason if payload.action == "reject" else None,
        },
    )
    db.commit()
    db.refresh(item)
    return _replenishment_read_for_actor(db, actor, item)


@router.patch(
    "/inventory/replenishment-requests/{request_id}",
    response_model=ReplenishmentRequestRead,
    deprecated=True,
)
def update_replenishment_request(request_id: int):
    raise HTTPException(status_code=410, detail="Use the authenticated replenishment action endpoint")


def _validate_vehicle_return_warehouses(
    db: Session,
    source: Warehouse,
    destination: Warehouse,
    engineer_id: int,
) -> None:
    if not source.is_active or not warehouse_is_vehicle(db, source):
        raise HTTPException(status_code=409, detail="Return source must be an active engineer vehicle")
    if source.assigned_user_id != engineer_id:
        raise HTTPException(status_code=403, detail="Return source is not assigned to this engineer")
    if not destination.is_active or warehouse_is_vehicle(db, destination):
        raise HTTPException(status_code=409, detail="Return destination must be an active non-vehicle warehouse")
    if source.id == destination.id:
        raise HTTPException(status_code=400, detail="Return source and destination must be different")


def _vehicle_return_read_for_actor(
    db: Session,
    actor: Actor,
    item: VehicleReturnRequest,
) -> VehicleReturnRequestRead:
    payload = VehicleReturnRequestRead.model_validate(item).model_dump()
    part = db.get(Part, item.part_id)
    source = db.get(Warehouse, item.source_warehouse_id)
    destination = db.get(Warehouse, item.destination_warehouse_id)
    requested_device = db.get(UserDevice, item.requested_device_id)
    shipped_device = db.get(UserDevice, item.shipped_device_id) if item.shipped_device_id else None

    def user_name(user_id: int | None) -> str | None:
        user = db.get(User, user_id) if user_id else None
        return user.name if user else None

    warehouse_operator = actor.role in {UserRole.ADMIN, UserRole.WAREHOUSE}
    is_engineer_owner = bool(actor.role == UserRole.ENGINEER and actor.user_id == item.engineer_id)
    payload.update(
        part_number=part.part_number if part else None,
        part_name=part.name if part else None,
        source_warehouse_name=source.name if source else None,
        destination_warehouse_name=destination.name if destination else None,
        engineer_name=user_name(item.engineer_id),
        requested_by_name=user_name(item.requested_by),
        requested_device_name=requested_device.device_name if requested_device else None,
        approved_by_name=user_name(item.approved_by),
        shipped_by_name=user_name(item.shipped_by),
        shipped_device_name=shipped_device.device_name if shipped_device else None,
        received_by_name=user_name(item.received_by),
        cancelled_by_name=user_name(item.cancelled_by),
        source_quantity=get_stock_quantity(db, item.part_id, item.source_warehouse_id),
        destination_quantity=get_stock_quantity(db, item.part_id, item.destination_warehouse_id),
        can_approve=warehouse_operator and item.status == "requested",
        can_ship=is_engineer_owner and actor.device_verified and item.status == "approved",
        can_receive=warehouse_operator and item.status == "shipped",
        can_cancel=(warehouse_operator or is_engineer_owner) and item.status in {"requested", "approved"},
    )
    return VehicleReturnRequestRead(**payload)


@router.get("/inventory/vehicle-return-destinations", response_model=list[WarehouseRead])
def vehicle_return_destinations(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    rows = db.scalars(select(Warehouse).where(Warehouse.is_active.is_(True)).order_by(Warehouse.name)).all()
    return [warehouse for warehouse in rows if not warehouse_is_vehicle(db, warehouse)]


@router.post("/inventory/vehicle-returns", response_model=VehicleReturnRequestRead)
def create_vehicle_return_request(
    payload: VehicleReturnRequestCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ENGINEER or actor.user_id is None:
        raise HTTPException(status_code=403, detail="Only an engineer can request a vehicle return")
    require_bound_device(actor)
    client_request_id = payload.client_request_id.strip()
    reason = payload.reason.strip()
    if len(reason) < 3:
        raise HTTPException(status_code=422, detail="Return reason must be at least 3 non-whitespace characters")

    def matches_existing(candidate: VehicleReturnRequest) -> bool:
        return (
            candidate.part_id == payload.part_id
            and candidate.source_warehouse_id == payload.source_warehouse_id
            and candidate.destination_warehouse_id == payload.destination_warehouse_id
            and candidate.quantity == payload.quantity
            and candidate.reason == reason
            and candidate.engineer_id == actor.user_id
        )

    existing = db.scalar(
        select(VehicleReturnRequest).where(VehicleReturnRequest.client_request_id == client_request_id)
    )
    if existing:
        if not matches_existing(existing):
            raise HTTPException(status_code=409, detail="client_request_id was already used for another return")
        return _vehicle_return_read_for_actor(db, actor, existing)

    part = db.get(Part, payload.part_id)
    source = db.get(Warehouse, payload.source_warehouse_id)
    destination = db.get(Warehouse, payload.destination_warehouse_id)
    if not part:
        raise HTTPException(status_code=404, detail="Part not found")
    if not source or not destination:
        raise HTTPException(status_code=404, detail="Return warehouse not found")
    _validate_vehicle_return_warehouses(db, source, destination, actor.user_id)
    if get_stock_quantity(db, part.id, source.id) < payload.quantity:
        raise HTTPException(status_code=409, detail="Vehicle stock is insufficient for this return")

    item = VehicleReturnRequest(
        client_request_id=client_request_id,
        part_id=part.id,
        source_warehouse_id=source.id,
        destination_warehouse_id=destination.id,
        engineer_id=actor.user_id,
        quantity=payload.quantity,
        reason=reason,
        requested_by=actor.user_id,
        requested_device_id=actor.device_record_id,
    )
    try:
        db.add(item)
        db.flush()
        _audit(
            db,
            actor,
            "vehicle_return_requested",
            "vehicle_return_request",
            item.id,
            {
                "part_id": item.part_id,
                "quantity": item.quantity,
                "source_warehouse_id": item.source_warehouse_id,
                "destination_warehouse_id": item.destination_warehouse_id,
                "engineer_id": item.engineer_id,
                "client_request_id": item.client_request_id,
                "reason": item.reason,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(VehicleReturnRequest).where(VehicleReturnRequest.client_request_id == client_request_id)
        )
        if existing and matches_existing(existing):
            return _vehicle_return_read_for_actor(db, actor, existing)
        if existing:
            raise HTTPException(status_code=409, detail="client_request_id was already used for another return")
        raise HTTPException(status_code=409, detail="Vehicle return request could not be created") from exc
    db.refresh(item)
    return _vehicle_return_read_for_actor(db, actor, item)


@router.get("/inventory/vehicle-returns", response_model=list[VehicleReturnRequestRead])
def list_vehicle_return_requests(
    status: str | None = Query(default=None, pattern="^(requested|approved|shipped|received|cancelled)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE, UserRole.ENGINEER)
    stmt = select(VehicleReturnRequest).order_by(VehicleReturnRequest.id.desc())
    if actor.role == UserRole.ENGINEER:
        stmt = stmt.where(VehicleReturnRequest.engineer_id == actor.user_id)
    if status:
        stmt = stmt.where(VehicleReturnRequest.status == status)
    rows = db.scalars(stmt.limit(limit)).all()
    return [_vehicle_return_read_for_actor(db, actor, item) for item in rows]


@router.post("/inventory/vehicle-returns/{request_id}/actions", response_model=VehicleReturnRequestRead)
def act_on_vehicle_return_request(
    request_id: int,
    payload: VehicleReturnRequestAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    begin_inventory_write(db)
    item = db.scalar(
        select(VehicleReturnRequest)
        .where(
            VehicleReturnRequest.id == request_id,
            VehicleReturnRequest.organization_id == actor.organization_id,
        )
        .with_for_update()
    )
    if not item:
        raise HTTPException(status_code=404, detail="Vehicle return request not found")

    warehouse_operator = actor.role in {UserRole.ADMIN, UserRole.WAREHOUSE}
    engineer_owner = bool(actor.role == UserRole.ENGINEER and actor.user_id == item.engineer_id)
    target_status = {
        "approve": "approved",
        "ship": "shipped",
        "receive": "received",
        "cancel": "cancelled",
    }[payload.action]
    if payload.action in {"approve", "receive"} and not warehouse_operator:
        raise HTTPException(status_code=403, detail="Warehouse or administrator access required")
    if payload.action == "ship":
        if not engineer_owner:
            raise HTTPException(status_code=403, detail="Only the vehicle owner can hand over this return")
        require_bound_device(actor)
        if item.status == "shipped" and item.shipped_device_id != actor.device_record_id:
            raise HTTPException(status_code=403, detail="Return was handed over on another registered device")
    if payload.action == "cancel" and not (warehouse_operator or engineer_owner):
        raise HTTPException(status_code=403, detail="Only the vehicle owner or warehouse can cancel this return")
    if item.status == target_status:
        return _vehicle_return_read_for_actor(db, actor, item)
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Vehicle return changed; refresh before continuing")

    part = db.scalar(select(Part).where(Part.id == item.part_id).with_for_update())
    source = db.get(Warehouse, item.source_warehouse_id)
    destination = db.get(Warehouse, item.destination_warehouse_id)
    if not part or not source or not destination:
        raise HTTPException(status_code=409, detail="Return inventory references are incomplete")

    previous_status = item.status
    transaction_id: int | None = None
    now = datetime.utcnow()
    if payload.action == "approve":
        if item.status != "requested":
            raise HTTPException(status_code=409, detail="Only a requested return can be approved")
        _validate_vehicle_return_warehouses(db, source, destination, item.engineer_id)
        if get_available_stock_quantity(db, item.part_id, item.source_warehouse_id) < item.quantity:
            raise HTTPException(status_code=409, detail="Vehicle stock is no longer available for approval")
        item.approved_by = actor.user_id
        item.approved_at = now

    elif payload.action == "ship":
        if item.status != "approved":
            raise HTTPException(status_code=409, detail="Only an approved return can be handed over")
        _validate_vehicle_return_warehouses(db, source, destination, item.engineer_id)
        if source.assigned_user_id != actor.user_id:
            raise HTTPException(status_code=409, detail="Vehicle assignment changed after approval")
        _require_account_reauthentication(db, actor, payload.account_password)
        if get_stock_quantity(db, item.part_id, item.source_warehouse_id) < item.quantity:
            raise HTTPException(status_code=409, detail="Vehicle stock is insufficient for handover")
        transaction = InventoryTransaction(
            part_id=item.part_id,
            transaction_type=TransactionType.OUTBOUND,
            quantity=item.quantity,
            from_warehouse_id=item.source_warehouse_id,
            vehicle_return_request_id=item.id,
            movement_stage="return_ship",
            user_id=actor.user_id,
            unit_cost=part.default_cost,
            notes=f"Vehicle return #{item.id} handed over",
        )
        db.add(transaction)
        db.flush()
        transaction_id = transaction.id
        item.shipment_transaction_id = transaction.id
        item.shipped_by = actor.user_id
        item.shipped_device_id = actor.device_record_id
        item.shipped_at = now

    elif payload.action == "receive":
        if item.status != "shipped":
            raise HTTPException(status_code=409, detail="Only a handed-over return can be received")
        if not destination.is_active or warehouse_is_vehicle(db, destination):
            raise HTTPException(status_code=409, detail="Return destination is no longer an active warehouse")
        shipment = db.get(InventoryTransaction, item.shipment_transaction_id) if item.shipment_transaction_id else None
        if (
            not shipment
            or shipment.vehicle_return_request_id != item.id
            or shipment.movement_stage != "return_ship"
            or shipment.transaction_type != TransactionType.OUTBOUND
            or shipment.part_id != item.part_id
            or shipment.quantity != item.quantity
            or shipment.from_warehouse_id != item.source_warehouse_id
        ):
            raise HTTPException(status_code=409, detail="Return shipment ledger is incomplete")
        transaction = InventoryTransaction(
            part_id=item.part_id,
            transaction_type=TransactionType.INBOUND,
            quantity=item.quantity,
            to_warehouse_id=item.destination_warehouse_id,
            vehicle_return_request_id=item.id,
            movement_stage="return_receive",
            user_id=actor.user_id,
            unit_cost=shipment.unit_cost,
            notes=f"Vehicle return #{item.id} received",
        )
        db.add(transaction)
        db.flush()
        transaction_id = transaction.id
        item.receipt_transaction_id = transaction.id
        item.received_by = actor.user_id
        item.received_at = now

    else:
        if item.status not in {"requested", "approved"}:
            raise HTTPException(status_code=409, detail="Only requested or approved returns can be cancelled")
        if not payload.reason or len(payload.reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="Cancellation reason must be at least 3 characters")
        item.cancelled_by = actor.user_id
        item.cancelled_at = now
        item.cancellation_reason = payload.reason.strip()

    item.status = target_status
    item.version += 1
    _audit(
        db,
        actor,
        f"vehicle_return_{payload.action}",
        "vehicle_return_request",
        item.id,
        {
            "from_status": previous_status,
            "to_status": target_status,
            "previous_version": payload.expected_version,
            "new_version": item.version,
            "part_id": item.part_id,
            "quantity": item.quantity,
            "source_warehouse_id": item.source_warehouse_id,
            "destination_warehouse_id": item.destination_warehouse_id,
            "engineer_id": item.engineer_id,
            "inventory_transaction_id": transaction_id,
            "reason": item.cancellation_reason if payload.action == "cancel" else None,
        },
    )
    db.commit()
    db.refresh(item)
    return _vehicle_return_read_for_actor(db, actor, item)


def _inventory_count_quantity(db: Session, item: InventoryCountSession, part_id: int) -> int:
    if item.location_id is not None:
        return get_location_stock_quantity(db, part_id, item.location_id)
    return get_stock_quantity(db, part_id, item.warehouse_id)


def _inventory_count_read(db: Session, actor: Actor, item: InventoryCountSession) -> InventoryCountRead:
    warehouse = db.get(Warehouse, item.warehouse_id)
    location = db.get(StorageLocation, item.location_id) if item.location_id else None
    rows = db.scalars(
        select(InventoryCountLine).where(InventoryCountLine.session_id == item.id).order_by(InventoryCountLine.id)
    ).all()
    lines = []
    for row in rows:
        part = db.get(Part, row.part_id)
        lines.append(InventoryCountLineRead(
            id=row.id, part_id=row.part_id, part_number=part.part_number if part else None,
            part_name=part.name if part else None, counted_quantity=row.counted_quantity,
            submitted_book_quantity=row.submitted_book_quantity,
            approved_book_quantity=row.approved_book_quantity, variance_quantity=row.variance_quantity,
            counted_by=row.counted_by, counted_at=row.counted_at,
            adjustment_transaction_id=row.adjustment_transaction_id, notes=row.notes,
        ))
    operator = actor.role in {UserRole.ADMIN, UserRole.WAREHOUSE}
    return InventoryCountRead(
        id=item.id, client_request_id=item.client_request_id, warehouse_id=item.warehouse_id,
        warehouse_name=warehouse.name if warehouse else None, location_id=item.location_id,
        location_code=location.code if location else None, title=item.title, notes=item.notes,
        status=item.status, version=item.version, created_by=item.created_by,
        submitted_by=item.submitted_by, submitted_at=item.submitted_at,
        approved_by=item.approved_by, approved_at=item.approved_at,
        cancelled_by=item.cancelled_by, cancelled_at=item.cancelled_at,
        cancellation_reason=item.cancellation_reason, lines=lines,
        can_edit=operator and item.status == "draft",
        can_submit=operator and item.status == "draft" and bool(lines),
        can_approve=actor.role == UserRole.ADMIN and item.status == "submitted",
        can_cancel=operator and item.status == "draft" or actor.role == UserRole.ADMIN and item.status == "submitted",
        created_at=item.created_at, updated_at=item.updated_at,
    )


@router.post("/inventory/counts", response_model=InventoryCountRead)
def create_inventory_count(
    payload: InventoryCountCreate,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.WAREHOUSE)
    client_request_id = payload.client_request_id.strip()
    title = payload.title.strip()
    if len(client_request_id) < 8:
        raise HTTPException(status_code=422, detail="client_request_id must contain at least 8 non-whitespace characters")
    if len(title) < 3:
        raise HTTPException(status_code=422, detail="Count title must contain at least 3 non-whitespace characters")
    existing = db.scalar(select(InventoryCountSession).where(
        InventoryCountSession.client_request_id == client_request_id
    ))
    if existing:
        if (existing.warehouse_id, existing.location_id, existing.title) != (
            payload.warehouse_id, payload.location_id, title
        ):
            raise HTTPException(status_code=409, detail="client_request_id was already used for another count")
        return _inventory_count_read(db, actor, existing)
    warehouse = db.get(Warehouse, payload.warehouse_id)
    if not warehouse or not warehouse.is_active:
        raise HTTPException(status_code=404, detail="Active warehouse not found")
    if warehouse_is_vehicle(db, warehouse):
        raise HTTPException(status_code=409, detail="Vehicle stock requires an engineer-owned count workflow")
    location = db.get(StorageLocation, payload.location_id) if payload.location_id else None
    if location and (not location.is_active or location.warehouse_id != warehouse.id):
        raise HTTPException(status_code=400, detail="Active location does not belong to warehouse")
    item = InventoryCountSession(
        client_request_id=client_request_id, warehouse_id=warehouse.id,
        location_id=location.id if location else None, title=title, notes=payload.notes,
        created_by=actor.user_id,
    )
    try:
        db.add(item)
        db.flush()
        _audit(db, actor, "inventory_count_created", "inventory_count", item.id, {
            "warehouse_id": item.warehouse_id, "location_id": item.location_id, "title": item.title,
        })
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(InventoryCountSession).where(
            InventoryCountSession.client_request_id == client_request_id
        ))
        if existing and (existing.warehouse_id, existing.location_id, existing.title) == (
            payload.warehouse_id, payload.location_id, title
        ):
            return _inventory_count_read(db, actor, existing)
        raise HTTPException(status_code=409, detail="Inventory count could not be created") from exc
    db.refresh(item)
    return _inventory_count_read(db, actor, item)


@router.get("/inventory/counts", response_model=list[InventoryCountRead])
def list_inventory_counts(
    status: str | None = Query(default=None, pattern="^(draft|submitted|approved|cancelled)$"),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    stmt = select(InventoryCountSession).order_by(InventoryCountSession.id.desc())
    if status:
        stmt = stmt.where(InventoryCountSession.status == status)
    return [_inventory_count_read(db, actor, item) for item in db.scalars(stmt.limit(limit)).all()]


@router.put("/inventory/counts/{count_id}/lines", response_model=InventoryCountRead)
def upsert_inventory_count_line(
    count_id: int,
    payload: InventoryCountLineUpsert,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.WAREHOUSE)
    begin_inventory_write(db)
    item = db.scalar(select(InventoryCountSession).where(
        InventoryCountSession.id == count_id,
        InventoryCountSession.organization_id == actor.organization_id,
    ).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Inventory count not found")
    if item.status != "draft" or item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Count is no longer editable; refresh before continuing")
    if not db.get(Part, payload.part_id):
        raise HTTPException(status_code=404, detail="Part not found")
    line = db.scalar(select(InventoryCountLine).where(
        InventoryCountLine.session_id == item.id, InventoryCountLine.part_id == payload.part_id
    ))
    if line:
        previous = line.counted_quantity
        line.counted_quantity = payload.counted_quantity
        line.notes = payload.notes
        line.counted_by = actor.user_id
        line.counted_at = datetime.utcnow()
    else:
        previous = None
        line = InventoryCountLine(session_id=item.id, part_id=payload.part_id,
            counted_quantity=payload.counted_quantity, notes=payload.notes, counted_by=actor.user_id)
        db.add(line)
    item.version += 1
    db.flush()
    _audit(db, actor, "inventory_count_line_recorded", "inventory_count", item.id, {
        "line_id": line.id, "part_id": line.part_id, "previous_quantity": previous,
        "counted_quantity": line.counted_quantity, "new_version": item.version,
    })
    db.commit()
    db.refresh(item)
    return _inventory_count_read(db, actor, item)


@router.post("/inventory/counts/{count_id}/actions", response_model=InventoryCountRead)
def act_on_inventory_count(
    count_id: int,
    payload: InventoryCountAction,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.WAREHOUSE)
    begin_inventory_write(db)
    item = db.scalar(select(InventoryCountSession).where(
        InventoryCountSession.id == count_id,
        InventoryCountSession.organization_id == actor.organization_id,
    ).with_for_update())
    if not item:
        raise HTTPException(status_code=404, detail="Inventory count not found")
    if item.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Inventory count changed; refresh before continuing")
    now = datetime.utcnow()
    previous_status = item.status
    lines = db.scalars(select(InventoryCountLine).where(InventoryCountLine.session_id == item.id)).all()
    if payload.action == "submit":
        if item.status != "draft" or not lines:
            raise HTTPException(status_code=409, detail="Only a non-empty draft count can be submitted")
        for line in lines:
            line.submitted_book_quantity = _inventory_count_quantity(db, item, line.part_id)
        item.status, item.submitted_by, item.submitted_at = "submitted", actor.user_id, now
    elif payload.action == "approve":
        if actor.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Administrator approval is required to adjust inventory")
        if item.status != "submitted":
            raise HTTPException(status_code=409, detail="Only a submitted count can be approved")
        _require_account_reauthentication(db, actor, payload.password)
        for line in lines:
            part = db.scalar(select(Part).where(Part.id == line.part_id).with_for_update())
            if not part:
                raise HTTPException(status_code=409, detail="Counted part no longer exists")
            book = _inventory_count_quantity(db, item, line.part_id)
            variance = line.counted_quantity - book
            line.approved_book_quantity, line.variance_quantity = book, variance
            if variance:
                tx = InventoryTransaction(
                    part_id=line.part_id, transaction_type=TransactionType.ADJUSTMENT,
                    quantity=abs(variance),
                    from_warehouse_id=item.warehouse_id if variance < 0 else None,
                    to_warehouse_id=item.warehouse_id if variance > 0 else None,
                    from_location_id=item.location_id if variance < 0 else None,
                    to_location_id=item.location_id if variance > 0 else None,
                    inventory_count_line_id=line.id, user_id=actor.user_id,
                    unit_cost=part.default_cost, notes=f"Approved inventory count #{item.id}",
                )
                db.add(tx)
                db.flush()
                line.adjustment_transaction_id = tx.id
        item.status, item.approved_by, item.approved_at = "approved", actor.user_id, now
    else:
        allowed = item.status == "draft" or actor.role == UserRole.ADMIN and item.status == "submitted"
        if not allowed:
            raise HTTPException(status_code=409, detail="This inventory count cannot be cancelled")
        if not payload.reason or len(payload.reason.strip()) < 3:
            raise HTTPException(status_code=422, detail="Cancellation reason must be at least 3 characters")
        item.status, item.cancelled_by, item.cancelled_at = "cancelled", actor.user_id, now
        item.cancellation_reason = payload.reason.strip()
    item.version += 1
    _audit(db, actor, f"inventory_count_{payload.action}", "inventory_count", item.id, {
        "from_status": previous_status, "to_status": item.status, "line_count": len(lines),
        "previous_version": payload.expected_version, "new_version": item.version,
        "warehouse_id": item.warehouse_id, "location_id": item.location_id,
        "reason": item.cancellation_reason if payload.action == "cancel" else None,
    })
    db.commit()
    db.refresh(item)
    return _inventory_count_read(db, actor, item)


@router.get("/work-orders/{work_order_id}/part-recommendations", response_model=list[WorkOrderPartRecommendation])
def work_order_part_recommendations(
    work_order_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_work_order_scope(db, actor, work_order_id)
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    consume_monthly_usage(db, actor.organization_id, ai_requests=1)
    result = build_part_recommendations(db, work_order)
    db.commit()
    return result


@router.get("/work-order-parts", response_model=list[WorkOrderPartRead])
def list_work_order_parts(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(WorkOrderPart).order_by(WorkOrderPart.id.desc())
    if work_order_id is not None:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(WorkOrderPart.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER and actor.user_id:
        stmt = stmt.where(WorkOrderPart.user_id == actor.user_id)
    elif actor.role not in {UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE}:
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/qc-pictures", response_model=QCPictureRead)
def create_qc_picture(
    payload: QCPictureCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    work_order = require_work_order_execution_scope(db, actor, payload.work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")
    if work_order.is_locked or work_order.status == "PENDING_APPROVAL":
        raise HTTPException(status_code=400, detail="Work order cannot accept more photos in its current state")
    payload.uploaded_by = actor.user_id
    item = QCPicture(**payload.model_dump())
    db.add(item)
    _audit(db, actor, "upload_qc_picture", "qc_picture", None, {"work_order_id": payload.work_order_id})
    db.commit()
    db.refresh(item)
    return item


@router.get("/qc-pictures", response_model=list[QCPictureRead])
def list_qc_pictures(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(QCPicture).order_by(QCPicture.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(QCPicture.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/job-status", response_model=JobStatusRead)
def create_job_status(
    payload: JobStatusCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    work_order = require_work_order_execution_scope(db, actor, payload.work_order_id)
    if work_order and (work_order.is_locked or work_order.status == "PENDING_APPROVAL"):
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")
    if payload.status.strip().upper() in {"COMPLETED", "PENDING_APPROVAL", "APPROVAL_REJECTED"}:
        raise HTTPException(status_code=400, detail="Reserved status requires the completion workflow")
    data = payload.model_dump()
    if not data.get("timestamp"):
        data["timestamp"] = datetime.utcnow()
    item = JobStatus(**data)
    db.add(item)
    _audit(db, actor, "update_status", "job_status", None, {"work_order_id": payload.work_order_id, "status": data.get("status")})
    db.commit()
    db.refresh(item)
    return item


@router.get("/job-status", response_model=list[JobStatusRead])
def list_job_status(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(JobStatus).order_by(JobStatus.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(JobStatus.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.post("/return-equipments", response_model=ReturnEquipmentRead)
def create_return_equipment(
    payload: ReturnEquipmentCreate, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    work_order = require_work_order_execution_scope(db, actor, payload.work_order_id)
    if work_order and (work_order.is_locked or work_order.status == "PENDING_APPROVAL"):
        raise HTTPException(status_code=400, detail="Work order is locked and cannot be edited")
    item = ReturnEquipment(**payload.model_dump())
    db.add(item)
    _audit(
        db,
        actor,
        "return_equipment",
        "return_equipment",
        None,
        {"work_order_id": payload.work_order_id, "equipment_type": payload.equipment_type, "quantity": payload.quantity},
    )
    db.commit()
    db.refresh(item)
    return item


@router.get("/return-equipments", response_model=list[ReturnEquipmentRead])
def list_return_equipments(
    work_order_id: int | None = Query(default=None, ge=1),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    stmt = select(ReturnEquipment).order_by(ReturnEquipment.id.desc())
    if work_order_id:
        require_work_order_scope(db, actor, work_order_id)
        stmt = stmt.where(ReturnEquipment.work_order_id == work_order_id)
    elif actor.role == UserRole.ENGINEER:
        raise HTTPException(status_code=403, detail="work_order_id is required for technician scope")
    return db.scalars(stmt.offset(skip).limit(limit)).all()


@router.get("/work-orders/{work_order_id}/profit", response_model=WorkOrderProfit)
def work_order_profit(work_order_id: int, db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_permission(actor, REPORTS_READ)
    work_order = db.get(WorkOrder, work_order_id)
    if not work_order:
        raise HTTPException(status_code=404, detail="Work order not found")

    parts_cost = get_work_order_parts_cost(db, work_order_id)
    return WorkOrderProfit(
        work_order_id=work_order_id,
        ticket_number=work_order.ticket_number,
        wo_number=work_order.wo_number,
        revenue=work_order.revenue,
        labor_cost=work_order.labor_cost,
        parts_cost=parts_cost,
        profit=work_order.revenue - work_order.labor_cost - parts_cost,
    )


@router.get("/export/inventory.xlsx")
def export_inventory_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    balances = get_stock_balances(db)
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory Balance"
    ws.append(["Part ID", "Part Number", "Part Name", "Warehouse ID", "Warehouse", "Quantity", "Safety Stock", "Low Stock"])
    for row in balances:
        ws.append([
            row.part_id,
            row.part_number,
            row.part_name,
            row.warehouse_id,
            row.warehouse_name,
            row.quantity,
            row.safety_stock,
            "YES" if row.is_low_stock else "NO",
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=inventory.xlsx"},
    )


@router.get("/export/parts.xlsx")
def export_parts_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = db.scalars(select(Part).order_by(Part.id.asc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "Parts"
    ws.append(["part_number", "name", "unit", "default_cost", "safety_stock", "supplier", "notes"])
    for row in rows:
        ws.append([row.part_number, row.name, row.unit, row.default_cost, row.safety_stock, row.supplier, row.notes])

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=parts.xlsx"},
    )


@router.post("/imports/parts/preview", response_model=ImportBatchRead)
async def preview_parts_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    content = await file.read(settings.max_import_upload_bytes + 1)
    if len(content) > settings.max_import_upload_bytes:
        raise HTTPException(status_code=413, detail="Import file exceeds the configured upload limit")

    file_hash = sha256(content).hexdigest()
    existing_batch = db.scalar(
        select(ImportBatch)
        .where(ImportBatch.import_type == "parts", ImportBatch.file_sha256 == file_hash)
        .order_by(ImportBatch.id.desc())
    )
    if existing_batch:
        return _import_batch_read(existing_batch)

    try:
        workbook = load_workbook(filename=BytesIO(content), data_only=True, read_only=True)
        worksheet = workbook.active
        raw_headers = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded workbook could not be read") from exc
    if not raw_headers:
        raise HTTPException(status_code=400, detail="The workbook is empty")

    headers = [_normalize_import_header(value) for value in raw_headers]
    if len(set(filter(None, headers))) != len(list(filter(None, headers))):
        raise HTTPException(status_code=400, detail="The workbook contains duplicate column names")
    missing = [field for field in ("part_number", "name") if field not in headers]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing)}")

    field_indexes = {field: headers.index(field) for field in PART_IMPORT_FIELDS if field in headers}
    custom_indexes = {header: index for index, header in enumerate(headers) if header.startswith("custom_")}
    normalized_rows: list[dict] = []
    errors: list[dict] = []
    seen_numbers: set[str] = set()
    seen_barcodes: set[str] = set()
    total_rows = 0
    for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not any(value not in (None, "") for value in row):
            continue
        total_rows += 1
        values = {field: row[index] if index < len(row) else None for field, index in field_indexes.items()}
        custom_fields = {
            field.removeprefix("custom_"): row[index]
            for field, index in custom_indexes.items()
            if index < len(row) and row[index] not in (None, "")
        }
        part_number = str(values.get("part_number") or "").strip()
        name = str(values.get("name") or "").strip()
        row_errors: list[str] = []
        if not part_number:
            row_errors.append("part_number is required")
        if not name:
            row_errors.append("name is required")
        if part_number and part_number in seen_numbers:
            row_errors.append("duplicate part_number in file")
        if part_number:
            seen_numbers.add(part_number)
        barcode = str(values.get("barcode") or "").strip() or None
        if barcode and barcode in seen_barcodes:
            row_errors.append("duplicate barcode in file")
        if barcode:
            seen_barcodes.add(barcode)
            barcode_owner = db.scalar(select(Part).where(Part.barcode == barcode))
            if barcode_owner and barcode_owner.part_number != part_number:
                row_errors.append("barcode already belongs to another item")
        tracking_mode = str(values.get("tracking_mode") or "none").strip().lower()
        if tracking_mode not in {"none", "batch", "serial"}:
            row_errors.append("tracking_mode must be none, batch, or serial")
        try:
            default_cost = _parse_non_negative_number(values.get("default_cost"), float, "default_cost")
            safety_stock = _parse_non_negative_number(values.get("safety_stock"), int, "safety_stock")
            min_stock = _parse_non_negative_number(values.get("min_stock"), int, "min_stock")
        except (TypeError, ValueError) as exc:
            row_errors.append(str(exc))
            default_cost, safety_stock, min_stock = 0.0, 0, 0

        if row_errors:
            errors.append({"row": row_number, "part_number": part_number or None, "messages": row_errors})
            continue
        normalized_rows.append(
            {
                "row_number": row_number,
                "part_number": part_number,
                "name": name,
                "category": str(values.get("category") or "").strip() or None,
                "barcode": barcode,
                "item_type": str(values.get("item_type") or "stock").strip() or "stock",
                "tracking_mode": tracking_mode,
                "is_active": str(values.get("is_active") or "true").strip().lower() not in {"false", "0", "no"},
                "custom_fields": custom_fields,
                "english_name": str(values.get("english_name") or "").strip() or None,
                "machine_type": str(values.get("machine_type") or "").strip() or None,
                "unit": str(values.get("unit") or "pcs").strip() or "pcs",
                "default_cost": default_cost,
                "safety_stock": safety_stock,
                "min_stock": min_stock,
                "supplier": str(values.get("supplier") or "").strip() or None,
                "image_url": str(values.get("image_url") or "").strip() or None,
                "notes": str(values.get("notes") or "").strip() or None,
            }
        )

    part_numbers = [row["part_number"] for row in normalized_rows]
    existing_numbers = set(
        db.scalars(select(Part.part_number).where(Part.part_number.in_(part_numbers))).all()
    ) if part_numbers else set()
    batch = ImportBatch(
        import_type="parts",
        filename=Path(file.filename).name,
        file_sha256=file_hash,
        status="ready" if not errors else "invalid",
        total_rows=total_rows,
        valid_rows=len(normalized_rows),
        error_rows=len(errors),
        created_count=sum(1 for number in part_numbers if number not in existing_numbers),
        updated_count=sum(1 for number in part_numbers if number in existing_numbers),
        payload_json=json.dumps(normalized_rows, ensure_ascii=False),
        errors_json=json.dumps(errors, ensure_ascii=False),
        created_by=actor.user_id,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _import_batch_read(batch)


@router.post("/imports/parts/{batch_id}/commit", response_model=ImportBatchRead)
def commit_parts_import(
    batch_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.import_type != "parts":
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch.status == "committed":
        return _import_batch_read(batch)
    if batch.status != "ready":
        raise HTTPException(status_code=409, detail="Import batch has validation errors")

    rows = json.loads(batch.payload_json or "[]")
    created = 0
    updated = 0
    for row in rows:
        data = {key: value for key, value in row.items() if key != "row_number"}
        item = db.scalar(select(Part).where(Part.part_number == data["part_number"]))
        if item:
            for key, value in data.items():
                setattr(item, key, value)
            updated += 1
        else:
            db.add(Part(**data))
            created += 1
    batch.status = "committed"
    batch.created_count = created
    batch.updated_count = updated
    batch.committed_at = datetime.utcnow()
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _import_batch_read(batch)


@router.get("/imports/parts", response_model=list[ImportBatchRead])
def list_parts_imports(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    batches = db.scalars(
        select(ImportBatch).where(ImportBatch.import_type == "parts").order_by(ImportBatch.id.desc()).offset(skip).limit(limit)
    ).all()
    return [_import_batch_read(batch) for batch in batches]


@router.post("/imports/opening-inventory/preview", response_model=ImportBatchRead)
async def preview_opening_inventory_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")
    content = await file.read(settings.max_import_upload_bytes + 1)
    if len(content) > settings.max_import_upload_bytes:
        raise HTTPException(status_code=413, detail="Import file exceeds the configured upload limit")
    file_hash = sha256(content).hexdigest()
    existing_batch = db.scalar(
        select(ImportBatch)
        .where(ImportBatch.import_type == "opening_inventory", ImportBatch.file_sha256 == file_hash)
        .order_by(ImportBatch.id.desc())
    )
    if existing_batch:
        return _import_batch_read(existing_batch)

    try:
        workbook = load_workbook(filename=BytesIO(content), data_only=True, read_only=True)
        worksheet = workbook.active
        raw_headers = next(worksheet.iter_rows(min_row=1, max_row=1, values_only=True), None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="The uploaded workbook could not be read") from exc
    if not raw_headers:
        raise HTTPException(status_code=400, detail="The workbook is empty")
    headers = [_normalize_import_header(value) for value in raw_headers]
    missing = [field for field in ("part_number", "warehouse", "quantity") if field not in headers]
    if missing:
        raise HTTPException(status_code=400, detail=f"Missing required columns: {', '.join(missing)}")

    indexes = {field: headers.index(field) for field in ("part_number", "warehouse", "quantity", "unit_cost", "notes") if field in headers}
    parts = {part.part_number: part for part in db.scalars(select(Part)).all()}
    warehouses = {warehouse.name.strip().lower(): warehouse for warehouse in db.scalars(select(Warehouse)).all()}
    normalized_rows: list[dict] = []
    errors: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()
    total_rows = 0
    for row_number, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
        if not row or not any(value not in (None, "") for value in row):
            continue
        total_rows += 1
        values = {field: row[index] if index < len(row) else None for field, index in indexes.items()}
        part_number = str(values.get("part_number") or "").strip()
        warehouse_name = str(values.get("warehouse") or "").strip()
        part = parts.get(part_number)
        warehouse = warehouses.get(warehouse_name.lower())
        row_errors: list[str] = []
        if not part:
            row_errors.append("part_number does not exist in this organization")
        if not warehouse:
            row_errors.append("warehouse does not exist in this organization")
        elif warehouse_is_vehicle(db, warehouse):
            row_errors.append(
                "opening inventory cannot post to a vehicle; use replenishment and engineer receipt"
            )
        pair = (part_number, warehouse_name.lower())
        if part_number and warehouse_name and pair in seen_pairs:
            row_errors.append("duplicate part and warehouse in file")
        seen_pairs.add(pair)
        try:
            quantity = int(values.get("quantity"))
            if quantity <= 0:
                raise ValueError("quantity must be greater than zero")
        except (TypeError, ValueError) as exc:
            row_errors.append(str(exc) if str(exc) else "quantity must be a whole number")
            quantity = 0
        try:
            unit_cost = _parse_non_negative_number(values.get("unit_cost"), float, "unit_cost")
        except (TypeError, ValueError) as exc:
            row_errors.append(str(exc))
            unit_cost = 0.0
        if row_errors:
            errors.append({"row": row_number, "part_number": part_number or None, "messages": row_errors})
            continue
        current_quantity = get_stock_quantity(db, part.id, warehouse.id)
        normalized_rows.append(
            {
                "row_number": row_number,
                "part_id": part.id,
                "part_number": part.part_number,
                "part_name": part.name,
                "warehouse_id": warehouse.id,
                "warehouse": warehouse.name,
                "quantity": quantity,
                "current_quantity": current_quantity,
                "projected_quantity": current_quantity + quantity,
                "unit_cost": unit_cost,
                "notes": str(values.get("notes") or "").strip() or None,
            }
        )

    batch = ImportBatch(
        import_type="opening_inventory",
        filename=Path(file.filename).name,
        file_sha256=file_hash,
        status="ready" if not errors else "invalid",
        total_rows=total_rows,
        valid_rows=len(normalized_rows),
        error_rows=len(errors),
        created_count=len(normalized_rows),
        updated_count=0,
        payload_json=json.dumps(normalized_rows, ensure_ascii=False),
        errors_json=json.dumps(errors, ensure_ascii=False),
        created_by=actor.user_id,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _import_batch_read(batch)


@router.post("/imports/opening-inventory/{batch_id}/commit", response_model=ImportBatchRead)
def commit_opening_inventory_import(
    batch_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    begin_inventory_write(db)
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.import_type != "opening_inventory":
        raise HTTPException(status_code=404, detail="Import batch not found")
    if batch.status == "committed":
        return _import_batch_read(batch)
    if batch.status != "ready":
        raise HTTPException(status_code=409, detail="Import batch has validation errors")
    rows = json.loads(batch.payload_json or "[]")
    part_ids = sorted({row["part_id"] for row in rows})
    if part_ids:
        locked_parts = db.scalars(
            select(Part).where(Part.id.in_(part_ids)).order_by(Part.id).with_for_update()
        ).all()
        if len(locked_parts) != len(part_ids):
            raise HTTPException(status_code=409, detail="An opening inventory part no longer exists")
    for row in rows:
        warehouse = db.get(Warehouse, row["warehouse_id"])
        if not warehouse or warehouse_is_vehicle(db, warehouse):
            raise HTTPException(
                status_code=409,
                detail="Opening inventory can only be committed to non-vehicle warehouses",
            )
        db.add(
            InventoryTransaction(
                part_id=row["part_id"],
                transaction_type=TransactionType.INBOUND,
                quantity=row["quantity"],
                to_warehouse_id=row["warehouse_id"],
                user_id=actor.user_id,
                unit_cost=row["unit_cost"],
                notes=f"Opening inventory import #{batch.id}. {row.get('notes') or ''}".strip(),
            )
        )
    batch.status = "committed"
    batch.created_count = len(rows)
    batch.updated_count = 0
    batch.committed_at = datetime.utcnow()
    db.add(batch)
    _audit(
        db,
        actor,
        "opening_inventory_committed",
        "import_batch",
        batch.id,
        {"rows": len(rows), "warehouse_ids": sorted({row["warehouse_id"] for row in rows})},
    )
    db.commit()
    db.refresh(batch)
    return _import_batch_read(batch)


@router.get("/imports/opening-inventory", response_model=list[ImportBatchRead])
def list_opening_inventory_imports(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    batches = db.scalars(
        select(ImportBatch)
        .where(ImportBatch.import_type == "opening_inventory")
        .order_by(ImportBatch.id.desc())
        .offset(skip)
        .limit(limit)
    ).all()
    return [_import_batch_read(batch) for batch in batches]


@router.post("/import/parts.xlsx")
async def import_parts_excel(
    file: UploadFile = File(...), db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")

    content = await file.read(settings.max_import_upload_bytes + 1)
    if len(content) > settings.max_import_upload_bytes:
        raise HTTPException(status_code=413, detail="Import file exceeds the configured upload limit")
    wb = load_workbook(filename=BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    created = 0
    updated = 0

    for row_number, row in enumerate(rows, start=2):
        if not row or not row[0]:
            continue
        part_number = str(row[0]).strip()
        name = str(row[1]).strip() if row[1] else part_number
        unit = str(row[2]).strip() if row[2] else "pcs"
        default_cost = float(row[3] or 0)
        safety_stock = int(row[4] or 0)
        supplier = str(row[5]).strip() if row[5] else None
        notes = str(row[6]).strip() if row[6] else None

        item = db.scalar(select(Part).where(Part.part_number == part_number))
        if item:
            item.name = name
            item.unit = unit
            item.default_cost = default_cost
            item.safety_stock = safety_stock
            item.supplier = supplier
            item.notes = notes
            updated += 1
        else:
            db.add(
                Part(
                    part_number=part_number,
                    name=name,
                    unit=unit,
                    default_cost=default_cost,
                    safety_stock=safety_stock,
                    supplier=supplier,
                    notes=notes,
                )
            )
            created += 1
    db.commit()
    return {"created": created, "updated": updated}


@router.get("/export/work-orders.xlsx")
def export_work_orders_excel(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_permission(actor, REPORTS_READ)
    rows = db.scalars(select(WorkOrder).order_by(WorkOrder.id.asc())).all()
    wb = Workbook()
    ws = wb.active
    ws.title = "WorkOrders"
    ws.append(
        [
            "wo_number",
            "ticket_number",
            "schedule_date",
            "outlet_name",
            "job_type",
            "description",
            "address",
            "city",
            "state",
            "zip",
            "contact_phone",
            "status",
            "revenue",
            "labor_cost",
            "assigned_user_id",
            "engineer_id",
        ]
    )
    for row in rows:
        ws.append(
            [
                row.wo_number,
                row.ticket_number,
                row.schedule_date.isoformat() if row.schedule_date else None,
                row.outlet_name,
                row.job_type,
                row.description,
                row.address,
                row.city,
                row.state,
                row.zip,
                row.contact_phone,
                row.status,
                row.revenue,
                row.labor_cost,
                row.assigned_user_id,
                row.engineer_id,
            ]
        )

    output = BytesIO()
    wb.save(output)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": "attachment; filename=work-orders.xlsx"},
    )


@router.post("/import/work-orders.xlsx")
async def import_work_orders_excel(
    file: UploadFile = File(...), db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Please upload an .xlsx file")

    content = await file.read()
    wb = load_workbook(filename=BytesIO(content), data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    created = 0
    updated = 0

    for row in rows:
        if not row:
            continue
        wo_number = str(row[0]).strip() if row[0] else None
        ticket_number = str(row[1]).strip() if row[1] else None
        if not wo_number and not ticket_number:
            continue
        if not ticket_number:
            ticket_number = wo_number
        if not wo_number:
            wo_number = ticket_number

        item = db.scalar(select(WorkOrder).where(WorkOrder.ticket_number == ticket_number))
        if not item and wo_number:
            item = db.scalar(select(WorkOrder).where(WorkOrder.wo_number == wo_number))

        schedule_date = None
        if row[2]:
            if isinstance(row[2], datetime):
                schedule_date = row[2].date()
            else:
                schedule_date = datetime.fromisoformat(str(row[2])).date()

        payload = {
            "wo_number": wo_number,
            "ticket_number": ticket_number,
            "schedule_date": schedule_date,
            "outlet_name": str(row[3]).strip() if row[3] else None,
            "store_name": str(row[3]).strip() if row[3] else None,
            "job_type": str(row[4]).strip() if row[4] else None,
            "description": str(row[5]).strip() if row[5] else None,
            "problem_description": str(row[5]).strip() if row[5] else None,
            "address": str(row[6]).strip() if row[6] else None,
            "city": str(row[7]).strip() if row[7] else None,
            "state": str(row[8]).strip() if row[8] else None,
            "zip": str(row[9]).strip() if row[9] else None,
            "contact_phone": str(row[10]).strip() if row[10] else None,
            "status": str(row[11]).strip() if row[11] else "open",
            "revenue": float(row[12] or 0),
            "labor_cost": float(row[13] or 0),
            "assigned_user_id": int(row[14]) if row[14] else None,
            "engineer_id": int(row[15]) if row[15] else None,
        }
        if payload["status"].strip().upper() in {"COMPLETED", "PENDING_APPROVAL", "APPROVAL_REJECTED"}:
            raise HTTPException(status_code=400, detail=f"Row {row_number}: terminal status requires the completion workflow")
        _require_tenant_user(db, payload["assigned_user_id"], "assigned_user_id")
        _require_tenant_user(db, payload["engineer_id"], "engineer_id")
        if payload["assigned_user_id"] and not payload["engineer_id"]:
            payload["engineer_id"] = payload["assigned_user_id"]
        if payload["engineer_id"] and not payload["assigned_user_id"]:
            payload["assigned_user_id"] = payload["engineer_id"]

        if item:
            for key, value in payload.items():
                setattr(item, key, value)
            updated += 1
        else:
            db.add(WorkOrder(**payload))
            created += 1

    db.commit()
    return {"created": created, "updated": updated}


@router.get("/dashboard/engineers/{user_id}", response_model=EngineerDashboard)
def engineer_dashboard(
    user_id: int,
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    if actor.role != UserRole.ENGINEER or actor.user_id != user_id:
        require_permission(actor, REPORTS_READ)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    open_work_orders = db.scalar(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assigned_user_id == user_id,
            WorkOrder.status != "completed",
        )
    )
    completed_work_orders = db.scalar(
        select(func.count(WorkOrder.id)).where(
            WorkOrder.assigned_user_id == user_id,
            WorkOrder.status == "completed",
        )
    )
    van_inventory = get_employee_van_inventory(db, user_id)
    low_stock_items = sum(1 for item in van_inventory if item.is_low_stock)

    return EngineerDashboard(
        user_id=user.id,
        user_name=user.name,
        open_work_orders=open_work_orders or 0,
        completed_work_orders=completed_work_orders or 0,
        van_low_stock_items=low_stock_items,
        van_inventory=van_inventory,
    )


@router.get("/dashboard/admin/warehouses", response_model=AdminWarehouseDashboard)
def admin_warehouse_dashboard(
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    warehouses = db.scalars(select(Warehouse).order_by(Warehouse.id.asc())).all()
    all_balances = get_stock_balances(db)
    total_parts = db.scalar(select(func.count(Part.id))) or 0

    warehouse_rows: list[WarehouseSummary] = []
    total_low_stock = 0
    for warehouse in warehouses:
        rows = [balance for balance in all_balances if balance.warehouse_id == warehouse.id]
        low_stock_items = sum(1 for row in rows if row.is_low_stock)
        total_low_stock += low_stock_items

        warehouse_rows.append(
            WarehouseSummary(
                warehouse_id=warehouse.id,
                warehouse_name=warehouse.name,
                assigned_user_id=warehouse.assigned_user_id,
                assigned_user_name=warehouse.assigned_user.name if warehouse.assigned_user else None,
                total_sku=sum(1 for row in rows if row.quantity > 0),
                total_quantity=sum(row.quantity for row in rows),
                low_stock_items=low_stock_items,
            )
        )

    return AdminWarehouseDashboard(
        total_warehouses=len(warehouse_rows),
        total_parts=total_parts,
        total_low_stock_items=total_low_stock,
        warehouses=warehouse_rows,
    )


@router.get("/inventory/low-stock-alerts", response_model=list[LowStockAlert])
def low_stock_alerts(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER, UserRole.WAREHOUSE)
    rows = get_stock_balances(db)
    alerts = [
        LowStockAlert(
            part_id=row.part_id,
            part_number=row.part_number,
            part_name=row.part_name,
            warehouse_id=row.warehouse_id,
            warehouse_name=row.warehouse_name,
            quantity=row.quantity,
            min_stock=max(row.safety_stock, db.get(Part, row.part_id).min_stock if db.get(Part, row.part_id) else 0),
        )
        for row in rows
        if row.is_low_stock
    ]
    return alerts[skip : skip + limit]


@router.get("/reports/abnormal-usage", response_model=list[AbnormalUsageRow])
def abnormal_usage_report(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    actor: Actor = Depends(get_current_actor),
):
    require_permission(actor, REPORTS_READ)
    work_orders = db.scalars(select(WorkOrder).order_by(WorkOrder.id.asc())).all()
    if not work_orders:
        return []
    costs = sorted([get_work_order_parts_cost(db, wo.id) for wo in work_orders if get_work_order_parts_cost(db, wo.id) > 0])
    if costs:
        idx = min(len(costs) - 1, int(0.9 * (len(costs) - 1)))
        p90_cost = costs[idx]
    else:
        p90_cost = 0.0

    tech_avgs: dict[int, float] = {}
    tech_map: dict[int, list[float]] = {}
    for wo in work_orders:
        if not wo.engineer_id:
            continue
        tech_map.setdefault(wo.engineer_id, []).append(get_work_order_parts_cost(db, wo.id))
    for tech_id, arr in tech_map.items():
        tech_avgs[tech_id] = (sum(arr) / len(arr)) if arr else 0.0

    repeated_part_flags: dict[int, set[int]] = {}
    usage_rows = db.scalars(select(WorkOrderPart).order_by(WorkOrderPart.created_at.asc())).all()
    for row in usage_rows:
        if not row.user_id:
            continue
        repeated_part_flags.setdefault(row.user_id, set())
        # repeated same part usage in short period (7 days)
        recent_count = sum(
            1
            for r in usage_rows
            if r.user_id == row.user_id
            and r.part_id == row.part_id
            and r.created_at >= (row.created_at - timedelta(days=7))
            and r.created_at <= row.created_at
        )
        if recent_count >= 3:
            repeated_part_flags[row.user_id].add(row.work_order_id)

    results: list[AbnormalUsageRow] = []
    for wo in work_orders:
        parts_cost = get_work_order_parts_cost(db, wo.id)
        reasons: list[str] = []
        if parts_cost >= p90_cost and parts_cost > 0:
            reasons.append("Parts cost above 90th percentile")
        if wo.engineer_id and tech_avgs.get(wo.engineer_id, 0) > 0 and parts_cost > tech_avgs[wo.engineer_id] * 1.8:
            reasons.append("Technician parts usage above historical average")
        if wo.engineer_id and wo.id in repeated_part_flags.get(wo.engineer_id, set()):
            reasons.append("Repeated same-part usage in short period")
        if reasons:
            results.append(
                AbnormalUsageRow(
                    work_order_id=wo.id,
                    ticket_number=wo.ticket_number,
                    engineer_id=wo.engineer_id,
                    parts_cost=parts_cost,
                    revenue=wo.revenue,
                    severity="high" if len(reasons) > 1 else "medium",
                    reason="; ".join(reasons),
                )
            )
    return results[skip : skip + limit]


@router.get("/pilot/checklist")
def pilot_checklist(db: Session = Depends(get_db), actor: Actor = Depends(get_current_actor)):
    require_roles(actor, UserRole.ADMIN, UserRole.MANAGER)
    low_stock = low_stock_alerts(db=db, actor=actor)
    abnormal = abnormal_usage_report(db=db, actor=actor)
    runtime = operations_monitor.snapshot(
        window_seconds=settings.operations_request_window_seconds
    )
    degraded = any(
        worker["enabled"] and worker["status"] in {"error", "stale"}
        for worker in runtime["workers"]
    )
    return {
        "system_health": "degraded" if degraded else "ok",
        "total_users": db.scalar(select(func.count(User.id))) or 0,
        "total_work_orders": db.scalar(select(func.count(WorkOrder.id))) or 0,
        "total_parts": db.scalar(select(func.count(Part.id))) or 0,
        "total_inventory_transactions": db.scalar(select(func.count(InventoryTransaction.id))) or 0,
        "low_stock_alert_count": len(low_stock),
        "abnormal_usage_alert_count": len(abnormal),
    }
