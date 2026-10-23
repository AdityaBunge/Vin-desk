const inr = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const dateFmt = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" });
const dateTimeFmt = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

/** Format a decimal string/number as Indian rupees: "12,34,567.50". Display only. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n) ? inr.format(n) : "-";
}
export const rupees = (value: string | number | null | undefined) => `₹ ${money(value)}`;

/** Quantity without trailing zeros: "2.00" -> "2", "1.50" -> "1.5". */
export function qty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  const n = Number(value);
  return Number.isFinite(n) ? String(Number(n.toFixed(2))) : "-";
}

export function fmtDate(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value.length === 10 ? `${value}T00:00:00` : value);
  return Number.isNaN(d.getTime()) ? "-" : dateFmt.format(d);
}
export function fmtDateTime(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? "-" : dateTimeFmt.format(d);
}

/** "AWAITING_PARTS" -> "Awaiting parts" */
const CHANNELS: Record<string, string> = { EMAIL: "Email", SMS: "SMS", WHATSAPP: "WhatsApp" };

/** Display name of a message channel (EMAIL, SMS, WHATSAPP). */
export function channelLabel(channel: string): string {
  return CHANNELS[channel] ?? label(channel);
}

export function label(value: string | null | undefined): string {
  if (!value) return "-";
  const text = value.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Matches the backend normalisation so searches behave the same on both sides. */
export function normaliseRegistration(raw: string): string {
  return raw.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

export function mobileDisplay(value: string | null | undefined): string {
  if (!value) return "-";
  const m = /^\+91(\d{5})(\d{5})$/.exec(value);
  return m ? `+91 ${m[1]} ${m[2]}` : value;
}

export const JOB_TYPE_LABEL: Record<string, string> = {
  PAID: "Paid",
  FREE_SERVICE: "Free service",
  WARRANTY: "Warranty",
  ACCIDENT: "Accident / insurance",
};

export const ROLE_LABEL: Record<string, string> = {
  SERVICE_MANAGER: "Service Manager",
  MECHANIC: "Mechanic",
  INVENTORY_STAFF: "Inventory Staff",
  ADMIN: "Administrator",
};

export function todayISO(offsetDays = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
