import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ServiceHistory } from "@/features/job/ServiceHistory";
import { useFeatures } from "@/hooks/useFeatures";
import { Alert, Button, Card, DescriptionList, ErrorState, Field, PageHeader, Spinner, StatusBadge, useToast } from "@/components/ui";
import { JOB_TYPE_LABEL, mobileDisplay, normaliseRegistration } from "@/lib/format";
import { ApiError, get, post } from "@/services/api";
import type { Customer, JobDetail, Lookup, Page, UserRef, Vehicle, VehicleModel } from "@/types";
import {
  type CustomerValues, type VehicleValues, type VisitValues, customerSchema, vehicleSchema, visitSchema,
} from "@/validation/schemas";

function RegisterVehicle({ registration, onDone }: { registration: string; onDone: () => void }) {
  const toast = useToast();
  const features = useFeatures();
  const models = useQuery({ queryKey: ["vehicle-models"], queryFn: () => get<VehicleModel[]>("/vehicle-models") });
  const [existing, setExisting] = useState<Customer | null>(null);
  const [search, setSearch] = useState("");
  const matches = useQuery({
    queryKey: ["customers", "search", search],
    queryFn: () => get<Page<Customer>>("/customers", { q: search, page_size: 5 }),
    enabled: search.trim().length >= 3,
  });
  const customerForm = useForm<CustomerValues>({
    resolver: zodResolver(customerSchema),
    defaultValues: { name: "", mobile: "", email: "", alternate_mobile: "", billing_address: "", gstin: "", email_opt_in: true, sms_opt_in: true, whatsapp_opt_in: true },
  });
  const vehicleForm = useForm<VehicleValues>({
    resolver: zodResolver(vehicleSchema),
    defaultValues: { registration_number: registration, model_id: "", vin: "", engine_number: "" },
  });
  const ce = customerForm.formState.errors;
  const ve = vehicleForm.formState.errors;

  const save = useMutation({
    mutationFn: async () => {
      const vehicleOk = await vehicleForm.trigger();
      const customerOk = existing ? true : await customerForm.trigger();
      if (!vehicleOk || !customerOk) throw new Error("Please correct the highlighted fields");
      const c = customerForm.getValues();
      const customer = existing ?? (await post<Customer>("/customers", { ...c, alternate_mobile: c.alternate_mobile || null }));
      setExisting(customer); // if the vehicle step fails, do not create the customer twice
      const v = vehicleForm.getValues();
      return post<Vehicle>("/vehicles", {
        registration_number: v.registration_number, model_id: Number(v.model_id), customer_id: customer.id,
        vin: v.vin || null, engine_number: v.engine_number || null,
      });
    },
    onSuccess: () => { toast.success("Customer and vehicle registered"); onDone(); },
    onError: (e) => toast.error(e),
  });

  return (
    <Card title="New vehicle - register customer and vehicle">
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-800">Customer</h3>
          {existing ? (
            <Alert tone="success">
              Using existing customer <strong>{existing.name}</strong> ({mobileDisplay(existing.mobile)}).{" "}
              <button type="button" className="underline" onClick={() => setExisting(null)}>Change</button>
            </Alert>
          ) : (<>
            <Field label="Find an existing customer" hint="Search by name or mobile to avoid duplicates">
              {(id) => <input id={id} className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Name or mobile number" />}
            </Field>
            {!!matches.data?.items.length && (
              <ul className="divide-y divide-slate-900/[0.05] rounded-xl border border-slate-900/[0.07] bg-white/45 text-sm">
                {matches.data.items.map((c) => (
                  <li key={c.id} className="flex items-center justify-between gap-2 px-3 py-2">
                    <span>{c.name} · {mobileDisplay(c.mobile)}</span>
                    <Button size="sm" variant="secondary" onClick={() => setExisting(c)}>Use</Button>
                  </li>
                ))}
              </ul>
            )}
            <p className="text-xs font-medium text-slate-500 uppercase">or add a new customer</p>
            <Field label="Customer name" required error={ce.name?.message}>{(id) => <input id={id} className="input" {...customerForm.register("name")} />}</Field>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Mobile number" required error={ce.mobile?.message}>{(id) => <input id={id} className="input" inputMode="tel" autoComplete="off" {...customerForm.register("mobile")} />}</Field>
              <Field label="Alternate contact" error={ce.alternate_mobile?.message}>{(id) => <input id={id} className="input" inputMode="tel" {...customerForm.register("alternate_mobile")} />}</Field>
            </div>
            <Field label="Email address" required error={ce.email?.message} hint="Invoices are emailed here">{(id) => <input id={id} type="email" className="input" {...customerForm.register("email")} />}</Field>
            <Field label="Billing address" error={ce.billing_address?.message}>{(id) => <textarea id={id} rows={2} className="input" {...customerForm.register("billing_address")} />}</Field>
            <Field label="GSTIN (optional)" error={ce.gstin?.message} hint="For business customers who need GST on the invoice">{(id, d) => <input id={id} aria-describedby={d} className="input uppercase" maxLength={15} {...customerForm.register("gstin")} />}</Field>
            <fieldset className="space-y-1 text-sm text-slate-700">
              <legend className="mb-1 font-medium">Consent for service messages (invoices)</legend>
              <label className="flex items-center gap-2"><input type="checkbox" {...customerForm.register("email_opt_in")} />Send invoices by email</label>
              {features.sms && <label className="flex items-center gap-2"><input type="checkbox" {...customerForm.register("sms_opt_in")} />Send invoice link by SMS</label>}
              {features.whatsapp && <label className="flex items-center gap-2"><input type="checkbox" {...customerForm.register("whatsapp_opt_in")} />Send invoices, payment and service reminders on WhatsApp</label>}
            </fieldset>
          </>)}
        </div>
        <div className="space-y-3">
          <h3 className="text-sm font-semibold text-slate-800">Vehicle</h3>
          <Field label="Registration number" required error={ve.registration_number?.message}>
            {(id) => <input id={id} className="input uppercase" {...vehicleForm.register("registration_number")} />}
          </Field>
          <Field label="Vehicle model" required error={ve.model_id?.message}>
            {(id) => (
              <select id={id} className="input" {...vehicleForm.register("model_id")}>
                <option value="">Select model</option>
                {models.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
              </select>
            )}
          </Field>
          <Field label="Chassis / VIN number" error={ve.vin?.message}>{(id) => <input id={id} className="input uppercase" {...vehicleForm.register("vin")} />}</Field>
          <Field label="Engine number" error={ve.engine_number?.message}>{(id) => <input id={id} className="input uppercase" {...vehicleForm.register("engine_number")} />}</Field>
        </div>
      </div>
      <div className="mt-4 flex justify-end">
        <Button loading={save.isPending} onClick={() => save.mutate()}>Register and continue</Button>
      </div>
    </Card>
  );
}

function VisitForm({ lookup }: { lookup: Lookup }) {
  const vehicle = lookup.vehicle!;
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const mechanics = useQuery({ queryKey: ["mechanics"], queryFn: () => get<UserRef[]>("/mechanics") });
  const [needOverride, setNeedOverride] = useState(lookup.active_jobs.length > 0);
  const { register, handleSubmit, setError, formState: { errors } } = useForm<VisitValues>({
    resolver: zodResolver(visitSchema),
    defaultValues: {
      odometer: String(vehicle.odometer || ""), fuel_level: "HALF", complaints: "", condition_notes: "", priority: "NORMAL", job_type: "PAID",
      estimated_completion_at: "", mechanic_id: "", override_reason: "",
    },
  });
  const create = useMutation({
    mutationFn: (v: VisitValues) => post<JobDetail>("/jobs", {
      vehicle_id: vehicle.id, odometer: Number(v.odometer), fuel_level: v.fuel_level, complaints: v.complaints,
      condition_notes: v.condition_notes, priority: v.priority, job_type: v.job_type,
      estimated_completion_at: v.estimated_completion_at ? new Date(v.estimated_completion_at).toISOString() : null,
      mechanic_id: v.mechanic_id ? Number(v.mechanic_id) : null,
      override_reason: v.override_reason || null,
    }),
    onSuccess: (job) => {
      void queryClient.invalidateQueries();
      toast.success(`Job card ${job.job_number} created`);
      navigate(`/jobs/${job.id}`);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "ACTIVE_JOB_EXISTS") {
        setNeedOverride(true);
        setError("override_reason", { message: "This vehicle already has an active job. Give a reason to open another." });
      } else toast.error(e);
    },
  });

  return (
    <Card title="Service visit details">
      <form onSubmit={handleSubmit((v) => create.mutate(v))} noValidate className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Odometer (km)" required error={errors.odometer?.message} hint={`Last recorded: ${vehicle.odometer} km`}>
            {(id, d) => <input id={id} aria-describedby={d} className="input" inputMode="numeric" {...register("odometer")} />}
          </Field>
          <Field label="Fuel level" required error={errors.fuel_level?.message}>
            {(id) => (
              <select id={id} className="input" {...register("fuel_level")}>
                <option value="EMPTY">Empty</option><option value="QUARTER">1/4</option><option value="HALF">1/2</option>
                <option value="THREE_QUARTER">3/4</option><option value="FULL">Full</option>
              </select>
            )}
          </Field>
          <Field label="Job type">
            {(id) => (
              <select id={id} className="input" {...register("job_type")}>
                {Object.entries(JOB_TYPE_LABEL).map(([k, text]) => <option key={k} value={k}>{text}</option>)}
              </select>
            )}
          </Field>
          <Field label="Priority">
            {(id) => (
              <select id={id} className="input" {...register("priority")}>
                <option value="LOW">Low</option><option value="NORMAL">Normal</option><option value="HIGH">High</option><option value="URGENT">Urgent</option>
              </select>
            )}
          </Field>
          <Field label="Estimated completion">
            {(id) => <input id={id} type="datetime-local" className="input" {...register("estimated_completion_at")} />}
          </Field>
        </div>
        <Field label="Customer complaints" required error={errors.complaints?.message}>
          {(id, d) => <textarea id={id} aria-describedby={d} rows={3} className="input" {...register("complaints")} />}
        </Field>
        <Field label="Vehicle condition notes" hint="Existing damage, accessories, items left in the vehicle">
          {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className="input" {...register("condition_notes")} />}
        </Field>
        <Field label="Assign mechanic" hint="Optional - can be assigned later from the job card" className="max-w-sm">
          {(id, d) => (
            <select id={id} aria-describedby={d} className="input" {...register("mechanic_id")}>
              <option value="">Assign later</option>
              {mechanics.data?.map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
            </select>
          )}
        </Field>
        {needOverride && (
          <Field label="Reason for opening another job on this vehicle" required error={errors.override_reason?.message}>
            {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className="input" {...register("override_reason")} />}
          </Field>
        )}
        <div className="flex justify-end">
          <Button type="submit" loading={create.isPending}>Create job card</Button>
        </div>
      </form>
    </Card>
  );
}

export default function NewVisit() {
  const [params, setParams] = useSearchParams();
  const registration = normaliseRegistration(params.get("registration") ?? "");
  const [term, setTerm] = useState(registration);
  const lookup = useQuery({
    queryKey: ["lookup", registration],
    queryFn: () => get<Lookup>("/vehicles/lookup", { registration }),
    enabled: registration.length >= 4,
  });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setParams(term.trim() ? { registration: normaliseRegistration(term) } : {});
  };
  const data = lookup.data;

  return (
    <>
      <PageHeader title="New Service Visit" subtitle="Search the registration number to find the vehicle or register a new one." />
      <div className="space-y-4">
        <Card>
          <form onSubmit={submit} role="search" className="flex flex-wrap items-end gap-3">
            <Field label="Vehicle registration number" className="w-full sm:w-64">
              {(id) => <input id={id} className="input uppercase" autoFocus placeholder="e.g. MH12AB1234" value={term} onChange={(e) => setTerm(e.target.value)} />}
            </Field>
            <Button type="submit" loading={lookup.isFetching}><Search className="h-4 w-4" />Search</Button>
          </form>
        </Card>

        {lookup.isLoading && <Spinner label="Searching..." />}
        {lookup.error && <ErrorState error={lookup.error} onRetry={() => void lookup.refetch()} />}
        {data && !data.found && (<>
          <Alert tone="info">No vehicle is registered as <strong>{data.registration_number}</strong>. Register it below.</Alert>
          <RegisterVehicle key={data.registration_number} registration={data.registration_number} onDone={() => void lookup.refetch()} />
        </>)}
        {data?.found && data.vehicle && (<>
          <Card title={`${data.vehicle.registration_number} - ${data.vehicle.model.name}`}
            actions={<Link className="text-sm font-medium text-brand-700 hover:underline" to={`/customers?customer=${data.vehicle.customer.id}`}>Edit customer</Link>}>
            <DescriptionList items={[
              ["Customer", `${data.vehicle.customer.name} (${data.vehicle.customer.code})`],
              ["Mobile", mobileDisplay(data.vehicle.customer.mobile)],
              ["Email", data.vehicle.customer.email],
              ["Billing address", data.vehicle.customer.billing_address],
              ["Chassis / VIN", data.vehicle.vin],
              ["Engine number", data.vehicle.engine_number],
              ["Last odometer", `${data.vehicle.odometer} km`],
              ["Previous visits", String(data.history.length)],
            ]} />
          </Card>
          {data.active_jobs.length > 0 && (
            <Alert tone="warn">
              <p className="font-medium">This vehicle already has {data.active_jobs.length} active job card(s):</p>
              <ul className="mt-1 list-inside list-disc">
                {data.active_jobs.map((j) => (
                  <li key={j.id}><Link className="underline" to={`/jobs/${j.id}`}>{j.job_number}</Link> <StatusBadge status={j.status} /></li>
                ))}
              </ul>
              <p className="mt-1">Opening another job requires a recorded reason.</p>
            </Alert>
          )}
          <VisitForm key={data.vehicle.id} lookup={data} />
          <Card title="Previous service history"><ServiceHistory entries={data.history} /></Card>
        </>)}
      </div>
    </>
  );
}
