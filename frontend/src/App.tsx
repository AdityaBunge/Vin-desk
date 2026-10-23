import { type ReactNode, Suspense, lazy } from "react";
import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { EmptyState, Spinner } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import AppLayout from "@/layouts/AppLayout";
import Dashboard from "@/pages/Dashboard";
import Login from "@/pages/Login";
import PublicInvoice from "@/pages/PublicInvoice";

const NewVisit = lazy(() => import("@/pages/NewVisit"));
const Jobs = lazy(() => import("@/pages/Jobs"));
const JobDetail = lazy(() => import("@/pages/JobDetail"));
const JobCardPrint = lazy(() => import("@/pages/JobCardPrint"));
const Customers = lazy(() => import("@/pages/Customers"));
const PartsRequests = lazy(() => import("@/pages/PartsRequests"));
const Parts = lazy(() => import("@/pages/Parts"));
const PartsSheet = lazy(() => import("@/pages/PartsSheet"));
const StockMovements = lazy(() => import("@/pages/Stock").then((m) => ({ default: m.StockMovements })));
const PurchaseRequests = lazy(() => import("@/pages/Stock").then((m) => ({ default: m.PurchaseRequests })));
const Invoices = lazy(() => import("@/pages/Invoices").then((m) => ({ default: m.Invoices })));
const InvoiceDetail = lazy(() => import("@/pages/Invoices").then((m) => ({ default: m.InvoiceDetail })));
const Deliveries = lazy(() => import("@/pages/Invoices").then((m) => ({ default: m.Deliveries })));
const Reports = lazy(() => import("@/pages/Reports"));
const DealerDashboard = lazy(() => import("@/pages/DealerDashboard"));
const Notifications = lazy(() => import("@/pages/Notifications"));
const Users = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.Users })));
const MasterData = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.MasterData })));
const Settings = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.Settings })));
const AuditLog = lazy(() => import("@/pages/Admin").then((m) => ({ default: m.AuditLog })));

function RequireAuth() {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <div className="flex min-h-screen items-center justify-center"><Spinner label="Restoring your session..." /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

/** Hides pages the role cannot use. The API enforces the same permissions independently. */
function Guard({ perms, children }: { perms: string[]; children: ReactNode }) {
  const { can } = useAuth();
  if (!can(...perms)) return <EmptyState title="You do not have access to this page" hint="Ask an administrator if you need this permission." />;
  return <>{children}</>;
}

const guard = (perms: string[], element: ReactNode) => <Guard perms={perms}>{element}</Guard>;

export default function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/i/:token" element={<PublicInvoice />} />
        <Route element={<RequireAuth />}>
          <Route path="/jobs/:id/print" element={guard(["job.read_all", "job.read_assigned"], <JobCardPrint />)} />
          <Route element={<AppLayout />}>
            <Route index element={<Dashboard />} />
            <Route path="/dealer" element={guard(["dealer.dashboard"], <DealerDashboard />)} />
            <Route path="/reception/new" element={guard(["reception.manage"], <NewVisit />)} />
            <Route path="/jobs" element={guard(["job.read_all", "job.read_assigned"], <Jobs />)} />
            <Route path="/jobs/:id" element={guard(["job.read_all", "job.read_assigned"], <JobDetail />)} />
            <Route path="/customers" element={guard(["customer.read"], <Customers />)} />
            <Route path="/parts-requests" element={guard(["inventory.read"], <PartsRequests />)} />
            <Route path="/parts" element={guard(["parts.read"], <Parts />)} />
            <Route path="/parts-sheet" element={guard(["inventory.read", "parts.manage"], <PartsSheet />)} />
            <Route path="/stock-movements" element={guard(["inventory.read"], <StockMovements />)} />
            <Route path="/purchase-requests" element={guard(["inventory.read"], <PurchaseRequests />)} />
            <Route path="/invoices" element={guard(["invoice.read"], <Invoices />)} />
            <Route path="/invoices/:id" element={guard(["invoice.read"], <InvoiceDetail />)} />
            <Route path="/deliveries" element={guard(["delivery.manage"], <Deliveries />)} />
            <Route path="/reports" element={guard(["report.view", "report.inventory"], <Reports />)} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/admin/users" element={guard(["user.manage"], <Users />)} />
            <Route path="/admin/master-data" element={guard(["masterdata.manage"], <MasterData />)} />
            <Route path="/admin/settings" element={guard(["settings.manage"], <Settings />)} />
            <Route path="/admin/audit" element={guard(["audit.read"], <AuditLog />)} />
            <Route path="*" element={<EmptyState title="Page not found" />} />
          </Route>
        </Route>
      </Routes>
    </Suspense>
  );
}
