from datetime import date, datetime
from pydantic import BaseModel, Field, model_validator

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
    name: str
    location: str | None = None
    warehouse_type: str = "main"
    assigned_user_id: int | None = None


class WarehouseRead(WarehouseCreate):
    id: int
    organization_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PartCreate(BaseModel):
    part_number: str
    name: str
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
