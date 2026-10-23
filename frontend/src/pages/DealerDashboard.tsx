import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, BadgeIndianRupee, Boxes, MessageSquareText, Star, Tags, CalendarClock, CarFront, Clock, Download, Gauge, Hourglass, PackageX, Target, Users, Wallet, Wrench,
} from "lucide-react";
import { type ReactNode, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button, ErrorState, Field, Modal, PageHeader, Spinner, cx, useToast } from "@/components/ui";
import { Panel, SERIES_COLORS } from "@/features/dashboard/parts";
import { JOB_TYPE_LABEL, fmtDate, label, qty, rupees, todayISO } from "@/lib/format";
import { get, put } from "@/services/api";

type Row = Record<string, string | number | null>;
interface Group { group: string; parts: number; value: number }
interface Dashboard {
  date_from: string; date_to: string;
  money: {
    revenue: number; revenue_previous_period: number; revenue_last_year: number; revenue_today: number; revenue_month: number;
    revenue_financial_year: number; invoices: number; average_bill: number; parts_sales: number; labour_sales: number;
    gst_collected: number; collected: number; outstanding: number; ageing: { bucket: string; amount: number }[];
    top_dues: Row[]; trend: { month: string; parts: number; labour: number }[];
  };
  workshop: {
    arrivals_today: number; arrivals: number; in_workshop: number; ready_for_delivery: number; delivered: number;
    average_turnaround_days: number; stages: { stage: string; jobs: number }[]; stuck_jobs: Row[]; mechanics: Row[];
    repeat_visits: Row[]; repeat_visit_count: number; by_type: { type: string; jobs: number; revenue: number }[];
  };
  customers: {
    feedback: { count: number; average: number; distribution: { rating: number; count: number }[]; low: Row[] };
    customers_served: number; new_customers: number; returning_customers: number; by_model: { model: string; jobs: number }[]; top_customers: Row[] };
  parts: {
    stock_value: number; parts_in_stock: number; by_abc: Group[]; by_movement: Group[]; dead_stock_days: number; dead_stock_parts: number;
    dead_stock_value: number; dead_stock: Row[]; count_difference_parts: number; count_differences: Row[]; running_low: Row[];
    top_by_value: Row[]; top_by_qty: Row[]; shortage_lines: number; unavailable_lists: number; pending_purchase_requests: number;
  };
  growth: {
    parts_sales: number; parts_cost: number; parts_margin: number; parts_margin_percent: number;
    targets: { revenue_target: number; revenue_month: number; vehicles_target: number; vehicles_month: number };
    service_interval_days: number; service_due_count: number; service_due: Row[];
  };
}

// --- Date range ------------------------------------------------------------------------------

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
function presets(): { key: string; label: string; from: string; to: string }[] {
  const now = new Date();
  const y = now.getFullYear(), m = now.getMonth();
  const fyStart = new Date(m >= 3 ? y : y - 1, 3, 1);
  return [
    { key: "month", label: "This month", from: iso(new Date(y, m, 1)), to: todayISO() },
    { key: "last-month", label: "Last month", from: iso(new Date(y, m - 1, 1)), to: iso(new Date(y, m, 0)) },
    { key: "30", label: "Last 30 days", from: todayISO(-29), to: todayISO() },
    { key: "fy", label: "This financial year", from: iso(fyStart), to: todayISO() },
  ];
}

// --- Small pieces ----------------------------------------------------------------------------

const num = (v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 1 });
const rs = (v: number) => rupees(Math.round(v));

function change(now: number, before: number): { text: string; up: boolean } | null {
  if (!before) return null;
  const pct = ((now - before) / before) * 100;
  return { text: `${pct >= 0 ? "+" : ""}${pct.toFixed(0)}%`, up: pct >= 0 };
}

/** Headline number with an optional comparison line. */
function Stat({ label: name, value, hint, icon: Icon, compare, tone }: {
  label: string; value: string; hint?: ReactNode; icon: typeof Gauge; compare?: { against: string; now: number; before: number }; tone?: "warn" | "danger";
}) {
  const delta = compare ? change(compare.now, compare.before) : null;
  return (
    <div className="glass flex flex-col gap-1 rounded-2xl p-4">
      <p className="flex items-center gap-2 text-xs font-medium text-slate-500">
        <Icon className={cx("h-4 w-4", tone === "danger" ? "text-red-600" : tone === "warn" ? "text-amber-600" : "text-brand-600")} aria-hidden />{name}
      </p>
      <p className={cx("text-2xl font-semibold tracking-tight tabular-nums", tone === "danger" ? "text-red-700" : tone === "warn" ? "text-amber-700" : "text-slate-900")}>{value}</p>
      {compare && (
        <p className="text-xs text-slate-500">
          {delta ? <span className={cx("font-semibold", delta.up ? "text-emerald-700" : "text-red-700")}>{delta.up ? "▲" : "▼"} {delta.text}</span> : <span>No figure</span>}
          {" "}vs {compare.against} ({rs(compare.before)})
        </p>
      )}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

/** Horizontal bars for a short categorical list; one hue, value labelled on every row. */
function BarList({ rows, format = num, empty = "Nothing to show" }: { rows: { name: string; value: number; note?: string }[]; format?: (v: number) => string; empty?: string }) {
  const max = Math.max(...rows.map((r) => r.value), 0);
  if (!rows.length || max === 0) return <p className="py-6 text-center text-sm text-slate-500">{empty}</p>;
  return (
    <ul className="space-y-2.5">
      {rows.map((r) => (
        <li key={r.name} className="grid grid-cols-[minmax(6rem,9rem)_1fr_auto] items-center gap-3 text-sm">
          <span className="truncate text-slate-700" title={r.name}>{r.name}</span>
          <span className="h-2.5 rounded-full bg-slate-500/10">
            <span className="block h-full rounded-full" style={{ width: `${Math.max((r.value / max) * 100, r.value > 0 ? 2 : 0)}%`, background: SERIES_COLORS[0] }} />
          </span>
          <span className="text-right font-medium text-slate-900 tabular-nums">{format(r.value)}{r.note && <span className="ml-1.5 text-xs font-normal text-slate-500">{r.note}</span>}</span>
        </li>
      ))}
    </ul>
  );
}

interface Column { key: string; label: string; type?: "money" | "number" | "date" | "status" }
function cellText(c: Column, v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "-";
  if (c.type === "money") return rs(Number(v));
  if (c.type === "number") return qty(Number(v));
  if (c.type === "date") return fmtDate(String(v));
  if (c.type === "status") return label(String(v));
  return String(v);
}

function downloadCsv(name: string, columns: Column[], rows: Row[]) {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const text = [columns.map((c) => esc(c.label)), ...rows.map((r) => columns.map((c) => esc(r[c.key] == null ? "" : String(r[c.key]))))]
    .map((line) => line.join(",")).join("\n");
  const url = URL.createObjectURL(new Blob([`﻿${text}`], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: `${name}.csv` });
  a.click();
  URL.revokeObjectURL(url);
}

function Table({ name, columns, rows, empty = "Nothing here" }: { name: string; columns: Column[]; rows: Row[]; empty?: string }) {
  if (!rows.length) return <p className="py-6 text-center text-sm text-slate-500">{empty}</p>;
  return (
    <div>
      <div className="-mx-5 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-900/[0.06] text-left text-[11px] tracking-wide text-slate-500 uppercase">
              {columns.map((c) => <th key={c.key} className={cx("px-5 py-2 font-medium whitespace-nowrap", (c.type === "money" || c.type === "number") && "text-right")}>{c.label}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-900/[0.05]">
            {rows.map((r, i) => (
              <tr key={i}>
                {columns.map((c) => (
                  <td key={c.key} className={cx("px-5 py-2 text-slate-800", c.type === "money" || c.type === "number" ? "text-right tabular-nums whitespace-nowrap" : "max-w-64 truncate")}
                    title={c.type ? undefined : String(r[c.key] ?? "")}>{cellText(c, r[c.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex justify-end">
        <Button size="sm" variant="ghost" onClick={() => downloadCsv(name, columns, rows)}><Download className="h-3.5 w-3.5" aria-hidden />CSV</Button>
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <h2 className="pt-2 text-[13px] font-semibold tracking-[0.12em] text-slate-500 uppercase">{title}</h2>
      {children}
    </section>
  );
}

const monthLabel = (m: string) => new Date(`${m}-01T00:00:00`).toLocaleDateString("en-IN", { month: "short", year: "2-digit" });

function SalesTooltip({ active, payload, label: month }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string }) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + Number(p.value), 0);
  return (
    <div className="glass-strong rounded-xl px-3 py-2 text-xs">
      <p className="mb-1 font-medium text-slate-900">{monthLabel(String(month))}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-slate-600">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden />{p.name}: <span className="font-semibold text-slate-900 tabular-nums">{rs(p.value)}</span>
        </p>
      ))}
      <p className="mt-1 border-t border-slate-900/10 pt-1 text-slate-600">Total: <span className="font-semibold text-slate-900 tabular-nums">{rs(total)}</span></p>
    </div>
  );
}

/** Monthly sales before GST, parts and labour stacked. */
function SalesTrend({ data }: { data: Dashboard["money"]["trend"] }) {
  const series = [{ key: "parts", name: "Parts" }, { key: "labour", name: "Labour" }];
  const totals = series.map((s) => data.reduce((sum, r) => sum + r[s.key as "parts" | "labour"], 0));
  const axis = { tick: { fontSize: 11, fill: "#64748b" }, tickLine: false, axisLine: false };
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
        {series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SERIES_COLORS[i] }} aria-hidden />{s.name} <span className="font-semibold text-slate-900 tabular-nums">{rs(totals[i]!)}</span>
          </span>
        ))}
        <span className="ml-auto text-slate-400">Last 12 months, before GST</span>
      </div>
      <div style={{ height: 240 }} role="img" aria-label={`Sales over the last 12 months: parts ${rs(totals[0]!)}, labour ${rs(totals[1]!)}`}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="24%">
            <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
            <XAxis dataKey="month" tickFormatter={monthLabel} {...axis} />
            <YAxis width={56} tickFormatter={(v: number) => `₹${v >= 100000 ? `${(v / 100000).toFixed(1)}L` : v >= 1000 ? `${Math.round(v / 1000)}k` : v}`} {...axis} />
            <Tooltip content={<SalesTooltip />} cursor={{ fill: "rgb(148 163 184 / 0.12)" }} />
            {series.map((s, i) => (
              <Bar key={s.key} dataKey={s.key} name={s.name} stackId="sales" fill={SERIES_COLORS[i]} stroke="#fff" strokeWidth={2}
                radius={i === series.length - 1 ? [4, 4, 0, 0] : 0} maxBarSize={36} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Progress({ name, now, target, format }: { name: string; now: number; target: number; format: (v: number) => string }) {
  if (!target) return <p className="text-sm text-slate-500">{name}: <span className="font-medium text-slate-900">{format(now)}</span> · no target set</p>;
  const pct = (now / target) * 100;
  return (
    <div>
      <p className="mb-1 flex justify-between text-sm"><span className="text-slate-700">{name}</span>
        <span className="tabular-nums"><span className="font-semibold text-slate-900">{format(now)}</span> <span className="text-slate-500">of {format(target)} · {pct.toFixed(0)}%</span></span></p>
      <div className="h-2.5 rounded-full bg-slate-500/10" role="progressbar" aria-label={name} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(pct, 100)}%`, background: SERIES_COLORS[0] }} />
      </div>
    </div>
  );
}

function TargetsModal({ growth, onClose }: { growth: Dashboard["growth"]; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [v, setV] = useState({
    revenue: String(growth.targets.revenue_target || ""), vehicles: String(growth.targets.vehicles_target || ""), interval: String(growth.service_interval_days),
  });
  const valid = Number(v.revenue || 0) >= 0 && Number.isInteger(Number(v.vehicles || 0)) && Number(v.interval) >= 30 && Number(v.interval) <= 730;
  const save = useMutation({
    mutationFn: () => put("/dealer-dashboard/targets", {
      monthly_revenue_target: Number(v.revenue || 0), monthly_vehicles_target: Number(v.vehicles || 0), service_interval_days: Number(v.interval),
    }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["dealer-dashboard"] }); toast.success("Targets saved"); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open title="Monthly targets" onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="grid gap-3">
        <Field label="Revenue target per month (₹, incl. GST)" hint="Leave empty for no target">{(id) => <input id={id} className="input" inputMode="decimal" value={v.revenue} onChange={(e) => setV({ ...v, revenue: e.target.value })} />}</Field>
        <Field label="Vehicles delivered per month" hint="Leave empty for no target">{(id) => <input id={id} className="input" inputMode="numeric" value={v.vehicles} onChange={(e) => setV({ ...v, vehicles: e.target.value })} />}</Field>
        <Field label="Service due after (days since last visit)" hint="Between 30 and 730 days">{(id) => <input id={id} className="input" inputMode="numeric" value={v.interval} onChange={(e) => setV({ ...v, interval: e.target.value })} />}</Field>
      </div>
    </Modal>
  );
}

// --- Page ------------------------------------------------------------------------------------

export default function DealerDashboard() {
  const options = presets();
  const [range, setRange] = useState({ key: "month", from: options[0]!.from, to: options[0]!.to });
  const [editingTargets, setEditingTargets] = useState(false);
  const q = useQuery({
    queryKey: ["dealer-dashboard", range.from, range.to],
    queryFn: () => get<Dashboard>("/dealer-dashboard", { date_from: range.from, date_to: range.to }),
    enabled: range.from <= range.to,
    placeholderData: keepPreviousData,
  });
  const d = q.data;
  const period = options.find((o) => o.key === range.key)?.label.toLowerCase() ?? `${fmtDate(range.from)} to ${fmtDate(range.to)}`;

  return (
    <>
      <PageHeader title="Dealer Dashboard" subtitle={`Business overview · ${period}${q.isFetching && d ? " · updating..." : ""}`} />
      <div className="glass mb-6 flex flex-wrap items-end gap-3 rounded-2xl p-4">
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Period">
          {options.map((o) => (
            <Button key={o.key} size="sm" variant={range.key === o.key ? "primary" : "secondary"} onClick={() => setRange({ key: o.key, from: o.from, to: o.to })}>{o.label}</Button>
          ))}
        </div>
        <Field label="From" className="w-40">{(id) => <input id={id} type="date" className="input" value={range.from} max={range.to} onChange={(e) => setRange({ key: "custom", from: e.target.value, to: range.to })} />}</Field>
        <Field label="To" className="w-40">{(id) => <input id={id} type="date" className="input" value={range.to} min={range.from} onChange={(e) => setRange({ key: "custom", from: range.from, to: e.target.value })} />}</Field>
      </div>

      {q.isLoading ? <Spinner /> : q.error && !d ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : d && (
        <div className="space-y-8">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <Stat label="Revenue (incl. GST)" value={rs(d.money.revenue)} icon={BadgeIndianRupee} compare={{ against: "previous period", now: d.money.revenue, before: d.money.revenue_previous_period }} />
            <Stat label="Collected" value={rs(d.money.collected)} icon={Wallet} hint="Payments received in the period" />
            <Stat label="Outstanding dues" value={rs(d.money.outstanding)} icon={AlertTriangle} tone={d.money.outstanding > 0 ? "warn" : undefined} hint="All unpaid invoices, today" />
            <Stat label="Vehicles delivered" value={num(d.workshop.delivered)} icon={CarFront} hint={`${num(d.workshop.arrivals)} came in`} />
            <Stat label="Average turnaround" value={`${d.workshop.average_turnaround_days.toFixed(1)} days`} icon={Clock} hint="Arrival to delivery" />
            <Stat label="Stock value (parts sheet)" value={rs(d.parts.stock_value)} icon={Boxes} hint={`${num(d.parts.parts_in_stock)} parts in stock`} />
          </div>

          <Section title="Money">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Same period last year" value={rs(d.money.revenue_last_year)} icon={CalendarClock} compare={{ against: "last year", now: d.money.revenue, before: d.money.revenue_last_year }} />
              <Stat label="Today / this month" value={rs(d.money.revenue_today)} icon={BadgeIndianRupee} hint={<>This month {rs(d.money.revenue_month)} · financial year {rs(d.money.revenue_financial_year)}</>} />
              <Stat label="Average bill" value={rs(d.money.average_bill)} icon={Gauge} hint={`${num(d.money.invoices)} invoices`} />
              <Stat label="GST collected" value={rs(d.money.gst_collected)} icon={BadgeIndianRupee} hint="On invoices finalised in the period" />
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="Sales by month" icon={BadgeIndianRupee} className="lg:col-span-2"><SalesTrend data={d.money.trend} /></Panel>
              <Panel title="Parts vs labour (period)" icon={Wrench}>
                <BarList format={rs} rows={[{ name: "Parts", value: d.money.parts_sales }, { name: "Labour", value: d.money.labour_sales }]}
                  empty="No sales in this period" />
                <p className="mt-3 text-xs text-slate-500">Before GST and after discounts.</p>
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="How old the dues are" icon={Hourglass} accent="text-amber-700 bg-amber-400/15">
                <BarList format={rs} rows={d.money.ageing.map((a) => ({ name: a.bucket, value: a.amount }))} empty="No dues - every invoice is paid" />
              </Panel>
              <Panel title="Biggest dues" icon={AlertTriangle} to="/invoices" toLabel="Invoices" accent="text-amber-700 bg-amber-400/15" className="lg:col-span-2">
                <Table name="dues" rows={d.money.top_dues} empty="No dues - every invoice is paid" columns={[
                  { key: "invoice_number", label: "Invoice" }, { key: "customer_name", label: "Customer" }, { key: "customer_mobile", label: "Mobile" },
                  { key: "vehicle_registration", label: "Vehicle" }, { key: "days", label: "Days", type: "number" }, { key: "outstanding", label: "Due", type: "money" },
                ]} />
              </Panel>
            </div>
          </Section>

          <Section title="Targets and growth">
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="This month's targets" icon={Target}>
                <div className="space-y-4">
                  <Progress name="Revenue" now={d.growth.targets.revenue_month} target={d.growth.targets.revenue_target} format={rs} />
                  <Progress name="Vehicles delivered" now={d.growth.targets.vehicles_month} target={d.growth.targets.vehicles_target} format={num} />
                  <Button size="sm" variant="secondary" onClick={() => setEditingTargets(true)}>Set targets</Button>
                </div>
              </Panel>
              <Panel title="Parts margin (period)" icon={BadgeIndianRupee} accent="text-emerald-700 bg-emerald-500/10">
                <p className="text-2xl font-semibold text-slate-900 tabular-nums">{rs(d.growth.parts_margin)} <span className="text-base font-medium text-slate-500">{d.growth.parts_margin_percent.toFixed(1)}%</span></p>
                <dl className="mt-3 space-y-1 text-sm">
                  <div className="flex justify-between"><dt className="text-slate-500">Parts sold (before GST)</dt><dd className="tabular-nums">{rs(d.growth.parts_sales)}</dd></div>
                  <div className="flex justify-between"><dt className="text-slate-500">Landed cost</dt><dd className="tabular-nums">{rs(d.growth.parts_cost)}</dd></div>
                </dl>
                <p className="mt-3 text-xs text-slate-500">Catalogue parts only, at today&apos;s landed cost (Closing Value ÷ Closing Qty.).</p>
              </Panel>
              <Panel title="Customers (period)" icon={Users}>
                <BarList rows={[{ name: "New", value: d.customers.new_customers }, { name: "Returning", value: d.customers.returning_customers }]} empty="No customers in this period" />
                <p className="mt-3 text-xs text-slate-500">{num(d.customers.customers_served)} customers served.</p>
              </Panel>
            </div>
            <Panel title={`Service due (${num(d.growth.service_due_count)})`} icon={CalendarClock} to="/customers" toLabel="Customers">
              <p className="mb-3 text-xs text-slate-500">Vehicles with no visit for {d.growth.service_interval_days} days or more and no open job: call them in.</p>
              <Table name="service-due" rows={d.growth.service_due} empty="No vehicle is due for service" columns={[
                { key: "registration_number", label: "Vehicle" }, { key: "model", label: "Model" }, { key: "customer", label: "Customer" },
                { key: "mobile", label: "Mobile" }, { key: "last_visit", label: "Last visit", type: "date" }, { key: "days", label: "Days since", type: "number" },
              ]} />
            </Panel>
          </Section>

          <Section title="Workshop">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label="Arrived today" value={num(d.workshop.arrivals_today)} icon={CarFront} />
              <Stat label="In the workshop now" value={num(d.workshop.in_workshop)} icon={Wrench} />
              <Stat label="Ready for delivery" value={num(d.workshop.ready_for_delivery)} icon={CarFront} />
              <Stat label="Repeat visits (within 30 days)" value={num(d.workshop.repeat_visit_count)} icon={AlertTriangle} tone={d.workshop.repeat_visit_count ? "warn" : undefined} hint="Vehicles back soon after a visit" />
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="Open jobs by stage" icon={Gauge} to="/jobs" toLabel="Job cards">
                <BarList rows={d.workshop.stages.map((s) => ({ name: s.stage, value: s.jobs }))} empty="No open jobs" />
              </Panel>
              <Panel title="Stuck jobs" icon={Hourglass} to="/jobs" toLabel="Job cards" accent="text-red-600 bg-red-500/10" className="lg:col-span-2">
                <p className="mb-3 text-xs text-slate-500">On hold, or open for more than 7 days.</p>
                <Table name="stuck-jobs" rows={d.workshop.stuck_jobs} empty="No stuck jobs" columns={[
                  { key: "job_number", label: "Job" }, { key: "registration_number", label: "Vehicle" }, { key: "model", label: "Model" },
                  { key: "status", label: "Status", type: "status" }, { key: "days", label: "Days open", type: "number" },
                ]} />
              </Panel>
            </div>
            <Panel title="Jobs and revenue by job type (period)" icon={Tags}>
              <Table name="job-types" rows={d.workshop.by_type.map((t) => ({ type: JOB_TYPE_LABEL[t.type] ?? t.type, jobs: t.jobs, revenue: t.revenue }))} columns={[
                { key: "type", label: "Job type" }, { key: "jobs", label: "Vehicles in", type: "number" }, { key: "revenue", label: "Billed (incl. GST)", type: "money" },
              ]} />
            </Panel>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Mechanics" icon={Users}>
                <Table name="mechanics" rows={d.workshop.mechanics} empty="No jobs assigned yet" columns={[
                  { key: "mechanic", label: "Mechanic" }, { key: "open_jobs", label: "Open jobs", type: "number" },
                  { key: "delivered", label: "Delivered (period)", type: "number" }, { key: "avg_days", label: "Avg days", type: "number" },
                ]} />
              </Panel>
              <Panel title="Repeat visits" icon={AlertTriangle} accent="text-amber-700 bg-amber-400/15">
                <Table name="repeat-visits" rows={d.workshop.repeat_visits} empty="No repeat visits in this period" columns={[
                  { key: "job_number", label: "Job" }, { key: "registration_number", label: "Vehicle" },
                  { key: "previous_visit", label: "Previous visit", type: "date" }, { key: "visit_at", label: "This visit", type: "date" },
                ]} />
              </Panel>
            </div>
          </Section>

          <Section title="Customers">
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="Customer feedback (period)" icon={Star} accent="text-amber-700 bg-amber-400/15">
                {d.customers.feedback.count ? (<>
                  <p className="text-2xl font-semibold text-slate-900 tabular-nums">{d.customers.feedback.average.toFixed(1)} <span className="text-base font-medium text-slate-500">out of 5 · {num(d.customers.feedback.count)} ratings</span></p>
                  <div className="mt-3"><BarList rows={d.customers.feedback.distribution.map((r) => ({ name: `${r.rating} star${r.rating > 1 ? "s" : ""}`, value: r.count }))} /></div>
                </>) : <p className="py-6 text-center text-sm text-slate-500">No ratings yet. Customers rate their visit on the invoice link.</p>}
              </Panel>
              <Panel title="Low ratings to follow up (3 stars or less)" icon={MessageSquareText} accent="text-red-600 bg-red-500/10" className="lg:col-span-2">
                <Table name="low-ratings" rows={d.customers.feedback.low} empty="No low ratings in this period" columns={[
                  { key: "job_number", label: "Job" }, { key: "customer_name", label: "Customer" }, { key: "customer_mobile", label: "Mobile" },
                  { key: "rating", label: "Stars", type: "number" }, { key: "comment", label: "Comment" }, { key: "created_at", label: "Date", type: "date" },
                ]} />
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              <Panel title="Vehicles serviced by model" icon={CarFront}>
                <BarList rows={d.customers.by_model.map((m) => ({ name: m.model, value: m.jobs }))} empty="No vehicles in this period" />
              </Panel>
              <Panel title="Top customers by spend" icon={Users} className="lg:col-span-2">
                <Table name="top-customers" rows={d.customers.top_customers} empty="No invoices in this period" columns={[
                  { key: "name", label: "Customer" }, { key: "mobile", label: "Mobile" }, { key: "invoices", label: "Invoices", type: "number" }, { key: "spend", label: "Spend", type: "money" },
                ]} />
              </Panel>
            </div>
          </Section>

          <Section title="Parts and stock">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Stat label={`Dead stock (no sale in ${d.parts.dead_stock_days} days)`} value={rs(d.parts.dead_stock_value)} icon={PackageX} tone={d.parts.dead_stock_value ? "warn" : undefined} hint={`${num(d.parts.dead_stock_parts)} parts`} />
              <Stat label="Count differences" value={num(d.parts.count_difference_parts)} icon={AlertTriangle} tone={d.parts.count_difference_parts ? "warn" : undefined} hint="ACTUAL QUANTITY differs from Closing Qty." />
              <Stat label="Parts shortages" value={num(d.parts.shortage_lines + d.parts.unavailable_lists)} icon={PackageX} tone={d.parts.shortage_lines + d.parts.unavailable_lists ? "danger" : undefined} hint="Requests waiting for parts" />
              <Stat label="Purchase requests to approve" value={num(d.parts.pending_purchase_requests)} icon={Boxes} />
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Stock value by ABC class" icon={Boxes} to="/parts" toLabel="Catalogue">
                <BarList format={rs} rows={d.parts.by_abc.map((g) => ({ name: g.group, value: g.value, note: `${num(g.parts)} parts` }))} empty="No stock in the parts sheet" />
              </Panel>
              <Panel title="Stock value by movement class" icon={Boxes} to="/parts" toLabel="Catalogue">
                <BarList format={rs} rows={d.parts.by_movement.map((g) => ({ name: g.group, value: g.value, note: `${num(g.parts)} parts` }))} empty="No stock in the parts sheet" />
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Top parts by sales value (period)" icon={BadgeIndianRupee}>
                <Table name="top-parts-value" rows={d.parts.top_by_value} empty="No parts sold in this period" columns={[
                  { key: "sku", label: "Part number" }, { key: "name", label: "Part" }, { key: "qty", label: "Qty", type: "number" }, { key: "value", label: "Sales", type: "money" },
                ]} />
              </Panel>
              <Panel title="Top parts by quantity (period)" icon={Boxes}>
                <Table name="top-parts-qty" rows={d.parts.top_by_qty} empty="No parts sold in this period" columns={[
                  { key: "sku", label: "Part number" }, { key: "name", label: "Part" }, { key: "qty", label: "Qty", type: "number" }, { key: "value", label: "Sales", type: "money" },
                ]} />
              </Panel>
            </div>
            <div className="grid gap-4 lg:grid-cols-2">
              <Panel title="Running low (less than a month's sales left)" icon={PackageX} accent="text-red-600 bg-red-500/10">
                <Table name="running-low" rows={d.parts.running_low} empty="No fast-moving part is running low" columns={[
                  { key: "sku", label: "Part number" }, { key: "name", label: "Part" }, { key: "qty", label: "On shelf", type: "number" }, { key: "sold_30_days", label: "Sold, 30 days", type: "number" },
                ]} />
              </Panel>
              <Panel title="Dead stock (most money stuck)" icon={PackageX} accent="text-amber-700 bg-amber-400/15">
                <Table name="dead-stock" rows={d.parts.dead_stock} empty="No dead stock" columns={[
                  { key: "sku", label: "Part number" }, { key: "name", label: "Part" }, { key: "qty", label: "Qty", type: "number" },
                  { key: "value", label: "Value", type: "money" }, { key: "last_sold", label: "Last sold", type: "date" },
                ]} />
              </Panel>
            </div>
            <Panel title="Biggest count differences" icon={AlertTriangle} accent="text-amber-700 bg-amber-400/15">
              <p className="mb-3 text-xs text-slate-500">Physical count (ACTUAL QUANTITY) against Closing Qty. in the parts sheet, valued at landed cost. Negative = fewer on the shelf.</p>
              <Table name="count-differences" rows={d.parts.count_differences} empty="Every counted part matches the sheet" columns={[
                { key: "sku", label: "Part number" }, { key: "name", label: "Part" }, { key: "closing_qty", label: "Closing Qty.", type: "number" },
                { key: "actual_qty", label: "Actual", type: "number" }, { key: "difference", label: "Difference", type: "number" }, { key: "value", label: "Value", type: "money" },
              ]} />
            </Panel>
          </Section>
        </div>
      )}
      {editingTargets && d && <TargetsModal growth={d.growth} onClose={() => setEditingTargets(false)} />}
    </>
  );
}
