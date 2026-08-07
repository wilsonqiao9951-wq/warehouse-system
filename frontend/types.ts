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

export type PermissionEffect = "allow" | "deny" | "inherit";

export interface PermissionDefinition {
  code: string;
  name: string;
  description: string;
  default_roles: UserRole[];
  sensitive: boolean;
}

export interface PermissionOverride {
  permission_code: string;
  effect: Exclude<PermissionEffect, "inherit">;
  reason?: string | null;
  granted_by_id?: number | null;
  updated_at: string;
}

export interface UserPermissionMatrix {
  user_id: number;
  role: UserRole;
  role_permissions: string[];
  effective_permissions: string[];
  overrides: PermissionOverride[];
  definitions: PermissionDefinition[];
}

export interface AuthToken {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: User;
  device_id?: string | null;
}

export interface BrowserSession {
  token_type: "cookie";
  csrf_token: string;
  expires_in: number;
  user: User;
  device_id?: string | null;
}

export interface MfaChallenge {
  mfa_required: true;
  challenge_token: string;
  expires_in: number;
}

export type AuthLoginResult = AuthToken | BrowserSession | MfaChallenge;
export type AuthSession = AuthToken | BrowserSession;

export interface MfaStatus {
  eligible: boolean;
  available: boolean;
  enabled: boolean;
  enabled_at?: string | null;
  enrollment_pending: boolean;
}

export interface MfaEnrollment {
  secret: string;
  provisioning_uri: string;
  expires_at: string;
}

export interface MfaRecoveryCodes {
  recovery_codes: string[];
}

export interface AuthSecurityEvent {
  id: number;
  user_id?: number | null;
  event_type: "login" | "session_revocation" | "password_reset" | "mfa";
  outcome:
    | "success"
    | "invalid_credentials"
    | "rate_limited"
    | "subscription_denied"
    | "device_rejected"
    | "sessions_revoked"
    | "reset_requested"
    | "reset_request_ignored"
    | "reset_delivered"
    | "reset_delivery_failed"
    | "reset_completed"
    | "reset_rejected"
    | "mfa_challenge_required"
    | "mfa_success"
    | "mfa_invalid"
    | "mfa_recovery_used"
    | "mfa_enrolled"
    | "mfa_disabled"
    | "mfa_recovery_regenerated";
  occurred_at: string;
}

export interface PasswordResetConfiguration {
  available: boolean;
  expires_in_minutes: number;
}

export interface PasswordResetRequestResult {
  accepted: boolean;
  message: string;
  reset_url?: string | null;
}

export interface AuditLogEntry {
  id: number;
  organization_id: number;
  user_id?: number | null;
  user_name?: string | null;
  action: string;
  entity_type: string;
  entity_id?: number | null;
  timestamp: string;
  metadata: Record<string, unknown>;
  metadata_valid: boolean;
}

export interface AuditLogPage {
  items: AuditLogEntry[];
  total: number;
  next_before_id?: number | null;
}

export interface AuditLogSummaryBucket {
  value: string;
  count: number;
}

export interface AuditLogSummary {
  window_days: number;
  total_events: number;
  unique_actors: number;
  latest_event_at?: string | null;
  by_action: AuditLogSummaryBucket[];
  by_entity_type: AuditLogSummaryBucket[];
}

export interface AuditLogFilters {
  action?: string;
  entity_type?: string;
  entity_id?: number;
  user_id?: number;
  from_at?: string;
  to_at?: string;
}

export interface OperationsRequestMetrics {
  window_seconds: number;
  total: number;
  server_errors: number;
  server_error_rate: number;
  average_duration_ms: number;
  p95_duration_ms: number;
}

export interface OperationsWorker {
  name: string;
  enabled: boolean;
  status: "disabled" | "starting" | "standby" | "ok" | "error" | "stale";
  interval_seconds: number;
  grace_seconds: number;
  last_started_at?: string | null;
  last_success_at?: string | null;
  last_error_at?: string | null;
  last_error_type?: string | null;
  last_result_count?: number | null;
  last_standby_at?: string | null;
  lease_generation?: number | null;
  lease_expires_at?: string | null;
  next_run_at?: string | null;
  run_started_at?: string | null;
}

export interface OperationsAlert {
  severity: "warning" | "critical";
  code: string;
  message: string;
  count: number;
}

export interface OperationsHistoryPoint {
  bucket_at: string;
  instances_reporting: number;
  sample_count: number;
  schema_not_ready_samples: number;
  worker_degraded_samples: number;
  request_window_seconds: number;
  request_total: number;
  server_errors: number;
  server_error_rate: number;
  average_duration_ms: number;
  p95_duration_ms: number;
}

export interface PlatformOperationsHistory {
  from_at: string;
  to_at: string;
  bucket_minutes: number;
  expected_buckets: number;
  buckets_present: number;
  bucket_coverage_rate: number;
  instances_seen: number;
  sample_count: number;
  latest_sample_at?: string | null;
  truncated: boolean;
  points: OperationsHistoryPoint[];
}

export interface PlatformOperationsSummary {
  status: "healthy" | "degraded" | "critical";
  checked_at: string;
  started_at: string;
  uptime_seconds: number;
  database_status: "ok" | "error";
  database_latency_ms: number;
  schema_status: "ok" | "error";
  schema_revision: string;
  requests: OperationsRequestMetrics;
  workers: OperationsWorker[];
  integration_queue: {
    outbound_pending: number;
    outbound_due: number;
    outbound_failed: number;
    stale_processing: number;
  };
  open_critical_billing_notices: number;
  data_protection: {
    active_organizations: number;
    organizations_without_recent_backup: number;
    backup_warning_days: number;
    restore_plans_with_conflicts: number;
  };
  alerts: OperationsAlert[];
}

export interface OperationsStaleDeliveryRecoveryResult {
  recovered_count: number;
  organization_count: number;
  recovered_delivery_ids: number[];
  stale_before: string;
  queued_at: string;
}

export type PlanCode = "starter" | "professional" | "enterprise";
export type SubscriptionStatus =
  | "trialing"
  | "active"
  | "past_due"
  | "suspended"
  | "cancelled";

export interface OrganizationBranding {
  name: string;
  slug: string;
  brand_logo_url?: string | null;
  brand_primary_color: string;
  brand_login_headline?: string | null;
}

export interface OrganizationSettings extends OrganizationBranding {
  id: number;
  is_active: boolean;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  trial_ends_at?: string | null;
  max_users?: number | null;
  max_warehouses?: number | null;
  max_vehicle_warehouses?: number | null;
  ai_monthly_limit?: number | null;
  api_monthly_limit?: number | null;
  data_residency_region?: string | null;
  data_residency_enforced_at?: string | null;
  deployment_region: string;
  data_residency_status: "unrestricted" | "compliant" | "blocked";
  usage_period_start: string;
  ai_monthly_used: number;
  api_monthly_used: number;
  settings_version: number;
  active_users: number;
  pending_invitations: number;
  active_warehouses: number;
  active_vehicle_warehouses: number;
}

export interface Organization extends OrganizationSettings {
  total_users: number;
  total_parts: number;
  total_work_orders: number;
  custom_domain?: string | null;
  custom_domain_status?: "pending" | "verified" | null;
  email_sender_address?: string | null;
  created_at: string;
}

export interface OrganizationDomain {
  id: number;
  organization_id: number;
  domain: string;
  status: "pending" | "verified";
  verification_record_type: "TXT";
  verification_name: string;
  verification_value: string;
  last_checked_at?: string | null;
  verification_error?: string | null;
  verified_at?: string | null;
  email_from_name?: string | null;
  email_from_local_part?: string | null;
  email_identity_enabled: boolean;
  email_sender_address?: string | null;
  login_url?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export type BillingProvider = "manual" | "generic" | "stripe";
export type BillingEventType =
  | "trial.started"
  | "subscription.activated"
  | "subscription.renewed"
  | "payment.failed"
  | "subscription.cancellation_scheduled"
  | "subscription.cancellation_reversed"
  | "subscription.suspended"
  | "subscription.cancelled";

export interface BillingAccount {
  id: number;
  organization_id: number;
  provider: BillingProvider;
  external_customer_id?: string | null;
  external_subscription_id?: string | null;
  current_period_start?: string | null;
  current_period_end?: string | null;
  cancel_at_period_end: boolean;
  grace_ends_at?: string | null;
  last_event_at?: string | null;
  last_event_id?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface PlatformBillingAccount extends BillingAccount {
  organization_name: string;
  organization_slug: string;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  open_notice_count: number;
}

export interface BillingLifecycleEvent {
  id: number;
  organization_id: number;
  billing_account_id: number;
  provider: string;
  external_event_id: string;
  event_type: BillingEventType;
  processing_status: "applied" | "ignored_stale";
  payload_sha256: string;
  before_subscription_status: string;
  after_subscription_status: string;
  before_plan_code: string;
  after_plan_code: string;
  occurred_at: string;
  received_at: string;
  processed_at: string;
}

export interface SubscriptionNotice {
  id: number;
  organization_id: number;
  source_event_id?: number | null;
  notice_type:
    | "trial_ending"
    | "trial_expired"
    | "renewal_upcoming"
    | "renewal_overdue"
    | "cancellation_scheduled"
    | "payment_past_due"
    | "subscription_suspended"
    | "subscription_cancelled";
  status: "open" | "acknowledged" | "resolved";
  severity: "info" | "warning" | "critical";
  message: string;
  effective_at: string;
  acknowledged_by?: number | null;
  acknowledged_at?: string | null;
  resolved_at?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface OrganizationBillingOverview {
  organization_id: number;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  trial_ends_at?: string | null;
  account?: BillingAccount | null;
  notices: SubscriptionNotice[];
  stripe_enabled: boolean;
  stripe_checkout_plans: PlanCode[];
  stripe_portal_available: boolean;
}

export interface StripeRedirectSession {
  operation_id: number;
  status: "pending" | "succeeded" | "failed";
  external_object_id?: string | null;
  url?: string | null;
  expires_at?: string | null;
  replayed: boolean;
}

export interface StripeRefundResult {
  operation_id: number;
  status: "pending" | "succeeded" | "failed";
  external_object_id?: string | null;
  amount_minor?: number | null;
  replayed: boolean;
}

export interface CommercialUsagePeriod {
  period_start: string;
  ai_requests: number;
  api_requests: number;
  last_ai_used_at?: string | null;
  last_api_used_at?: string | null;
}

export interface OrganizationCommercialReport {
  organization_id: number;
  organization_name: string;
  organization_slug: string;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  generated_at: string;
  ai_monthly_limit?: number | null;
  api_monthly_limit?: number | null;
  capacity: {
    active_users: number;
    pending_invitations: number;
    active_warehouses: number;
    active_vehicle_warehouses: number;
    max_users?: number | null;
    max_warehouses?: number | null;
    max_vehicle_warehouses?: number | null;
  };
  periods: CommercialUsagePeriod[];
}

export interface OrganizationDataExport {
  id: number;
  organization_id: number;
  requested_by?: number | null;
  format_version: "opf-portable-v1";
  sha256: string;
  size_bytes: number;
  record_count: number;
  file_count: number;
  missing_file_count: number;
  include_files: boolean;
  table_counts: Record<string, number>;
  generated_at: string;
}

export type OrganizationDataRestoreStatus =
  | "validated"
  | "approved"
  | "rejected"
  | "applied"
  | "rolled_back";

export interface OrganizationDataRestore {
  id: number;
  organization_id: number;
  requested_by?: number | null;
  approved_by?: number | null;
  rejected_by?: number | null;
  applied_by?: number | null;
  rolled_back_by?: number | null;
  matched_export_id?: number | null;
  format_version: "opf-portable-v1";
  status: OrganizationDataRestoreStatus;
  archive_sha256: string;
  archive_size_bytes: number;
  plan_sha256: string;
  source_schema_revision?: string | null;
  source_exported_at?: string | null;
  record_count: number;
  file_count: number;
  create_count: number;
  file_create_count: number;
  file_overwrite_count: number;
  file_unchanged_count: number;
  file_conflict_count: number;
  update_count: number;
  unchanged_count: number;
  conflict_count: number;
  protected_count: number;
  table_summary: Record<string, {
    records: number;
    creates: number;
    updates: number;
    unchanged: number;
    conflicts: number;
    protected: number;
  }>;
  validation_messages: string[];
  approval_note?: string | null;
  rollback_size_bytes: number;
  file_rollback_sha256?: string | null;
  file_rollback_size_bytes: number;
  rollback_expires_at?: string | null;
  rollback_evidence_purged_at?: string | null;
  rollback_evidence_purged_by?: number | null;
  version: number;
  approved_at?: string | null;
  rejected_at?: string | null;
  applied_at?: string | null;
  rolled_back_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface OrganizationDataRetention {
  organization_id: number;
  settings_version: number;
  data_export_evidence_retention_days: number;
  data_restore_rehearsal_retention_days: number;
  data_restore_rollback_retention_days: number;
  export_cutoff: string;
  restore_rehearsal_cutoff: string;
  generated_at: string;
  export_evidence_candidates: number;
  restore_rehearsal_candidates: number;
  rollback_evidence_candidates: number;
  rollback_database_bytes: number;
  rollback_file_bytes: number;
}

export interface OrganizationDataRetentionCleanupResult {
  organization_id: number;
  executed_at: string;
  export_evidence_deleted: number;
  restore_rehearsals_deleted: number;
  rollback_evidence_purged: number;
  rollback_database_bytes_purged: number;
  rollback_file_bytes_purged: number;
  recovered_interrupted_file_cleanups: number;
  file_cleanup_pending: boolean;
  remaining_candidates: number;
}

export interface PlatformCommercialReportRow {
  organization_id: number;
  organization_name: string;
  organization_slug: string;
  plan_code: PlanCode;
  subscription_status: SubscriptionStatus;
  period_start: string;
  ai_requests: number;
  ai_monthly_limit?: number | null;
  api_requests: number;
  api_monthly_limit?: number | null;
  active_users: number;
  pending_invitations: number;
  max_users?: number | null;
  active_warehouses: number;
  max_warehouses?: number | null;
  active_vehicle_warehouses: number;
  max_vehicle_warehouses?: number | null;
}

export type ExternalIntegrationProvider =
  | "appsheet"
  | "generic"
  | "google_sheets"
  | "crm"
  | "erp"
  | "wms";

export type ExternalWebhookEvent =
  | "work_order.status_changed"
  | "work_order.completed"
  | "work_order.part_used";

export interface ExternalIntegration {
  id: number;
  organization_id: number;
  name: string;
  provider: ExternalIntegrationProvider;
  key_prefix: string;
  masked_api_key: string;
  field_mapping: Record<string, string>;
  webhook_url?: string | null;
  subscribed_events: ExternalWebhookEvent[];
  is_active: boolean;
  version: number;
  last_used_at?: string | null;
  created_by?: number | null;
  updated_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface ExternalIntegrationSecret {
  integration: ExternalIntegration;
  api_key: string;
}

export interface ExternalSyncLog {
  id: number;
  integration_id: number;
  direction: "inbound" | "outbound";
  event_type: string;
  external_id: string;
  idempotency_key: string;
  status: "pending" | "processing" | "processed" | "failed";
  attempt_count: number;
  work_order_id?: number | null;
  changed_fields: string[];
  response_status_code?: number | null;
  error_message?: string | null;
  next_retry_at?: string | null;
  last_attempt_at?: string | null;
  processed_at?: string | null;
  created_at: string;
  updated_at: string;
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
  delivery_status: "manual" | "pending" | "sent" | "failed";
  invitation_url?: string | null;
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
  region_id?: number | null;
}

export interface InventoryRegion {
  id: number;
  organization_id: number;
  code: string;
  name: string;
  timezone: string;
  is_default: boolean;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface InventoryRegionSummary {
  region_id: number;
  region_code: string;
  region_name: string;
  timezone: string;
  is_default: boolean;
  is_active: boolean;
  warehouse_count: number;
  main_warehouse_count: number;
  vehicle_warehouse_count: number;
  total_quantity: number;
  low_stock_sku_count: number;
  cross_region_transfer_count: number;
}

export interface CrossRegionTransfer {
  transaction_id: number;
  created_at: string;
  part_id: number;
  part_number: string;
  part_name: string;
  quantity: number;
  from_warehouse_id: number;
  from_warehouse_name: string;
  from_region_id: number;
  from_region_name: string;
  to_warehouse_id: number;
  to_warehouse_name: string;
  to_region_id: number;
  to_region_name: string;
}

export interface AnalyticsKpi {
  code: string;
  label: string;
  value?: number | null;
  unit: "count" | "percent" | "hours" | "currency" | string;
  previous_value?: number | null;
  delta_percent?: number | null;
  definition: string;
}

export interface AnalyticsTrendPoint {
  bucket_start: string;
  label: string;
  created_count: number;
  completed_count: number;
  first_time_fix_rate?: number | null;
  rework_rate?: number | null;
  average_repair_minutes?: number | null;
  revenue: number;
  contribution: number;
}

export interface AnalyticsEngineerRow {
  engineer_id?: number | null;
  engineer_name: string;
  completed_count: number;
  first_time_fix_rate?: number | null;
  first_time_fix_coverage: number;
  rework_rate: number;
  average_repair_minutes?: number | null;
  parts_cost: number;
  revenue: number;
  contribution: number;
}

export interface AnalyticsJobTypeRow {
  job_type: string;
  completed_count: number;
  first_time_fix_rate?: number | null;
  rework_rate: number;
  average_repair_minutes?: number | null;
  contribution: number;
}

export interface AnalyticsRegionRow {
  region_id: number;
  region_code: string;
  region_name: string;
  warehouse_count: number;
  stock_quantity: number;
  stock_value: number;
  low_stock_sku_count: number;
  completed_work_orders_with_usage: number;
  consumed_quantity: number;
  consumed_parts_cost: number;
}

export interface EnterpriseAnalytics {
  generated_at: string;
  period: {
    from_date: string;
    to_date: string;
    previous_from_date: string;
    previous_to_date: string;
    days: number;
    grain: string;
    timezone: string;
  };
  filters: {
    engineer_id?: number | null;
    job_type?: string | null;
    engineers: Array<{ value: string; label: string }>;
    job_types: Array<{ value: string; label: string }>;
  };
  kpis: AnalyticsKpi[];
  trend: AnalyticsTrendPoint[];
  engineers: AnalyticsEngineerRow[];
  job_types: AnalyticsJobTypeRow[];
  regions: AnalyticsRegionRow[];
  data_quality: {
    completed_work_orders: number;
    first_time_fix_labeled: number;
    first_time_fix_coverage: number;
    repair_duration_labeled: number;
    repair_duration_coverage: number;
    engineer_attributed: number;
    engineer_attribution_coverage: number;
    warnings: string[];
  };
  source_freshness: {
    work_orders_updated_at?: string | null;
    work_order_parts_updated_at?: string | null;
    inventory_transactions_updated_at?: string | null;
  };
}

export type EnterpriseAgentIntent =
  | "daily_brief"
  | "backlog_risk"
  | "service_quality"
  | "inventory_risk"
  | "integration_health";

export interface EnterpriseAgentEvidence {
  code: string;
  label: string;
  value: number | string;
  unit: string;
  source: string;
  definition: string;
}

export interface EnterpriseAgentFinding {
  code: string;
  severity: "info" | "warning" | "critical";
  title: string;
  summary: string;
  recommendation: string;
  evidence: EnterpriseAgentEvidence[];
  links: string[];
}

export interface EnterpriseAgentResponse {
  run_id: number;
  generated_at: string;
  mode: "deterministic_evidence";
  intent: EnterpriseAgentIntent;
  summary: string;
  priority: "normal" | "warning" | "critical";
  confidence: number;
  filters: {
    from_date: string;
    to_date: string;
    engineer_id?: number | null;
    job_type?: string | null;
    engineers: Array<{ value: string; label: string }>;
    job_types: Array<{ value: string; label: string }>;
  };
  findings: EnterpriseAgentFinding[];
  tools_used: string[];
  limitations: string[];
  guardrails: {
    read_only: boolean;
    mutations_performed: string[];
    raw_question_retained: boolean;
    cross_tenant_access: boolean;
    external_model_called: boolean;
  };
}

export interface EnterpriseAgentRun {
  id: number;
  user_id?: number | null;
  intent: EnterpriseAgentIntent;
  question_sha256: string;
  question_length: number;
  filters: Record<string, string | number | null>;
  tools_used: string[];
  finding_count: number;
  duration_ms: number;
  status: string;
  error_code?: string | null;
  created_at: string;
}

export interface EnterpriseAgentOptions {
  intents: Array<{ value: EnterpriseAgentIntent; label: string }>;
  engineers: Array<{ value: string; label: string }>;
  job_types: Array<{ value: string; label: string }>;
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

export interface InventoryScanResult {
  matched: boolean;
  confidence: number;
  recognition_method: string;
  part?: Part | null;
  quantity_requested: number;
  warehouse_id?: number | null;
  location_id?: number | null;
  current_quantity?: number | null;
  projected_quantity?: number | null;
  feedback: string;
}

export interface InventoryNotification {
  id: number; part_id: number; warehouse_id: number; work_order_id?: number | null;
  notification_type: string; message: string; status: string; created_at: string;
}

export interface ReplenishmentRequest {
  id: number;
  organization_id?: number;
  notification_id?: number | null;
  client_request_id?: string | null;
  request_reason?: string | null;
  part_id: number;
  part_number?: string | null;
  part_name?: string | null;
  destination_warehouse_id: number;
  destination_warehouse_name?: string | null;
  source_warehouse_id?: number | null;
  source_warehouse_name?: string | null;
  target_user_id?: number | null;
  target_user_name?: string | null;
  quantity: number;
  work_order_id?: number | null;
  work_order_ticket_number?: string | null;
  requested_by?: number | null;
  requested_by_name?: string | null;
  status: "requested" | "picking" | "shipped" | "received" | "completed" | "cancelled" | "rejected";
  version: number;
  requires_reconciliation: boolean;
  approval_status: "pending" | "approved" | "rejected";
  approved_by?: number | null;
  approved_by_name?: string | null;
  approved_at?: string | null;
  rejected_by?: number | null;
  rejected_by_name?: string | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  picking_by?: number | null;
  picking_by_name?: string | null;
  picking_at?: string | null;
  shipped_by?: number | null;
  shipped_by_name?: string | null;
  shipped_at?: string | null;
  received_by?: number | null;
  received_by_name?: string | null;
  received_at?: string | null;
  received_device_name?: string | null;
  completed_by?: number | null;
  completed_by_name?: string | null;
  completed_at?: string | null;
  cancelled_by_name?: string | null;
  cancelled_by?: number | null;
  cancelled_at?: string | null;
  cancellation_reason?: string | null;
  shipment_transaction_id?: number | null;
  receipt_transaction_id?: number | null;
  source_available_quantity?: number | null;
  destination_quantity?: number | null;
  can_start_picking: boolean;
  can_approve: boolean;
  can_reject: boolean;
  can_ship: boolean;
  can_receive: boolean;
  can_complete: boolean;
  can_cancel: boolean;
  can_reconcile: boolean;
  created_at: string;
  updated_at?: string | null;
}

export interface InventoryLocationScan {
  scan_type: "warehouse" | "location";
  label_token: string;
  warehouse_id: number;
  warehouse_code: string;
  warehouse_name: string;
  location_id?: number | null;
  location_code?: string | null;
  location_name?: string | null;
  zone?: string | null;
}

export interface InventoryLocationLabel {
  label_token: string;
  warehouse_id: number;
  warehouse_code: string;
  warehouse_name: string;
  location_id?: number | null;
  location_code?: string | null;
  location_name?: string | null;
  zone?: string | null;
}

export interface VehicleReturnRequest {
  id: number;
  organization_id: number;
  client_request_id: string;
  part_id: number;
  part_number?: string | null;
  part_name?: string | null;
  source_warehouse_id: number;
  source_warehouse_name?: string | null;
  destination_warehouse_id: number;
  destination_warehouse_name?: string | null;
  engineer_id: number;
  engineer_name?: string | null;
  quantity: number;
  reason: string;
  version: number;
  status: "requested" | "approved" | "shipped" | "received" | "cancelled";
  requested_by: number;
  requested_by_name?: string | null;
  requested_device_id: number;
  requested_device_name?: string | null;
  requested_at: string;
  approved_by?: number | null;
  approved_by_name?: string | null;
  approved_at?: string | null;
  shipped_by?: number | null;
  shipped_by_name?: string | null;
  shipped_device_id?: number | null;
  shipped_device_name?: string | null;
  shipped_at?: string | null;
  received_by?: number | null;
  received_by_name?: string | null;
  received_at?: string | null;
  cancelled_by?: number | null;
  cancelled_by_name?: string | null;
  cancelled_at?: string | null;
  cancellation_reason?: string | null;
  shipment_transaction_id?: number | null;
  receipt_transaction_id?: number | null;
  source_quantity: number;
  destination_quantity: number;
  can_approve: boolean;
  can_ship: boolean;
  can_receive: boolean;
  can_cancel: boolean;
  created_at: string;
  updated_at: string;
}

export interface InventoryCountLine {
  id: number;
  part_id: number;
  part_number?: string | null;
  part_name?: string | null;
  counted_quantity: number;
  submitted_book_quantity?: number | null;
  approved_book_quantity?: number | null;
  variance_quantity?: number | null;
  adjustment_transaction_id?: number | null;
  notes?: string | null;
}

export interface InventoryCount {
  id: number;
  client_request_id: string;
  warehouse_id: number;
  warehouse_name?: string | null;
  location_id?: number | null;
  location_code?: string | null;
  title: string;
  notes?: string | null;
  status: "draft" | "submitted" | "approved" | "cancelled";
  version: number;
  lines: InventoryCountLine[];
  can_edit: boolean;
  can_submit: boolean;
  can_approve: boolean;
  can_cancel: boolean;
  cancellation_reason?: string | null;
  created_at: string;
  updated_at: string;
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

export type PartRecognitionStatus =
  | "ai_candidate"
  | "employee_confirmed"
  | "admin_confirmed"
  | "usage_verified"
  | "trusted"
  | "rejected";

export type PartRecognitionAnalysisStatus =
  | "not_requested"
  | "pending"
  | "succeeded"
  | "failed";

export interface PartRecognitionAnalysis {
  id: number;
  observation_id: number;
  requested_by?: number | null;
  client_request_id: string;
  attempt_number: number;
  provider: "openai";
  model: string;
  prompt_version: string;
  status: Exclude<PartRecognitionAnalysisStatus, "not_requested">;
  image_sha256: string;
  request_sha256: string;
  output_sha256?: string | null;
  external_request_id?: string | null;
  failure_code?: string | null;
  result_json?: {
    visible_label_text?: string;
    manufacturer?: string;
    machine_model?: string;
    visual_description?: string;
    part_hints?: Array<{
      catalog_part_id?: number | null;
      part_number?: string;
      name?: string;
      confidence?: number;
      reason?: string;
    }>;
  } | null;
  candidate_count: number;
  completed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PartRecognitionConfiguration {
  available: boolean;
  provider: "openai";
  model: string;
  image_detail: "low" | "high" | "original" | "auto";
  automatic_analysis: boolean;
}

export interface PartRecognitionCandidate {
  id: number;
  organization_id: number;
  observation_id: number;
  part_id: number;
  part: Part;
  rank: number;
  confidence: number;
  reason: string;
  status: PartRecognitionStatus;
  version: number;
  employee_confirmed_by?: number | null;
  employee_confirmed_at?: string | null;
  admin_confirmed_by?: number | null;
  admin_confirmed_at?: string | null;
  usage_verified_by?: number | null;
  usage_verified_at?: string | null;
  trusted_at?: string | null;
  rejected_by?: number | null;
  rejected_at?: string | null;
  rejection_reason?: string | null;
  can_employee_confirm: boolean;
  can_admin_confirm: boolean;
  can_verify_usage: boolean;
  can_promote_trusted: boolean;
  can_reject: boolean;
  created_at: string;
  updated_at: string;
}

export interface PartRecognitionObservation {
  id: number;
  organization_id: number;
  work_order_id?: number | null;
  machine_model?: string | null;
  label_text?: string | null;
  image_url: string;
  notes?: string | null;
  analysis_status: PartRecognitionAnalysisStatus;
  analysis_version: number;
  latest_analysis?: PartRecognitionAnalysis | null;
  can_analyze: boolean;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
  candidates: PartRecognitionCandidate[];
}

export type MachineKnowledgeEntryType =
  | "fault"
  | "repair_step"
  | "tool"
  | "caution"
  | "common_error"
  | "photo"
  | "video"
  | "note";

export type MachineKnowledgeStatus = "draft" | "published" | "archived";
export type MachineKnowledgePartRole =
  | "recommended"
  | "alternative"
  | "consumable"
  | "reference";

export interface MachineKnowledgePart {
  id: number;
  part_number: string;
  name: string;
  image_url?: string | null;
  recognition_source?: string | null;
  confidence?: number | null;
  confirmed_count?: number | null;
}

export interface MachineKnowledgeEvidence {
  completed_work_orders: number;
  labeled_outcomes: number;
  first_time_fix_rate?: number | null;
  average_repair_minutes?: number | null;
  latest_completed_at?: string | null;
}

export interface MachineKnowledgeEntry {
  id: number;
  organization_id: number;
  profile_id: number;
  entry_type: MachineKnowledgeEntryType;
  title: string;
  content: string;
  fault_code?: string | null;
  related_part?: MachineKnowledgePart | null;
  related_part_role?: MachineKnowledgePartRole | null;
  alternative_for_part?: MachineKnowledgePart | null;
  installation_location?: string | null;
  source_work_order_id?: number | null;
  media_url?: string | null;
  media_mime_type?: string | null;
  media_size_bytes?: number | null;
  sort_order: number;
  status: MachineKnowledgeStatus;
  version: number;
  created_by?: number | null;
  updated_by?: number | null;
  published_by?: number | null;
  published_at?: string | null;
  archived_by?: number | null;
  archived_at?: string | null;
  can_edit: boolean;
  can_publish: boolean;
  can_archive: boolean;
  can_reopen: boolean;
  created_at: string;
  updated_at: string;
}

export interface MachineKnowledgeDraftGeneration {
  profile: MachineKnowledgeProfile;
  created_entries: number;
  skipped_entries: number;
}

export interface MachineKnowledgeProfile {
  id: number;
  organization_id: number;
  manufacturer?: string | null;
  model: string;
  equipment_type?: string | null;
  summary?: string | null;
  version: number;
  is_active: boolean;
  created_by?: number | null;
  updated_by?: number | null;
  can_edit: boolean;
  can_add_entry: boolean;
  entries: MachineKnowledgeEntry[];
  related_parts: MachineKnowledgePart[];
  evidence: MachineKnowledgeEvidence;
  created_at: string;
  updated_at: string;
}

export interface WorkOrder {
  id: number;
  customer_id?: number | null;
  equipment_id?: number | null;
  form_template_id?: number | null;
  form_template_version?: number | null;
  form_version: number;
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
  paused_at?: string | null;
  repair_result?: string | null;
  fault_type?: string | null;
  error_code?: string | null;
  environment_info?: string | null;
  final_outcome?: string | null;
  first_time_fix?: boolean | null;
  is_rework: boolean;
  repair_duration_minutes?: number | null;
  checklist_json?: string | null;
  customer_signature_name?: string | null;
  customer_signature_data?: string | null;
  customer_signed_at?: string | null;
  completion_requested_by?: number | null;
  completion_requested_at?: string | null;
  completion_approved_by?: number | null;
  completion_approved_at?: string | null;
  is_locked?: boolean;
  description?: string | null;
  problem_description?: string | null;
  state?: string | null;
  zip?: string | null;
  started_at?: string | null;
  machine_type?: string | null;
  claimed_by_id?: number | null;
  claimed_at?: string | null;
  claimed_device_id?: number | null;
  claim_version: number;
  completed_by_id?: number | null;
  completed_device_id?: number | null;
  claimed_by_name?: string | null;
  completed_by_name?: string | null;
  completed_device_name?: string | null;
  can_claim: boolean;
  can_edit: boolean;
  can_complete: boolean;
}

export type WorkOrderFormFieldType =
  | "text"
  | "textarea"
  | "number"
  | "boolean"
  | "date"
  | "select"
  | "photo"
  | "signature";

export type WorkOrderFormValue = string | number | boolean | null;

export interface OfflineQueuedResult {
  queued: true;
  queue_id: string;
  queued_at: string;
}

export type WorkOrderFormConflictStatus =
  | "pending"
  | "kept_server"
  | "applied_local"
  | "merged";

export interface WorkOrderFormConflictReceipt {
  id: number;
  status: WorkOrderFormConflictStatus;
  version: number;
}

export interface WorkOrderFormConflict extends WorkOrderFormConflictReceipt {
  organization_id: number;
  work_order_id: number;
  work_order_ticket_number: string;
  client_queue_id: string;
  created_by: number;
  created_by_name: string | null;
  created_device_id: number;
  created_device_name: string | null;
  claim_version: number;
  base_form_version: number;
  server_form_version: number;
  current_server_form_version: number;
  local_values: Record<string, WorkOrderFormValue>;
  server_values: Record<string, WorkOrderFormValue>;
  current_server_values: Record<string, WorkOrderFormValue>;
  resolved_values: Record<string, WorkOrderFormValue> | null;
  resolved_server_form_version: number | null;
  resolution_notes: string | null;
  resolved_by: number | null;
  resolved_by_name: string | null;
  resolved_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkOrderFormField {
  id?: number | null;
  field_key: string;
  label: string;
  field_type: WorkOrderFormFieldType;
  help_text?: string | null;
  placeholder?: string | null;
  default_value?: WorkOrderFormValue;
  options: string[];
  required_at_completion: boolean;
  requires_photo: boolean;
  requires_signature: boolean;
  requires_approval: boolean;
  triggers_notification: boolean;
  affects_inventory: boolean;
  include_in_ai_learning: boolean;
  sort_order: number;
}

export interface WorkOrderFormTemplate {
  id: number;
  organization_id: number;
  name: string;
  industry?: string | null;
  description?: string | null;
  applicable_machine_type?: string | null;
  applicable_job_type?: string | null;
  default_work_order_status: "open" | "scheduled";
  is_active: boolean;
  version: number;
  fields: WorkOrderFormField[];
  created_by?: number | null;
  updated_by?: number | null;
  can_edit: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkOrderForm {
  work_order_id: number;
  template_id?: number | null;
  template_name?: string | null;
  template_version?: number | null;
  form_version: number;
  fields: WorkOrderFormField[];
  values: Record<string, WorkOrderFormValue>;
  missing_required_fields: string[];
  can_edit: boolean;
  is_frozen: boolean;
}

export interface WorkOrderFormAction {
  id: number;
  organization_id: number;
  work_order_id: number;
  work_order_ticket_number: string;
  template_id?: number | null;
  template_name?: string | null;
  field_key: string;
  field_label: string;
  action_type: "notification" | "inventory_review";
  status: "pending" | "acknowledged" | "resolved";
  triggered_form_version: number;
  version: number;
  created_by?: number | null;
  created_by_name?: string | null;
  acknowledged_by?: number | null;
  acknowledged_by_name?: string | null;
  acknowledged_at?: string | null;
  resolved_by?: number | null;
  resolved_by_name?: string | null;
  resolved_at?: string | null;
  resolution_notes?: string | null;
  can_acknowledge: boolean;
  can_resolve: boolean;
  created_at: string;
  updated_at: string;
}

export interface CompletionPolicy {
  id?: number | null;
  organization_id: number;
  job_type?: string | null;
  source: "job_type" | "organization_default" | "legacy_default";
  require_repair_result: boolean;
  require_customer_signature: boolean;
  require_completion_photo: boolean;
  require_all_checklist_items: boolean;
  require_parts_usage: boolean;
  require_manager_approval: boolean;
}

export interface Customer {
  id: number; name: string; account_number?: string | null; contact_name?: string | null;
  email?: string | null; phone?: string | null; address?: string | null; city?: string | null;
  state?: string | null; zip?: string | null; notes?: string | null;
}

export interface Equipment {
  id: number; customer_id?: number | null; asset_tag?: string | null; manufacturer?: string | null;
  model: string; serial_number?: string | null; equipment_type?: string | null; location?: string | null;
  install_date?: string | null; notes?: string | null;
}

export interface ServiceHistoryItem {
  id: number; ticket_number: string; schedule_date?: string | null; job_type?: string | null;
  problem_description?: string | null; repair_result?: string | null; status: string;
  fault_type?: string | null; error_code?: string | null; environment_info?: string | null;
  final_outcome?: string | null; first_time_fix?: boolean | null; is_rework: boolean;
  repair_duration_minutes?: number | null;
  completed_at?: string | null; engineer_id?: number | null;
  parts_used: Array<{ part_number: string; name: string; quantity: number }>;
}

export interface WorkOrderServiceContext {
  customer?: Customer | null; equipment?: Equipment | null; fallback_customer_name?: string | null;
  fallback_contact_phone?: string | null; fallback_equipment_model?: string | null; history: ServiceHistoryItem[];
}

export interface ServiceIntelligencePattern {
  value: string;
  count: number;
}

export interface ServiceIntelligenceFaultAnalysis {
  machine_model?: string | null;
  completed_work_orders: number;
  labeled_outcomes: number;
  first_time_fix_rate?: number | null;
  rework_rate?: number | null;
  average_repair_minutes?: number | null;
  top_fault_types: ServiceIntelligencePattern[];
  top_error_codes: ServiceIntelligencePattern[];
  summary: string;
  warnings: string[];
}

export interface ServiceIntelligenceSimilarWorkOrder {
  id: number;
  ticket_number: string;
  completed_at?: string | null;
  job_type?: string | null;
  problem_description?: string | null;
  fault_type?: string | null;
  error_code?: string | null;
  repair_result?: string | null;
  final_outcome?: string | null;
  first_time_fix?: boolean | null;
  is_rework: boolean;
  repair_duration_minutes?: number | null;
  parts_used: Array<{ part_number: string; name: string; quantity: number }>;
  confidence: number;
  reason: string;
}

export interface ServiceIntelligenceKnowledgeEntry {
  id: number;
  profile_id: number;
  machine_model: string;
  entry_type: MachineKnowledgeEntryType;
  title: string;
  content: string;
  fault_code?: string | null;
  related_part?: MachineKnowledgePart | null;
  related_part_role?: MachineKnowledgePartRole | null;
  alternative_for_part?: MachineKnowledgePart | null;
  installation_location?: string | null;
  media_url?: string | null;
  media_mime_type?: string | null;
  published_at?: string | null;
  confidence: number;
  reason: string;
}

export interface WorkOrderServiceIntelligence {
  work_order_id: number;
  evidence_scope: "organization_completed_work_orders_and_published_exact_model_knowledge";
  fault_analysis: ServiceIntelligenceFaultAnalysis;
  knowledge_entries: ServiceIntelligenceKnowledgeEntry[];
  similar_work_orders: ServiceIntelligenceSimilarWorkOrder[];
}

export interface WorkOrderPartRecommendation {
  part: Part;
  recommended_quantity: number;
  usage_count: number;
  total_quantity: number;
  success_rate?: number | null;
  average_repair_minutes?: number | null;
  available_quantity: number;
  inventory_location?: string | null;
  inventory_warehouse_id?: number | null;
  inventory_location_id?: number | null;
  confidence: number;
  reason: string;
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

export interface WorkOrderVoiceNote {
  id: number;
  work_order_id: number;
  created_by?: number | null;
  audio_url: string;
  mime_type: string;
  duration_seconds?: number | null;
  transcript?: string | null;
  transcription_status: string;
  created_at: string;
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
