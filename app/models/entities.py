from datetime import date, datetime
from enum import Enum

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, Enum as SqlEnum, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TransactionType(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"
    TRANSFER = "transfer"
    WORK_ORDER_USED = "work_order_used"
    WORK_ORDER_USE = "work_order_used"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    DAMAGE = "damage"


class UserRole(str, Enum):
    ADMIN = "admin"
    MANAGER = "manager"
    WAREHOUSE = "warehouse"
    ENGINEER = "engineer"
    ASSISTANT = "assistant"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(255), unique=True, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole), default=UserRole.ENGINEER, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class Warehouse(Base):
    __tablename__ = "warehouses"
    __table_args__ = (
        UniqueConstraint("organization_id", "code", name="uq_warehouses_org_code"),
        UniqueConstraint("organization_id", "name", name="uq_warehouses_org_name"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warehouse_type: Mapped[str] = mapped_column(String(20), default="main")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_user = relationship("User")
    organization = relationship("Organization")


class StorageLocation(Base):
    __tablename__ = "storage_locations"
    __table_args__ = (UniqueConstraint("warehouse_id", "code", name="uq_storage_locations_warehouse_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zone: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location_type: Mapped[str] = mapped_column(String(30), default="bin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    warehouse = relationship("Warehouse")


class Part(Base):
    __tablename__ = "parts"
    __table_args__ = (
        UniqueConstraint("organization_id", "part_number", name="uq_parts_org_part_number"),
        UniqueConstraint("organization_id", "barcode", name="uq_parts_org_barcode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(120), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(120), nullable=True)
    item_type: Mapped[str] = mapped_column(String(50), default="stock", nullable=False)
    tracking_mode: Mapped[str] = mapped_column(String(20), default="none", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    custom_fields: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    english_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    machine_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit: Mapped[str] = mapped_column(String(50), default="pcs")
    default_cost: Mapped[float] = mapped_column(Float, default=0.0)
    safety_stock: Mapped[int] = mapped_column(Integer, default=0)
    min_stock: Mapped[int] = mapped_column(Integer, default=0)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class PartMachineAssociation(Base):
    __tablename__ = "part_machine_associations"
    __table_args__ = (UniqueConstraint("organization_id", "machine_model", "part_id", name="uq_part_machine_part"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    machine_model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recognition_source: Mapped[str] = mapped_column(String(40), default="employee_photo", nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    confirmed_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    last_confirmed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    part = relationship("Part")


class PartRecognitionObservation(Base):
    __tablename__ = "part_recognition_observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), default=1, nullable=False, index=True
    )
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id"), nullable=True, index=True
    )
    machine_model: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    label_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    work_order = relationship("WorkOrder")
    creator = relationship("User")
    candidates = relationship(
        "PartRecognitionCandidate",
        back_populates="observation",
        cascade="all, delete-orphan",
    )


class PartRecognitionCandidate(Base):
    __tablename__ = "part_recognition_candidates"
    __table_args__ = (
        UniqueConstraint(
            "observation_id",
            "part_id",
            name="uq_part_recognition_observation_part",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_part_recognition_confidence",
        ),
        CheckConstraint("rank > 0", name="ck_part_recognition_rank_positive"),
        CheckConstraint(
            "status IN ('ai_candidate', 'employee_confirmed', 'admin_confirmed', "
            "'usage_verified', 'trusted', 'rejected')",
            name="ck_part_recognition_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), default=1, nullable=False, index=True
    )
    observation_id: Mapped[int] = mapped_column(
        ForeignKey("part_recognition_observations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), default="ai_candidate", nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    employee_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    employee_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    admin_confirmed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    admin_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    usage_verified_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    usage_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    trusted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    observation = relationship("PartRecognitionObservation", back_populates="candidates")
    part = relationship("Part")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("organization_id", "account_number", name="uq_customers_org_account"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (UniqueConstraint("organization_id", "device_id", name="uq_user_devices_org_device"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    device_id: Mapped[str] = mapped_column(String(128), nullable=False)
    device_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    device_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user = relationship("User")
    organization = relationship("Organization")


class Equipment(Base):
    __tablename__ = "equipment"
    __table_args__ = (UniqueConstraint("organization_id", "asset_tag", name="uq_equipment_org_asset_tag"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    asset_tag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(160), nullable=True)
    equipment_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    install_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    customer = relationship("Customer")
    organization = relationship("Organization")


class MachineKnowledgeProfile(Base):
    __tablename__ = "machine_knowledge_profiles"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "model_key",
            name="uq_machine_knowledge_org_model",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_machine_knowledge_profile_version_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    manufacturer: Mapped[str | None] = mapped_column(String(160), nullable=True)
    model: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    model_key: Mapped[str] = mapped_column(String(255), nullable=False)
    equipment_type: Mapped[str | None] = mapped_column(String(160), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    entries = relationship(
        "MachineKnowledgeEntry",
        back_populates="profile",
        cascade="all, delete-orphan",
    )


class MachineKnowledgeEntry(Base):
    __tablename__ = "machine_knowledge_entries"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "origin_key",
            name="uq_machine_knowledge_entry_profile_origin",
        ),
        CheckConstraint(
            "entry_type IN ('fault', 'repair_step', 'tool', 'caution', "
            "'common_error', 'photo', 'video', 'note')",
            name="ck_machine_knowledge_entry_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_machine_knowledge_entry_status",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_machine_knowledge_entry_sort_non_negative",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_machine_knowledge_entry_version_non_negative",
        ),
        CheckConstraint(
            "related_part_role IS NULL OR related_part_role IN "
            "('recommended', 'alternative', 'consumable', 'reference')",
            name="ck_machine_knowledge_related_part_role",
        ),
        CheckConstraint(
            "related_part_role IS NULL OR related_part_id IS NOT NULL",
            name="ck_machine_knowledge_part_role_requires_part",
        ),
        CheckConstraint(
            "related_part_role != 'alternative' OR alternative_for_part_id IS NOT NULL",
            name="ck_machine_knowledge_alternative_requires_primary",
        ),
        CheckConstraint(
            "alternative_for_part_id IS NULL OR alternative_for_part_id != related_part_id",
            name="ck_machine_knowledge_alternative_distinct",
        ),
        CheckConstraint(
            "alternative_for_part_id IS NULL OR related_part_role = 'alternative'",
            name="ck_machine_knowledge_primary_only_for_alternative",
        ),
        CheckConstraint(
            "media_size_bytes IS NULL OR media_size_bytes >= 0",
            name="ck_machine_knowledge_media_size_non_negative",
        ),
        Index(
            "ix_machine_knowledge_entry_profile_status",
            "profile_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("machine_knowledge_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entry_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    fault_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    related_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("parts.id"), nullable=True, index=True
    )
    related_part_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    alternative_for_part_id: Mapped[int | None] = mapped_column(
        ForeignKey("parts.id"), nullable=True, index=True
    )
    installation_location: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source_work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id"), nullable=True, index=True
    )
    origin_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    media_storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    media_mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="draft", nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    archived_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    profile = relationship("MachineKnowledgeProfile", back_populates="entries")
    related_part = relationship("Part", foreign_keys=[related_part_id])
    alternative_for_part = relationship("Part", foreign_keys=[alternative_for_part_id])
    source_work_order = relationship("WorkOrder")


class CompletionPolicy(Base):
    __tablename__ = "completion_policies"
    __table_args__ = (UniqueConstraint("organization_id", "job_type_key", name="uq_completion_policy_org_job_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    job_type_key: Mapped[str] = mapped_column(String(120), default="*", nullable=False)
    require_repair_result: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_customer_signature: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_completion_photo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_all_checklist_items: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_parts_usage: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    require_manager_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class WorkOrderFormTemplate(Base):
    __tablename__ = "work_order_form_templates"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_work_order_form_template_org_name",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_work_order_form_template_version_non_negative",
        ),
        CheckConstraint(
            "default_work_order_status IN ('open', 'scheduled')",
            name="ck_work_order_form_template_default_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    applicable_machine_type: Mapped[str | None] = mapped_column(
        String(255), nullable=True, index=True
    )
    applicable_job_type: Mapped[str | None] = mapped_column(
        String(120), nullable=True, index=True
    )
    default_work_order_status: Mapped[str] = mapped_column(
        String(50), default="open", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    fields = relationship(
        "WorkOrderFormField",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="WorkOrderFormField.sort_order, WorkOrderFormField.id",
    )
    organization = relationship("Organization")


class WorkOrderFormField(Base):
    __tablename__ = "work_order_form_fields"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "field_key",
            name="uq_work_order_form_field_template_key",
        ),
        CheckConstraint(
            "field_type IN ('text', 'textarea', 'number', 'boolean', 'date', "
            "'select', 'photo', 'signature')",
            name="ck_work_order_form_field_type",
        ),
        CheckConstraint(
            "sort_order >= 0",
            name="ck_work_order_form_field_sort_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    template_id: Mapped[int] = mapped_column(
        ForeignKey("work_order_form_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field_key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(160), nullable=False)
    field_type: Mapped[str] = mapped_column(String(20), nullable=False)
    help_text: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    placeholder: Mapped[str | None] = mapped_column(String(500), nullable=True)
    default_value_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    options_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    required_at_completion: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    requires_photo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_signature: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    requires_approval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    triggers_notification: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    affects_inventory: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    include_in_ai_learning: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    template = relationship("WorkOrderFormTemplate", back_populates="fields")
    organization = relationship("Organization")


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        CheckConstraint(
            "repair_duration_minutes IS NULL OR repair_duration_minutes >= 0",
            name="ck_work_order_repair_duration_non_negative",
        ),
        CheckConstraint(
            "form_version >= 0",
            name="ck_work_order_form_version_non_negative",
        ),
        CheckConstraint(
            "form_template_version IS NULL OR form_template_version >= 0",
            name="ck_work_order_form_template_version_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True, index=True)
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True, index=True)
    form_template_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_order_form_templates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    form_template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    form_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    form_schema_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    form_data_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    claimed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    claimed_device_id: Mapped[int | None] = mapped_column(ForeignKey("user_devices.id"), nullable=True)
    claim_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    completed_device_id: Mapped[int | None] = mapped_column(ForeignKey("user_devices.id"), nullable=True)
    ticket_number: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    wo_number: Mapped[str | None] = mapped_column(String(120), unique=True, nullable=True)
    schedule_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    outlet_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    job_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    store_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    state: Mapped[str | None] = mapped_column(String(120), nullable=True)
    zip: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    machine_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    problem_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    fault_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    environment_info: Mapped[str | None] = mapped_column(Text, nullable=True)
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assistant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    labor_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="open")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    paused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    repair_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_outcome: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    first_time_fix: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_rework: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    repair_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checklist_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_signature_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_signature_data: Mapped[str | None] = mapped_column(Text, nullable=True)
    customer_signed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completion_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completion_approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completion_approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_locked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    engineer = relationship("User", foreign_keys=[engineer_id])
    assistant = relationship("User", foreign_keys=[assistant_id])
    organization = relationship("Organization")
    customer = relationship("Customer")
    equipment = relationship("Equipment")
    completion_requester = relationship("User", foreign_keys=[completion_requested_by])
    completion_approver = relationship("User", foreign_keys=[completion_approved_by])
    claimant = relationship("User", foreign_keys=[claimed_by_id])
    completed_by = relationship("User", foreign_keys=[completed_by_id])
    claimed_device = relationship("UserDevice", foreign_keys=[claimed_device_id])
    completed_device = relationship("UserDevice", foreign_keys=[completed_device_id])
    form_template = relationship("WorkOrderFormTemplate")


class ExternalIntegration(Base):
    __tablename__ = "external_integrations"
    __table_args__ = (
        UniqueConstraint(
            "organization_id",
            "name",
            name="uq_external_integration_org_name",
        ),
        UniqueConstraint("key_prefix", name="uq_external_integration_key_prefix"),
        UniqueConstraint("api_key_hash", name="uq_external_integration_api_key_hash"),
        CheckConstraint(
            "provider IN ('appsheet', 'generic', 'google_sheets', 'crm', 'erp', 'wms')",
            name="ck_external_integration_provider",
        ),
        CheckConstraint(
            "version >= 0",
            name="ck_external_integration_version_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    key_prefix: Mapped[str] = mapped_column(String(24), nullable=False)
    api_key_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    field_mapping_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)
    webhook_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    subscribed_events_json: Mapped[str] = mapped_column(
        Text, default="[]", nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    work_order_links = relationship(
        "ExternalWorkOrderLink",
        back_populates="integration",
        cascade="all, delete-orphan",
    )
    sync_logs = relationship(
        "ExternalSyncLog",
        back_populates="integration",
        cascade="all, delete-orphan",
    )


class ExternalWorkOrderLink(Base):
    __tablename__ = "external_work_order_links"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "external_id",
            name="uq_external_work_order_integration_external",
        ),
        UniqueConstraint(
            "integration_id",
            "work_order_id",
            name="uq_external_work_order_integration_work_order",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("external_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    work_order_id: Mapped[int] = mapped_column(
        ForeignKey("work_orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    last_inbound_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    integration = relationship("ExternalIntegration", back_populates="work_order_links")
    work_order = relationship("WorkOrder")


class ExternalSyncLog(Base):
    __tablename__ = "external_sync_logs"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "idempotency_key",
            name="uq_external_sync_integration_idempotency",
        ),
        CheckConstraint(
            "direction IN ('inbound', 'outbound')",
            name="ck_external_sync_direction",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_external_sync_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_external_sync_attempt_non_negative",
        ),
        Index(
            "ix_external_sync_org_integration_created",
            "organization_id",
            "integration_id",
            "created_at",
        ),
        Index(
            "ix_external_sync_due_delivery",
            "direction",
            "status",
            "next_retry_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id"), nullable=False, index=True
    )
    integration_id: Mapped[int] = mapped_column(
        ForeignKey("external_integrations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default="processing", nullable=False, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    work_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    changed_fields_json: Mapped[str] = mapped_column(Text, default="[]", nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    integration = relationship("ExternalIntegration", back_populates="sync_logs")
    work_order = relationship("WorkOrder")


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"
    __table_args__ = (
        UniqueConstraint("replenishment_request_id", "movement_stage", name="uq_inventory_replenishment_stage"),
        UniqueConstraint("vehicle_return_request_id", "movement_stage", name="uq_inventory_vehicle_return_stage"),
        CheckConstraint(
            "movement_stage IS NULL OR movement_stage IN ('ship', 'receive', 'return_ship', 'return_receive')",
            name="ck_inventory_replenishment_stage",
        ),
        CheckConstraint(
            "(replenishment_request_id IS NULL AND vehicle_return_request_id IS NULL AND movement_stage IS NULL) OR "
            "(replenishment_request_id IS NOT NULL AND vehicle_return_request_id IS NULL "
            "AND movement_stage IN ('ship', 'receive')) OR "
            "(replenishment_request_id IS NULL AND vehicle_return_request_id IS NOT NULL "
            "AND movement_stage IN ('return_ship', 'return_receive'))",
            name="ck_inventory_replenishment_link",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(SqlEnum(TransactionType), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    from_location_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id"), nullable=True)
    to_location_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id"), nullable=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    replenishment_request_id: Mapped[int | None] = mapped_column(ForeignKey("replenishment_requests.id"), nullable=True, index=True)
    vehicle_return_request_id: Mapped[int | None] = mapped_column(ForeignKey("vehicle_return_requests.id"), nullable=True, index=True)
    inventory_count_line_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_count_lines.id"), nullable=True, unique=True, index=True)
    movement_stage: Mapped[str | None] = mapped_column(String(20), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    part = relationship("Part")
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
    from_location = relationship("StorageLocation", foreign_keys=[from_location_id])
    to_location = relationship("StorageLocation", foreign_keys=[to_location_id])
    work_order = relationship("WorkOrder")
    user = relationship("User")
    organization = relationship("Organization")


class WorkOrderPart(Base):
    __tablename__ = "work_order_parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    installed: Mapped[str] = mapped_column(String(20), default="yes")
    old_part_returned: Mapped[str] = mapped_column(String(20), default="no")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_order = relationship("WorkOrder")
    part = relationship("Part")
    warehouse = relationship("Warehouse")
    user = relationship("User")
    organization = relationship("Organization")


class QCPicture(Base):
    __tablename__ = "qc_pictures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_order = relationship("WorkOrder")
    uploader = relationship("User")
    organization = relationship("Organization")


class WorkOrderVoiceNote(Base):
    __tablename__ = "work_order_voice_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False, index=True)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    audio_url: Mapped[str] = mapped_column(String(500), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcription_status: Mapped[str] = mapped_column(String(30), default="not_requested", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    work_order = relationship("WorkOrder")
    creator = relationship("User")
    organization = relationship("Organization")


class WorkOrderPartMemory(Base):
    __tablename__ = "work_order_part_memory"
    __table_args__ = (UniqueConstraint("organization_id", "machine_type", "job_type", "part_id", name="uq_work_order_part_memory"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    machine_type: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    job_type: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    total_quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    part = relationship("Part")


class JobStatus(Base):
    __tablename__ = "job_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_order = relationship("WorkOrder")
    organization = relationship("Organization")


class ReturnEquipment(Base):
    __tablename__ = "return_equipments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    work_order_id: Mapped[int] = mapped_column(ForeignKey("work_orders.id"), nullable=False)
    equipment_type: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    work_order = relationship("WorkOrder")
    organization = relationship("Organization")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(120), nullable=False)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")
    organization = relationship("Organization")


class InventoryNotification(Base):
    __tablename__ = "inventory_notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    notification_type: Mapped[str] = mapped_column(String(40), default="replenishment", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    part = relationship("Part")
    warehouse = relationship("Warehouse")


class ReplenishmentRequest(Base):
    __tablename__ = "replenishment_requests"
    __table_args__ = (
        UniqueConstraint("notification_id", name="uq_replenishment_notification_id"),
        UniqueConstraint("organization_id", "client_request_id", name="uq_replenishment_org_client_request"),
        UniqueConstraint("shipment_transaction_id", name="uq_replenishment_shipment_transaction_id"),
        UniqueConstraint("receipt_transaction_id", name="uq_replenishment_receipt_transaction_id"),
        CheckConstraint("quantity > 0", name="ck_replenishment_quantity_positive"),
        CheckConstraint("version >= 0", name="ck_replenishment_version_non_negative"),
        CheckConstraint(
            "status IN ('requested', 'picking', 'shipped', 'received', 'completed', 'cancelled', 'rejected')",
            name="ck_replenishment_status",
        ),
        CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_replenishment_approval_status",
        ),
        Index("ix_replenishment_org_status", "organization_id", "status"),
        Index("ix_replenishment_org_target_status", "organization_id", "target_user_id", "status"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    destination_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    source_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    requested_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    notification_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_notifications.id"), nullable=True)
    client_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    request_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    requires_reconciliation: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    picking_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    picking_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    received_device_id: Mapped[int | None] = mapped_column(ForeignKey("user_devices.id"), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipment_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="requested", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class VehicleReturnRequest(Base):
    __tablename__ = "vehicle_return_requests"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_request_id", name="uq_vehicle_return_org_client_request"),
        UniqueConstraint("shipment_transaction_id", name="uq_vehicle_return_shipment_transaction_id"),
        UniqueConstraint("receipt_transaction_id", name="uq_vehicle_return_receipt_transaction_id"),
        CheckConstraint("quantity > 0", name="ck_vehicle_return_quantity_positive"),
        CheckConstraint("version >= 0", name="ck_vehicle_return_version_non_negative"),
        CheckConstraint(
            "status IN ('requested', 'approved', 'shipped', 'received', 'cancelled')",
            name="ck_vehicle_return_status",
        ),
        Index("ix_vehicle_return_org_status", "organization_id", "status"),
        Index("ix_vehicle_return_org_engineer_status", "organization_id", "engineer_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    client_request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    source_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    destination_warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False)
    engineer_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="requested", nullable=False)
    requested_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    requested_device_id: Mapped[int] = mapped_column(ForeignKey("user_devices.id"), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    shipped_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shipped_device_id: Mapped[int | None] = mapped_column(ForeignKey("user_devices.id"), nullable=True)
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    received_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    shipment_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    receipt_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryCountSession(Base):
    __tablename__ = "inventory_count_sessions"
    __table_args__ = (
        UniqueConstraint("organization_id", "client_request_id", name="uq_inventory_count_org_client_request"),
        CheckConstraint("version >= 0", name="ck_inventory_count_version_non_negative"),
        CheckConstraint("status IN ('draft', 'submitted', 'approved', 'cancelled')", name="ck_inventory_count_status"),
        Index("ix_inventory_count_org_status", "organization_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    client_request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"), nullable=False, index=True)
    location_id: Mapped[int | None] = mapped_column(ForeignKey("storage_locations.id"), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancellation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryCountLine(Base):
    __tablename__ = "inventory_count_lines"
    __table_args__ = (
        UniqueConstraint("session_id", "part_id", name="uq_inventory_count_session_part"),
        CheckConstraint("counted_quantity >= 0", name="ck_inventory_count_line_quantity_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("inventory_count_sessions.id"), nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False, index=True)
    counted_quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    submitted_book_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_book_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    variance_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    counted_by: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    counted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    adjustment_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True, unique=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    import_type: Mapped[str] = mapped_column(String(50), nullable=False, default="parts")
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="previewed")
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    creator = relationship("User")


class UserInvitation(Base):
    __tablename__ = "user_invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[UserRole] = mapped_column(SqlEnum(UserRole), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")
    inviter = relationship("User")
