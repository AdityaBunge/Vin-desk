import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";
import { DataTable } from "@/components/DataTable";
import { Button, Card, Field, Modal, PageHeader, Spinner, useToast } from "@/components/ui";
import { ServiceHistory } from "@/features/job/ServiceHistory";
import { useAuth } from "@/hooks/useAuth";
import { useFeatures } from "@/hooks/useFeatures";
import { useListParams } from "@/hooks/useListParams";
import { fmtDateTime, mobileDisplay } from "@/lib/format";
import { get, patch } from "@/services/api";
import type { Customer, HistoryEntry, Page, Vehicle, VehicleModel } from "@/types";
import { type CustomerValues, customerSchema } from "@/validation/schemas";

interface CustomerDetail extends Customer {
  vehicles: { id: number; registration_number: string; model: VehicleModel }[];
  consents: { id: number; channel: string; granted: boolean; source: string; recorded_at: string }[];
}

function CustomerModal({ customerId, onClose }: { customerId: number; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const features = useFeatures();
  const q = useQuery({ queryKey: ["customer", customerId], queryFn: () => get<CustomerDetail>(`/customers/${customerId}`) });
  const { register, handleSubmit, reset, formState: { errors, isDirty } } = useForm<CustomerValues>({ resolver: zodResolver(customerSchema) });
  useEffect(() => {
    if (q.data) reset({
      name: q.data.name, mobile: q.data.mobile.replace(/^\+91/, ""), email: q.data.email ?? "", alternate_mobile: (q.data.alternate_mobile ?? "").replace(/^\+91/, ""),
      billing_address: q.data.billing_address, gstin: q.data.gstin ?? "", email_opt_in: q.data.email_opt_in, sms_opt_in: q.data.sms_opt_in, whatsapp_opt_in: q.data.whatsapp_opt_in,
    });
  }, [q.data, reset]);
  const save = useMutation({
    mutationFn: (v: CustomerValues) => patch(`/customers/${customerId}`, { ...v, alternate_mobile: v.alternate_mobile || null }),
    onSuccess: () => { void queryClient.invalidateQueries(); toast.success("Customer updated"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const editable = can("reception.manage");
  return (
    <Modal open wide title={q.data ? `${q.data.name} (${q.data.code})` : "Customer"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Close</Button>
        {editable && <Button form="customer-form" type="submit" disabled={!isDirty} loading={save.isPending}>Save changes</Button>}
      </>}>
      {q.isLoading || !q.data ? <Spinner /> : (
        <form id="customer-form" onSubmit={handleSubmit((v) => save.mutate(v))} noValidate className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Customer name" required error={errors.name?.message}>{(id) => <input id={id} className="input" disabled={!editable} {...register("name")} />}</Field>
            <Field label="Mobile number" required error={errors.mobile?.message}>{(id, d) => <input id={id} aria-describedby={d} className="input" disabled={!editable} {...register("mobile")} />}</Field>
            <Field label="Email address" required error={errors.email?.message} hint="Invoice email is sent to this address">{(id, d) => <input id={id} aria-describedby={d} type="email" className="input" disabled={!editable} {...register("email")} />}</Field>
            <Field label="Alternate contact" error={errors.alternate_mobile?.message}>{(id) => <input id={id} className="input" disabled={!editable} {...register("alternate_mobile")} />}</Field>
          </div>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Billing address" className="sm:col-span-2">{(id) => <textarea id={id} rows={2} className="input" disabled={!editable} {...register("billing_address")} />}</Field>
            <Field label="GSTIN" error={errors.gstin?.message} hint="Business customers only; printed on the tax invoice">{(id, d) => <input id={id} aria-describedby={d} className="input uppercase" maxLength={15} disabled={!editable} {...register("gstin")} />}</Field>
          </div>
          <fieldset className="flex flex-wrap gap-4 text-sm text-slate-700">
            <legend className="mb-1 font-medium">Consent for service messages</legend>
            <label className="flex items-center gap-2"><input type="checkbox" disabled={!editable} {...register("email_opt_in")} />Email</label>
            {features.sms && <label className="flex items-center gap-2"><input type="checkbox" disabled={!editable} {...register("sms_opt_in")} />SMS</label>}
            {features.whatsapp && <label className="flex items-center gap-2"><input type="checkbox" disabled={!editable} {...register("whatsapp_opt_in")} />WhatsApp (invoices and reminders)</label>}
          </fieldset>
          <div>
            <h3 className="mb-1 text-sm font-semibold text-slate-800">Vehicles</h3>
            <ul className="text-sm text-slate-700">
              {q.data.vehicles.map((v) => (
                <li key={v.id} className="flex items-center justify-between py-1">
                  {v.registration_number} · {v.model.name}
                  {editable && <Link className="text-brand-700 hover:underline" to={`/reception/new?registration=${v.registration_number}`}>New visit</Link>}
                </li>
              ))}
            </ul>
          </div>
          <details className="text-sm">
            <summary className="cursor-pointer font-medium text-slate-700">Consent history ({q.data.consents.length})</summary>
            <ul className="mt-1 text-xs text-slate-600">
              {q.data.consents.map((c) => <li key={c.id}>{fmtDateTime(c.recorded_at)} · {c.channel} {c.granted ? "granted" : "withdrawn"} · {c.source}</li>)}
            </ul>
          </details>
        </form>
      )}
    </Modal>
  );
}

function VehicleModal({ vehicle, models, onClose }: { vehicle: Vehicle; models: VehicleModel[]; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [v, setV] = useState({ model_id: String(vehicle.model.id), vin: vehicle.vin ?? "", engine_number: vehicle.engine_number ?? "", is_active: vehicle.is_active });
  const save = useMutation({
    mutationFn: () => patch(`/vehicles/${vehicle.id}`, { model_id: Number(v.model_id), vin: v.vin.trim().toUpperCase() || null, engine_number: v.engine_number.trim().toUpperCase() || null, is_active: v.is_active }),
    onSuccess: () => { void queryClient.invalidateQueries(); toast.success("Vehicle updated"); onClose(); },
    onError: (e) => toast.error(e),
  });
  return (
    <Modal open title={`Edit vehicle ${vehicle.registration_number}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button loading={save.isPending} onClick={() => save.mutate()}>Save changes</Button></>}>
      <div className="space-y-3">
        <Field label="Vehicle model" required>
          {(id) => <select id={id} className="input" value={v.model_id} onChange={(e) => setV({ ...v, model_id: e.target.value })}>
            {!models.some((m) => m.id === vehicle.model.id) && <option value={vehicle.model.id}>{vehicle.model.name}</option>}
            {models.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
          </select>}
        </Field>
        <Field label="Chassis / VIN number">{(id) => <input id={id} className="input uppercase" value={v.vin} onChange={(e) => setV({ ...v, vin: e.target.value })} />}</Field>
        <Field label="Engine number">{(id) => <input id={id} className="input uppercase" value={v.engine_number} onChange={(e) => setV({ ...v, engine_number: e.target.value })} />}</Field>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={v.is_active} onChange={(e) => setV({ ...v, is_active: e.target.checked })} />Vehicle record active</label>
        <p className="text-xs text-slate-500">The registration number identifies the vehicle and its history, so it cannot be changed here.</p>
      </div>
    </Modal>
  );
}

function HistoryModal({ vehicle, onClose }: { vehicle: Vehicle; onClose: () => void }) {
  const q = useQuery({ queryKey: ["vehicle-history", vehicle.id], queryFn: () => get<HistoryEntry[]>(`/vehicles/${vehicle.id}/history`) });
  return (
    <Modal open wide title={`Service history - ${vehicle.registration_number}`} onClose={onClose} footer={<Button variant="secondary" onClick={onClose}>Close</Button>}>
      {q.isLoading ? <Spinner /> : <ServiceHistory entries={q.data} />}
    </Modal>
  );
}

const KEYS = ["q", "model_id", "customer"] as const;
const PAGE_SIZE = 20;

export default function Customers() {
  const { values, page, set } = useListParams(KEYS);
  const { can } = useAuth();
  const [search, setSearch] = useState(values.q);
  const [history, setHistory] = useState<Vehicle | null>(null);
  const [editingVehicle, setEditingVehicle] = useState<Vehicle | null>(null);
  useEffect(() => {
    const t = setTimeout(() => search !== values.q && set({ q: search }), 350);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery({
    queryKey: ["vehicles", values.q, values.model_id, page],
    queryFn: () => get<Page<Vehicle>>("/vehicles", { q: values.q, model_id: values.model_id, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const models = useQuery({ queryKey: ["vehicle-models"], queryFn: () => get<VehicleModel[]>("/vehicle-models") });
  const columns = useMemo<ColumnDef<Vehicle>[]>(() => [
    { accessorKey: "registration_number", header: "Registration", cell: ({ row }) => <span className="font-medium">{row.original.registration_number}</span> },
    { id: "model", accessorFn: (v) => v.model.name, header: "Model" },
    { id: "customer", accessorFn: (v) => v.customer.name, header: "Customer", cell: ({ row }) => (
      <button type="button" className="text-left text-brand-700 hover:underline" onClick={() => set({ customer: row.original.customer.id })}>{row.original.customer.name}</button>
    ) },
    { id: "mobile", header: "Mobile", enableSorting: false, cell: ({ row }) => mobileDisplay(row.original.customer.mobile) },
    { accessorKey: "odometer", header: "Odometer", cell: ({ row }) => `${row.original.odometer} km` },
    { id: "actions", header: "", enableSorting: false, cell: ({ row }) => (
      <span className="flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={() => setHistory(row.original)}>History</Button>
        {can("reception.manage") && <Button size="sm" variant="ghost" onClick={() => setEditingVehicle(row.original)}>Edit</Button>}
        {can("reception.manage") && <Link to={`/reception/new?registration=${row.original.registration_number}`}><Button size="sm" variant="secondary">New visit</Button></Link>}
      </span>
    ) },
  ], [can, set]);
  return (
    <>
      <PageHeader title="Customers & Vehicles" subtitle="Search by registration, chassis number, customer name or phone number." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-3">
          <Field label="Search" className="sm:col-span-2">{(id) => <input id={id} type="search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="MH12AB1234, customer name, 98220..." />}</Field>
          <Field label="Vehicle model">
            {(id) => (
              <select id={id} className="input" value={values.model_id} onChange={(e) => set({ model_id: e.target.value })}>
                <option value="">All models</option>
                {models.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            )}
          </Field>
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()}
          emptyTitle="No vehicles found" emptyHint="Register a new vehicle from New Service Visit."
          pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
      {values.customer && <CustomerModal customerId={Number(values.customer)} onClose={() => set({ customer: "", page })} />}
      {history && <HistoryModal vehicle={history} onClose={() => setHistory(null)} />}
      {editingVehicle && <VehicleModal vehicle={editingVehicle} models={models.data ?? []} onClose={() => setEditingVehicle(null)} />}
    </>
  );
}
