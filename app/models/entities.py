from datetime import date, datetime
from enum import Enum

from sqlalchemy import Boolean, Date, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String, Text
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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    organization = relationship("Organization")


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    warehouse_type: Mapped[str] = mapped_column(String(20), default="main")
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_user = relationship("User")
    organization = relationship("Organization")


class Part(Base):
    __tablename__ = "parts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
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


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
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
    assigned_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    engineer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    assistant_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    revenue: Mapped[float] = mapped_column(Float, default=0.0)
    labor_cost: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(50), default="open")
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_locked: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assigned_user = relationship("User", foreign_keys=[assigned_user_id])
    engineer = relationship("User", foreign_keys=[engineer_id])
    assistant = relationship("User", foreign_keys=[assistant_id])
    organization = relationship("Organization")


class InventoryTransaction(Base):
    __tablename__ = "inventory_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), default=1, nullable=False, index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("parts.id"), nullable=False)
    transaction_type: Mapped[TransactionType] = mapped_column(SqlEnum(TransactionType), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    from_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    to_warehouse_id: Mapped[int | None] = mapped_column(ForeignKey("warehouses.id"), nullable=True)
    work_order_id: Mapped[int | None] = mapped_column(ForeignKey("work_orders.id"), nullable=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    part = relationship("Part")
    from_warehouse = relationship("Warehouse", foreign_keys=[from_warehouse_id])
    to_warehouse = relationship("Warehouse", foreign_keys=[to_warehouse_id])
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
