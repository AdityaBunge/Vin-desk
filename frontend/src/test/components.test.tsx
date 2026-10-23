import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "@/App";
import { DataTable } from "@/components/DataTable";
import { ConfirmProvider, StatusBadge, ToastProvider } from "@/components/ui";
import { DeliveryPanel } from "@/features/invoice/DeliveryPanel";
import { InvoiceDocument } from "@/features/invoice/InvoiceDocument";
import { AuthProvider } from "@/hooks/useAuth";
import PublicInvoice from "@/pages/PublicInvoice";
import type { Delivery, Invoice, Me } from "@/types";

type Handler = (url: URL, init?: RequestInit) => unknown | [number, unknown];

/** Replace fetch with a route table: { "POST /api/auth/login": handler }. */
function mockApi(routes: Record<string, Handler>) {
  const calls: { key: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    const key = `${init?.method ?? "GET"} ${url.pathname}`;
    calls.push({ key, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const handler = routes[key];
    if (!handler) return new Response(JSON.stringify({ detail: `no mock for ${key}` }), { status: 404 });
    const result = handler(url, init);
    const [status, body] = Array.isArray(result) ? (result as [number, unknown]) : [200, result];
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  }));
  return calls;
}

function Providers({ children, path = "/" }: { children: ReactNode; path?: string }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider><ConfirmProvider><AuthProvider>{children}</AuthProvider></ConfirmProvider></ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>
  );
}

const me = (role: Me["role_code"], permissions: string[]): Me => ({
  id: 1, email: "u@example.com", full_name: "Test User", phone: null, role_code: role, is_active: true, is_demo: false,
  last_login_at: null, created_at: "2026-01-01T00:00:00Z", permissions,
});
const session = (user: Me) => ({ access_token: "token", expires_in: 1800, user });

const delivery = (over: Partial<Delivery>): Delivery => ({
  id: 1, kind: "INVOICE", invoice_id: 7, vehicle_id: null, channel: "EMAIL", destination: "owner@example.com", status: "SENT", display_status: "SENT", trigger: "AUTO",
  attempt_count: 1, max_attempts: 5, next_attempt_at: "2026-01-01T10:00:00Z", provider: "smtp", receipts_supported: true, simulated: false,
  last_error: null, last_attempt_at: "2026-01-01T10:00:00Z", sent_at: "2026-01-01T10:00:00Z", delivered_at: null, created_at: "2026-01-01T10:00:00Z", attempts: [], ...over,
});
const invoice = (jobs: Delivery[]): Invoice => ({
  id: 7, invoice_number: "INV-2026-0001", job_id: 3, job_number: "SC-2026-0001", status: "FINALISED", payment_status: "UNPAID",
  customer_name: "Ganesh Tours", customer_mobile: "+919822012345", vehicle_registration: "MH12AB1234", vehicle_model: "Force Traveller",
  total: "8500.00", amount_paid: "0.00", outstanding: "8500.00", finalised_at: "2026-01-01T10:00:00Z", created_at: "2026-01-01T09:00:00Z",
  customer_id: 2, customer_email: "owner@example.com", billing_address: "Pune", centre: { name: "Sahyadri Force", address: "", phone: "", email: "", gstin: "" },
  subtotal_labour: "1300.00", subtotal_parts: "5900.00", discount_total: "0.00", taxable_total: "7200.00", tax_total: "1300.00", notes: "", terms: "",
  cancel_reason: null, cancelled_at: null, lines: [], payments: [], tax_breakdown: [], delivery_jobs: jobs,
  customer_gstin: null, hsn_summary: [], round_off: "0.00", total_in_words: "", tax_in_words: "",
  links: [{ id: 1, expires_at: "2026-02-01T00:00:00Z", revoked_at: null, created_at: "2026-01-01T10:00:00Z", last_accessed_at: null, access_count: 0, usable: true }],
});

describe("sign-in and role-based navigation", () => {
  it("shows the login form when there is no session and signs in", async () => {
    const manager = me("SERVICE_MANAGER", ["reception.manage", "job.read_all", "customer.read", "invoice.read", "report.view"]);
    const calls = mockApi({
      "POST /api/auth/refresh": () => [401, { detail: "Session expired" }],
      "POST /api/auth/login": () => session(manager),
      "GET /api/dashboard": () => ({ role: "SERVICE_MANAGER", generated_at: "2026-01-01T10:00:00Z", cards: { awaiting_assignment: 3, outstanding_total: "12500.00" } }),
      "GET /api/notifications/unread-count": () => ({ unread: 2 }),
      "GET /api/jobs": () => ({ items: [], total: 0, page: 1, page_size: 8 }),
    });
    render(<Providers path="/"><App /></Providers>);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email/i), "manager@demo.local");
    await user.type(screen.getByLabelText(/password/i), "Demo@12345");
    await user.click(screen.getByRole("button", { name: /sign in/i }));

    expect(await screen.findByRole("heading", { name: /service manager dashboard/i })).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/auth/login")?.body).toEqual({ email: "manager@demo.local", password: "Demo@12345" });
    const nav = screen.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(nav).getByRole("link", { name: "New Service Visit" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Invoices" })).toBeInTheDocument();
    expect(within(nav).queryByRole("link", { name: "Users & Roles" })).not.toBeInTheDocument();
    expect(await screen.findByText("Awaiting mechanic assignment")).toBeInTheDocument();
    expect(await screen.findByText("₹ 12,500.00")).toBeInTheDocument();
  });

  it("shows a failed sign-in message from the server", async () => {
    mockApi({ "POST /api/auth/refresh": () => [401, {}], "POST /api/auth/login": () => [401, { detail: "Invalid email or password" }] });
    render(<Providers><App /></Providers>);
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText(/email/i), "x@y.z");
    await user.type(screen.getByLabelText(/password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
  });

  it("limits a mechanic's navigation and blocks other pages", async () => {
    mockApi({
      "POST /api/auth/refresh": () => session(me("MECHANIC", ["job.read_assigned", "job.work", "parts.read", "masterdata.read"])),
      "GET /api/notifications/unread-count": () => ({ unread: 0 }),
    });
    render(<Providers path="/invoices"><App /></Providers>);
    expect(await screen.findByText(/do not have access to this page/i)).toBeInTheDocument();
    const nav = screen.getAllByRole("navigation", { name: "Main" })[0];
    expect(within(nav).getByRole("link", { name: "My Jobs" })).toBeInTheDocument();
    for (const hidden of ["Invoices", "New Service Visit", "Parts Requests", "Settings"]) {
      expect(within(nav).queryByRole("link", { name: hidden })).not.toBeInTheDocument();
    }
  });
});

describe("invoice delivery panel", () => {
  const renderPanel = (jobs: Delivery[]) => {
    const calls = mockApi({
      "POST /api/auth/refresh": () => session(me("SERVICE_MANAGER", ["delivery.manage"])),
      "POST /api/deliveries/2/retry": () => delivery({ id: 2, channel: "SMS", status: "PENDING" }),
      "POST /api/invoices/7/resend": () => [201, delivery({ id: 3, trigger: "MANUAL", status: "PENDING" })],
    });
    render(<Providers><DeliveryPanel invoice={invoice(jobs)} /></Providers>);
    return calls;
  };

  it("never presents provider acceptance as delivered, and shows failures per channel", () => {
    renderPanel([
      delivery({}),
      delivery({ id: 2, channel: "SMS", destination: "+919822012345", status: "FAILED", display_status: "FAILED", last_error: "SMS gateway rejected the request", provider: "msg91" }),
    ]);
    expect(screen.getByText("Sent (awaiting receipt)")).toBeInTheDocument();
    expect(screen.queryByText("Delivered")).not.toBeInTheDocument();
    expect(screen.getByText("Failed")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("SMS gateway rejected the request");
    expect(screen.getByRole("button", { name: "Retry SMS" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Retry Email" })).not.toBeInTheDocument();
  });

  it("retries only the failed channel", async () => {
    const calls = renderPanel([delivery({}), delivery({ id: 2, channel: "SMS", status: "FAILED", display_status: "FAILED", last_error: "rejected" })]);
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry SMS" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/deliveries/2/retry")).toBe(true));
    expect(calls.some((c) => c.key.includes("/resend"))).toBe(false);
  });

  it("asks for confirmation before a manual resend and sends the explicit confirm flag", async () => {
    const calls = renderPanel([delivery({}), delivery({ id: 2, channel: "SMS", status: "SENT", display_status: "DELIVERY_STATUS_UNKNOWN" })]);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Resend Email" }));
    expect(calls.some((c) => c.key.includes("/resend"))).toBe(false); // nothing sent before confirming
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Other channels are not affected");
    await user.click(within(dialog).getByRole("button", { name: "Resend Email" }));
    await waitFor(() => expect(calls.find((c) => c.key === "POST /api/invoices/7/resend")?.body).toEqual({ channel: "EMAIL", confirm: true }));
  });

  it("labels simulated deliveries and disables resend while a delivery is in progress", () => {
    renderPanel([delivery({ simulated: true, display_status: "SIMULATED", provider: "dev-simulator" }), delivery({ id: 2, channel: "SMS", status: "RETRY_SCHEDULED", display_status: "RETRY_SCHEDULED" })]);
    expect(screen.getByText("Simulated (not sent)")).toBeInTheDocument();
    expect(screen.getByText(/development simulator/i, { selector: "strong" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Resend SMS" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Resend Email" })).toBeEnabled();
  });

  it("shows WhatsApp and sends a payment reminder after confirmation", async () => {
    const calls = mockApi({
      "POST /api/auth/refresh": () => session(me("SERVICE_MANAGER", ["delivery.manage"])),
      "GET /api/features": () => ({ sms: false, whatsapp: true, parts_sheet: false }),
      "POST /api/invoices/7/payment-reminder": () => [201, delivery({ id: 5, kind: "PAYMENT_REMINDER", channel: "WHATSAPP", trigger: "MANUAL", status: "PENDING" })],
    });
    const jobs = [delivery({}), delivery({ id: 2, channel: "WHATSAPP", destination: "+919822012345", provider: "meta-whatsapp" }),
      delivery({ id: 4, kind: "PAYMENT_REMINDER", channel: "WHATSAPP", status: "CANCELLED", display_status: "CANCELLED", last_error: "Not sent: the invoice has been paid" })];
    render(<Providers><DeliveryPanel invoice={invoice(jobs)} /></Providers>);
    expect(await screen.findByRole("button", { name: "Resend WhatsApp" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Resend SMS" })).not.toBeInTheDocument();
    expect(screen.getByText("Payment reminders (WhatsApp)")).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Send payment reminder" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Send reminder" }));
    await waitFor(() => expect(calls.some((c) => c.key === "POST /api/invoices/7/payment-reminder")).toBe(true));
  });
});

describe("invoice rendering", () => {
  const view = {
    centre: { name: "Sahyadri Force", address: "Pune", phone: "020", email: "", gstin: "27ABCDE1234F1Z5" }, invoice_number: "INV-2026-0001",
    date: "2026-01-01T10:00:00Z", job_number: "SC-2026-0001", customer_name: "Ganesh Tours", vehicle_registration: "MH12AB1234", vehicle_model: "Force Traveller",
    lines: [
      { line_type: "LABOUR" as const, code: "LAB-GS", description: "General service", quantity: "2.00", unit_price: "650.00", discount_amount: "0.00", tax_rate: "18.00", tax_amount: "234.00", line_total: "1534.00" },
      { line_type: "PART" as const, code: "FM-OIL", description: "Engine oil", quantity: "1.00", unit_price: "1950.00", discount_amount: "0.00", tax_rate: "18.00", tax_amount: "351.00", line_total: "2301.00" },
    ],
    subtotal_labour: "1300.00", subtotal_parts: "1950.00", discount_total: "0.00", tax_total: "585.00",
    tax_breakdown: [{ name: "GST 18%", rate: "18.00", taxable: "3250.00", tax: "585.00", cgst: "292.50", sgst: "292.50" }],
    total: "3835.00", amount_paid: "1000.00", outstanding: "2835.00", payment_status: "PARTIALLY_PAID",
  };

  it("renders a GST tax invoice with HSN/SAC, CGST/SGST, total in words and party GSTIN", () => {
    render(<InvoiceDocument invoice={{
      ...view, customer_gstin: "27AAALM4691H1ZS", total: "3835.00", round_off: "0.00",
      total_in_words: "INR Three Thousand Eight Hundred Thirty Five Only", tax_in_words: "INR Five Hundred Eighty Five Only",
      centre: { ...view.centre, pan: "AAVFB6252C" },
      lines: view.lines.map((l) => ({ ...l, hsn_code: l.line_type === "PART" ? "27101980" : "998714", unit: l.line_type === "PART" ? "Nos" : "HRS" })),
      hsn_summary: [
        { hsn_code: "27101980", rate: "18.00", taxable: "1950.00", tax: "351.00", cgst_rate: "9.00", cgst: "175.50", sgst_rate: "9.00", sgst: "175.50" },
        { hsn_code: "998714", rate: "18.00", taxable: "1300.00", tax: "234.00", cgst_rate: "9.00", cgst: "117.00", sgst_rate: "9.00", sgst: "117.00" },
      ],
    }} />);
    expect(screen.getByText("INV-2026-0001")).toBeInTheDocument();
    expect(screen.getByText("Tax Invoice")).toBeInTheDocument();
    for (const h of ["Description of Goods and Services", "HSN/SAC", "Quantity", "Rate", "per", "Amount"]) {
      expect(screen.getAllByRole("columnheader", { name: h }).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("GENERAL SERVICE", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("1 Nos")).toBeInTheDocument(); // quantity with unit; labour shows no quantity
    expect(screen.getByText("₹ 3,835.00")).toBeInTheDocument();
    expect(screen.getByText("INR Three Thousand Eight Hundred Thirty Five Only")).toBeInTheDocument();
    expect(screen.getAllByText("292.50")).toHaveLength(4); // CGST and SGST rows plus the HSN summary totals
    expect(screen.getByText("GSTIN/UIN: 27ABCDE1234F1Z5")).toBeInTheDocument();
    expect(screen.getByText("GSTIN/UIN : 27AAALM4691H1ZS")).toBeInTheDocument();
    expect(screen.getByText("AAVFB6252C")).toBeInTheDocument();
    expect(screen.getByText("Authorised Signatory")).toBeInTheDocument();
  });

  it("renders the customer's secure invoice page without signing in", async () => {
    mockApi({ "GET /api/public/invoices/abc.def": () => ({ ...view, invoice_date: view.date, date: undefined }) });
    render(<Providers path="/i/abc.def"><Routes><Route path="/i/:token" element={<PublicInvoice />} /></Routes></Providers>);
    expect(await screen.findByText("INV-2026-0001")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /download pdf/i })).toHaveAttribute("href", "/api/public/invoices/abc.def/pdf");
    expect(screen.getByText(/Thank you for choosing Sahyadri Force/)).toBeInTheDocument();
  });

  it("explains an expired link without revealing invoice details", async () => {
    mockApi({ "GET /api/public/invoices/old.token": () => [410, { detail: "This invoice link has expired." }] });
    render(<Providers path="/i/old.token"><Routes><Route path="/i/:token" element={<PublicInvoice />} /></Routes></Providers>);
    expect(await screen.findByRole("alert")).toHaveTextContent("This invoice link has expired");
    expect(screen.queryByText(/INV-/)).not.toBeInTheDocument();
  });
});

describe("responsive data table", () => {
  const rows = [{ id: 1, number: "SC-2026-0001", status: "IN_SERVICE" }];
  const columns = [
    { id: "number", header: "Job card", cell: ({ row }: { row: { original: (typeof rows)[0] } }) => row.original.number },
    { id: "status", header: "Status", cell: ({ row }: { row: { original: (typeof rows)[0] } }) => <StatusBadge status={row.original.status} /> },
  ];
  const stubWidth = (phone: boolean) =>
    vi.stubGlobal("matchMedia", (query: string) => ({ matches: phone, media: query, addEventListener: () => {}, removeEventListener: () => {} }));

  it("renders a table on wide screens", () => {
    stubWidth(false);
    render(<DataTable columns={columns} data={rows} />);
    expect(screen.getByRole("columnheader", { name: "Job card" })).toBeInTheDocument();
  });

  it("renders tappable cards with labelled values on phones", async () => {
    stubWidth(true);
    const onRowClick = vi.fn();
    render(<DataTable columns={columns} data={rows} onRowClick={onRowClick} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
    expect(screen.getByText("Status")).toBeInTheDocument();
    expect(screen.getByText("In service")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("button", { name: /SC-2026-0001/ }));
    expect(onRowClick).toHaveBeenCalledWith(rows[0]);
  });
});

describe("status badge", () => {
  it("uses readable labels", () => {
    render(<><StatusBadge status="AWAITING_PARTS" /><StatusBadge status="DELIVERY_STATUS_UNKNOWN" /></>);
    expect(screen.getByText("Awaiting parts")).toBeInTheDocument();
    expect(screen.getByText("Sent (delivery unconfirmed)")).toBeInTheDocument();
  });
});
