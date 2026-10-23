import { useQuery } from "@tanstack/react-query";
import {
  ArrowLeftRight, BarChart3, Bell, Boxes, CarFront, ClipboardList, FileText, Gauge, LayoutGrid, LineChart, LogOut, Menu,
  PackageSearch, PlusCircle, ScrollText, Send, Settings, Sheet, ShoppingCart, SlidersHorizontal, Users, Wrench, X,
} from "lucide-react";
import { type ComponentType, useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { cx } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useFeatures } from "@/hooks/useFeatures";
import { ROLE_LABEL } from "@/lib/format";
import { get } from "@/services/api";

interface NavItem { to: string; label: string; short?: string; icon: ComponentType<{ className?: string }>; perms?: string[]; feature?: "partsSheet"; end?: boolean }
const NAV: { heading?: string; items: NavItem[] }[] = [
  {
    items: [
      { to: "/", label: "Dashboard", short: "Home", icon: Gauge, end: true },
      { to: "/dealer", label: "Dealer Dashboard", short: "Dealer", icon: BarChart3, perms: ["dealer.dashboard"] },
      { to: "/reception/new", label: "New Service Visit", short: "New visit", icon: PlusCircle, perms: ["reception.manage"] },
      { to: "/jobs", label: "Job Cards", short: "Jobs", icon: ClipboardList, perms: ["job.read_all", "job.read_assigned"] },
      { to: "/customers", label: "Customers & Vehicles", short: "Customers", icon: CarFront, perms: ["customer.read"] },
    ],
  },
  {
    heading: "Parts",
    items: [
      { to: "/parts-requests", label: "Parts Requests", short: "Requests", icon: PackageSearch, perms: ["inventory.read"] },
      { to: "/parts", label: "Parts Catalogue", short: "Parts", icon: Boxes, perms: ["parts.read"] },
      { to: "/parts-sheet", label: "Parts Sheet", short: "Sheet", icon: Sheet, perms: ["inventory.read", "parts.manage"], feature: "partsSheet" },
      { to: "/stock-movements", label: "Stock Movements", short: "Movements", icon: ArrowLeftRight, perms: ["inventory.read"] },
      { to: "/purchase-requests", label: "Purchase Requests", short: "Purchases", icon: ShoppingCart, perms: ["inventory.read"] },
    ],
  },
  {
    heading: "Billing",
    items: [
      { to: "/invoices", label: "Invoices", icon: FileText, perms: ["invoice.read"] },
      { to: "/deliveries", label: "Invoice Delivery", short: "Delivery", icon: Send, perms: ["delivery.manage"] },
      { to: "/reports", label: "Reports", icon: LineChart, perms: ["report.view", "report.inventory"] },
    ],
  },
  {
    heading: "Administration",
    items: [
      { to: "/admin/users", label: "Users & Roles", short: "Users", icon: Users, perms: ["user.manage"] },
      { to: "/admin/master-data", label: "Master Data", short: "Master data", icon: SlidersHorizontal, perms: ["masterdata.manage"] },
      { to: "/admin/settings", label: "Settings", icon: Settings, perms: ["settings.manage"] },
      { to: "/admin/audit", label: "Audit Log", short: "Audit", icon: ScrollText, perms: ["audit.read"] },
    ],
  },
];

/** Order in which pages earn a slot in the phone tab bar (after Dashboard). */
const TAB_PRIORITY = ["/jobs", "/reception/new", "/parts-requests", "/invoices", "/parts", "/admin/users", "/admin/audit", "/reports"];

const initials = (name?: string) => (name ?? "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]!.toUpperCase()).join("") || "?";

function Brand({ compact, dark }: { compact?: boolean; dark?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5">
      <span className={cx("grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-brand-400 to-brand-700 shadow-lg",
        dark ? "shadow-brand-500/30 ring-1 ring-white/15" : "shadow-brand-900/30")}>
        <Wrench className="h-[18px] w-[18px] text-white" aria-hidden />
      </span>
      <span className={cx("leading-tight", compact && "hidden sm:block")}>
        <span className={cx("block text-sm font-semibold tracking-tight", dark ? "text-white" : "text-slate-900")}>Vin Desk</span>
        <span className={cx("block text-xs", dark ? "text-slate-400" : "text-slate-500")}>Service Centre Management</span>
      </span>
    </Link>
  );
}

/** Dark navy panel shared by the desktop sidebar and the phone menu (matches the sign-in page). */
const NAVY = "bg-[radial-gradient(28rem_20rem_at_0%_0%,rgb(47_107_176/0.35),transparent_60%),linear-gradient(180deg,#0f1f35,#0b1526)] text-slate-300";

export default function AppLayout() {
  const { user, logout, can } = useAuth();
  const features = useFeatures();
  const [open, setOpen] = useState(false);
  const location = useLocation();
  const unread = useQuery({
    queryKey: ["notifications", "unread"],
    queryFn: () => get<{ unread: number }>("/notifications/unread-count"),
    refetchInterval: 30_000,
  });
  useEffect(() => setOpen(false), [location.pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  const allowed = (item: NavItem) => (!item.perms || can(...item.perms)) && (!item.feature || features[item.feature]);
  const display = (item: NavItem, short = false) =>
    item.to === "/jobs" && !can("job.read_all") ? "My Jobs" : short ? item.short ?? item.label : item.label;
  const flat = NAV.flatMap((g) => g.items).filter(allowed);
  const tabs = [flat[0]!, ...TAB_PRIORITY.map((to) => flat.find((i) => i.to === to)).filter((i): i is NavItem => !!i)].slice(0, 4);
  const count = unread.data?.unread ?? 0;

  const nav = (
    <nav aria-label="Main" className="flex-1 space-y-5 overflow-y-auto px-3 py-2">
      {NAV.map((group, i) => {
        const items = group.items.filter(allowed);
        if (!items.length) return null;
        return (
          <div key={i}>
            {group.heading && <p className="mb-1.5 px-3 text-[11px] font-semibold tracking-wider text-slate-500 uppercase">{group.heading}</p>}
            <ul className="space-y-0.5">
              {items.map((item) => {
                const Icon = item.icon;
                return (
                  <li key={item.to}>
                    <NavLink to={item.to} end={item.end}
                      className={({ isActive }) => cx("group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-200",
                        isActive ? "bg-white/10 text-white shadow-inner ring-1 ring-white/10" : "text-slate-400 hover:translate-x-0.5 hover:bg-white/[0.06] hover:text-white")}>
                      {({ isActive }) => (<>
                        {isActive && <span aria-hidden className="absolute top-1/2 -left-3 h-6 w-1 -translate-y-1/2 rounded-r-full bg-gradient-to-b from-sky-300 to-brand-500 shadow-[0_0_12px] shadow-sky-400/60" />}
                        <Icon className={cx("h-[18px] w-[18px] shrink-0 transition-colors", isActive ? "text-sky-300" : "text-slate-500 group-hover:text-slate-200")} />
                        {display(item)}
                      </>)}
                    </NavLink>
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </nav>
  );

  const account = (
    <div className="m-3 flex items-center gap-3 rounded-xl border border-white/10 bg-white/[0.06] p-2.5">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-gradient-to-br from-sky-400 to-brand-600 text-xs font-semibold text-white" aria-hidden>{initials(user?.full_name)}</span>
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-sm font-medium text-white">{user?.full_name}</p>
        <p className="truncate text-xs text-slate-400">{user && ROLE_LABEL[user.role_code]}</p>
      </div>
      <button type="button" onClick={() => void logout()} aria-label="Sign out" title="Sign out"
        className="rounded-lg p-2 text-slate-400 transition-colors hover:bg-white/10 hover:text-red-300">
        <LogOut className="h-4 w-4" />
      </button>
    </div>
  );

  return (
    <div className="min-h-dvh lg:pl-[17.5rem]">
      {/* Floating desktop sidebar */}
      <aside className={cx("no-print fixed inset-y-3 left-3 z-30 hidden w-64 flex-col rounded-2xl shadow-2xl shadow-slate-900/30 ring-1 ring-white/10 lg:flex", NAVY)}>
        <div className="px-5 pt-5 pb-4"><Brand dark /></div>
        {nav}
        {account}
      </aside>

      {/* Slide-over navigation for tablets and phones */}
      {open && (
        <div className="no-print fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 animate-fade-in bg-slate-900/30 backdrop-blur-[3px]" onClick={() => setOpen(false)} />
          <aside className={cx("absolute inset-y-0 left-0 flex w-72 max-w-[85vw] animate-drawer-in flex-col rounded-r-3xl shadow-2xl pt-[env(safe-area-inset-top)]", NAVY)}>
            <div className="flex items-center justify-between px-5 pt-5 pb-4">
              <Brand dark />
              <button type="button" aria-label="Close menu" className="rounded-lg p-2 text-slate-400 hover:bg-white/10 hover:text-white" onClick={() => setOpen(false)}>
                <X className="h-5 w-5" />
              </button>
            </div>
            {nav}
            <div className="pb-[env(safe-area-inset-bottom)]">{account}</div>
          </aside>
        </div>
      )}

      <header className="no-print sticky top-0 z-20 border-b border-white/60 bg-white/55 pt-[env(safe-area-inset-top)] backdrop-blur-xl lg:border-transparent lg:bg-transparent lg:backdrop-blur-none">
        <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-3 px-4 sm:px-6 lg:h-16">
          <div className="flex items-center gap-2 lg:hidden">
            <button type="button" aria-label="Open menu" className="-ml-2 rounded-lg p-2 text-slate-600 hover:bg-slate-900/5" onClick={() => setOpen(true)}>
              <Menu className="h-5 w-5" />
            </button>
            <Brand compact />
          </div>
          <p className="hidden text-sm text-slate-500 lg:block">
            Signed in as <span className="font-medium text-slate-700">{user && ROLE_LABEL[user.role_code]}</span>
          </p>
          <div className="flex items-center gap-1.5">
            <Link to="/notifications" aria-label={`Notifications, ${count} unread`}
              className={cx("relative grid h-10 w-10 place-items-center rounded-xl transition-colors lg:glass",
                location.pathname === "/notifications" ? "text-brand-700" : "text-slate-600 hover:text-slate-900")}>
              <Bell className="h-5 w-5" />
              {count > 0 && (
                <span className="absolute top-1 right-1 min-w-[18px] rounded-full bg-red-500 px-1 text-center text-[10px] leading-[18px] font-semibold text-white ring-2 ring-white">
                  {count > 99 ? "99+" : count}
                </span>
              )}
            </Link>
            <span className="grid h-9 w-9 place-items-center rounded-full bg-brand-500/15 text-xs font-semibold text-brand-700 lg:hidden" title={user?.full_name} aria-hidden>
              {initials(user?.full_name)}
            </span>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 pt-3 pb-28 sm:px-6 lg:pt-2 lg:pb-10">
        <ErrorBoundary resetKey={location.pathname}>
          {/* Each page glides in when opened. */}
          <div key={location.pathname} className="animate-[rise_500ms_cubic-bezier(0.16,1,0.3,1)_both]"><Outlet /></div>
        </ErrorBoundary>
      </main>

      {/* Phone and tablet tab bar */}
      <nav aria-label="Quick navigation" className="no-print glass-strong fixed inset-x-3 bottom-3 z-30 rounded-2xl pb-[env(safe-area-inset-bottom)] lg:hidden">
        <ul className="grid grid-cols-5">
          {tabs.map((item) => {
            const Icon = item.icon;
            return (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end}
                  className={({ isActive }) => cx("flex flex-col items-center gap-0.5 py-2 text-[11px] font-medium transition-colors",
                    isActive ? "text-brand-700" : "text-slate-500 hover:text-slate-800")}>
                  {({ isActive }) => (<>
                    <span className={cx("grid h-7 w-12 place-items-center rounded-full transition-colors", isActive && "bg-brand-500/12")}>
                      <Icon className="h-[18px] w-[18px]" />
                    </span>
                    <span className="max-w-full truncate px-1">{display(item, true)}</span>
                  </>)}
                </NavLink>
              </li>
            );
          })}
          <li className={cx(tabs.length < 4 && "col-start-5")}>
            <button type="button" onClick={() => setOpen(true)} className="flex w-full flex-col items-center gap-0.5 py-2 text-[11px] font-medium text-slate-500 hover:text-slate-800">
              <span className="grid h-7 w-12 place-items-center rounded-full"><LayoutGrid className="h-[18px] w-[18px]" /></span>
              More
            </button>
          </li>
        </ul>
      </nav>
    </div>
  );
}
