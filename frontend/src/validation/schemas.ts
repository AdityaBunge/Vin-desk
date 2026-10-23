import { z } from "zod";
import { normaliseRegistration } from "@/lib/format";

const text = (max = 4000) => z.string().trim().max(max);
const required = (label: string, max = 160) => z.string().trim().min(1, `${label} is required`).max(max);

/** Accepts 9822012345, 09822012345, +91 98220 12345. */
export const indianMobile = z
  .string()
  .trim()
  .refine((v) => /^[6-9]\d{9}$/.test(v.replace(/\D/g, "").replace(/^(91|0)(?=\d{10}$)/, "")), "Enter a valid 10-digit Indian mobile number");

/** Blank, or a 15-character GSTIN such as 27AAALM4691H1ZS (case-insensitive). */
const optionalGstin = z.union([
  z.literal(""),
  z.string().trim().regex(/^[0-9]{2}[A-Za-z]{5}[0-9]{4}[A-Za-z][1-9A-Za-z][Zz][0-9A-Za-z]$/, "Enter a valid 15-character GSTIN, e.g. 27AAALM4691H1ZS"),
]);
const decimal = (label: string) =>
  z.string().trim().regex(/^\d+(\.\d{1,2})?$/, `${label} must be a number with up to 2 decimals`);

export const loginSchema = z.object({
  email: z.string().trim().min(1, "Email is required"),
  password: z.string().min(1, "Password is required"),
});
export type LoginValues = z.infer<typeof loginSchema>;

export const customerSchema = z.object({
  name: required("Customer name", 120),
  mobile: indianMobile,
  email: z.string().trim().min(1, "Email address is required").email("Enter a valid email address"),
  alternate_mobile: z.union([z.literal(""), indianMobile]),
  billing_address: text(1000),
  gstin: optionalGstin,
  email_opt_in: z.boolean(),
  sms_opt_in: z.boolean(),
  whatsapp_opt_in: z.boolean(),
});
export type CustomerValues = z.infer<typeof customerSchema>;

export const vehicleSchema = z.object({
  registration_number: z.string().trim().refine((v) => normaliseRegistration(v).length >= 4, "Enter a valid registration number"),
  model_id: z.string().min(1, "Select the vehicle model"),
  vin: text(40),
  engine_number: text(40),
});
export type VehicleValues = z.infer<typeof vehicleSchema>;

export const visitSchema = z.object({
  odometer: z.string().trim().regex(/^\d{1,7}$/, "Enter the odometer reading in km"),
  fuel_level: z.enum(["EMPTY", "QUARTER", "HALF", "THREE_QUARTER", "FULL"]),
  complaints: z.string().trim().min(3, "Describe the customer's complaints").max(4000),
  condition_notes: text(),
  priority: z.enum(["LOW", "NORMAL", "HIGH", "URGENT"]),
  job_type: z.enum(["PAID", "FREE_SERVICE", "WARRANTY", "ACCIDENT"]),
  estimated_completion_at: z.string(),
  mechanic_id: z.string(),
  override_reason: text(),
});
export type VisitValues = z.infer<typeof visitSchema>;

export const paymentSchema = z.object({
  amount: decimal("Amount").refine((v) => Number(v) > 0, "Amount must be greater than zero"),
  method: z.enum(["CASH", "CARD", "UPI", "BANK_TRANSFER"]),
  external_reference: text(80),
  notes: text(1000),
});
export type PaymentValues = z.infer<typeof paymentSchema>;

export const partSchema = z.object({
  sku: required("Part number", 40),
  name: required("Part name"),
  description: text(),
  category_id: z.string(),
  purchase_cost: decimal("Purchase cost"),
  selling_price: decimal("Selling price"),
  tax_rate_id: z.string(),
  reorder_threshold: decimal("Reorder threshold"),
  supplier_id: z.string(),
  storage_location: text(60),
  hsn_code: z.string().trim().regex(/^(\d{4,8})?$/, "HSN code is 4 to 8 digits"),
  unit: required("Unit", 10),
  is_active: z.boolean(),
  compatible_model_ids: z.array(z.string()),
});
export type PartValues = z.infer<typeof partSchema>;

export const userSchema = z.object({
  email: z.string().trim().email("Enter a valid email address"),
  full_name: required("Full name", 120),
  phone: text(20),
  role_code: z.enum(["SERVICE_MANAGER", "MECHANIC", "INVENTORY_STAFF", "ADMIN"]),
  password: z.union([z.literal(""), z.string().min(10, "Use at least 10 characters").max(72)]),
  is_active: z.boolean(),
});
export type UserValues = z.infer<typeof userSchema>;

export const inspectionSchema = z.object({
  recommended_repairs: text(),
  // Picked from the catalogue ("SKU · Name - qty" per line) or written; stored as text on the inspection.
  spare_parts_notes: text(),
  priority: z.enum(["LOW", "NORMAL", "HIGH", "URGENT"]),
});
export type InspectionValues = z.infer<typeof inspectionSchema>;
