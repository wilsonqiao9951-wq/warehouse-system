export type UserRole = "admin" | "manager" | "warehouse" | "engineer" | "assistant";

export interface User {
  id: number;
  name: string;
  email?: string | null;
  phone?: string | null;
  role: UserRole;
  organization_id: number;
  is_active: boolean;
  is_platform_admin: boolean;
}

export interface AuthToken {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
}

export interface Organization {
  id: number;
  name: string;
  slug: string;
  is_active: boolean;
  total_users: number;
  total_parts: number;
  total_work_orders: number;
  created_at: string;
}

export interface ImportBatch {
  id: number;
  organization_id: number;
  import_type: string;
  filename: string;
  file_sha256: string;
  status: "ready" | "invalid" | "committed";
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  created_count: number;
  updated_count: number;
  errors: Array<{ row: number; part_number?: string | null; messages: string[] }>;
  preview_rows: Array<Record<string, string | number | null>>;
  created_by?: number | null;
  committed_at?: string | null;
  created_at: string;
}

export interface InvitationCreated {
  id: number;
  email: string;
  name: string;
  role: UserRole;
  expires_at: string;
  invitation_url: string;
}

export interface InvitationInfo {
  email: string;
  name: string;
  role: UserRole;
  organization_name: string;
  expires_at: string;
}

export interface Warehouse {
  id: number;
  code?: string | null;
  name: string;
  location?: string | null;
  warehouse_type?: string;
  is_active?: boolean;
  assigned_user_id?: number | null;
}

export interface StorageLocation {
  id: number;
  warehouse_id: number;
  code: string;
  name?: string | null;
  zone?: string | null;
  location_type: string;
  is_active: boolean;
}

export interface LocationStockBalance {
  part_id: number;
  part_number: string;
  part_name: string;
  warehouse_id: number;
  warehouse_name: string;
  location_id: number;
  location_code: string;
  location_name?: string | null;
  quantity: number;
}

export interface Part {
  id: number;
  part_number: string;
  name: string;
  category?: string | null;
  barcode?: string | null;
  item_type: string;
  tracking_mode: "none" | "batch" | "serial";
  is_active: boolean;
  custom_fields: Record<string, unknown>;
  unit: string;
  default_cost: number;
  safety_stock: number;
  min_stock?: number;
}

export interface WorkOrder {
  id: number;
  ticket_number: string;
  wo_number?: string | null;
  store_name?: string | null;
  assigned_user_id?: number | null;
  engineer_id?: number | null;
  revenue: number;
  labor_cost: number;
  status: string;
  city?: string | null;
  job_type?: string | null;
  schedule_date?: string | null;
  outlet_name?: string | null;
  address?: string | null;
  contact_phone?: string | null;
  completed_at?: string | null;
  is_locked?: boolean;
  description?: string | null;
  problem_description?: string | null;
  state?: string | null;
  zip?: string | null;
  started_at?: string | null;
}

export interface WorkOrderPart {
  id: number;
  work_order_id: number;
  part_id: number;
  warehouse_id: number;
  user_id?: number | null;
  quantity: number;
  unit_cost: number;
  total_cost: number;
  installed: string;
  old_part_returned: string;
  notes?: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface QCPicture {
  id: number;
  work_order_id: number;
  image_url: string;
  uploaded_by?: number | null;
}

export interface JobStatus {
  id: number;
  work_order_id: number;
  status: string;
  timestamp?: string | null;
}

export interface ReturnEquipment {
  id: number;
  work_order_id: number;
  equipment_type: string;
  quantity: number;
}

export interface LowStockAlert {
  part_id: number;
  part_number: string;
  part_name: string;
  warehouse_id: number;
  warehouse_name: string;
  quantity: number;
  min_stock: number;
}

export interface AbnormalUsageRow {
  work_order_id: number;
  ticket_number: string;
  engineer_id?: number | null;
  parts_cost: number;
  revenue: number;
  severity: string;
  reason: string;
}

export interface PilotChecklist {
  system_health: string;
  total_users: number;
  total_work_orders: number;
  total_parts: number;
  total_inventory_transactions: number;
  low_stock_alert_count: number;
  abnormal_usage_alert_count: number;
}

export interface StockBalance {
  part_id: number;
  part_number: string;
  part_name: string;
  warehouse_id: number;
  warehouse_name: string;
  quantity: number;
  safety_stock: number;
  is_low_stock: boolean;
}

export interface EngineerDashboard {
  user_id: number;
  user_name: string;
  open_work_orders: number;
  completed_work_orders: number;
  van_low_stock_items: number;
}

export interface WorkOrderProfit {
  work_order_id: number;
  revenue: number;
  labor_cost: number;
  parts_cost: number;
  profit: number;
}
