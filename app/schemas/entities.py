from datetime import date, datetime
import base64
import binascii
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.entities import TransactionType, UserRole


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


class PasswordSet(BaseModel):
    password: str = Field(min_length=10, max_length=128)


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
    invitation_url: str


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
    token_type: str = "bearer"
    expires_in: int
    user: UserRead
    device_id: str | None = None


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$", min_length=2, max_length=120)
    admin_name: str = Field(min_length=2, max_length=120)
    admin_email: str = Field(min_length=3, max_length=255)
    admin_password: str = Field(min_length=10, max_length=128)


class OrganizationUpdate(BaseModel):
    is_active: bool


class OrganizationRead(BaseModel):
    id: int
    name: str
    slug: str
    is_active: bool
    total_users: int = 0
    total_parts: int = 0
    total_work_orders: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


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


class WorkOrderCreate(BaseModel):
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
    assigned_user_id: int | None = None
    engineer_id: int | None = None
    assistant_id: int | None = None
    revenue: float | None = None
    labor_cost: float | None = None
    status: str | None = None


class WorkOrderRead(WorkOrderCreate):
    id: int
    organization_id: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None
    repair_result: str | None = None
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
