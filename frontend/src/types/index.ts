/** API types. Money and quantities arrive as decimal strings and are only parsed for display. */
export type Role = "SERVICE_MANAGER" | "MECHANIC" | "INVENTORY_STAFF" | "ADMIN";
export type Dec = string;

export interface User {
  id: number;
  email: string;
  full_name: string;
  phone: string | null;
  role_code: Role;
  is_active: boolean;
  is_demo: boolean;
  last_login_at: string | null;
  created_at: string;
}
export interface Me extends User {
  permissions: string[];
}
export interface TokenResponse {
  access_token: string;
  expires_in: number;
  user: Me;
}
export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
export interface UserRef {
  id: number;
  full_name: string;
}

export interface VehicleModel {
  id: number;
  name: string;
  is_active: boolean;
  sort_order: number;
}
export interface TaxRate {
  id: number;
  name: string;
  rate: Dec;
  is_active: boolean;
}
export interface Category {
  id: number;
  name: string;
  is_active: boolean;
}
export interface LabourOp {
  id: number;
  code: string;
  name: string;
  description: string;
  default_hours: Dec;
  hourly_rate: Dec;
  tax_rate_id: number | null;
  tax_rate: TaxRate | null;
  sac_code: string;
  is_active: boolean;
}
export interface ChecklistItem {
  id: number;
  label: string;
  category: string;
  is_active: boolean;
  sort_order: number;
}

export interface Customer {
  id: number;
  code: string;
  name: string;
  mobile: string;
  email: string | null;
  alternate_mobile: string | null;
  billing_address: string;
  gstin: string | null;
  email_opt_in: boolean;
  sms_opt_in: boolean;
  whatsapp_opt_in: boolean;
  created_at: string;
}
export interface VehicleBrief {
  id: number;
  registration_number: string;
  model: VehicleModel;
  vin: string | null;
  engine_number: string | null;
  odometer: number;
  is_active: boolean;
}
export interface Vehicle extends VehicleBrief {
  customer: Customer;
  created_at: string;
}
export interface HistoryEntry {
  job_id: number;
  job_number: string;
  visit_at: string;
  status: string;
  odometer: number;
  complaints: string;
  diagnostic_findings: string;
  recommended_repairs?: string;
  spare_parts_notes?: string;
  repairs_completed: string;
  labour: string[];
  parts: { sku: string; name: string; quantity: Dec }[];
  mechanic: string | null;
  invoice_number?: string | null;
  invoice_total?: Dec | null;
}
export interface Lookup {
  registration_number: string;
  found: boolean;
  vehicle: Vehicle | null;
  active_jobs: JobSummary[];
  history: HistoryEntry[];
}

export interface JobSummary {
  id: number;
  job_number: string;
  status: string;
  priority: string;
  job_type: string;
  visit_at: string;
  odometer: number;
  complaints: string;
  estimated_completion_at: string | null;
  rework_count: number;
  returned_for_rework: boolean;
  customer: Customer;
  vehicle: VehicleBrief;
  assigned_mechanic: UserRef | null;
}
export interface JobEvent {
  id: number;
  event_type: string;
  message: string;
  from_status: string | null;
  to_status: string | null;
  actor: UserRef | null;
  created_at: string;
}
export interface Inspection {
  id: number;
  initial_observations: string;
  diagnostic_findings: string;
  recommended_repairs: string;
  spare_parts_notes: string;
  safety_observations: string;
  additional_recommendations: string;
  mechanic_notes: string;
  priority: string;
  submitted_at: string | null;
  updated_at: string;
  /** Inventory's handling of the written list: "" (nothing to do), PENDING (not yet checked),
   *  AVAILABLE / UNAVAILABLE (checked by hand), DONE (older catalogue flow). */
  spare_parts_status: SparePartsStatus;
  spare_parts_done_at: string | null;
  spare_parts_done_note: string;
  spare_parts_unconfirmed: string;
}
export type SparePartsStatus = "" | "PENDING" | "AVAILABLE" | "UNAVAILABLE" | "DONE";
/** A part inventory confirmed by hand for the written list (no stock tracking); billed as entered. */
export interface ManualPart {
  id: number;
  part_id: number | null;
  part: { id: number; sku: string; name: string } | null;
  description: string;
  quantity: Dec;
  unit: string;
  unit_price: Dec;
  hsn_code: string;
  tax_rate_id: number | null;
  tax_rate: { id: number; name: string; rate: Dec } | null;
}
/** A mechanic's written spare parts list, as inventory staff see it. */
export interface SparePartsList {
  job_id: number;
  job_number: string;
  job_status: string;
  registration_number: string;
  model_name: string;
  mechanic_name: string | null;
  notes: string;
  status: SparePartsStatus;
  submitted_at: string | null;
  done_by_name: string | null;
  done_at: string | null;
  done_note: string;
  /** Text added since inventory last confirmed (new list or additional parts). */
  unconfirmed: string;
  parts: ManualPart[];
}
export interface JobLabour {
  id: number;
  code: string;
  description: string;
  estimated_hours: Dec;
  actual_hours: Dec | null;
  hourly_rate: Dec;
  approval_status: string;
  is_additional: boolean;
  notes: string;
}
export interface PartRef {
  id: number;
  sku: string;
  name: string;
  selling_price: Dec;
  storage_location: string;
}
export interface PartsLine {
  id: number;
  request_id: number;
  part: PartRef;
  original_part: PartRef | null;
  alt_part: PartRef | null;
  alt_status: string | null;
  alt_notes: string;
  qty_requested: Dec;
  qty_approved: Dec;
  qty_reserved: Dec;
  qty_issued: Dec;
  qty_returned: Dec;
  qty_consumed: Dec | null;
  qty_outstanding: Dec;
  qty_unreconciled: Dec;
  urgency: string;
  notes: string;
  status: string;
  approval_status: string;
  is_short: boolean;
  expected_restock_date: string | null;
  inventory_notes: string;
  cancel_reason: string | null;
}
export interface PartsRequest {
  id: number;
  request_number: string;
  job_id: number;
  status: string;
  is_additional: boolean;
  notes: string;
  created_at: string;
  requested_by: UserRef;
  lines: PartsLine[];
  job?: {
    id: number;
    job_number: string;
    status: string;
    registration_number: string;
    model_name: string;
    mechanic_name: string | null;
  };
}
export interface DocLine {
  id: number;
  line_type: "LABOUR" | "PART";
  code: string;
  description: string;
  hsn_code?: string;
  unit?: string;
  /** Item the Service Manager added to the draft bill by hand. */
  is_custom?: boolean;
  price_override?: Dec | null;
  quantity: Dec;
  unit_price: Dec;
  discount_amount: Dec;
  tax_name?: string;
  tax_rate: Dec;
  tax_amount: Dec;
  line_total: Dec;
}
export interface Estimate {
  id: number;
  job_id: number;
  version: number;
  status: string;
  notes: string;
  terms: string;
  subtotal_labour: Dec;
  subtotal_parts: Dec;
  discount_total: Dec;
  tax_total: Dec;
  total: Dec;
  sent_at: string | null;
  decided_at: string | null;
  created_at: string;
  lines: DocLine[];
  approvals: { id: number; decision: string; method: string; notes: string; decided_at: string }[];
}
export interface Completion {
  id: number;
  repairs_completed: string;
  outstanding_issues: string;
  final_observations: string;
  completed_at: string;
  mechanic: UserRef;
}
export interface QualityInspection {
  id: number;
  result: string;
  reason: string;
  road_test_notes: string;
  created_at: string;
  inspector: UserRef;
  results: { checklist_item_id: number; label: string; passed: boolean | null; notes: string }[];
}
export interface InvoiceSummary {
  id: number;
  invoice_number: string | null;
  job_id: number;
  job_number: string;
  status: string;
  payment_status: string;
  customer_name: string;
  customer_mobile: string | null;
  vehicle_registration: string;
  vehicle_model: string;
  total: Dec;
  amount_paid: Dec;
  outstanding: Dec;
  finalised_at: string | null;
  created_at: string;
}
export interface Payment {
  id: number;
  reference: string;
  amount: Dec;
  method: string;
  paid_at: string;
  external_reference: string;
  notes: string;
  recorded_by: UserRef;
  voided_at: string | null;
  void_reason: string | null;
}
export type Channel = "EMAIL" | "SMS" | "WHATSAPP";
export interface Delivery {
  id: number;
  kind: "INVOICE" | "PAYMENT_REMINDER" | "SERVICE_REMINDER";
  invoice_id: number | null;
  vehicle_id: number | null;
  channel: Channel;
  destination: string;
  status: string;
  display_status: string;
  trigger: string;
  attempt_count: number;
  max_attempts: number;
  next_attempt_at: string;
  provider: string;
  receipts_supported: boolean;
  simulated: boolean;
  last_error: string | null;
  last_attempt_at: string | null;
  sent_at: string | null;
  delivered_at: string | null;
  created_at: string;
  attempts: {
    id: number;
    attempt_number: number;
    started_at: string;
    finished_at: string;
    outcome: string;
    provider: string;
    error: string | null;
  }[];
}
export interface TaxBreakdownRow {
  name: string;
  rate: Dec;
  taxable: Dec;
  tax: Dec;
  cgst?: Dec;
  sgst?: Dec;
}
export interface HsnSummaryRow {
  hsn_code: string;
  rate: Dec;
  taxable: Dec;
  tax: Dec;
  cgst_rate?: Dec;
  cgst?: Dec;
  sgst_rate?: Dec;
  sgst?: Dec;
}
export interface Centre {
  name: string;
  address: string;
  phone: string;
  email: string;
  gstin: string;
  other_registration?: string;
  pan?: string;
  state_name?: string;
  state_code?: string;
  declaration?: string;
  gst_split_intra_state?: boolean;
}
export interface Invoice extends InvoiceSummary {
  customer_id: number;
  customer_email: string | null;
  billing_address: string;
  customer_gstin: string | null;
  centre: Centre;
  subtotal_labour: Dec;
  subtotal_parts: Dec;
  discount_total: Dec;
  taxable_total: Dec;
  tax_total: Dec;
  notes: string;
  terms: string;
  cancel_reason: string | null;
  cancelled_at: string | null;
  lines: DocLine[];
  payments: Payment[];
  tax_breakdown: TaxBreakdownRow[];
  hsn_summary: HsnSummaryRow[];
  round_off: Dec;
  total_in_words: string;
  tax_in_words: string;
  delivery_jobs: Delivery[];
  links: {
    id: number;
    expires_at: string;
    revoked_at: string | null;
    created_at: string;
    last_accessed_at: string | null;
    access_count: number;
    usable: boolean;
  }[];
}
export interface JobDetail extends JobSummary {
  fuel_level: string;
  condition_notes: string;
  hold_reason: string | null;
  cancel_reason: string | null;
  active_job_override_reason: string | null;
  ready_for_delivery_at: string | null;
  delivered_at: string | null;
  handover_to: string | null;
  handover_notes: string | null;
  created_at: string;
  events: JobEvent[];
  photos: { id: number; original_name: string; content_type: string; size_bytes: number; created_at: string }[];
  inspection: Inspection | null;
  labour: JobLabour[];
  parts_requests: PartsRequest[];
  manual_parts: ManualPart[];
  completions: Completion[];
  quality_inspections: QualityInspection[];
  estimates: Estimate[];
  invoices: InvoiceSummary[];
  billing_blockers: string[];
  pending_approvals: string[];
}

export interface Supplier {
  id: number;
  name: string;
  contact_name: string;
  phone: string;
  email: string;
  address: string;
  is_active: boolean;
}
export interface Part {
  id: number;
  sku: string;
  name: string;
  description: string;
  category: Category | null;
  purchase_cost?: Dec;
  selling_price: Dec;
  tax_rate?: TaxRate | null;
  reorder_threshold?: Dec;
  supplier?: Supplier | null;
  storage_location: string;
  hsn_code?: string;
  unit?: string;
  is_active: boolean;
  stock: { qty_on_hand: Dec; qty_reserved: Dec; qty_available: Dec };
  compatible_models: VehicleModel[];
  // The parts sheet's own columns, as last synced (not sent to catalogue-only roles).
  dms_bin?: string;
  dms_category?: string;
  movement_class?: string;
  abc_class?: string;
  hml_class?: string;
  ris_class?: string;
  sheet_closing_qty?: Dec | null;
  sheet_closing_value?: Dec | null;
  sheet_actual_qty?: Dec | null;
}
export interface Movement {
  id: number;
  part: { id: number; sku: string; name: string };
  movement_type: string;
  quantity: Dec;
  on_hand_after: Dec;
  reserved_after: Dec;
  job_id: number | null;
  job_number: string | null;
  reason: string;
  performed_by: UserRef;
  created_at: string;
}
export interface PurchaseRequest {
  id: number;
  pr_number: string;
  status: string;
  notes: string;
  supplier: Supplier | null;
  created_by: UserRef;
  decided_by: UserRef | null;
  decided_at: string | null;
  decision_notes: string;
  received_at: string | null;
  created_at: string;
  lines: {
    id: number;
    part: { id: number; sku: string; name: string };
    quantity: Dec;
    qty_received: Dec;
    unit_cost: Dec;
    parts_request_line_id: number | null;
  }[];
}
export interface Notification {
  id: number;
  type: string;
  title: string;
  message: string;
  entity_type: string | null;
  entity_id: number | null;
  is_read: boolean;
  created_at: string;
}
export interface AuditEntry {
  id: number;
  actor_email: string;
  actor_role: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  details: Record<string, unknown> | null;
  created_at: string;
}
export interface ReportColumn {
  key: string;
  label: string;
  type: "text" | "number" | "money" | "date" | "datetime" | "status";
}
export interface Report {
  title: string;
  columns: ReportColumn[];
  rows: Record<string, string | number | null>[];
  summary: Record<string, string | number | null>;
  chart?: { x: string; series: string[] };
  date_from: string;
  date_to: string;
}
export interface Dashboard {
  role: Role;
  generated_at: string;
  cards: Record<string, number | string | Record<string, number>>;
  /** Open jobs by status (manager: all, mechanic: own). */
  pipeline?: Record<string, number>;
  /** Last 7 days, oldest first: { date, <series>: value }. */
  trend?: ({ date: string } & Record<string, number | string>)[];
  /** Inventory: parts at or below their reorder level. */
  low_stock?: { id: number; sku: string; name: string; available: Dec; threshold: Dec }[];
}
