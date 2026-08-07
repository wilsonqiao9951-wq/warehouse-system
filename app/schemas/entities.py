from datetime import date, datetime, timezone
import base64
import binascii
import json
from urllib.parse import urlsplit
from typing import Annotated, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.data_residency import normalize_region_code
from app.models.entities import TransactionType, UserRole
from app.services.domains import normalize_custom_domain


class UserBase(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    role: UserRole = UserRole.ENGINEER


class UserCreate(UserBase):
    password: str | None = Field(default=None, min_length=10, max_length=128)


class UserRead(UserBase):
    id: int
    organization_id: int
    is_active: bool
    is_platform_admin: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PermissionDefinitionRead(BaseModel):
    code: str
    name: str
    description: str
    default_roles: list[UserRole]
    sensitive: bool


class PermissionOverrideRead(BaseModel):
    permission_code: str
    effect: Literal["allow", "deny"]
    reason: str | None = None
    granted_by_id: int | None = None
    updated_at: datetime


class UserPermissionMatrixRead(BaseModel):
    user_id: int
    role: UserRole
    role_permissions: list[str]
    effective_permissions: list[str]
    overrides: list[PermissionOverrideRead]
    definitions: list[PermissionDefinitionRead]


class PermissionOverrideUpdate(BaseModel):
    effect: Literal["allow", "deny", "inherit"]
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return normalized


class PasswordSet(BaseModel):
    password: str = Field(min_length=10, max_length=128)


class SessionRevoke(BaseModel):
    account_password: str = Field(min_length=10, max_length=128)


class AuthSecurityEventRead(BaseModel):
    id: int
    user_id: int | None
    event_type: Literal["login", "session_revocation", "password_reset", "mfa"]
    outcome: Literal[
        "success",
        "invalid_credentials",
        "rate_limited",
        "subscription_denied",
        "device_rejected",
        "sessions_revoked",
        "reset_requested",
        "reset_request_ignored",
        "reset_delivered",
        "reset_delivery_failed",
        "reset_completed",
        "reset_rejected",
        "mfa_challenge_required",
        "mfa_success",
        "mfa_invalid",
        "mfa_recovery_used",
        "mfa_enrolled",
        "mfa_disabled",
        "mfa_recovery_regenerated",
    ]
    occurred_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PasswordResetRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)


class PasswordResetRequestRead(BaseModel):
    accepted: bool = True
    message: str
    reset_url: str | None = None


class PasswordResetComplete(BaseModel):
    token: str = Field(min_length=32, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class PasswordResetConfigurationRead(BaseModel):
    available: bool
    expires_in_minutes: int


class InvitationCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    name: str = Field(min_length=2, max_length=120)
    role: UserRole = UserRole.ENGINEER


class InvitationCreated(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole
    expires_at: datetime
    delivery_status: Literal["manual", "pending", "sent", "failed"]
    invitation_url: str | None = None


class InvitationInfo(BaseModel):
    email: str
    name: str
    role: UserRole
    organization_name: str
    expires_at: datetime


class InvitationAccept(BaseModel):
    token: str = Field(min_length=20, max_length=500)
    password: str = Field(min_length=10, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserRead
    device_id: str | None = None


class BrowserSessionResponse(BaseModel):
    token_type: Literal["cookie"] = "cookie"
    csrf_token: str
    expires_in: int
    user: UserRead
    device_id: str | None = None


class MfaChallengeRead(BaseModel):
    mfa_required: Literal[True] = True
    challenge_token: str
    expires_in: int


class MfaLoginComplete(BaseModel):
    challenge_token: str = Field(min_length=20, max_length=2000)
    code: str = Field(min_length=6, max_length=32)


class MfaStatusRead(BaseModel):
    eligible: bool
    available: bool
    enabled: bool
    enabled_at: datetime | None = None
    enrollment_pending: bool


class MfaEnrollmentStart(BaseModel):
    account_password: str = Field(min_length=10, max_length=128)


class MfaEnrollmentRead(BaseModel):
    secret: str
    provisioning_uri: str
    expires_at: datetime


class MfaCodeVerify(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaDisable(BaseModel):
    account_password: str = Field(min_length=10, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class MfaRecoveryRegenerate(BaseModel):
    account_password: str = Field(min_length=10, max_length=128)
    code: str = Field(min_length=6, max_length=32)


class MfaRecoveryCodesRead(BaseModel):
    recovery_codes: list[str]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=120)
    admin_name: str = Field(min_length=2, max_length=120)
    admin_email: str = Field(min_length=3, max_length=255)
    admin_password: str = Field(min_length=10, max_length=128)
    plan_code: Literal["starter", "professional", "enterprise"] = "professional"
    trial_days: int = Field(default=14, ge=0, le=90)
    data_residency_region: str | None = Field(default=None, max_length=64)

    @field_validator("data_residency_region")
    @classmethod
    def normalize_data_residency_region(cls, value: str | None) -> str | None:
        return normalize_region_code(value)

    @model_validator(mode="after")
    def require_enterprise_residency(self):
        if self.data_residency_region and self.plan_code != "enterprise":
            raise ValueError("Data residency is available only on the Enterprise plan")
        return self


class OrganizationUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    is_active: bool | None = None
    plan_code: Literal["starter", "professional", "enterprise"] | None = None
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ] | None = None
    trial_ends_at: datetime | None = None
    max_users: int | None = Field(default=None, ge=1)
    max_warehouses: int | None = Field(default=None, ge=1)
    max_vehicle_warehouses: int | None = Field(default=None, ge=1)
    ai_monthly_limit: int | None = Field(default=None, ge=0)
    api_monthly_limit: int | None = Field(default=None, ge=0)
    data_residency_region: str | None = Field(default=None, max_length=64)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("data_residency_region")
    @classmethod
    def normalize_data_residency_region(cls, value: str | None) -> str | None:
        return normalize_region_code(value)

    @field_validator("trial_ends_at")
    @classmethod
    def normalize_trial_end(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def require_update(self):
        if not (self.model_fields_set - {"expected_version", "account_password"}):
            raise ValueError("At least one organization setting must be supplied")
        return self


class OrganizationBrandingRead(BaseModel):
    name: str
    slug: str
    brand_logo_url: str | None = None
    brand_primary_color: str
    brand_login_headline: str | None = None


class OrganizationBrandingUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    brand_logo_url: str | None = Field(default=None, max_length=1000)
    brand_primary_color: str | None = Field(
        default=None,
        pattern=r"^#[0-9a-fA-F]{6}$",
    )
    brand_login_headline: str | None = Field(default=None, max_length=200)

    @field_validator("brand_logo_url")
    @classmethod
    def validate_logo_url(cls, value: str | None) -> str | None:
        cleaned = (value or "").strip()
        if not cleaned:
            return None
        if any(character in cleaned for character in "\"'<>\\\r\n\t"):
            raise ValueError("Brand logo URL must use HTTPS")
        try:
            parsed = urlsplit(cleaned)
            valid = (
                parsed.scheme.lower() == "https"
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("Brand logo URL must be a valid HTTPS URL") from exc
        if not valid:
            raise ValueError("Brand logo URL must use HTTPS without embedded credentials")
        return cleaned

    @field_validator("brand_primary_color")
    @classmethod
    def normalize_primary_color(cls, value: str | None) -> str | None:
        return value.lower() if value else None

    @field_validator("brand_login_headline")
    @classmethod
    def normalize_login_headline(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @model_validator(mode="after")
    def require_branding_update(self):
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("At least one branding field must be supplied")
        return self


class OrganizationSettingsRead(OrganizationBrandingRead):
    id: int
    is_active: bool
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ]
    trial_ends_at: datetime | None = None
    max_users: int | None = None
    max_warehouses: int | None = None
    max_vehicle_warehouses: int | None = None
    ai_monthly_limit: int | None = None
    api_monthly_limit: int | None = None
    data_residency_region: str | None = None
    data_residency_enforced_at: datetime | None = None
    deployment_region: str
    data_residency_status: Literal["unrestricted", "compliant", "blocked"]
    usage_period_start: date
    ai_monthly_used: int = Field(default=0, ge=0)
    api_monthly_used: int = Field(default=0, ge=0)
    settings_version: int = Field(ge=0)
    active_users: int = 0
    pending_invitations: int = 0
    active_warehouses: int = 0
    active_vehicle_warehouses: int = 0


class OrganizationRead(BaseModel):
    id: int
    name: str
    slug: str
    is_active: bool
    brand_logo_url: str | None = None
    brand_primary_color: str
    brand_login_headline: str | None = None
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ]
    trial_ends_at: datetime | None = None
    max_users: int | None = None
    max_warehouses: int | None = None
    max_vehicle_warehouses: int | None = None
    ai_monthly_limit: int | None = None
    api_monthly_limit: int | None = None
    data_residency_region: str | None = None
    data_residency_enforced_at: datetime | None = None
    deployment_region: str
    data_residency_status: Literal["unrestricted", "compliant", "blocked"]
    usage_period_start: date
    ai_monthly_used: int = Field(default=0, ge=0)
    api_monthly_used: int = Field(default=0, ge=0)
    settings_version: int = Field(ge=0)
    active_users: int = 0
    pending_invitations: int = 0
    active_warehouses: int = 0
    active_vehicle_warehouses: int = 0
    total_users: int = 0
    total_parts: int = 0
    total_work_orders: int = 0
    custom_domain: str | None = None
    custom_domain_status: Literal["pending", "verified"] | None = None
    email_sender_address: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class OrganizationDomainUpsert(BaseModel):
    domain: str = Field(min_length=3, max_length=253)
    expected_version: int | None = Field(default=None, ge=0)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, value: str) -> str:
        return normalize_custom_domain(value)


class OrganizationDomainAction(BaseModel):
    expected_version: int = Field(ge=0)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class OrganizationEmailIdentityUpdate(OrganizationDomainAction):
    enabled: bool
    from_name: str = Field(min_length=1, max_length=160)
    local_part: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9](?:[a-z0-9._-]{0,62}[a-z0-9])?$",
    )

    @field_validator("from_name")
    @classmethod
    def normalize_from_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if any(character in value for character in "\r\n"):
            raise ValueError("Sender name cannot contain line breaks")
        if not cleaned:
            raise ValueError("Sender name cannot be blank")
        return cleaned

    @field_validator("local_part", mode="before")
    @classmethod
    def normalize_local_part(cls, value: str) -> str:
        cleaned = value.strip().casefold()
        if ".." in cleaned:
            raise ValueError("Sender local part cannot contain consecutive dots")
        return cleaned


class OrganizationDomainRead(BaseModel):
    id: int
    organization_id: int
    domain: str
    status: Literal["pending", "verified"]
    verification_record_type: Literal["TXT"] = "TXT"
    verification_name: str
    verification_value: str
    last_checked_at: datetime | None = None
    verification_error: str | None = None
    verified_at: datetime | None = None
    email_from_name: str | None = None
    email_from_local_part: str | None = None
    email_identity_enabled: bool
    email_sender_address: str | None = None
    login_url: str | None = None
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class BillingAccountUpsert(BaseModel):
    expected_version: int = Field(default=0, ge=0)
    provider: Literal["manual", "generic", "stripe"]
    external_customer_id: str | None = Field(default=None, min_length=1, max_length=200)
    external_subscription_id: str | None = Field(default=None, min_length=1, max_length=200)
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    grace_ends_at: datetime | None = None
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("external_customer_id", "external_subscription_id")
    @classmethod
    def normalize_external_reference(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator(
        "current_period_start",
        "current_period_end",
        "grace_ends_at",
    )
    @classmethod
    def normalize_billing_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def validate_binding(self):
        references = (self.external_customer_id, self.external_subscription_id)
        if self.provider == "manual" and any(references):
            raise ValueError("Manual billing cannot include provider references")
        if self.provider == "generic" and not all(references):
            raise ValueError("Generic billing requires customer and subscription references")
        if (
            self.provider == "stripe"
            and self.external_subscription_id
            and not self.external_customer_id
        ):
            raise ValueError("A Stripe subscription requires a customer reference")
        if (self.current_period_start is None) != (self.current_period_end is None):
            raise ValueError("Billing period start and end must be supplied together")
        if (
            self.current_period_start is not None
            and self.current_period_end is not None
            and self.current_period_end <= self.current_period_start
        ):
            raise ValueError("Billing period end must be after its start")
        return self


BillingEventType = Literal[
    "trial.started",
    "subscription.activated",
    "subscription.renewed",
    "payment.failed",
    "subscription.cancellation_scheduled",
    "subscription.cancellation_reversed",
    "subscription.suspended",
    "subscription.cancelled",
]


class BillingWebhookEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$",
    )
    event_type: BillingEventType
    occurred_at: datetime
    external_customer_id: str = Field(min_length=1, max_length=200)
    external_subscription_id: str = Field(min_length=1, max_length=200)
    plan_code: Literal["starter", "professional", "enterprise"] | None = None
    trial_ends_at: datetime | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool | None = None
    grace_ends_at: datetime | None = None

    @field_validator("external_customer_id", "external_subscription_id")
    @classmethod
    def normalize_webhook_reference(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Provider reference cannot be blank")
        return cleaned

    @field_validator(
        "occurred_at",
        "trial_ends_at",
        "current_period_start",
        "current_period_end",
        "grace_ends_at",
    )
    @classmethod
    def normalize_webhook_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def validate_event_timeline(self):
        if (self.current_period_start is None) != (self.current_period_end is None):
            raise ValueError("Billing period start and end must be supplied together")
        if (
            self.current_period_start is not None
            and self.current_period_end is not None
            and self.current_period_end <= self.current_period_start
        ):
            raise ValueError("Billing period end must be after its start")
        if self.current_period_start is not None and self.current_period_start > self.occurred_at:
            raise ValueError("Billing period start cannot be after the event")
        if self.current_period_end is not None and self.current_period_end <= self.occurred_at:
            raise ValueError("Billing period end must be after the event")
        if self.event_type == "trial.started":
            if self.trial_ends_at is None or self.trial_ends_at <= self.occurred_at:
                raise ValueError("A trial event requires a future trial end")
        if self.event_type in {"subscription.activated", "subscription.renewed"}:
            if self.current_period_end is None or self.current_period_end <= self.occurred_at:
                raise ValueError("An active subscription event requires a future billing period")
        if self.grace_ends_at is not None:
            if self.event_type != "payment.failed" or self.grace_ends_at <= self.occurred_at:
                raise ValueError("Only a payment failure may set a future grace end")
        if self.cancel_at_period_end is not None and self.event_type not in {
            "subscription.activated",
            "subscription.renewed",
        }:
            raise ValueError("This event type cannot set cancel_at_period_end directly")
        return self


class BillingAccountRead(BaseModel):
    id: int
    organization_id: int
    provider: Literal["manual", "generic", "stripe"]
    external_customer_id: str | None = None
    external_subscription_id: str | None = None
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    cancel_at_period_end: bool
    grace_ends_at: datetime | None = None
    last_event_at: datetime | None = None
    last_event_id: str | None = None
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlatformBillingAccountRead(BillingAccountRead):
    organization_name: str
    organization_slug: str
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ]
    open_notice_count: int = Field(ge=0)


class BillingLifecycleEventRead(BaseModel):
    id: int
    organization_id: int
    billing_account_id: int
    provider: str
    external_event_id: str
    event_type: BillingEventType
    processing_status: Literal["applied", "ignored_stale"]
    payload_sha256: str
    before_subscription_status: str
    after_subscription_status: str
    before_plan_code: str
    after_plan_code: str
    occurred_at: datetime
    received_at: datetime
    processed_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SubscriptionNoticeRead(BaseModel):
    id: int
    organization_id: int
    source_event_id: int | None = None
    notice_type: Literal[
        "trial_ending",
        "trial_expired",
        "renewal_upcoming",
        "renewal_overdue",
        "cancellation_scheduled",
        "payment_past_due",
        "subscription_suspended",
        "subscription_cancelled",
    ]
    status: Literal["open", "acknowledged", "resolved"]
    severity: Literal["info", "warning", "critical"]
    message: str
    effective_at: datetime
    acknowledged_by: int | None = None
    acknowledged_at: datetime | None = None
    resolved_at: datetime | None = None
    version: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class OrganizationBillingOverviewRead(BaseModel):
    organization_id: int
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ]
    trial_ends_at: datetime | None = None
    account: BillingAccountRead | None = None
    notices: list[SubscriptionNoticeRead]
    stripe_enabled: bool = False
    stripe_checkout_plans: list[Literal["starter", "professional", "enterprise"]] = []
    stripe_portal_available: bool = False


class SubscriptionNoticeAcknowledge(BaseModel):
    expected_version: int = Field(ge=0)


class BillingWebhookResponse(BaseModel):
    event_id: int | None = None
    external_event_id: str
    processing_status: Literal["applied", "ignored_stale", "bound", "ignored"]
    duplicate: bool
    subscription_status: str | None = None
    plan_code: str | None = None


StripeRequestId = Annotated[
    str,
    Field(min_length=8, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$"),
]


class StripeCheckoutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_plan_code: Literal["starter", "professional", "enterprise"]
    client_request_id: StripeRequestId
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class StripePortalSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_request_id: StripeRequestId
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class StripeRefundRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    organization_id: int = Field(ge=1)
    payment_intent_id: str = Field(
        min_length=4,
        max_length=200,
        pattern=r"^pi_[A-Za-z0-9_]+$",
    )
    amount_minor: int | None = Field(default=None, ge=1)
    reason: Literal["duplicate", "fraudulent", "requested_by_customer"]
    business_reason: str = Field(min_length=10, max_length=1000)
    client_request_id: StripeRequestId
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class StripeRedirectSessionRead(BaseModel):
    operation_id: int
    status: Literal["pending", "succeeded", "failed"]
    external_object_id: str | None = None
    url: str | None = None
    expires_at: datetime | None = None
    replayed: bool = False


class StripeRefundRead(BaseModel):
    operation_id: int
    status: Literal["pending", "succeeded", "failed"]
    external_object_id: str | None = None
    amount_minor: int | None = None
    replayed: bool = False


class StripeBillingOperationRead(BaseModel):
    id: int
    organization_id: int
    requested_by: int | None = None
    client_request_id: str
    operation_type: Literal["checkout", "portal", "refund"]
    status: Literal["pending", "succeeded", "failed"]
    target_plan_code: Literal["starter", "professional", "enterprise"] | None = None
    amount_minor: int | None = None
    external_object_id: str | None = None
    external_request_id: str | None = None
    failure_code: str | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class BillingReconciliationRead(BaseModel):
    organizations_checked: int = Field(ge=0)
    notices_created: int = Field(ge=0)
    notices_resolved: int = Field(ge=0)


class OrganizationDataExportRequest(BaseModel):
    include_files: bool = True
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class OrganizationDataExportRead(BaseModel):
    id: int
    organization_id: int
    requested_by: int | None = None
    format_version: Literal["opf-portable-v1"]
    sha256: str = Field(min_length=64, max_length=64)
    size_bytes: int = Field(ge=0)
    record_count: int = Field(ge=0)
    file_count: int = Field(ge=0)
    missing_file_count: int = Field(ge=0)
    include_files: bool
    table_counts: dict[str, int]
    generated_at: datetime


class OrganizationDataRestoreDecision(BaseModel):
    expected_version: int = Field(ge=0)
    decision: Literal["approve", "reject"]
    account_password: str | None = Field(default=None, min_length=10, max_length=128)
    note: str = Field(min_length=3, max_length=1000)


class OrganizationDataRestoreRollback(BaseModel):
    expected_version: int = Field(ge=0)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class OrganizationDataRetentionPolicyUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    data_export_evidence_retention_days: int = Field(ge=30, le=3650)
    data_restore_rehearsal_retention_days: int = Field(ge=7, le=3650)
    data_restore_rollback_retention_days: int = Field(ge=7, le=3650)
    reason: str = Field(min_length=3, max_length=500)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return normalized


class OrganizationDataRetentionCleanup(BaseModel):
    expected_version: int = Field(ge=0)
    reason: str = Field(min_length=3, max_length=500)
    max_items: int = Field(default=100, ge=1, le=500)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return normalized


class OrganizationDataRetentionRead(BaseModel):
    organization_id: int
    settings_version: int = Field(ge=0)
    data_export_evidence_retention_days: int = Field(ge=30, le=3650)
    data_restore_rehearsal_retention_days: int = Field(ge=7, le=3650)
    data_restore_rollback_retention_days: int = Field(ge=7, le=3650)
    export_cutoff: datetime
    restore_rehearsal_cutoff: datetime
    generated_at: datetime
    export_evidence_candidates: int = Field(ge=0)
    restore_rehearsal_candidates: int = Field(ge=0)
    rollback_evidence_candidates: int = Field(ge=0)
    rollback_database_bytes: int = Field(ge=0)
    rollback_file_bytes: int = Field(ge=0)


class OrganizationDataRetentionCleanupRead(BaseModel):
    organization_id: int
    executed_at: datetime
    export_evidence_deleted: int = Field(ge=0)
    restore_rehearsals_deleted: int = Field(ge=0)
    rollback_evidence_purged: int = Field(ge=0)
    rollback_database_bytes_purged: int = Field(ge=0)
    rollback_file_bytes_purged: int = Field(ge=0)
    recovered_interrupted_file_cleanups: int = Field(ge=0)
    file_cleanup_pending: bool = False
    remaining_candidates: int = Field(ge=0)


class OrganizationDataRestoreRead(BaseModel):
    id: int
    organization_id: int
    requested_by: int | None = None
    approved_by: int | None = None
    rejected_by: int | None = None
    applied_by: int | None = None
    rolled_back_by: int | None = None
    matched_export_id: int | None = None
    format_version: Literal["opf-portable-v1"]
    status: Literal["validated", "approved", "rejected", "applied", "rolled_back"]
    archive_sha256: str = Field(min_length=64, max_length=64)
    archive_size_bytes: int = Field(ge=0)
    plan_sha256: str = Field(min_length=64, max_length=64)
    source_schema_revision: str | None = None
    source_exported_at: datetime | None = None
    record_count: int = Field(ge=0)
    file_count: int = Field(ge=0)
    create_count: int = Field(ge=0)
    file_create_count: int = Field(ge=0)
    file_overwrite_count: int = Field(ge=0)
    file_unchanged_count: int = Field(ge=0)
    file_conflict_count: int = Field(ge=0)
    update_count: int = Field(ge=0)
    unchanged_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    protected_count: int = Field(ge=0)
    table_summary: dict[str, dict[str, int]]
    validation_messages: list[str]
    approval_note: str | None = None
    rollback_size_bytes: int = Field(ge=0)
    file_rollback_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    file_rollback_size_bytes: int = Field(ge=0)
    rollback_expires_at: datetime | None = None
    rollback_evidence_purged_at: datetime | None = None
    rollback_evidence_purged_by: int | None = None
    version: int = Field(ge=0)
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    applied_at: datetime | None = None
    rolled_back_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class CommercialUsagePeriodRead(BaseModel):
    period_start: date
    ai_requests: int = Field(ge=0)
    api_requests: int = Field(ge=0)
    last_ai_used_at: datetime | None = None
    last_api_used_at: datetime | None = None


class CommercialCapacityRead(BaseModel):
    active_users: int = Field(ge=0)
    pending_invitations: int = Field(ge=0)
    active_warehouses: int = Field(ge=0)
    active_vehicle_warehouses: int = Field(ge=0)
    max_users: int | None = None
    max_warehouses: int | None = None
    max_vehicle_warehouses: int | None = None


class OrganizationCommercialReportRead(BaseModel):
    organization_id: int
    organization_name: str
    organization_slug: str
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: Literal[
        "trialing",
        "active",
        "past_due",
        "suspended",
        "cancelled",
    ]
    generated_at: datetime
    ai_monthly_limit: int | None = None
    api_monthly_limit: int | None = None
    capacity: CommercialCapacityRead
    periods: list[CommercialUsagePeriodRead]


class PlatformCommercialReportRow(BaseModel):
    organization_id: int
    organization_name: str
    organization_slug: str
    plan_code: Literal["starter", "professional", "enterprise"]
    subscription_status: str
    period_start: date
    ai_requests: int = Field(ge=0)
    ai_monthly_limit: int | None = None
    api_requests: int = Field(ge=0)
    api_monthly_limit: int | None = None
    active_users: int = Field(ge=0)
    pending_invitations: int = Field(ge=0)
    max_users: int | None = None
    active_warehouses: int = Field(ge=0)
    max_warehouses: int | None = None
    active_vehicle_warehouses: int = Field(ge=0)
    max_vehicle_warehouses: int | None = None


class CommercialReportExportRequest(BaseModel):
    months: int = Field(default=12, ge=1, le=36)
    account_password: str | None = Field(default=None, min_length=10, max_length=128)


class PlatformCommercialReportExportRequest(BaseModel):
    period_start: date
    account_password: str | None = Field(default=None, min_length=10, max_length=128)

    @field_validator("period_start")
    @classmethod
    def require_month_start(cls, value: date) -> date:
        if value.day != 1:
            raise ValueError("Commercial report period must start on the first day of a month")
        return value


ExternalIntegrationProvider = Literal[
    "appsheet",
    "generic",
    "google_sheets",
    "crm",
    "erp",
    "wms",
]

ExternalWebhookEvent = Literal[
    "work_order.status_changed",
    "work_order.completed",
    "work_order.part_used",
]


class ExternalIntegrationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    provider: ExternalIntegrationProvider = "appsheet"
    field_mapping: dict[str, str] = Field(default_factory=dict)
    webhook_url: str | None = Field(default=None, max_length=1000)
    subscribed_events: list[ExternalWebhookEvent] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Integration name must contain at least 2 characters")
        return cleaned


class ExternalIntegrationUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    field_mapping: dict[str, str] | None = None
    webhook_url: str | None = Field(default=None, max_length=1000)
    subscribed_events: list[ExternalWebhookEvent] | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Integration name must contain at least 2 characters")
        return cleaned


class ExternalIntegrationRotate(BaseModel):
    expected_version: int = Field(ge=0)


class ExternalIntegrationRead(BaseModel):
    id: int
    organization_id: int
    name: str
    provider: ExternalIntegrationProvider
    key_prefix: str
    masked_api_key: str
    field_mapping: dict[str, str] = Field(default_factory=dict)
    webhook_url: str | None = None
    subscribed_events: list[ExternalWebhookEvent] = Field(default_factory=list)
    is_active: bool
    version: int = Field(ge=0)
    last_used_at: datetime | None = None
    created_by: int | None = None
    updated_by: int | None = None
    created_at: datetime
    updated_at: datetime


class ExternalIntegrationSecretRead(BaseModel):
    integration: ExternalIntegrationRead
    api_key: str


class ExternalSyncLogRead(BaseModel):
    id: int
    integration_id: int
    direction: Literal["inbound", "outbound"]
    event_type: str
    external_id: str
    idempotency_key: str
    status: Literal["pending", "processing", "processed", "failed"]
    attempt_count: int = Field(ge=0)
    work_order_id: int | None = None
    changed_fields: list[str] = Field(default_factory=list)
    response_status_code: int | None = None
    error_message: str | None = None
    next_retry_at: datetime | None = None
    last_attempt_at: datetime | None = None
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ExternalWorkOrderUpsert(BaseModel):
    external_id: str = Field(min_length=1, max_length=255)
    data: dict[str, object] = Field(default_factory=dict)

    @field_validator("external_id")
    @classmethod
    def normalize_external_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("external_id cannot be blank")
        return cleaned

    @field_validator("data")
    @classmethod
    def bound_external_data(cls, value: dict[str, object]) -> dict[str, object]:
        if len(value) > 200:
            raise ValueError("data cannot contain more than 200 fields")
        encoded = json.dumps(value, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > 262_144:
            raise ValueError("data cannot exceed 256 KiB")
        return value


class ExternalWorkOrderUpsertRead(BaseModel):
    integration_id: int
    external_id: str
    work_order_id: int
    ticket_number: str
    result: Literal["created", "updated"]
    changed_fields: list[str] = Field(default_factory=list)
    replayed: bool = False


class ExternalInventoryBalanceRead(BaseModel):
    part_number: str
    part_name: str
    warehouse_code: str
    warehouse_name: str
    quantity: int
    available_quantity: int
    unit: str
    is_low_stock: bool


class ExternalWorkOrderRead(BaseModel):
    external_id: str
    work_order_id: int
    ticket_number: str
    status: str
    assigned_engineer_id: int | None = None
    claimed: bool
    started_at: datetime | None = None
    paused_at: datetime | None = None
    completed_at: datetime | None = None
    final_outcome: str | None = None
    updated_at: datetime


class ExternalPartRecommendationRead(BaseModel):
    part_number: str
    part_name: str
    recommended_quantity: int
    historical_usage_count: int
    success_rate: float | None = None
    average_repair_minutes: float | None = None
    available_quantity: int
    inventory_location: str | None = None
    confidence: float
    reason: str


class InventoryRegionCreate(BaseModel):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    is_default: bool = False
    is_active: bool = True


class InventoryRegionUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    is_default: bool | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_change(self):
        if not (self.model_fields_set - {"expected_version"}):
            raise ValueError("At least one region field must be supplied")
        return self


class InventoryRegionRead(BaseModel):
    id: int
    organization_id: int
    code: str
    name: str
    timezone: str
    is_default: bool
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class InventoryRegionSummary(BaseModel):
    region_id: int
    region_code: str
    region_name: str
    timezone: str
    is_default: bool
    is_active: bool
    warehouse_count: int
    main_warehouse_count: int
    vehicle_warehouse_count: int
    total_quantity: int
    low_stock_sku_count: int
    cross_region_transfer_count: int


class CrossRegionTransferRead(BaseModel):
    transaction_id: int
    created_at: datetime
    part_id: int
    part_number: str
    part_name: str
    quantity: int
    from_warehouse_id: int
    from_warehouse_name: str
    from_region_id: int
    from_region_name: str
    to_warehouse_id: int
    to_warehouse_name: str
    to_region_id: int
    to_region_name: str


class WarehouseRegionAssignment(BaseModel):
    region_id: int = Field(gt=0)
    expected_region_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=500)


class WarehouseCreate(BaseModel):
    code: str | None = None
    name: str
    location: str | None = None
    warehouse_type: str = "main"
    is_active: bool = True
    assigned_user_id: int | None = None


class WarehouseRead(WarehouseCreate):
    id: int
    organization_id: int
    region_id: int | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class StorageLocationCreate(BaseModel):
    warehouse_id: int
    code: str
    name: str | None = None
    zone: str | None = None
    location_type: str = "bin"
    is_active: bool = True


class StorageLocationRead(StorageLocationCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PartCreate(BaseModel):
    part_number: str
    name: str
    category: str | None = None
    barcode: str | None = None
    item_type: str = "stock"
    tracking_mode: str = Field(default="none", pattern=r"^(none|batch|serial)$")
    is_active: bool = True
    custom_fields: dict = Field(default_factory=dict)
    english_name: str | None = None
    machine_type: str | None = None
    unit: str = "pcs"
    default_cost: float = 0.0
    safety_stock: int = 0
    min_stock: int = 0
    supplier: str | None = None
    image_url: str | None = None
    notes: str | None = None


class PartRead(PartCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PartMachineAssociationRead(BaseModel):
    id: int
    machine_model: str
    part_id: int
    photo_url: str | None = None
    recognition_source: str
    confidence: float
    confirmed_count: int
    last_confirmed_at: datetime

    class Config:
        from_attributes = True


class PartRecognitionCandidateRead(BaseModel):
    id: int
    organization_id: int
    observation_id: int
    part_id: int
    part: PartRead
    rank: int = Field(gt=0)
    confidence: float = Field(ge=0, le=1)
    reason: str
    status: Literal[
        "ai_candidate",
        "employee_confirmed",
        "admin_confirmed",
        "usage_verified",
        "trusted",
        "rejected",
    ]
    version: int = Field(ge=0)
    employee_confirmed_by: int | None = None
    employee_confirmed_at: datetime | None = None
    admin_confirmed_by: int | None = None
    admin_confirmed_at: datetime | None = None
    usage_verified_by: int | None = None
    usage_verified_at: datetime | None = None
    trusted_at: datetime | None = None
    rejected_by: int | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    can_employee_confirm: bool = False
    can_admin_confirm: bool = False
    can_verify_usage: bool = False
    can_promote_trusted: bool = False
    can_reject: bool = False
    created_at: datetime
    updated_at: datetime


class PartRecognitionAnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    observation_id: int
    requested_by: int | None = None
    client_request_id: str
    attempt_number: int = Field(gt=0)
    provider: Literal["openai"]
    model: str
    prompt_version: str
    status: Literal["pending", "succeeded", "failed"]
    image_sha256: str
    request_sha256: str
    output_sha256: str | None = None
    external_request_id: str | None = None
    failure_code: str | None = None
    result_json: dict | None = None
    candidate_count: int = Field(ge=0)
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

class PartRecognitionObservationRead(BaseModel):
    id: int
    organization_id: int
    work_order_id: int | None = None
    machine_model: str | None = None
    label_text: str | None = None
    image_url: str
    notes: str | None = None
    analysis_status: Literal["not_requested", "pending", "succeeded", "failed"]
    analysis_version: int = Field(ge=0)
    latest_analysis: PartRecognitionAnalysisRead | None = None
    can_analyze: bool = False
    created_by: int | None = None
    created_at: datetime
    updated_at: datetime
    candidates: list[PartRecognitionCandidateRead] = Field(default_factory=list)


class PartRecognitionAnalyzeRequest(BaseModel):
    client_request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$",
    )
    expected_analysis_version: int = Field(ge=0)


class PartRecognitionConfigurationRead(BaseModel):
    available: bool
    provider: Literal["openai"] = "openai"
    model: str
    image_detail: Literal["low", "high", "original", "auto"]
    automatic_analysis: bool = True


class PartRecognitionCandidateAction(BaseModel):
    action: Literal[
        "employee_confirm",
        "admin_confirm",
        "verify_usage",
        "promote_trusted",
        "reject",
    ]
    expected_version: int = Field(ge=0)
    work_order_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class ImportBatchRead(BaseModel):
    id: int
    organization_id: int
    import_type: str
    filename: str
    file_sha256: str
    status: str
    total_rows: int
    valid_rows: int
    error_rows: int
    created_count: int
    updated_count: int
    errors: list[dict]
    preview_rows: list[dict] = Field(default_factory=list)
    created_by: int | None = None
    committed_at: datetime | None = None
    created_at: datetime


WorkOrderFormFieldType = Literal[
    "text",
    "textarea",
    "number",
    "boolean",
    "date",
    "select",
    "photo",
    "signature",
]
WorkOrderFormValue = str | int | float | bool | None


class WorkOrderFormFieldCreate(BaseModel):
    field_key: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    )
    label: str = Field(min_length=1, max_length=160)
    field_type: WorkOrderFormFieldType
    help_text: str | None = Field(default=None, max_length=1000)
    placeholder: str | None = Field(default=None, max_length=500)
    default_value: WorkOrderFormValue = None
    options: list[str] = Field(default_factory=list, max_length=100)
    required_at_completion: bool = False
    requires_photo: bool = False
    requires_signature: bool = False
    requires_approval: bool = False
    triggers_notification: bool = False
    affects_inventory: bool = False
    include_in_ai_learning: bool = False
    sort_order: int = Field(default=0, ge=0, le=10_000)

    @field_validator("field_key")
    @classmethod
    def normalize_field_key(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("label")
    @classmethod
    def normalize_field_label(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Field label cannot be blank")
        return cleaned

    @field_validator("options")
    @classmethod
    def validate_field_options(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            cleaned = value.strip()
            if not cleaned or len(cleaned) > 160:
                raise ValueError("Field options must contain 1 to 160 characters")
            if cleaned not in normalized:
                normalized.append(cleaned)
        return normalized

    @model_validator(mode="after")
    def validate_type_configuration(self):
        if self.field_type == "select" and not self.options:
            raise ValueError("Select fields require at least one option")
        if self.field_type != "select" and self.options:
            raise ValueError("Only select fields may define options")
        if self.requires_photo and self.field_type != "photo":
            raise ValueError("requires_photo can only be set on photo fields")
        if self.requires_signature and self.field_type != "signature":
            raise ValueError("requires_signature can only be set on signature fields")
        return self


class WorkOrderFormTemplateCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    industry: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    applicable_machine_type: str | None = Field(default=None, max_length=255)
    applicable_job_type: str | None = Field(default=None, max_length=120)
    default_work_order_status: Literal["open", "scheduled"] = "open"
    fields: list[WorkOrderFormFieldCreate] = Field(default_factory=list, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_template_name(cls, value: str) -> str:
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Template name must contain at least two characters")
        return cleaned

    @model_validator(mode="after")
    def validate_unique_field_keys(self):
        keys = [field.field_key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Template field keys must be unique")
        return self


class WorkOrderFormTemplateUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    industry: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=5000)
    applicable_machine_type: str | None = Field(default=None, max_length=255)
    applicable_job_type: str | None = Field(default=None, max_length=120)
    default_work_order_status: Literal["open", "scheduled"] | None = None
    is_active: bool | None = None
    fields: list[WorkOrderFormFieldCreate] | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_template_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if len(cleaned) < 2:
            raise ValueError("Template name must contain at least two characters")
        return cleaned

    @model_validator(mode="after")
    def validate_unique_field_keys(self):
        if self.fields is None:
            return self
        keys = [field.field_key for field in self.fields]
        if len(keys) != len(set(keys)):
            raise ValueError("Template field keys must be unique")
        return self


class WorkOrderFormFieldRead(WorkOrderFormFieldCreate):
    id: int | None = None


class WorkOrderFormTemplateRead(BaseModel):
    id: int
    organization_id: int
    name: str
    industry: str | None = None
    description: str | None = None
    applicable_machine_type: str | None = None
    applicable_job_type: str | None = None
    default_work_order_status: Literal["open", "scheduled"]
    is_active: bool
    version: int = Field(ge=0)
    fields: list[WorkOrderFormFieldRead] = Field(default_factory=list)
    created_by: int | None = None
    updated_by: int | None = None
    can_edit: bool = False
    created_at: datetime
    updated_at: datetime


class WorkOrderFormRead(BaseModel):
    work_order_id: int
    template_id: int | None = None
    template_name: str | None = None
    template_version: int | None = None
    form_version: int = Field(ge=0)
    fields: list[WorkOrderFormFieldRead] = Field(default_factory=list)
    values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)
    missing_required_fields: list[str] = Field(default_factory=list)
    can_edit: bool = False
    is_frozen: bool = False


class WorkOrderFormUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)

    @field_validator("values")
    @classmethod
    def bound_values(
        cls,
        values: dict[str, WorkOrderFormValue],
    ) -> dict[str, WorkOrderFormValue]:
        if len(values) > 100:
            raise ValueError("Form cannot contain more than 100 values")
        encoded = json.dumps(values, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > 262_144:
            raise ValueError("Form values cannot exceed 256 KiB")
        return values


class WorkOrderFormConflictCreate(BaseModel):
    work_order_id: int = Field(ge=1)
    client_queue_id: str = Field(min_length=8, max_length=80)
    claim_version: int = Field(ge=0)
    base_form_version: int = Field(ge=0)
    local_values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)

    @field_validator("client_queue_id")
    @classmethod
    def normalize_queue_id(cls, value: str) -> str:
        return value.strip()

    @field_validator("local_values")
    @classmethod
    def bound_local_values(
        cls,
        values: dict[str, WorkOrderFormValue],
    ) -> dict[str, WorkOrderFormValue]:
        if len(values) > 100:
            raise ValueError("Form cannot contain more than 100 values")
        encoded = json.dumps(values, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > 262_144:
            raise ValueError("Form values cannot exceed 256 KiB")
        return values


class WorkOrderFormConflictReceipt(BaseModel):
    id: int
    status: Literal["pending", "kept_server", "applied_local", "merged"]
    version: int = Field(ge=0)


class WorkOrderFormConflictRead(WorkOrderFormConflictReceipt):
    organization_id: int
    work_order_id: int
    work_order_ticket_number: str
    client_queue_id: str
    created_by: int
    created_by_name: str | None = None
    created_device_id: int
    created_device_name: str | None = None
    claim_version: int = Field(ge=0)
    base_form_version: int = Field(ge=0)
    server_form_version: int = Field(ge=0)
    current_server_form_version: int = Field(ge=0)
    local_values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)
    server_values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)
    current_server_values: dict[str, WorkOrderFormValue] = Field(default_factory=dict)
    resolved_values: dict[str, WorkOrderFormValue] | None = None
    resolved_server_form_version: int | None = Field(default=None, ge=0)
    resolution_notes: str | None = None
    resolved_by: int | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class WorkOrderFormConflictResolve(BaseModel):
    expected_version: int = Field(ge=0)
    expected_server_form_version: int = Field(ge=0)
    action: Literal["keep_server", "apply_local", "merge"]
    values: dict[str, WorkOrderFormValue] | None = None
    resolution_notes: str = Field(min_length=3, max_length=2000)

    @field_validator("resolution_notes")
    @classmethod
    def normalize_conflict_notes(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("Resolution notes must contain at least 3 characters")
        return normalized

    @field_validator("values")
    @classmethod
    def bound_resolution_values(
        cls,
        values: dict[str, WorkOrderFormValue] | None,
    ) -> dict[str, WorkOrderFormValue] | None:
        if values is None:
            return None
        if len(values) > 100:
            raise ValueError("Form cannot contain more than 100 values")
        encoded = json.dumps(values, separators=(",", ":"), default=str)
        if len(encoded.encode("utf-8")) > 262_144:
            raise ValueError("Form values cannot exceed 256 KiB")
        return values


class WorkOrderFormActionRead(BaseModel):
    id: int
    organization_id: int
    work_order_id: int
    work_order_ticket_number: str
    template_id: int | None = None
    template_name: str | None = None
    field_key: str
    field_label: str
    action_type: Literal["notification", "inventory_review"]
    status: Literal["pending", "acknowledged", "resolved"]
    triggered_form_version: int = Field(ge=1)
    version: int = Field(ge=0)
    created_by: int | None = None
    created_by_name: str | None = None
    acknowledged_by: int | None = None
    acknowledged_by_name: str | None = None
    acknowledged_at: datetime | None = None
    resolved_by: int | None = None
    resolved_by_name: str | None = None
    resolved_at: datetime | None = None
    resolution_notes: str | None = None
    can_acknowledge: bool = False
    can_resolve: bool = False
    created_at: datetime
    updated_at: datetime


class WorkOrderFormActionUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    action: Literal["acknowledge", "resolve"]
    resolution_notes: str | None = Field(default=None, max_length=2000)

    @field_validator("resolution_notes")
    @classmethod
    def normalize_resolution_notes(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class WorkOrderCreate(BaseModel):
    customer_id: int | None = None
    equipment_id: int | None = None
    form_template_id: int | None = Field(default=None, ge=1)
    ticket_number: str | None = None
    wo_number: str | None = None
    schedule_date: date | None = None
    outlet_name: str | None = None
    job_type: str | None = None
    description: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contact_phone: str | None = None
    machine_type: str | None = None
    problem_description: str | None = None
    fault_type: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)
    environment_info: str | None = Field(default=None, max_length=4000)
    assigned_user_id: int | None = None
    engineer_id: int | None = None
    assistant_id: int | None = None
    revenue: float = 0.0
    labor_cost: float = 0.0
    status: str = "open"

    @model_validator(mode="after")
    def ensure_identifier(self):
        if not self.ticket_number and not self.wo_number:
            raise ValueError("Either ticket_number or wo_number is required")
        return self


class WorkOrderUpdate(BaseModel):
    customer_id: int | None = None
    equipment_id: int | None = None
    ticket_number: str | None = None
    wo_number: str | None = None
    schedule_date: date | None = None
    outlet_name: str | None = None
    job_type: str | None = None
    description: str | None = None
    store_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contact_phone: str | None = None
    machine_type: str | None = None
    problem_description: str | None = None
    fault_type: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)
    environment_info: str | None = Field(default=None, max_length=4000)
    final_outcome: str | None = Field(default=None, max_length=120)
    first_time_fix: bool | None = None
    is_rework: bool | None = None
    assigned_user_id: int | None = None
    engineer_id: int | None = None
    assistant_id: int | None = None
    revenue: float | None = None
    labor_cost: float | None = None
    status: str | None = None


class WorkOrderRead(WorkOrderCreate):
    id: int
    organization_id: int
    form_template_version: int | None = None
    form_version: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None
    repair_result: str | None = None
    final_outcome: str | None = None
    first_time_fix: bool | None = None
    is_rework: bool = False
    repair_duration_minutes: int | None = None
    checklist_json: str | None = None
    customer_signature_name: str | None = None
    customer_signature_data: str | None = None
    customer_signed_at: datetime | None = None
    completion_requested_by: int | None = None
    completion_requested_at: datetime | None = None
    completion_approved_by: int | None = None
    completion_approved_at: datetime | None = None
    claimed_by_id: int | None = None
    claimed_at: datetime | None = None
    claimed_device_id: int | None = None
    claim_version: int = 0
    completed_by_id: int | None = None
    completed_device_id: int | None = None
    claimed_by_name: str | None = None
    completed_by_name: str | None = None
    completed_device_name: str | None = None
    can_claim: bool = False
    can_edit: bool = False
    can_complete: bool = False
    is_locked: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryTransactionCreate(BaseModel):
    part_id: int
    transaction_type: TransactionType
    quantity: int = Field(gt=0)
    from_warehouse_id: int | None = None
    to_warehouse_id: int | None = None
    from_location_id: int | None = None
    to_location_id: int | None = None
    work_order_id: int | None = None
    user_id: int | None = None
    unit_cost: float = 0.0
    notes: str | None = None


class InventoryTransactionRead(InventoryTransactionCreate):
    id: int
    organization_id: int
    replenishment_request_id: int | None = None
    vehicle_return_request_id: int | None = None
    inventory_count_line_id: int | None = None
    movement_stage: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryLedgerRowRead(BaseModel):
    id: int
    transaction_type: TransactionType
    # Read models must preserve legacy ledger evidence instead of rejecting a
    # whole page when an older import contains an unusual quantity.
    quantity: int
    unit_cost: float = Field(ge=0)
    total_cost: float = Field(ge=0)
    part_id: int
    part_number: str
    part_name: str
    from_warehouse_id: int | None = None
    from_warehouse_code: str | None = None
    from_warehouse_name: str | None = None
    to_warehouse_id: int | None = None
    to_warehouse_code: str | None = None
    to_warehouse_name: str | None = None
    from_location_id: int | None = None
    from_location_code: str | None = None
    to_location_id: int | None = None
    to_location_code: str | None = None
    work_order_id: int | None = None
    work_order_ticket_number: str | None = None
    user_id: int | None = None
    user_name: str | None = None
    source: Literal[
        "manual",
        "replenishment",
        "vehicle_return",
        "inventory_count",
        "work_order",
    ]
    replenishment_request_id: int | None = None
    vehicle_return_request_id: int | None = None
    inventory_count_line_id: int | None = None
    movement_stage: str | None = None
    notes: str | None = None
    created_at: datetime
    updated_at: datetime


class InventoryLedgerPageRead(BaseModel):
    items: list[InventoryLedgerRowRead] = Field(default_factory=list)
    total: int = Field(ge=0)
    next_before_id: int | None = None


class InventoryLedgerOptionRead(BaseModel):
    id: int
    label: str


class InventoryLedgerOptionsRead(BaseModel):
    parts: list[InventoryLedgerOptionRead] = Field(default_factory=list)
    warehouses: list[InventoryLedgerOptionRead] = Field(default_factory=list)
    users: list[InventoryLedgerOptionRead] = Field(default_factory=list)
    transaction_types: list[TransactionType] = Field(default_factory=list)


class InventoryReconciliationExceptionRead(BaseModel):
    id: str
    source: Literal["replenishment", "vehicle_return", "inventory_count"]
    kind: Literal[
        "legacy_reconciliation",
        "custody_ledger_mismatch",
        "count_pending_variance",
        "count_ledger_mismatch",
    ]
    severity: Literal["critical", "warning"]
    entity_type: Literal[
        "replenishment_request",
        "vehicle_return_request",
        "inventory_count",
    ]
    entity_id: int
    line_id: int | None = None
    status: str
    title: str
    detail: str
    part_id: int
    part_number: str
    part_name: str
    warehouse_label: str | None = None
    quantity: int | None = None
    variance_quantity: int | None = None
    shipment_transaction_id: int | None = None
    receipt_transaction_id: int | None = None
    adjustment_transaction_id: int | None = None
    action_route: str
    action_label: str
    updated_at: datetime


class InventoryReconciliationPageRead(BaseModel):
    items: list[InventoryReconciliationExceptionRead] = Field(default_factory=list)
    total: int = Field(ge=0)
    critical: int = Field(ge=0)
    warning: int = Field(ge=0)
    replenishment: int = Field(ge=0)
    vehicle_return: int = Field(ge=0)
    inventory_count: int = Field(ge=0)
    truncated: bool = False
    candidate_scan_limit: int = Field(ge=1)


class LocationStockBalance(BaseModel):
    part_id: int
    part_number: str
    part_name: str
    warehouse_id: int
    warehouse_name: str
    location_id: int
    location_code: str
    location_name: str | None = None
    quantity: int


class WorkOrderPartCreate(BaseModel):
    work_order_id: int
    part_id: int
    warehouse_id: int
    user_id: int | None = None
    quantity: int = Field(gt=0)
    unit_cost: float = 0.0
    installed: str = "yes"
    old_part_returned: str = "no"
    notes: str | None = None


class WorkOrderPartRead(WorkOrderPartCreate):
    id: int
    organization_id: int
    total_cost: float
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkOrderPartRecommendation(BaseModel):
    part: PartRead
    recommended_quantity: int
    usage_count: int
    total_quantity: int
    success_rate: float | None = Field(default=None, ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    available_quantity: int = Field(ge=0)
    inventory_location: str | None = None
    inventory_warehouse_id: int | None = None
    inventory_location_id: int | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str


class InventoryNotificationRead(BaseModel):
    id: int
    part_id: int
    warehouse_id: int
    work_order_id: int | None = None
    notification_type: str
    message: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class ReplenishmentRequestRead(BaseModel):
    id: int
    organization_id: int
    notification_id: int | None = None
    client_request_id: str | None = None
    request_reason: str | None = None
    part_id: int
    destination_warehouse_id: int
    source_warehouse_id: int | None = None
    quantity: int
    work_order_id: int | None = None
    requested_by: int | None = None
    target_user_id: int | None = None
    version: int = 0
    requires_reconciliation: bool = False
    approval_status: str = "pending"
    approved_by: int | None = None
    approved_at: datetime | None = None
    rejected_by: int | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    picking_by: int | None = None
    picking_at: datetime | None = None
    shipped_by: int | None = None
    shipped_at: datetime | None = None
    received_by: int | None = None
    received_device_id: int | None = None
    received_at: datetime | None = None
    completed_by: int | None = None
    completed_at: datetime | None = None
    cancelled_by: int | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    shipment_transaction_id: int | None = None
    receipt_transaction_id: int | None = None
    status: str
    part_number: str | None = None
    part_name: str | None = None
    source_warehouse_name: str | None = None
    destination_warehouse_name: str | None = None
    target_user_name: str | None = None
    requested_by_name: str | None = None
    approved_by_name: str | None = None
    rejected_by_name: str | None = None
    picking_by_name: str | None = None
    shipped_by_name: str | None = None
    received_by_name: str | None = None
    received_device_name: str | None = None
    completed_by_name: str | None = None
    cancelled_by_name: str | None = None
    work_order_ticket_number: str | None = None
    source_available_quantity: int | None = None
    destination_quantity: int = 0
    can_start_picking: bool = False
    can_approve: bool = False
    can_reject: bool = False
    can_ship: bool = False
    can_receive: bool = False
    can_complete: bool = False
    can_cancel: bool = False
    can_reconcile: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryScanRequest(BaseModel):
    barcode: str | None = None
    part_number: str | None = None
    quantity: int = Field(default=1, ge=1)
    warehouse_id: int | None = None
    location_id: int | None = None


class InventoryScanRead(BaseModel):
    matched: bool
    confidence: float
    recognition_method: str
    part: PartRead | None = None
    quantity_requested: int
    warehouse_id: int | None = None
    location_id: int | None = None
    current_quantity: int | None = None
    projected_quantity: int | None = None
    feedback: str


class InventoryLocationScanRequest(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    expected_warehouse_id: int | None = None


class InventoryLocationScanRead(BaseModel):
    scan_type: Literal["warehouse", "location"]
    label_token: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    location_id: int | None = None
    location_code: str | None = None
    location_name: str | None = None
    zone: str | None = None


class InventoryLocationLabelRead(BaseModel):
    label_token: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    location_id: int | None = None
    location_code: str | None = None
    location_name: str | None = None
    zone: str | None = None


class StockBalance(BaseModel):
    part_id: int
    part_number: str
    part_name: str
    warehouse_id: int
    warehouse_name: str
    quantity: int
    safety_stock: int
    is_low_stock: bool


VanPlanningAction = Literal["replenish", "return", "balanced"]


class VanConsumptionDayRead(BaseModel):
    date: date
    quantity: int = Field(ge=0)


class VanEngineerConsumptionRead(BaseModel):
    engineer_id: int
    engineer_name: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    region_id: int | None = None
    consumed_quantity: int = Field(ge=0)
    work_order_count: int = Field(ge=0)
    average_daily_usage: float = Field(ge=0)
    trend: list[VanConsumptionDayRead]


class VanRebalanceRecommendationRead(BaseModel):
    engineer_id: int
    engineer_name: str
    warehouse_id: int
    warehouse_code: str
    warehouse_name: str
    region_id: int | None = None
    part_id: int
    part_number: str
    part_name: str
    current_quantity: int
    threshold_quantity: int = Field(ge=0)
    consumed_quantity: int = Field(ge=0)
    average_daily_usage: float = Field(ge=0)
    forecast_quantity: int = Field(ge=0)
    target_quantity: int = Field(ge=0)
    pending_inbound_quantity: int = Field(ge=0)
    pending_outbound_quantity: int = Field(ge=0)
    projected_quantity: int
    recommended_action: VanPlanningAction
    recommended_quantity: int = Field(ge=0)
    suggested_warehouse_id: int | None = None
    suggested_warehouse_code: str | None = None
    suggested_warehouse_name: str | None = None
    suggested_warehouse_available_quantity: int | None = Field(default=None, ge=0)
    source_can_fulfill: bool = False
    reason: str


class VanPlanningSummaryRead(BaseModel):
    vehicle_count: int = Field(ge=0)
    engineer_count: int = Field(ge=0)
    consumed_quantity: int = Field(ge=0)
    work_order_count: int = Field(ge=0)
    replenish_count: int = Field(ge=0)
    return_count: int = Field(ge=0)
    balanced_count: int = Field(ge=0)
    recommended_replenish_quantity: int = Field(ge=0)
    recommended_return_quantity: int = Field(ge=0)


class VanPlanningRead(BaseModel):
    generated_at: datetime
    lookback_days: int = Field(ge=1, le=366)
    coverage_days: int = Field(ge=1, le=90)
    summary: VanPlanningSummaryRead
    engineers: list[VanEngineerConsumptionRead]
    recommendations: list[VanRebalanceRecommendationRead]
    truncated: bool = False


class WorkOrderProfit(BaseModel):
    work_order_id: int
    ticket_number: str
    wo_number: str | None = None
    revenue: float
    labor_cost: float
    parts_cost: float
    profit: float


class WorkOrderFlowAction(BaseModel):
    notes: str | None = None
    account_password: str | None = Field(default=None, max_length=128)
    repair_result: str | None = None
    fault_type: str | None = Field(default=None, max_length=120)
    error_code: str | None = Field(default=None, max_length=120)
    environment_info: str | None = Field(default=None, max_length=4000)
    final_outcome: str | None = Field(default=None, max_length=120)
    first_time_fix: bool | None = None
    is_rework: bool | None = None
    checklist_json: str | None = None
    customer_signature_name: str | None = None
    customer_signature_data: str | None = None

    @field_validator("customer_signature_data")
    @classmethod
    def validate_signature_data(cls, value: str | None):
        if value is None:
            return value
        if not value.startswith("data:image/png;base64,"):
            raise ValueError("Customer signature must be a PNG data URL")
        if len(value) > 1_500_000:
            raise ValueError("Customer signature exceeds the 1.5 MB limit")
        try:
            decoded = base64.b64decode(value.split(",", 1)[1], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError("Customer signature contains invalid base64 data") from exc
        if not decoded.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Customer signature is not a valid PNG image")
        return value


class WorkOrderClaimRelease(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CompletionPolicyUpsert(BaseModel):
    job_type: str | None = Field(default=None, max_length=120)
    require_repair_result: bool = False
    require_customer_signature: bool = False
    require_completion_photo: bool = False
    require_all_checklist_items: bool = False
    require_parts_usage: bool = False
    require_manager_approval: bool = False


class CompletionPolicyRead(BaseModel):
    id: int | None = None
    organization_id: int
    job_type: str | None = None
    source: str = "legacy_default"
    require_repair_result: bool = False
    require_customer_signature: bool = False
    require_completion_photo: bool = False
    require_all_checklist_items: bool = False
    require_parts_usage: bool = False
    require_manager_approval: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class LowStockAlert(BaseModel):
    part_id: int
    part_number: str
    part_name: str
    warehouse_id: int
    warehouse_name: str
    quantity: int
    min_stock: int


class AbnormalUsageRow(BaseModel):
    work_order_id: int
    ticket_number: str
    engineer_id: int | None
    parts_cost: float
    revenue: float
    severity: str
    reason: str


class EngineerDashboard(BaseModel):
    user_id: int
    user_name: str
    open_work_orders: int
    completed_work_orders: int
    van_low_stock_items: int
    van_inventory: list[StockBalance]


class WarehouseSummary(BaseModel):
    warehouse_id: int
    warehouse_name: str
    assigned_user_id: int | None
    assigned_user_name: str | None
    total_sku: int
    total_quantity: int
    low_stock_items: int


class AdminWarehouseDashboard(BaseModel):
    total_warehouses: int
    total_parts: int
    total_low_stock_items: int
    warehouses: list[WarehouseSummary]


class RootInfo(BaseModel):
    name: str
    version: str
    docs: str
    api_prefix: str


class QCPictureCreate(BaseModel):
    work_order_id: int
    image_url: str
    uploaded_by: int | None = None


class QCPictureRead(QCPictureCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReplenishmentRequestAction(BaseModel):
    action: str = Field(pattern=r"^(approve|reject|start_picking|ship|receive|complete|cancel)$")
    expected_version: int = Field(ge=0)
    source_warehouse_id: int | None = Field(default=None, ge=1)
    reason: str | None = Field(default=None, max_length=500)
    account_password: str | None = Field(default=None, max_length=128)


class ReplenishmentRequestCreate(BaseModel):
    part_id: int = Field(ge=1)
    destination_warehouse_id: int = Field(ge=1)
    quantity: int = Field(ge=1)
    source_warehouse_id: int | None = Field(default=None, ge=1)
    reason: str = Field(min_length=3, max_length=500)
    client_request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$",
    )


class ReplenishmentRequestReconcile(BaseModel):
    expected_version: int = Field(ge=0)
    resolution: str = Field(pattern=r"^(reset_requested|accept_historical)$")
    reason: str = Field(min_length=3, max_length=500)
    account_password: str | None = Field(default=None, max_length=128)


class VehicleReturnRequestCreate(BaseModel):
    part_id: int = Field(ge=1)
    source_warehouse_id: int = Field(ge=1)
    destination_warehouse_id: int = Field(ge=1)
    quantity: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    client_request_id: str = Field(
        min_length=8,
        max_length=100,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,99}$",
    )


class VehicleReturnRequestAction(BaseModel):
    action: str = Field(pattern=r"^(approve|ship|receive|cancel)$")
    expected_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=500)
    account_password: str | None = Field(default=None, max_length=128)


class VehicleReturnRequestRead(BaseModel):
    id: int
    organization_id: int
    client_request_id: str
    part_id: int
    source_warehouse_id: int
    destination_warehouse_id: int
    engineer_id: int
    quantity: int
    reason: str
    version: int
    status: str
    requested_by: int
    requested_device_id: int
    requested_at: datetime
    approved_by: int | None = None
    approved_at: datetime | None = None
    shipped_by: int | None = None
    shipped_device_id: int | None = None
    shipped_at: datetime | None = None
    received_by: int | None = None
    received_at: datetime | None = None
    cancelled_by: int | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    shipment_transaction_id: int | None = None
    receipt_transaction_id: int | None = None
    part_number: str | None = None
    part_name: str | None = None
    source_warehouse_name: str | None = None
    destination_warehouse_name: str | None = None
    engineer_name: str | None = None
    requested_by_name: str | None = None
    requested_device_name: str | None = None
    approved_by_name: str | None = None
    shipped_by_name: str | None = None
    shipped_device_name: str | None = None
    received_by_name: str | None = None
    cancelled_by_name: str | None = None
    source_quantity: int = 0
    destination_quantity: int = 0
    can_approve: bool = False
    can_ship: bool = False
    can_receive: bool = False
    can_cancel: bool = False
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryCountCreate(BaseModel):
    client_request_id: str = Field(min_length=8, max_length=100)
    warehouse_id: int
    location_id: int | None = None
    title: str = Field(min_length=3, max_length=160)
    notes: str | None = Field(default=None, max_length=2000)


class InventoryCountLineUpsert(BaseModel):
    part_id: int
    counted_quantity: int = Field(ge=0)
    notes: str | None = Field(default=None, max_length=1000)
    expected_version: int = Field(ge=0)


class InventoryCountAction(BaseModel):
    action: Literal["submit", "approve", "cancel"]
    expected_version: int = Field(ge=0)
    reason: str | None = Field(default=None, max_length=2000)
    password: str | None = Field(default=None, min_length=1, max_length=255)


class InventoryCountLineRead(BaseModel):
    id: int
    part_id: int
    part_number: str | None = None
    part_name: str | None = None
    counted_quantity: int
    submitted_book_quantity: int | None = None
    approved_book_quantity: int | None = None
    variance_quantity: int | None = None
    counted_by: int
    counted_at: datetime
    adjustment_transaction_id: int | None = None
    notes: str | None = None


class InventoryCountRead(BaseModel):
    id: int
    client_request_id: str
    warehouse_id: int
    warehouse_name: str | None = None
    location_id: int | None = None
    location_code: str | None = None
    title: str
    notes: str | None = None
    status: str
    version: int
    created_by: int
    submitted_by: int | None = None
    submitted_at: datetime | None = None
    approved_by: int | None = None
    approved_at: datetime | None = None
    cancelled_by: int | None = None
    cancelled_at: datetime | None = None
    cancellation_reason: str | None = None
    lines: list[InventoryCountLineRead] = Field(default_factory=list)
    can_edit: bool = False
    can_submit: bool = False
    can_approve: bool = False
    can_cancel: bool = False
    created_at: datetime
    updated_at: datetime


class CustomerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    account_number: str | None = Field(default=None, max_length=120)
    contact_name: str | None = Field(default=None, max_length=255)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=50)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=120)
    state: str | None = Field(default=None, max_length=120)
    zip: str | None = Field(default=None, max_length=20)
    notes: str | None = None


class CustomerRead(CustomerCreate):
    id: int
    organization_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class EquipmentCreate(BaseModel):
    customer_id: int | None = None
    asset_tag: str | None = Field(default=None, max_length=120)
    manufacturer: str | None = Field(default=None, max_length=160)
    model: str = Field(min_length=1, max_length=255)
    serial_number: str | None = Field(default=None, max_length=160)
    equipment_type: str | None = Field(default=None, max_length=160)
    location: str | None = Field(default=None, max_length=255)
    install_date: date | None = None
    notes: str | None = None


class EquipmentRead(EquipmentCreate):
    id: int
    organization_id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


MachineKnowledgeEntryType = Literal[
    "fault",
    "repair_step",
    "tool",
    "caution",
    "common_error",
    "photo",
    "video",
    "note",
]

MachineKnowledgePartRole = Literal[
    "recommended",
    "alternative",
    "consumable",
    "reference",
]


class MachineKnowledgeProfileCreate(BaseModel):
    model: str = Field(min_length=1, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=160)
    equipment_type: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=5000)


class MachineKnowledgeProfileUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    model: str | None = Field(default=None, min_length=1, max_length=255)
    manufacturer: str | None = Field(default=None, max_length=160)
    equipment_type: str | None = Field(default=None, max_length=160)
    summary: str | None = Field(default=None, max_length=5000)
    is_active: bool | None = None


class MachineKnowledgeEntryCreate(BaseModel):
    entry_type: MachineKnowledgeEntryType
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=20000)
    fault_code: str | None = Field(default=None, max_length=120)
    related_part_id: int | None = Field(default=None, ge=1)
    related_part_role: MachineKnowledgePartRole | None = None
    alternative_for_part_id: int | None = Field(default=None, ge=1)
    installation_location: str | None = Field(default=None, max_length=500)
    source_work_order_id: int | None = Field(default=None, ge=1)
    media_url: str | None = Field(default=None, max_length=1000)
    sort_order: int = Field(default=0, ge=0, le=10000)


class MachineKnowledgeEntryUpdate(BaseModel):
    expected_version: int = Field(ge=0)
    entry_type: MachineKnowledgeEntryType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    content: str | None = Field(default=None, min_length=1, max_length=20000)
    fault_code: str | None = Field(default=None, max_length=120)
    related_part_id: int | None = Field(default=None, ge=1)
    related_part_role: MachineKnowledgePartRole | None = None
    alternative_for_part_id: int | None = Field(default=None, ge=1)
    installation_location: str | None = Field(default=None, max_length=500)
    source_work_order_id: int | None = Field(default=None, ge=1)
    media_url: str | None = Field(default=None, max_length=1000)
    sort_order: int | None = Field(default=None, ge=0, le=10000)


class MachineKnowledgeEntryAction(BaseModel):
    action: Literal["publish", "archive", "reopen"]
    expected_version: int = Field(ge=0)


class MachineKnowledgeDraftGenerate(BaseModel):
    work_order_id: int = Field(ge=1)


class MachineKnowledgePartRead(BaseModel):
    id: int
    part_number: str
    name: str
    image_url: str | None = None
    recognition_source: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    confirmed_count: int | None = Field(default=None, ge=0)


class MachineKnowledgeEvidenceRead(BaseModel):
    completed_work_orders: int = Field(ge=0)
    labeled_outcomes: int = Field(ge=0)
    first_time_fix_rate: float | None = Field(default=None, ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    latest_completed_at: datetime | None = None


class MachineKnowledgeEntryRead(BaseModel):
    id: int
    organization_id: int
    profile_id: int
    entry_type: MachineKnowledgeEntryType
    title: str
    content: str
    fault_code: str | None = None
    related_part: MachineKnowledgePartRead | None = None
    related_part_role: MachineKnowledgePartRole | None = None
    alternative_for_part: MachineKnowledgePartRead | None = None
    installation_location: str | None = None
    source_work_order_id: int | None = None
    media_url: str | None = None
    media_mime_type: str | None = None
    media_size_bytes: int | None = Field(default=None, ge=0)
    sort_order: int
    status: Literal["draft", "published", "archived"]
    version: int = Field(ge=0)
    created_by: int | None = None
    updated_by: int | None = None
    published_by: int | None = None
    published_at: datetime | None = None
    archived_by: int | None = None
    archived_at: datetime | None = None
    can_edit: bool = False
    can_publish: bool = False
    can_archive: bool = False
    can_reopen: bool = False
    created_at: datetime
    updated_at: datetime


class MachineKnowledgeProfileRead(BaseModel):
    id: int
    organization_id: int
    manufacturer: str | None = None
    model: str
    equipment_type: str | None = None
    summary: str | None = None
    version: int = Field(ge=0)
    is_active: bool
    created_by: int | None = None
    updated_by: int | None = None
    can_edit: bool = False
    can_add_entry: bool = False
    entries: list[MachineKnowledgeEntryRead] = Field(default_factory=list)
    related_parts: list[MachineKnowledgePartRead] = Field(default_factory=list)
    evidence: MachineKnowledgeEvidenceRead
    created_at: datetime
    updated_at: datetime


class MachineKnowledgeDraftGenerationRead(BaseModel):
    profile: MachineKnowledgeProfileRead
    created_entries: int = Field(ge=0)
    skipped_entries: int = Field(ge=0)


class ServiceHistoryPart(BaseModel):
    part_number: str
    name: str
    quantity: int


class ServiceHistoryItem(BaseModel):
    id: int
    ticket_number: str
    schedule_date: date | None = None
    job_type: str | None = None
    problem_description: str | None = None
    repair_result: str | None = None
    fault_type: str | None = None
    error_code: str | None = None
    environment_info: str | None = None
    final_outcome: str | None = None
    first_time_fix: bool | None = None
    is_rework: bool = False
    repair_duration_minutes: int | None = None
    status: str
    completed_at: datetime | None = None
    engineer_id: int | None = None
    parts_used: list[ServiceHistoryPart] = Field(default_factory=list)


class WorkOrderServiceContext(BaseModel):
    customer: CustomerRead | None = None
    equipment: EquipmentRead | None = None
    fallback_customer_name: str | None = None
    fallback_contact_phone: str | None = None
    fallback_equipment_model: str | None = None
    history: list[ServiceHistoryItem] = Field(default_factory=list)


class ServiceIntelligencePattern(BaseModel):
    value: str
    count: int = Field(ge=1)


class ServiceIntelligenceFaultAnalysis(BaseModel):
    machine_model: str | None = None
    completed_work_orders: int = Field(default=0, ge=0)
    labeled_outcomes: int = Field(default=0, ge=0)
    first_time_fix_rate: float | None = Field(default=None, ge=0, le=1)
    rework_rate: float | None = Field(default=None, ge=0, le=1)
    average_repair_minutes: float | None = Field(default=None, ge=0)
    top_fault_types: list[ServiceIntelligencePattern] = Field(default_factory=list)
    top_error_codes: list[ServiceIntelligencePattern] = Field(default_factory=list)
    summary: str
    warnings: list[str] = Field(default_factory=list)


class ServiceIntelligenceSimilarWorkOrder(BaseModel):
    id: int
    ticket_number: str
    completed_at: datetime | None = None
    job_type: str | None = None
    problem_description: str | None = None
    fault_type: str | None = None
    error_code: str | None = None
    repair_result: str | None = None
    final_outcome: str | None = None
    first_time_fix: bool | None = None
    is_rework: bool = False
    repair_duration_minutes: int | None = None
    parts_used: list[ServiceHistoryPart] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    reason: str


class ServiceIntelligenceKnowledgeEntry(BaseModel):
    id: int
    profile_id: int
    machine_model: str
    entry_type: MachineKnowledgeEntryType
    title: str
    content: str
    fault_code: str | None = None
    related_part: MachineKnowledgePartRead | None = None
    related_part_role: MachineKnowledgePartRole | None = None
    alternative_for_part: MachineKnowledgePartRead | None = None
    installation_location: str | None = None
    media_url: str | None = None
    media_mime_type: str | None = None
    published_at: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    reason: str


class WorkOrderServiceIntelligence(BaseModel):
    work_order_id: int
    evidence_scope: Literal[
        "organization_completed_work_orders_and_published_exact_model_knowledge"
    ]
    fault_analysis: ServiceIntelligenceFaultAnalysis
    knowledge_entries: list[ServiceIntelligenceKnowledgeEntry] = Field(default_factory=list)
    similar_work_orders: list[ServiceIntelligenceSimilarWorkOrder] = Field(default_factory=list)


class WorkOrderVoiceNoteRead(BaseModel):
    id: int
    organization_id: int
    work_order_id: int
    created_by: int | None = None
    audio_url: str
    mime_type: str
    duration_seconds: float | None = None
    transcript: str | None = None
    transcription_status: str
    created_at: datetime

    class Config:
        from_attributes = True


class JobStatusCreate(BaseModel):
    work_order_id: int
    status: str
    timestamp: datetime | None = None


class JobStatusRead(JobStatusCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ReturnEquipmentCreate(BaseModel):
    work_order_id: int
    equipment_type: str
    quantity: int = Field(default=1, gt=0)


class ReturnEquipmentRead(ReturnEquipmentCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AuditLogRead(BaseModel):
    id: int
    organization_id: int
    user_id: int | None = None
    user_name: str | None = None
    action: str
    entity_type: str
    entity_id: int | None = None
    timestamp: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)
    metadata_valid: bool = True


class AuditLogPageRead(BaseModel):
    items: list[AuditLogRead] = Field(default_factory=list)
    total: int = Field(ge=0)
    next_before_id: int | None = None


class AuditLogSummaryBucket(BaseModel):
    value: str
    count: int = Field(ge=0)


class AuditLogSummaryRead(BaseModel):
    window_days: int = Field(ge=1, le=365)
    total_events: int = Field(ge=0)
    unique_actors: int = Field(ge=0)
    latest_event_at: datetime | None = None
    by_action: list[AuditLogSummaryBucket] = Field(default_factory=list)
    by_entity_type: list[AuditLogSummaryBucket] = Field(default_factory=list)


class AuditLogExportRequest(BaseModel):
    action: str | None = Field(default=None, max_length=120)
    entity_type: str | None = Field(default=None, max_length=120)
    entity_id: int | None = Field(default=None, ge=1)
    user_id: int | None = Field(default=None, ge=1)
    from_at: datetime | None = None
    to_at: datetime | None = None
    account_password: str = Field(min_length=1, max_length=128)

    @field_validator("from_at", "to_at")
    @classmethod
    def normalize_audit_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def validate_time_range(self):
        if self.from_at and self.to_at and self.to_at < self.from_at:
            raise ValueError("to_at must be on or after from_at")
        self.action = self.action.strip() if self.action else None
        self.entity_type = self.entity_type.strip() if self.entity_type else None
        return self


class OperationsRequestMetricsRead(BaseModel):
    window_seconds: int = Field(ge=1)
    total: int = Field(ge=0)
    server_errors: int = Field(ge=0)
    server_error_rate: float = Field(ge=0, le=1)
    average_duration_ms: float = Field(ge=0)
    p95_duration_ms: float = Field(ge=0)


class OperationsWorkerRead(BaseModel):
    name: str
    enabled: bool
    status: Literal["disabled", "starting", "standby", "ok", "error", "stale"]
    interval_seconds: int = Field(ge=1)
    grace_seconds: int = Field(ge=1)
    last_started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error_type: str | None = None
    last_result_count: int | None = Field(default=None, ge=0)
    last_standby_at: datetime | None = None
    lease_generation: int | None = Field(default=None, ge=1)
    lease_expires_at: datetime | None = None
    next_run_at: datetime | None = None
    run_started_at: datetime | None = None


class OperationsQueueRead(BaseModel):
    outbound_pending: int = Field(ge=0)
    outbound_due: int = Field(ge=0)
    outbound_failed: int = Field(ge=0)
    stale_processing: int = Field(ge=0)


class OperationsStaleDeliveryRecovery(BaseModel):
    account_password: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=3, max_length=500)
    max_items: int = Field(default=100, ge=1, le=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 3:
            raise ValueError("reason must contain at least 3 non-whitespace characters")
        return normalized


class OperationsStaleDeliveryRecoveryRead(BaseModel):
    recovered_count: int = Field(ge=0)
    organization_count: int = Field(ge=0)
    recovered_delivery_ids: list[int] = Field(default_factory=list)
    stale_before: datetime
    queued_at: datetime


class OperationsDataProtectionRead(BaseModel):
    active_organizations: int = Field(ge=0)
    organizations_without_recent_backup: int = Field(ge=0)
    backup_warning_days: int = Field(ge=1)
    restore_plans_with_conflicts: int = Field(ge=0)


class OperationsAlertRead(BaseModel):
    severity: Literal["warning", "critical"]
    code: str
    message: str
    count: int = Field(ge=0)


class OperationsHistoryPointRead(BaseModel):
    bucket_at: datetime
    instances_reporting: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    schema_not_ready_samples: int = Field(ge=0)
    worker_degraded_samples: int = Field(ge=0)
    request_window_seconds: int = Field(ge=1)
    request_total: int = Field(ge=0)
    server_errors: int = Field(ge=0)
    server_error_rate: float = Field(ge=0, le=1)
    average_duration_ms: float = Field(ge=0)
    p95_duration_ms: float = Field(ge=0)


class PlatformOperationsHistoryRead(BaseModel):
    from_at: datetime
    to_at: datetime
    bucket_minutes: int = Field(ge=1, le=60)
    expected_buckets: int = Field(ge=1)
    buckets_present: int = Field(ge=0)
    bucket_coverage_rate: float = Field(ge=0, le=1)
    instances_seen: int = Field(ge=0)
    sample_count: int = Field(ge=0)
    latest_sample_at: datetime | None = None
    truncated: bool
    points: list[OperationsHistoryPointRead] = Field(default_factory=list)


class PlatformOperationsSummaryRead(BaseModel):
    status: Literal["healthy", "degraded", "critical"]
    checked_at: datetime
    started_at: datetime
    uptime_seconds: int = Field(ge=0)
    database_status: Literal["ok", "error"]
    database_latency_ms: float = Field(ge=0)
    schema_status: Literal["ok", "error"]
    schema_revision: str
    requests: OperationsRequestMetricsRead
    workers: list[OperationsWorkerRead] = Field(default_factory=list)
    integration_queue: OperationsQueueRead
    open_critical_billing_notices: int = Field(ge=0)
    data_protection: OperationsDataProtectionRead
    alerts: list[OperationsAlertRead] = Field(default_factory=list)
