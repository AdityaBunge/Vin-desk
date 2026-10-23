/** One dashboard per role, each designed around that person's day:
 *  Service Manager - workshop control room (also records the mechanics' inspection and work);
 *  Inventory - stores desk; Admin - system console. */
import { useQuery } from "@tanstack/react-query";
import {
  Activity, AlertTriangle, Boxes, CalendarCheck, CarFront, ClipboardList, Clock,
  Database, FileText, Gauge, IndianRupee, LayoutDashboard, ListChecks, Mail, PackageSearch, PlusCircle, Receipt,
  ScrollText, Search, Send, ShieldCheck, ShoppingCart, SlidersHorizontal, Truck, UserPlus, Users, Wallet,
  Warehouse, Wrench,
} from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { EmptyState, ErrorState, Spinner, StatusBadge, cx } from "@/components/ui";
import { DirectBillModal } from "@/features/dashboard/DirectBill";
import { CountUp, Figure, Hero, Panel, TrendChart } from "@/features/dashboard/parts";
import { useAuth, useViewStatus } from "@/hooks/useAuth";
import { ROLE_LABEL, fmtDateTime, label, qty, rupees, todayISO } from "@/lib/format";
import { get } from "@/services/api";
import type { Dashboard as DashboardData, JobSummary, Me, Movement, Page, SparePartsList } from "@/types";

const num = (d: DashboardData | undefined, key: string) => Number(d?.cards[key] ?? 0);
const jobsWith = (status: string) => `/jobs?status=${status}`;

// --- Shared pieces -------------------------------------------------------------------------

function JobRows({ params, empty, limit = 6 }: { params: Record<string, string | boolean | number>; empty: string; limit?: number }) {
  const viewStatus = useViewStatus();
  const q = useQuery({ queryKey: ["jobs", "dashboard", params], queryFn: () => get<Page<JobSummary>>("/jobs", { ...params, page_size: limit }) });
  if (q.isLoading) return <Spinner />;
  if (q.error) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  if (!q.data?.items.length) return <EmptyState title={empty} />;
  return (
    <ul className="-mx-2 space-y-0.5">
      {q.data.items.map((job) => (
        <li key={job.id}>
          <Link to={`/jobs/${job.id}`} className="group flex items-center justify-between gap-3 rounded-xl px-2 py-2.5 transition-colors hover:bg-white/80">
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-slate-900/[0.04] text-slate-500 transition-colors group-hover:bg-brand-500/10 group-hover:text-brand-600">
              <CarFront className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900">{job.vehicle.registration_number} <span className="font-normal text-slate-500">· {job.vehicle.model.name}</span></p>
              <p className="truncate text-xs text-slate-500">{job.job_number} · {job.complaints}</p>
            </div>
            <div className="flex shrink-0 items-center gap-1.5">
              {job.returned_for_rework && <StatusBadge status="FAIL" />}
              <StatusBadge status={viewStatus(job.status)} />
            </div>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function QuickSearch() {
  const navigate = useNavigate();
  const [term, setTerm] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (term.trim()) navigate(`/reception/new?registration=${encodeURIComponent(term.trim())}`);
  };
  return (
    <form onSubmit={submit} className="flex w-full gap-2 sm:w-auto" role="search">
      <label className="sr-only" htmlFor="quick-reg">Registration number</label>
      <input id="quick-reg" className="input min-w-0 flex-1 border-white/20 bg-white/10 text-white uppercase placeholder:text-slate-400 hover:bg-white/15 focus:bg-white focus:text-slate-900 sm:w-52 sm:flex-none"
        placeholder="Registration no." value={term} onChange={(e) => setTerm(e.target.value)} />
      <button type="submit" className="inline-flex h-10 items-center gap-1.5 rounded-xl border border-white/20 bg-white/10 px-4 text-sm font-medium text-white backdrop-blur transition-colors hover:bg-white/20">
        <Search className="h-4 w-4" />Search
      </button>
    </form>
  );
}

// --- Service Manager: workshop control room ----------------------------------------------------

const STAGES: [string, string, typeof Clock][] = [
  ["AWAITING_ASSIGNMENT", "Awaiting mechanic assignment", UserPlus],
  ["INSPECTION_IN_PROGRESS", "Inspection", ListChecks],
  ["AWAITING_PARTS", "Waiting for parts", PackageSearch],
  ["READY_FOR_SERVICE", "Ready for service", Wrench],
  ["IN_SERVICE", "In service", Activity],
  ["READY_FOR_BILLING", "Ready for billing", Receipt],
  ["READY_FOR_DELIVERY", "Ready for delivery", Truck],
];

/** Where every open vehicle is right now; the busiest stage is highlighted as the bottleneck. */
function Pipeline({ data }: { data: DashboardData }) {
  const counts = STAGES.map(([status]) => data.pipeline?.[status] ?? (status === "AWAITING_ASSIGNMENT" ? num(data, "awaiting_assignment") : 0));
  const max = Math.max(...counts);
  const total = counts.reduce((a, b) => a + b, 0);
  return (
    <Panel title="Workshop pipeline" icon={Gauge} to="/jobs?active_only=true" toLabel="All job cards" className="mb-6">
      <p className="-mt-1 mb-4 text-xs text-slate-500">{total} vehicle{total === 1 ? "" : "s"} in the workshop. The busiest stage is highlighted.</p>
      <ol className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
        {STAGES.map(([status, name, Icon], i) => {
          const n = counts[i]!;
          const hot = n > 0 && n === max && total > 1;
          return (
            <li key={status} className="relative">
              {i > 0 && <span aria-hidden className="absolute top-7 -left-2 hidden h-px w-2 bg-slate-300 lg:block" />}
              <Link to={jobsWith(status)}
                className={cx("group flex h-full flex-col gap-2 rounded-xl border p-3 transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md",
                  hot ? "border-amber-400/50 bg-amber-50/80" : n > 0 ? "border-brand-500/20 bg-white/80" : "border-slate-900/[0.06] bg-white/40")}>
                <span className="flex items-center justify-between">
                  <span className={cx("grid h-8 w-8 place-items-center rounded-lg", hot ? "bg-amber-400/20 text-amber-700" : n > 0 ? "bg-brand-500/10 text-brand-600" : "bg-slate-500/10 text-slate-400")}>
                    <Icon className="h-4 w-4" aria-hidden />
                  </span>
                  <span className={cx("text-2xl font-semibold tabular-nums", hot ? "text-amber-700" : n > 0 ? "text-slate-900" : "text-slate-300")}><CountUp value={n} /></span>
                </span>
                <span className="text-xs leading-snug font-medium text-slate-600">{name}</span>
                {hot && <span className="text-[10px] font-semibold tracking-wide text-amber-700 uppercase">Bottleneck</span>}
              </Link>
            </li>
          );
        })}
      </ol>
    </Panel>
  );
}

function ManagerDashboard({ user, data }: { user: Me; data: DashboardData }) {
  const [directBill, setDirectBill] = useState(false);
  const invoicedMonth = num(data, "revenue_month");
  const collectedMonth = num(data, "collected_month");
  const pct = invoicedMonth > 0 ? Math.min(100, Math.round((collectedMonth / invoicedMonth) * 100)) : 0;
  return (
    <>
      <Hero theme="blue" photo eyebrow="Workshop control room" icon={LayoutDashboard} name={user.full_name}
        title="Service Manager dashboard" subtitle={`Live figures as of ${fmtDateTime(data.generated_at)}`}
        metrics={[
          { label: "In the workshop", value: num(data, "active_jobs") },
          { label: "Arrived today", value: num(data, "todays_arrivals") },
          { label: "Collected today", value: num(data, "collected_today"), money: true },
        ]}
        actions={<>
          <QuickSearch />
          <Link to="/reception/new"
            className="inline-flex h-10 w-full items-center justify-center gap-1.5 rounded-xl bg-white px-4 text-sm font-semibold text-brand-800 shadow-lg shadow-black/25 transition-[transform,background-color] hover:-translate-y-0.5 hover:bg-sky-50 sm:w-auto">
            <PlusCircle className="h-4 w-4" />New Service Visit
          </Link>
          <button type="button" onClick={() => setDirectBill(true)}
            className="inline-flex h-10 w-full items-center justify-center gap-1.5 rounded-xl border border-white/25 bg-white/10 px-4 text-sm font-semibold text-white backdrop-blur transition-[transform,background-color] hover:-translate-y-0.5 hover:bg-white/20 sm:w-auto">
            <Receipt className="h-4 w-4" />Bill directly
          </button>
        </>} />
      {directBill && <DirectBillModal onClose={() => setDirectBill(false)} />}

      <Pipeline data={data} />

      <div className="stagger mb-6 grid gap-4 lg:grid-cols-3">
        <Panel title="Revenue" icon={IndianRupee} to="/reports?report=revenue" toLabel="Revenue report" className="lg:col-span-2">
          {data.trend ? (
            <TrendChart data={data.trend} money series={[{ key: "invoiced", name: "Invoiced" }, { key: "collected", name: "Collected" }]} />
          ) : <EmptyState title="No revenue yet" />}
        </Panel>
        <Panel title="Money owed" icon={Wallet} to="/invoices?outstanding_only=true" toLabel="Invoices" accent="text-red-600 bg-red-500/10">
          <p className="text-xs text-slate-500">Outstanding balances</p>
          <p className="text-3xl font-semibold tracking-tight text-slate-900 tabular-nums">{rupees(num(data, "outstanding_total"))}</p>
          <div className="mt-4 grid grid-cols-2 gap-2">
            <Figure label="Unpaid" value={num(data, "unpaid_invoices")} icon={FileText} tone="danger" to="/invoices?payment_status=UNPAID&status=FINALISED" />
            <Figure label="Part paid" value={num(data, "partially_paid_invoices")} icon={Wallet} tone="warn" to="/invoices?payment_status=PARTIALLY_PAID" />
          </div>
          <div className="mt-5">
            <div className="mb-1.5 flex justify-between text-xs text-slate-500"><span>Collected this month</span><span className="font-medium text-slate-900">{pct}%</span></div>
            <div className="h-2 overflow-hidden rounded-full bg-slate-900/[0.06]" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Collected this month">
              <div className="h-full rounded-full bg-gradient-to-r from-brand-500 to-sky-400 transition-[width] duration-1000" style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1.5 text-xs text-slate-500">{rupees(collectedMonth)} of {rupees(invoicedMonth)} invoiced</p>
          </div>
        </Panel>
      </div>

      <div className="stagger grid gap-4 lg:grid-cols-3">
        <Panel title="Needs your attention" icon={AlertTriangle} to="/jobs?active_only=true" toLabel="All jobs" accent="text-amber-600 bg-amber-400/15" className="lg:col-span-2">
          <JobRows params={{ status: "AWAITING_ASSIGNMENT,READY_FOR_BILLING,READY_FOR_DELIVERY" }} empty="Nothing is waiting on you" />
        </Panel>
        <div className="flex flex-col gap-4">
          <Panel title="Today's arrivals" icon={CalendarCheck} to={`/jobs?date_from=${todayISO()}`}>
            <JobRows params={{ date_from: todayISO() }} empty="No vehicles received today" limit={4} />
          </Panel>
          <Panel title="Parts & purchasing" icon={ShoppingCart} accent="text-violet-600 bg-violet-500/10">
            <div className="grid gap-2">
              <Figure label="Parts shortages" value={num(data, "parts_shortages")} icon={AlertTriangle} tone="danger" to="/reports?report=unavailable-parts" />
              <Figure label="Purchase requests to approve" value={num(data, "pending_purchase_requests")} icon={ShoppingCart} tone="warn" to="/purchase-requests?status=PENDING_APPROVAL" />
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}

// --- Inventory staff: stores desk ----------------------------------------------------------------

function InventoryDashboard({ user, data }: { user: Me; data: DashboardData }) {
  const lists = useQuery({ queryKey: ["spare-parts-lists"], queryFn: () => get<SparePartsList[]>("/spare-parts-lists") });
  const moves = useQuery({ queryKey: ["movements", "recent"], queryFn: () => get<Page<Movement>>("/inventory/movements", { page_size: 6 }) });
  return (
    <>
      <Hero theme="amber" eyebrow="Stores desk" icon={Warehouse} name={user.full_name} title="Inventory Staff dashboard"
        subtitle={`Updated ${fmtDateTime(data.generated_at)}`}
        metrics={[
          { label: "Lists to check", value: num(data, "spare_parts_lists") },
          { label: "Low-stock items", value: num(data, "low_stock_items") },
          { label: "Parts to take back", value: num(data, "returns_due") },
        ]}
        actions={<Link to="/parts-requests" className="inline-flex h-10 items-center gap-1.5 rounded-xl bg-white px-4 text-sm font-semibold text-amber-800 shadow-lg shadow-black/25 transition-transform hover:-translate-y-0.5">
          <PackageSearch className="h-4 w-4" />Open parts requests
        </Link>} />

      <div className="stagger mb-6 grid gap-4 lg:grid-cols-5">
        <Panel title="Parts lists from mechanics" icon={ListChecks} to="/parts-requests" toLabel="Check them" accent="text-amber-700 bg-amber-400/15" className="lg:col-span-3">
          {lists.isLoading ? <Spinner /> : !lists.data?.length ? <EmptyState title="Nothing to check" hint="New lists from mechanics appear here." /> : (
            <ul className="grid gap-2 sm:grid-cols-2">
              {lists.data.slice(0, 6).map((l) => (
                <li key={l.job_id}>
                  <Link to="/parts-requests" className="block h-full rounded-xl border border-amber-500/25 bg-amber-50/70 p-3 transition-all hover:-translate-y-0.5 hover:shadow-md">
                    <p className="flex items-center justify-between gap-2 text-sm font-medium text-slate-900">
                      {l.registration_number}{l.status === "UNAVAILABLE" && <StatusBadge status="UNAVAILABLE" />}
                    </p>
                    <p className="text-xs text-slate-500">{l.job_number} · {l.mechanic_name ?? "Unassigned"}</p>
                    <p className="mt-2 line-clamp-2 text-xs whitespace-pre-line text-slate-700">{l.unconfirmed || l.notes}</p>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Running low" icon={Boxes} to="/parts?low_stock=true" toLabel="Catalogue" accent="text-red-600 bg-red-500/10" className="lg:col-span-2">
          {!data.low_stock?.length ? <EmptyState title="Stock levels are healthy" /> : (<>
            <p className="-mt-1 mb-3 text-xs text-slate-500">Available / reorder level. The tick marks the reorder level.</p>
            <ul className="space-y-3">
              {data.low_stock.map((p) => {
                // Bar spans twice the reorder level; the tick marks the reorder level itself.
                const level = Number(p.threshold) > 0 ? Math.min(100, (Number(p.available) / (2 * Number(p.threshold))) * 100) : 0;
                return (
                  <li key={p.id}>
                    <div className="flex items-baseline justify-between gap-2 text-sm">
                      <span className="truncate font-medium text-slate-800">{p.name}</span>
                      <span className="shrink-0 text-xs text-slate-500 tabular-nums">{qty(p.available)} / {qty(p.threshold)}</span>
                    </div>
                    <div className="relative mt-1 h-1.5 rounded-full bg-slate-900/[0.06]" aria-hidden>
                      <div className={cx("h-full rounded-full", level < 25 ? "bg-red-500" : "bg-amber-500")} style={{ width: `${Math.max(level, 3)}%` }} />
                      <span className="absolute -top-1 left-1/2 h-3.5 w-0.5 rounded-full bg-slate-400" title="Reorder level" />
                    </div>
                  </li>
                );
              })}
            </ul>
          </>)}
        </Panel>
      </div>

      <div className="stagger grid gap-4 lg:grid-cols-3">
        <Panel title="Stock activity" icon={Activity} to="/stock-movements" toLabel="Movements" className="lg:col-span-2">
          {data.trend ? <TrendChart data={data.trend} series={[{ key: "movements", name: "Stock movements" }]} height={190} /> : <EmptyState title="No movements" />}
        </Panel>
        <Panel title="Workload" icon={ClipboardList} accent="text-amber-700 bg-amber-400/15">
          <div className="grid gap-2">
            <Figure label="Incoming parts requests" value={num(data, "incoming_requests")} icon={PackageSearch} tone="warn" to="/parts-requests?status=PENDING" />
            <Figure label="Unavailable parts" value={num(data, "unavailable_lines")} icon={AlertTriangle} tone="danger" to="/reports?report=unavailable-parts" />
            <Figure label="Purchases awaiting approval" value={num(data, "pending_purchase_requests")} icon={ShoppingCart} to="/purchase-requests?status=PENDING_APPROVAL" />
            <Figure label="Approved, awaiting receipt" value={num(data, "approved_awaiting_receipt")} icon={Truck} tone="good" to="/purchase-requests?status=APPROVED,PARTIALLY_RECEIVED" />
          </div>
        </Panel>
      </div>

      {!!moves.data?.items.length && (
        <Panel title="Latest movements" icon={Clock} to="/stock-movements" className="mt-4">
          <ol className="relative space-y-3 border-l border-slate-900/10 pl-5">
            {moves.data.items.map((m) => (
              <li key={m.id} className="relative text-sm">
                <span aria-hidden className="absolute top-1.5 -left-[25px] h-2.5 w-2.5 rounded-full bg-amber-500 ring-4 ring-white/70" />
                <span className="font-medium text-slate-900">{m.part.sku}</span> · {label(m.movement_type)} {qty(m.quantity)}{m.job_number ? ` · ${m.job_number}` : ""}
                <span className="block text-xs text-slate-500">{m.performed_by.full_name} · {fmtDateTime(m.created_at)}</span>
              </li>
            ))}
          </ol>
        </Panel>
      )}
    </>
  );
}

// --- Administrator: system console ---------------------------------------------------------------

function SystemHealth() {
  const q = useQuery({ queryKey: ["health"], queryFn: () => get<Record<string, string | number | boolean | null>>("/system/health"), refetchInterval: 30_000 });
  const h = q.data;
  const rows: [string, string, boolean, typeof Database][] = h ? [
    ["Database", String(h.database), h.database === "ok", Database],
    ["Email", `${h.email_provider}${h.email_simulated ? " (simulator)" : ""}`, !h.email_simulated, Mail],
    ["SMS", `${h.sms_provider}${h.sms_simulated ? " (simulator)" : ""}`, !h.sms_simulated, Send],
    ["WhatsApp", `${h.whatsapp_provider}${h.whatsapp_simulated ? " (simulator)" : ""}`, !h.whatsapp_simulated, Send],
    ["Delivery queue", `${h.delivery_backlog} waiting`, Number(h.delivery_backlog) < 20, Activity],
    ["Environment", String(h.environment), true, ShieldCheck],
  ] : [];
  return (
    <Panel title="System health" icon={ShieldCheck} accent="text-emerald-600 bg-emerald-500/10" className="lg:col-span-2">
      {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} /> : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {rows.map(([name, value, ok, Icon]) => (
            <li key={name} className="flex items-center gap-3 rounded-xl border border-slate-900/[0.06] bg-white/60 p-3">
              <Icon className="h-4 w-4 text-slate-400" aria-hidden />
              <div className="min-w-0 flex-1">
                <p className="text-xs text-slate-500">{name}</p>
                <p className="truncate text-sm font-medium text-slate-900">{value}</p>
              </div>
              <span className={cx("relative flex h-2.5 w-2.5", ok ? "text-emerald-500" : "text-amber-500")} title={ok ? "OK" : "Needs attention"}>
                {ok && <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />}
                <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-current" />
              </span>
              <span className="sr-only">{ok ? "OK" : "Needs attention"}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function AdminDashboard({ user, data }: { user: Me; data: DashboardData }) {
  const byRole = (data.cards.users_by_role ?? {}) as Record<string, number>;
  const maxUsers = Math.max(1, ...Object.values(byRole));
  return (
    <>
      <Hero theme="violet" eyebrow="System console" icon={ShieldCheck} name={user.full_name} title="Administrator dashboard"
        subtitle={`Updated ${fmtDateTime(data.generated_at)}`}
        metrics={[
          { label: "Active users", value: num(data, "active_users") },
          { label: "Audit entries today", value: num(data, "audit_entries_today") },
          { label: "Deliveries queued", value: num(data, "delivery_backlog") },
        ]} />
      <div className="stagger mb-6 grid gap-4 lg:grid-cols-3">
        <SystemHealth />
        <Panel title="Users by role" icon={Users} to="/admin/users" toLabel="Manage users" accent="text-violet-600 bg-violet-500/10">
          <ul className="space-y-3">
            {Object.entries(byRole).map(([role, n]) => (
              <li key={role}>
                <div className="flex justify-between text-sm"><span className="text-slate-700">{ROLE_LABEL[role] ?? label(role)}</span><span className="font-semibold text-slate-900 tabular-nums">{n}</span></div>
                <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-900/[0.06]" aria-hidden>
                  <div className="h-full rounded-full bg-gradient-to-r from-violet-500 to-fuchsia-400" style={{ width: `${(n / maxUsers) * 100}%` }} />
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>
      <div className="stagger grid gap-4 lg:grid-cols-3">
        <Panel title="Audit activity" icon={ScrollText} to="/admin/audit" toLabel="Audit log" className="lg:col-span-2">
          {data.trend ? <TrendChart data={data.trend} series={[{ key: "audit", name: "Audit entries" }]} height={190} /> : <EmptyState title="No activity" />}
        </Panel>
        <Panel title="Master data" icon={SlidersHorizontal} to="/admin/master-data" toLabel="Edit" accent="text-violet-600 bg-violet-500/10">
          <div className="grid gap-2">
            <Figure label="Vehicle models" value={num(data, "vehicle_models")} icon={CarFront} to="/admin/master-data" />
            <Figure label="Parts in catalogue" value={num(data, "parts")} icon={Boxes} to="/parts" />
            <Figure label="Labour operations" value={num(data, "labour_operations")} icon={Wrench} to="/admin/master-data?tab=labour" />
            <Figure label="Tax rates" value={num(data, "tax_rates")} icon={Receipt} to="/admin/master-data?tab=tax" />
          </div>
        </Panel>
      </div>
    </>
  );
}

// --- Page ----------------------------------------------------------------------------------------

export default function Dashboard() {
  const { user } = useAuth();
  const q = useQuery({ queryKey: ["dashboard"], queryFn: () => get<DashboardData>("/dashboard"), refetchInterval: 60_000 });
  if (!user) return null;
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  switch (user.role_code) {
    case "SERVICE_MANAGER": return <ManagerDashboard user={user} data={q.data} />;
    case "MECHANIC": return <EmptyState title="Mechanics do not use Vin Desk" hint="The Service Manager records inspections and work on job cards." />;
    case "INVENTORY_STAFF": return <InventoryDashboard user={user} data={q.data} />;
    default: return <AdminDashboard user={user} data={q.data} />;
  }
}
