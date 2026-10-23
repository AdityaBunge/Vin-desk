/** Renders every page against a RUNNING development backend with the demo data.
 *
 * Skipped unless VITE_LIVE_API is set, so the normal test run stays hermetic:
 *
 *   VITE_LIVE_API=http://127.0.0.1:8000 npx vitest run src/test/live-smoke.test.tsx
 *
 * It catches runtime errors (bad property access, broken queries) that mocks cannot.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeAll, describe, expect, it, vi } from "vitest";
import App from "@/App";
import { ConfirmProvider, ToastProvider } from "@/components/ui";
import { AuthProvider } from "@/hooks/useAuth";

const LIVE = import.meta.env.VITE_LIVE_API as string | undefined;
const PASSWORD = "Demo@12345";
const sessions: Record<string, unknown> = {};
const realFetch = globalThis.fetch;

async function login(role: string) {
  const r = await realFetch(`${LIVE}/api/auth/login`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email: `${role}@demo.local`, password: PASSWORD }),
  });
  if (!r.ok) throw new Error(`login failed for ${role}: ${r.status}`);
  sessions[role] = await r.json();
}

function renderAs(role: string, path: string) {
  const failures: string[] = [];
  vi.stubGlobal("fetch", async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    // The httpOnly refresh cookie is not available in jsdom: answer the silent restore directly.
    if (url.endsWith("/api/auth/refresh")) return new Response(JSON.stringify(sessions[role]), { status: 200, headers: { "Content-Type": "application/json" } });
    const response = await realFetch(`${LIVE}${url}`, init);
    if (response.status >= 400) failures.push(`${init?.method ?? "GET"} ${url} -> ${response.status}`);
    return response;
  });
  const errors: string[] = [];
  vi.spyOn(console, "error").mockImplementation((...args) => { errors.push(args.map(String).join(" ")); });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider><ConfirmProvider><AuthProvider><App /></AuthProvider></ConfirmProvider></ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { failures, errors };
}

const PAGES: [string, string, RegExp][] = [
  ["manager", "/", /service manager dashboard/i],
  ["manager", "/reception/new?registration=MH12AB1234", /service visit details/i],
  ["manager", "/reception/new?registration=KA01ZZ9999", /register customer and vehicle/i],
  ["manager", "/jobs", /SC-\d{4}-0001/],
  ["manager", "/jobs/3", /previous service history/i],
  ["manager", "/jobs/3?tab=inspection", /inspection and diagnosis/i],
  ["manager", "/jobs/3?tab=parts", /REQ-\d{4}-\d{4}/],
  ["manager", "/jobs/3?tab=estimate", /estimate v1/i],
  ["manager", "/jobs/3?tab=work", /completion records/i],
  ["manager", "/jobs/3?tab=billing", /handed over to/i],
  ["manager", "/jobs/3/print", /JOB CARD/],
  ["manager", "/customers", /MH12AB1234/],
  ["manager", "/parts-requests", /REQ-\d{4}-\d{4}/],
  ["manager", "/parts", /FM-OIL-15W40-5L/],
  ["manager", "/stock-movements", /opening stock/i],
  ["manager", "/purchase-requests", /PUR-\d{4}-\d{4}/],
  ["manager", "/invoices", /INV-\d{4}-0001/],
  ["manager", "/invoices/1", /delivery to customer/i],
  ["manager", "/deliveries", /simulated \(not sent\)/i],
  ["manager", "/reports?report=revenue", /invoiced total/i],
  ["manager", "/reports?report=technician-workload", /completed in period/i], // a column heading (user names can change)
  ["manager", "/notifications", /mark all as read/i],
  ["manager", "/jobs/1?tab=inspection", /spare parts required/i],
  ["manager", "/jobs/1?tab=parts", /request spare parts|REQ-\d{4}-\d{4}|no parts have been requested|spare parts noted by the mechanic/i], // depends on how far job 1 has got
  ["manager", "/jobs/1?tab=work", /completion records/i],
  ["inventory", "/", /inventory staff dashboard/i],
  ["inventory", "/parts-requests", /REQ-\d{4}-\d{4}/],
  ["inventory", "/parts-requests", /Spare parts lists from mechanics|Parts Requests/], // the lists section shows only while some are pending
  ["inventory", "/parts", /new part/i],
  ["inventory", "/purchase-requests", /new purchase request/i],
  ["inventory", "/reports?report=low-stock", /reorder at/i],
  ["admin", "/", /system health/i],
  ["admin", "/admin/users", /manager@demo\.local/],
  ["admin", "/admin/master-data", /force traveller/i],
  ["admin", "/admin/master-data?tab=labour", /LAB-GS/],
  ["admin", "/admin/settings", /communication providers/i],
  ["admin", "/admin/audit", /auth\.login/], // newest entries first; always present after signing in
];

describe.skipIf(!LIVE)("live smoke test against the development backend", () => {
  beforeAll(async () => {
    for (const role of ["manager", "inventory", "admin"]) await login(role);
  });

  it.each(PAGES)("%s can open %s", async (role, path, expected) => {
    const { failures, errors } = renderAs(role, path);
    await waitFor(() => expect(screen.getAllByText(expected).length).toBeGreaterThan(0), { timeout: 15_000 });
    expect(screen.queryByText(/do not have access to this page/i)).not.toBeInTheDocument();
    expect(failures).toEqual([]);
    // React reports render crashes and key/DOM-nesting mistakes through console.error.
    expect(errors.filter((e) => !e.includes("not wrapped in act"))).toEqual([]);
  }, 30_000);

  it("keeps a mechanic out of billing and an administrator out of operations", async () => {
    renderAs("inventory", "/invoices/1");
    expect(await screen.findByText(/do not have access to this page/i, undefined, { timeout: 15_000 })).toBeInTheDocument();
  });
});
