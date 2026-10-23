/** Building blocks shared by the role dashboards. */
import { ArrowUpRight, type LucideIcon } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import heroImage from "@/assets/login-urbania.png";
import { cx } from "@/components/ui";
import { rupees } from "@/lib/format";

// --- Motion ----------------------------------------------------------------------------------

const motionOk = () =>
  typeof window !== "undefined" && typeof window.matchMedia === "function" && !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Smoothly counts up to `target` (skipped for reduced motion and in tests). */
export function useCountUp(target: number, ms = 900): number {
  const animate = motionOk();
  const [value, setValue] = useState(animate ? 0 : target);
  const from = useRef(0);
  useEffect(() => {
    if (!animate) { setValue(target); return; }
    const start = performance.now();
    const begin = from.current;
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      setValue(begin + (target - begin) * (1 - Math.pow(1 - t, 3)));
      if (t < 1) frame = requestAnimationFrame(tick);
      else from.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, ms, animate]);
  return value;
}

export function CountUp({ value, money }: { value: number; money?: boolean }) {
  const shown = useCountUp(value);
  return <>{money ? rupees(shown) : Math.round(shown).toLocaleString("en-IN")}</>;
}

// --- Hero banners, one theme per role --------------------------------------------------------

export type Theme = "blue" | "emerald" | "amber" | "violet";
const HERO: Record<Theme, { bg: string; glow: string; eyebrow: string }> = {
  blue: { bg: "bg-[linear-gradient(100deg,#0b1526_15%,rgb(11_21_38/0.85)_45%,rgb(11_21_38/0.2))]", glow: "bg-sky-400/20", eyebrow: "text-sky-300" },
  emerald: { bg: "bg-[linear-gradient(110deg,#03241c,#064e3b_55%,#0f766e)]", glow: "bg-emerald-300/25", eyebrow: "text-emerald-300" },
  amber: { bg: "bg-[linear-gradient(110deg,#2a1505,#7c2d12_55%,#b45309)]", glow: "bg-amber-300/25", eyebrow: "text-amber-300" },
  violet: { bg: "bg-[linear-gradient(110deg,#140f2e,#312e81_55%,#4c1d95)]", glow: "bg-fuchsia-300/20", eyebrow: "text-violet-300" },
};

export interface HeroMetric { label: string; value: number; money?: boolean }

const greeting = () => {
  const h = new Date().getHours();
  return h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : "Good evening";
};

/** Role banner: eyebrow, greeting, title, headline figures and actions. The manager's shows the Urbania photo. */
export function Hero({ theme, eyebrow, icon: Icon, name, title, subtitle, metrics, actions, photo }: {
  theme: Theme; eyebrow: string; icon: LucideIcon; name: string; title: string; subtitle?: string;
  metrics?: HeroMetric[]; actions?: ReactNode; photo?: boolean;
}) {
  const t = HERO[theme];
  return (
    <section className="relative mb-6 overflow-hidden rounded-3xl bg-slate-950 text-white shadow-xl shadow-slate-900/20 ring-1 ring-white/10">
      {photo && <img src={heroImage} alt="" aria-hidden className="absolute inset-0 h-full w-full animate-ken-burns object-cover object-[50%_65%] opacity-45" />}
      <div aria-hidden className={cx("absolute inset-0", t.bg)} />
      {!photo && <div aria-hidden className="absolute inset-0 bg-[radial-gradient(rgb(255_255_255/0.07)_1px,transparent_1px)] [background-size:18px_18px]" />}
      <div aria-hidden className={cx("pointer-events-none absolute -top-1/2 -left-1/4 h-full w-2/3 animate-drift rounded-full blur-3xl", t.glow)} />
      <Icon aria-hidden className="pointer-events-none absolute -right-6 -bottom-8 h-48 w-48 rotate-[-12deg] text-white/[0.06]" strokeWidth={1.2} />
      <div className="relative flex flex-wrap items-end justify-between gap-6 p-6 sm:p-8">
        <div className="stagger min-w-0">
          <p className={cx("text-[11px] font-semibold tracking-[0.2em] uppercase", t.eyebrow)}>{eyebrow}</p>
          <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">{title}</h1>
          <p className="mt-1 text-sm text-white/70">
            {greeting()}, {name.split(" ")[0]} · {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long" })}
            {subtitle && <span className="hidden sm:inline"> · {subtitle}</span>}
          </p>
          {metrics && (
            <dl className="mt-5 flex flex-wrap gap-x-8 gap-y-3">
              {metrics.map((m) => (
                <div key={m.label} className="border-l border-white/20 pl-3 first:border-0 first:pl-0">
                  <dt className="text-[11px] tracking-wide text-white/60 uppercase">{m.label}</dt>
                  <dd className="text-2xl font-semibold tracking-tight tabular-nums"><CountUp value={m.value} money={m.money} /></dd>
                </div>
              ))}
            </dl>
          )}
        </div>
        {actions && <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">{actions}</div>}
      </div>
    </section>
  );
}

// --- Panels and small figures ----------------------------------------------------------------

/** White panel with an icon heading and an optional "view all" link. */
export function Panel({ title, icon: Icon, to, toLabel = "View all", className, children, accent = "text-brand-600 bg-brand-500/10" }: {
  title: string; icon: LucideIcon; to?: string; toLabel?: string; className?: string; children: ReactNode; accent?: string;
}) {
  return (
    <section className={cx("glass flex flex-col rounded-2xl", className)}>
      <header className="flex items-center justify-between gap-2 px-5 pt-4 pb-3">
        <h2 className="flex items-center gap-2.5 text-[15px] font-semibold tracking-tight text-slate-900">
          <span className={cx("grid h-8 w-8 place-items-center rounded-lg", accent)}><Icon className="h-4 w-4" aria-hidden /></span>
          {title}
        </h2>
        {to && (
          <Link to={to} className="group inline-flex items-center gap-1 text-xs font-medium text-slate-500 transition-colors hover:text-brand-700">
            {toLabel}<ArrowUpRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" aria-hidden />
          </Link>
        )}
      </header>
      <div className="flex-1 px-5 pb-5">{children}</div>
    </section>
  );
}

type Tone = "default" | "warn" | "danger" | "good";
const TONE_TEXT: Record<Tone, string> = { default: "text-slate-900", warn: "text-amber-700", danger: "text-red-700", good: "text-emerald-700" };
const TONE_ICON: Record<Tone, string> = {
  default: "bg-brand-500/10 text-brand-600", warn: "bg-amber-400/15 text-amber-600",
  danger: "bg-red-500/10 text-red-600", good: "bg-emerald-500/10 text-emerald-600",
};

/** Compact figure: icon, number, label; links somewhere when there is something to act on. */
export function Figure({ label, value, icon: Icon, tone = "default", to, money }: {
  label: string; value: number; icon: LucideIcon; tone?: Tone; to?: string; money?: boolean;
}) {
  const active = value > 0;
  const body = (
    <div className={cx("group flex h-full items-center gap-3 rounded-xl border border-slate-900/[0.06] bg-white/55 p-3 transition-all duration-200",
      to && "hover:-translate-y-0.5 hover:border-slate-900/10 hover:bg-white hover:shadow-md")}>
      <span className={cx("grid h-10 w-10 shrink-0 place-items-center rounded-xl transition-transform duration-200 group-hover:scale-105",
        active ? TONE_ICON[tone] : "bg-slate-500/10 text-slate-400")}>
        <Icon className="h-5 w-5" aria-hidden />
      </span>
      <div className="min-w-0">
        <p className={cx("text-xl leading-tight font-semibold tabular-nums", active ? TONE_TEXT[tone] : "text-slate-400")}><CountUp value={value} money={money} /></p>
        <p className="truncate text-xs text-slate-500">{label}</p>
      </div>
    </div>
  );
  return to ? <Link to={to} className="rounded-xl">{body}</Link> : body;
}

// --- 7-day trend chart -----------------------------------------------------------------------

/** Categorical slots 1 and 2 of the validated reference palette (blue, orange). */
export const SERIES_COLORS = ["#2a78d6", "#eb6834"];

export interface Series { key: string; name: string }

const dayLabel = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString("en-IN", { weekday: "short", day: "numeric" });
const fmt = (v: number, money?: boolean) => (money ? rupees(v) : v.toLocaleString("en-IN"));

function ChartTooltip({ active, payload, label, money }: { active?: boolean; payload?: { name: string; value: number; color: string }[]; label?: string; money?: boolean }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="glass-strong rounded-xl px-3 py-2 text-xs">
      <p className="mb-1 font-medium text-slate-900">{dayLabel(String(label))}</p>
      {payload.map((p) => (
        <p key={p.name} className="flex items-center gap-2 text-slate-600">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} aria-hidden />
          {p.name}: <span className="font-semibold text-slate-900 tabular-nums">{fmt(Number(p.value), money)}</span>
        </p>
      ))}
    </div>
  );
}

/** Last-7-days chart: area lines for money, bars for counts. A legend with 7-day totals gives the
 *  colours a text label (one series needs no legend box: the panel title names it). */
export function TrendChart({ data, series, money, kind = money ? "area" : "bar", height = 220 }: {
  data: Record<string, number | string>[]; series: Series[]; money?: boolean; kind?: "area" | "bar"; height?: number;
}) {
  const rows = data.map((d) => ({ ...d, ...Object.fromEntries(series.map((s) => [s.key, Number(d[s.key] ?? 0)])) }));
  const totals = series.map((s) => rows.reduce((sum, r) => sum + Number(r[s.key]), 0));
  const axis = { tick: { fontSize: 11, fill: "#64748b" }, tickLine: false, axisLine: false };
  return (
    <div>
      <div className="mb-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
        {series.map((s, i) => (
          <span key={s.key} className="flex items-center gap-2">
            {series.length > 1 && (
              <svg width="18" height="8" aria-hidden><line x1="0" y1="4" x2="18" y2="4" stroke={SERIES_COLORS[i]} strokeWidth="2.5" strokeDasharray={i > 0 ? "5 3" : undefined} /></svg>
            )}
            {s.name} <span className="font-semibold text-slate-900 tabular-nums">{fmt(totals[i]!, money)}</span>
          </span>
        ))}
        <span className="ml-auto text-slate-400">Last 7 days</span>
      </div>
      <div style={{ height }} role="img" aria-label={`${series.map((s, i) => `${s.name} ${fmt(totals[i]!, money)}`).join(", ")} over the last 7 days`}>
        <ResponsiveContainer width="100%" height="100%">
          {kind === "area" ? (
            <AreaChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
              <defs>
                {series.map((s, i) => (
                  <linearGradient key={s.key} id={`fill-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={SERIES_COLORS[i]} stopOpacity={0.22} />
                    <stop offset="100%" stopColor={SERIES_COLORS[i]} stopOpacity={0} />
                  </linearGradient>
                ))}
              </defs>
              <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={dayLabel} {...axis} />
              <YAxis width={money ? 64 : 32} tickFormatter={(v: number) => (money ? `₹${v >= 1000 ? `${Math.round(v / 1000)}k` : v}` : String(v))} {...axis} />
              <Tooltip content={<ChartTooltip money={money} />} cursor={{ stroke: "#94a3b8", strokeDasharray: "3 3" }} />
              {series.map((s, i) => (
                // Later series are dashed lines without fill, so identical series stay visible on top of each other.
                <Area key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={SERIES_COLORS[i]} strokeWidth={2}
                  strokeDasharray={i > 0 ? "6 4" : undefined} fill={i === 0 ? `url(#fill-${s.key})` : "none"}
                  dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#fff" }} />
              ))}
            </AreaChart>
          ) : (
            <BarChart data={rows} margin={{ top: 4, right: 4, bottom: 0, left: 0 }} barCategoryGap="28%">
              <CartesianGrid vertical={false} stroke="#e2e8f0" strokeDasharray="3 3" />
              <XAxis dataKey="date" tickFormatter={dayLabel} {...axis} />
              <YAxis width={32} allowDecimals={false} {...axis} />
              <Tooltip content={<ChartTooltip />} cursor={{ fill: "rgb(148 163 184 / 0.12)" }} />
              {series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.name} fill={SERIES_COLORS[i]} radius={[4, 4, 0, 0]} maxBarSize={36} />)}
            </BarChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
