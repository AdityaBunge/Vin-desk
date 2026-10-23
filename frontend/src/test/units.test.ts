import { describe, expect, it } from "vitest";
import { label, mobileDisplay, money, normaliseRegistration, qty } from "@/lib/format";
import { ApiError, parseError } from "@/services/api";
import { parseSpareLines } from "@/features/job/shared";
import { parseWrittenList } from "@/pages/PartsRequests";
import { customerSchema, paymentSchema, vehicleSchema, visitSchema } from "@/validation/schemas";

describe("formatting", () => {
  it("formats money with Indian digit grouping", () => {
    expect(money("1234567.5")).toBe("12,34,567.50");
    expect(money("8500")).toBe("8,500.00");
    expect(money(null)).toBe("-");
  });
  it("trims quantities and humanises statuses", () => {
    expect(qty("2.00")).toBe("2");
    expect(qty("1.50")).toBe("1.5");
    expect(label("AWAITING_PARTS")).toBe("Awaiting parts");
    expect(mobileDisplay("+919822012345")).toBe("+91 98220 12345");
  });
  it("normalises registration numbers like the backend", () => {
    expect(normaliseRegistration("mh 12-ab 1234")).toBe("MH12AB1234");
  });
});

describe("API error parsing", () => {
  it("reads plain, structured and validation errors", () => {
    expect(parseError(409, { detail: "Insufficient stock" }).message).toBe("Insufficient stock");
    const structured = parseError(409, { detail: { code: "ACTIVE_JOB_EXISTS", message: "Already open", active_jobs: [] } });
    expect(structured).toBeInstanceOf(ApiError);
    expect(structured.code).toBe("ACTIVE_JOB_EXISTS");
    expect(parseError(422, { detail: [{ loc: ["body", "mobile"], msg: "Enter a valid number" }] }).message).toBe("mobile: Enter a valid number");
    expect(parseError(500, null).message).toMatch(/server/i);
  });
});

describe("form validation", () => {
  const customer = { name: "Ganesh Tours", mobile: "98220 12345", email: "owner@example.com", alternate_mobile: "", billing_address: "", gstin: "", email_opt_in: true, sms_opt_in: true, whatsapp_opt_in: true };
  it("accepts Indian mobile numbers in common formats and rejects others", () => {
    expect(customerSchema.safeParse(customer).success).toBe(true);
    expect(customerSchema.safeParse({ ...customer, mobile: "+91 9822012345" }).success).toBe(true);
    expect(customerSchema.safeParse({ ...customer, mobile: "12345" }).success).toBe(false);
    expect(customerSchema.safeParse({ ...customer, mobile: "5822012345" }).success).toBe(false);
    expect(customerSchema.safeParse({ ...customer, email: "not-an-email" }).success).toBe(false);
    expect(customerSchema.safeParse({ ...customer, email: "" }).success).toBe(false); // email is mandatory
  });
  it("requires a model and a plausible registration", () => {
    expect(vehicleSchema.safeParse({ registration_number: "MH12AB1234", model_id: "5", vin: "", engine_number: "" }).success).toBe(true);
    expect(vehicleSchema.safeParse({ registration_number: "M-1", model_id: "5", vin: "", engine_number: "" }).success).toBe(false);
    expect(vehicleSchema.safeParse({ registration_number: "MH12AB1234", model_id: "", vin: "", engine_number: "" }).success).toBe(false);
  });
  it("requires complaints and a numeric odometer for a visit", () => {
    const visit = { odometer: "84250", fuel_level: "HALF", complaints: "Brake noise", condition_notes: "", priority: "NORMAL", job_type: "PAID", estimated_completion_at: "", mechanic_id: "", override_reason: "" };
    expect(visitSchema.safeParse(visit).success).toBe(true);
    expect(visitSchema.safeParse({ ...visit, odometer: "84,250" }).success).toBe(false);
    expect(visitSchema.safeParse({ ...visit, complaints: " " }).success).toBe(false);
  });
  it("rejects zero, negative or over-precise payment amounts", () => {
    const pay = { amount: "1500.50", method: "UPI", external_reference: "", notes: "" };
    expect(paymentSchema.safeParse(pay).success).toBe(true);
    for (const amount of ["0", "-5", "10.555", "abc"]) expect(paymentSchema.safeParse({ ...pay, amount }).success).toBe(false);
    expect(paymentSchema.safeParse({ ...pay, method: "CHEQUE" }).success).toBe(false);
  });
});

describe("hand-written spare parts list", () => {
  it("splits each line into part and quantity for inventory to check", () => {
    const rows = parseWrittenList("Engine oil 15W-40 (5 L) - 2\nOil - 1\n\nBrake pads x 2 set\noil", "7");
    expect(rows.map((r) => [r.description, r.quantity, r.unit])).toEqual([
      ["Engine oil 15W-40 (5 L)", "2", "NO"],
      ["Oil", "1", "NO"],
      ["Brake pads", "2", "set"],
      ["oil", "1", "NO"],
    ]);
    expect(rows.every((r) => r.unit_price === "" && r.tax_rate_id === "7")).toBe(true);
  });

  it("reads the part number of lines picked from the catalogue, on both sides", () => {
    const text = "A000040110610 · CYLINDER LINER OM016 - M4 - 2\nCoolant - 1";
    expect(parseSpareLines(text)).toEqual([
      { sku: "A000040110610", name: "CYLINDER LINER OM016 - M4", quantity: "2" },
      { sku: null, name: "Coolant", quantity: "1" },
    ]);
    expect(parseWrittenList(text, "").map((r) => [r.sku, r.description, r.quantity])).toEqual([
      ["A000040110610", "CYLINDER LINER OM016 - M4", "2"],
      [undefined, "Coolant", "1"],
    ]);
  });
});
