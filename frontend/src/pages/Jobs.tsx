import { keepPreviousData, useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataTable } from "@/components/DataTable";
import { Button, Card, Field, PageHeader, StatusBadge } from "@/components/ui";
import { useAuth, useViewStatus } from "@/hooks/useAuth";
import { useListParams } from "@/hooks/useListParams";
import { fmtDateTime, label, mobileDisplay } from "@/lib/format";
import { get } from "@/services/api";
import type { JobSummary, Page, UserRef, VehicleModel } from "@/types";

export const JOB_STATUSES = [
  "AWAITING_ASSIGNMENT", "INSPECTION_IN_PROGRESS", "AWAITING_PARTS", "READY_FOR_SERVICE",
  "IN_SERVICE", "READY_FOR_BILLING", "READY_FOR_DELIVERY", "COMPLETED", "ON_HOLD", "CANCELLED",
];
const KEYS = ["q", "status", "mechanic_id", "model_id", "date_from", "date_to", "active_only", "returned_only", "sort", "order"] as const;
const PAGE_SIZE = 20;

export default function Jobs() {
  const { can } = useAuth();
  const viewStatus = useViewStatus();
  const navigate = useNavigate();
  const all = can("job.read_all");
  const { values, page, set } = useListParams(KEYS);
  const [search, setSearch] = useState(values.q);
  useEffect(() => {
    const t = setTimeout(() => search !== values.q && set({ q: search }), 350); // debounce typing
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const sort = values.sort || "visit_at";
  const order = (values.order || "desc") as "asc" | "desc";

  const q = useQuery({
    queryKey: ["jobs", values, page],
    queryFn: () => get<Page<JobSummary>>("/jobs", { ...values, sort, order, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const mechanics = useQuery({ queryKey: ["mechanics"], queryFn: () => get<UserRef[]>("/mechanics"), enabled: all });
  const models = useQuery({ queryKey: ["vehicle-models"], queryFn: () => get<VehicleModel[]>("/vehicle-models") });

  const columns = useMemo<ColumnDef<JobSummary>[]>(() => [
    { id: "job_number", accessorFn: (r) => r.job_number, header: "Job card", cell: ({ row }) => <span className="font-medium text-brand-700">{row.original.job_number}</span> },
    { id: "vehicle", header: "Vehicle", enableSorting: false, cell: ({ row }) => <>{row.original.vehicle.registration_number}<br /><span className="text-xs text-slate-500">{row.original.vehicle.model.name}</span></> },
    { id: "customer", header: "Customer", enableSorting: false, cell: ({ row }) => <>{row.original.customer.name}<br /><span className="text-xs text-slate-500">{mobileDisplay(row.original.customer.mobile)}</span></> },
    { id: "status", accessorFn: (r) => r.status, header: "Status", cell: ({ row }) => <span className="flex flex-wrap gap-1"><StatusBadge status={viewStatus(row.original.status)} />{row.original.priority !== "NORMAL" && <StatusBadge status={row.original.priority} />}</span> },
    { id: "mechanic", header: "Mechanic", enableSorting: false, cell: ({ row }) => row.original.assigned_mechanic?.full_name ?? <span className="text-amber-700">Unassigned</span> },
    { id: "visit_at", accessorFn: (r) => r.visit_at, header: "Received", cell: ({ row }) => fmtDateTime(row.original.visit_at) },
  ], [viewStatus]);

  return (
    <>
      <PageHeader title={all ? "Job Cards" : "My Jobs"} subtitle="Search by job card, invoice, registration, customer, phone or part number." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Field label="Search" className="lg:col-span-2">{(id) => <input id={id} type="search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="SC-2026-0001, MH12AB1234, name..." />}</Field>
          <Field label="Status">
            {(id) => (
              <select id={id} className="input" value={values.status.includes(",") ? "" : values.status} onChange={(e) => set({ status: e.target.value })}>
                <option value="">All statuses</option>
                {JOB_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </select>
            )}
          </Field>
          {all && (
            <Field label="Mechanic">
              {(id) => (
                <select id={id} className="input" value={values.mechanic_id} onChange={(e) => set({ mechanic_id: e.target.value })}>
                  <option value="">All mechanics</option>
                  {mechanics.data?.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
                </select>
              )}
            </Field>
          )}
          <Field label="Vehicle model">
            {(id) => (
              <select id={id} className="input" value={values.model_id} onChange={(e) => set({ model_id: e.target.value })}>
                <option value="">All models</option>
                {models.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            )}
          </Field>
          <Field label="Received from">{(id) => <input id={id} type="date" className="input" value={values.date_from} onChange={(e) => set({ date_from: e.target.value })} />}</Field>
          <Field label="Received to">{(id) => <input id={id} type="date" className="input" value={values.date_to ? values.date_to.slice(0, 10) : ""} onChange={(e) => set({ date_to: e.target.value ? `${e.target.value}T23:59:59` : "" })} />}</Field>
          <label className="flex items-center gap-2 self-end pb-2 text-sm text-slate-700">
            <input type="checkbox" checked={values.active_only === "true"} onChange={(e) => set({ active_only: e.target.checked ? "true" : "" })} />Active jobs only
          </label>
          {Object.values(values).some(Boolean) && (
            <div className="self-end"><Button variant="ghost" onClick={() => { setSearch(""); set(Object.fromEntries(KEYS.map((k) => [k, ""])) as Record<(typeof KEYS)[number], string>); }}>Clear filters</Button></div>
          )}
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()}
          emptyTitle="No job cards match these filters" onRowClick={(job) => navigate(`/jobs/${job.id}`)}
          serverSort={{ sort, order, onChange: (s, o) => set({ sort: s, order: o }) }}
          pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
    </>
  );
}
