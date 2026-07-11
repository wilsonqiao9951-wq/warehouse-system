from datetime import date, datetime
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
    part_id: int
    destination_warehouse_id: int
    source_warehouse_id: int | None = None
    quantity: int
    work_order_id: int | None = None
    requested_by: int | None = None
    status: str
    created_at: datetime

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
        return value


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
