import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { FileDown, Plus, Printer, Trash2 } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, useNavigate, useParams } from "react-router-dom";
import { DataTable } from "@/components/DataTable";
import { Alert, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, useConfirm, useToast } from "@/components/ui";
import { DeliveryPanel } from "@/features/invoice/DeliveryPanel";
import { InvoiceDocument } from "@/features/invoice/InvoiceDocument";
import { useAuth } from "@/hooks/useAuth";
import { useFeatures } from "@/hooks/useFeatures";
import { useListParams } from "@/hooks/useListParams";
import { channelLabel, fmtDateTime, label, mobileDisplay, qty, rupees } from "@/lib/format";
import { del, get, openFile, patch, post } from "@/services/api";
import type { Delivery, Invoice, InvoiceSummary, Page, TaxRate } from "@/types";
import { type PaymentValues, paymentSchema } from "@/validation/schemas";

const KEYS = ["q", "status", "payment_status", "outstanding_only", "date_from", "date_to"] as const;
const PAGE_SIZE = 20;

export function Invoices() {
  const navigate = useNavigate();
  const { values, page, set } = useListParams(KEYS);
  const [search, setSearch] = useState(values.q);
  useEffect(() => {
    const t = setTimeout(() => search !== values.q && set({ q: search }), 350);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery({
    queryKey: ["invoices", values, page],
    queryFn: () => get<Page<InvoiceSummary>>("/invoices", { ...values, date_to: values.date_to ? `${values.date_to}T23:59:59` : "", page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<InvoiceSummary>[]>(() => [
    { id: "number", accessorFn: (i) => i.invoice_number ?? "", header: "Invoice", cell: ({ row }) => <span className="font-medium text-brand-700">{row.original.invoice_number ?? "Draft"}</span> },
    { accessorKey: "job_number", header: "Job card" },
    { accessorKey: "customer_name", header: "Customer", cell: ({ row }) => <>{row.original.customer_name}<br /><span className="text-xs text-slate-500">{mobileDisplay(row.original.customer_mobile)}</span></> },
    { accessorKey: "vehicle_registration", header: "Vehicle" },
    { id: "status", accessorFn: (i) => i.status, header: "Status", cell: ({ row }) => <span className="flex flex-wrap gap-1"><StatusBadge status={row.original.status} />{row.original.status === "FINALISED" && <StatusBadge status={row.original.payment_status} />}</span> },
    { id: "total", accessorFn: (i) => Number(i.total), header: "Total", cell: ({ row }) => <span className="tabular-nums">{rupees(row.original.total)}</span> },
    { id: "outstanding", accessorFn: (i) => Number(i.outstanding), header: "Outstanding", cell: ({ row }) => row.original.status === "FINALISED" ? <span className={`tabular-nums ${Number(row.original.outstanding) > 0 ? "font-semibold text-red-700" : ""}`}>{rupees(row.original.outstanding)}</span> : "-" },
    { id: "date", accessorFn: (i) => i.finalised_at ?? i.created_at, header: "Date", cell: ({ row }) => fmtDateTime(row.original.finalised_at ?? row.original.created_at) },
  ], []);
  return (
    <>
      <PageHeader title="Invoices" subtitle="Search by invoice number, job card, registration, customer or phone." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-6">
          <Field label="Search" className="lg:col-span-2">{(id) => <input id={id} type="search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="INV-2026-0001, MH12AB1234..." />}</Field>
          <Field label="Status">
            {(id) => <select id={id} className="input" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option><option value="DRAFT">Draft</option><option value="FINALISED">Finalised</option><option value="CANCELLED">Cancelled</option></select>}
          </Field>
          <Field label="Payment">
            {(id) => <select id={id} className="input" value={values.payment_status} onChange={(e) => set({ payment_status: e.target.value })}><option value="">All</option><option value="UNPAID">Unpaid</option><option value="PARTIALLY_PAID">Partially paid</option><option value="PAID">Paid</option></select>}
          </Field>
          <Field label="From">{(id) => <input id={id} type="date" className="input" value={values.date_from} onChange={(e) => set({ date_from: e.target.value })} />}</Field>
          <Field label="To">{(id) => <input id={id} type="date" className="input" value={values.date_to} onChange={(e) => set({ date_to: e.target.value })} />}</Field>
          <label className="flex items-center gap-2 text-sm text-slate-700 lg:col-span-2">
            <input type="checkbox" checked={values.outstanding_only === "true"} onChange={(e) => set({ outstanding_only: e.target.checked ? "true" : "" })} />With outstanding balance only
          </label>
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No invoices match these filters"
          onRowClick={(inv) => navigate(`/invoices/${inv.id}`)} pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
    </>
  );
}

function PaymentModal({ invoice, onClose }: { invoice: Invoice; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  // One key per opened form: a double-click or retry cannot record the payment twice.
  const idempotencyKey = useRef(crypto.randomUUID().replace(/-/g, ""));
  const { register, handleSubmit, setError, formState: { errors } } = useForm<PaymentValues>({
    resolver: zodResolver(paymentSchema),
    defaultValues: { amount: invoice.outstanding, method: "UPI", external_reference: "", notes: "" },
  });
  const save = useMutation({
    mutationFn: (v: PaymentValues) => post(`/invoices/${invoice.id}/payments`, { ...v, idempotency_key: idempotencyKey.current }),
    onSuccess: () => { for (const k of ["invoice", "invoices", "dashboard", "job"]) void queryClient.invalidateQueries({ queryKey: [k] }); toast.success("Payment recorded"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const submit = (v: PaymentValues) => {
    if (Number(v.amount) > Number(invoice.outstanding)) return setError("amount", { message: `Cannot exceed the outstanding balance of ${rupees(invoice.outstanding)}` });
    save.mutate(v);
  };
  return (
    <Modal open title={`Record payment - ${invoice.invoice_number}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="payment-form" loading={save.isPending}>Record payment</Button></>}>
      <form id="payment-form" onSubmit={handleSubmit(submit)} noValidate className="space-y-3">
        <Alert tone="info">Outstanding balance: <strong>{rupees(invoice.outstanding)}</strong> of {rupees(invoice.total)}</Alert>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Amount (₹)" required error={errors.amount?.message}>{(id, d) => <input id={id} aria-describedby={d} className="input" inputMode="decimal" {...register("amount")} />}</Field>
          <Field label="Payment method" required>
            {(id) => <select id={id} className="input" {...register("method")}><option value="CASH">Cash</option><option value="CARD">Card</option><option value="UPI">UPI</option><option value="BANK_TRANSFER">Bank transfer</option></select>}
          </Field>
        </div>
        <Field label="Reference" hint="UPI transaction ID, card slip or bank reference">{(id, d) => <input id={id} aria-describedby={d} className="input" {...register("external_reference")} />}</Field>
        <Field label="Notes">{(id) => <textarea id={id} rows={2} className="input" {...register("notes")} />}</Field>
        <p className="text-xs text-slate-500">This records a payment already received; it does not charge the customer.</p>
      </form>
    </Modal>
  );
}

/** The Service Manager adds an item to the draft bill by hand. */
function AddItemCard({ invoice, onDone }: { invoice: Invoice; onDone: () => void }) {
  const toast = useToast();
  const taxes = useQuery({ queryKey: ["tax-rates"], queryFn: () => get<TaxRate[]>("/tax-rates") });
  const defaultTax = String(taxes.data?.find((t) => Number(t.rate) === 18)?.id ?? "");
  const empty = { line_type: "PART", description: "", quantity: "1", unit: "NO", unit_price: "", hsn_code: "", tax_rate_id: "" };
  const [v, setV] = useState(empty);
  const add = useMutation({
    mutationFn: () => post(`/invoices/${invoice.id}/lines`, { ...v, tax_rate_id: (v.tax_rate_id || defaultTax) ? Number(v.tax_rate_id || defaultTax) : null }),
    onSuccess: () => { setV(empty); onDone(); toast.success("Item added to the bill"); },
    onError: (e) => toast.error(e),
  });
  const remove = useMutation({
    mutationFn: (lineId: number) => del(`/invoices/${invoice.id}/lines/${lineId}`),
    onSuccess: () => { onDone(); toast.success("Item removed"); },
    onError: (e) => toast.error(e),
  });
  const added = invoice.lines.filter((l) => l.is_custom);
  const valid = v.description.trim() && Number(v.quantity) > 0 && v.unit_price.trim() !== "" && Number(v.unit_price) >= 0 && /^(\d{4,8})?$/.test(v.hsn_code.trim());
  return (
    <Card className="no-print" title="Add an item to the bill">
      <div className="grid grid-cols-6 items-end gap-2 sm:grid-cols-[7rem_minmax(8rem,1fr)_4.5rem_5rem_6.5rem_6.5rem_6rem_auto]">
        <Field label="Type" className="col-span-2 sm:col-span-1">
          {(id) => <select id={id} className="input" value={v.line_type} onChange={(e) => setV({ ...v, line_type: e.target.value })}><option value="PART">Part</option><option value="LABOUR">Labour</option></select>}
        </Field>
        <Field label="Description" className="col-span-4 sm:col-span-1">{(id) => <input id={id} className="input" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}</Field>
        <Field label="Qty" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="decimal" value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} />}</Field>
        <Field label="Unit" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" value={v.unit} onChange={(e) => setV({ ...v, unit: e.target.value })} />}</Field>
        <Field label="Rate (₹)" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="decimal" value={v.unit_price} onChange={(e) => setV({ ...v, unit_price: e.target.value })} />}</Field>
        <Field label="HSN/SAC" className="col-span-3 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="numeric" value={v.hsn_code} onChange={(e) => setV({ ...v, hsn_code: e.target.value })} />}</Field>
        <Field label="Tax" className="col-span-3 sm:col-span-1">
          {(id) => (
            <select id={id} className="input" value={v.tax_rate_id || defaultTax} onChange={(e) => setV({ ...v, tax_rate_id: e.target.value })}>
              <option value="">None</option>
              {taxes.data?.map((t) => <option key={t.id} value={t.id}>{qty(t.rate)}%</option>)}
            </select>
          )}
        </Field>
        <Button className="col-span-6 sm:col-span-1" disabled={!valid} loading={add.isPending} onClick={() => add.mutate()}><Plus className="h-4 w-4" />Add</Button>
      </div>
      {added.length > 0 && (
        <ul className="mt-4 divide-y divide-slate-900/[0.05] border-t border-slate-900/[0.07] pt-2 text-sm">
          {added.map((l) => (
            <li key={l.id} className="flex items-center justify-between gap-2 py-1.5">
              <span>{l.description} · {qty(l.quantity)} {l.unit} × {rupees(l.unit_price)}</span>
              <Button size="sm" variant="ghost" aria-label={`Remove ${l.description}`} loading={remove.isPending && remove.variables === l.id} onClick={() => remove.mutate(l.id)}><Trash2 className="h-4 w-4" /></Button>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function InvoiceDetail() {
  const invoiceId = Number(useParams().id);
  const toast = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const [discounts, setDiscounts] = useState<Record<number, string>>({});
  const [rates, setRates] = useState<Record<number, string>>({});
  const [paying, setPaying] = useState(false);
  const q = useQuery({
    queryKey: ["invoice", invoiceId],
    queryFn: () => get<Invoice>(`/invoices/${invoiceId}`),
    // Poll while deliveries are still in flight so statuses update without a manual refresh.
    refetchInterval: (query) => (query.state.data?.delivery_jobs.some((d) => ["PENDING", "QUEUED", "RETRY_SCHEDULED"].includes(d.status)) ? 4000 : false),
  });
  const refresh = () => { for (const k of ["invoice", "invoices", "dashboard", "job", "jobs"]) void queryClient.invalidateQueries({ queryKey: [k] }); };
  const mutate = <T,>(fn: (v: T) => Promise<unknown>, message: string) => ({ mutationFn: fn, onSuccess: () => { refresh(); toast.success(message); }, onError: (e: unknown) => toast.error(e) });
  const saveEdits = useMutation(mutate(async () => {
    // Rates first (a rate change can affect the discount limit), then discounts.
    for (const [id, v] of Object.entries(rates)) await patch(`/invoices/${invoiceId}/lines/${id}`, { unit_price: v || "0" });
    if (Object.keys(discounts).length) {
      await patch(`/invoices/${invoiceId}`, { discounts: Object.entries(discounts).map(([id, v]) => ({ line_id: Number(id), discount_amount: v || "0" })) });
    }
    setRates({});
    setDiscounts({});
  }, "Bill updated"));
  const rebuild = useMutation(mutate((jobId: number) => post(`/jobs/${jobId}/invoice`), "Draft rebuilt from the job's verified labour and parts"));
  const finalise = useMutation(mutate(() => post(`/invoices/${invoiceId}/finalise`), "Invoice finalised and being sent to the customer"));
  const cancel = useMutation(mutate((reason: string) => post(`/invoices/${invoiceId}/cancel`, { reason }), "Invoice cancelled"));
  const voidPayment = useMutation(mutate(({ id, reason }: { id: number; reason: string }) => post(`/payments/${id}/void`, { reason }), "Payment voided"));

  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const inv = q.data;
  const draft = inv.status === "DRAFT";
  const manage = can("invoice.manage");
  const dirty = Object.keys(discounts).length > 0 || Object.keys(rates).length > 0;
  const ratesValid = Object.values(rates).every((v) => v.trim() !== "" && Number(v) >= 0);
  const livePayments = inv.payments.filter((p) => !p.voided_at);

  const onFinalise = async () => {
    const r = await confirm({
      title: "Finalise this invoice?",
      message: (
        <div className="space-y-2">
          <p>Total payable: <strong>{rupees(inv.total)}</strong> for {inv.vehicle_registration} ({inv.customer_name}).</p>
          <p>A finalised invoice cannot be edited. It will be sent to the customer automatically:</p>
          <ul className="list-inside list-disc">
            <li>Email with the PDF and a secure link to <strong>{inv.customer_email || "no email on record"}</strong></li>
          </ul>
        </div>
      ),
      confirmLabel: "Finalise and send",
    });
    if (r.ok) finalise.mutate(undefined);
  };

  return (
    <>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2">{inv.invoice_number ?? "Draft invoice"} <StatusBadge status={inv.status} />{inv.status === "FINALISED" && <StatusBadge status={inv.payment_status} />}</span>}
        subtitle={<>Job card <Link className="text-brand-700 hover:underline" to={`/jobs/${inv.job_id}?tab=billing`}>{inv.job_number}</Link> · {inv.vehicle_registration} · {inv.customer_name}</>}
        actions={<>
          <Button variant="secondary" onClick={() => void openFile(`/invoices/${inv.id}/pdf`).catch(toast.error)}><FileDown className="h-4 w-4" />{draft ? "Preview PDF" : "PDF"}</Button>
          <Button variant="secondary" onClick={() => window.print()}><Printer className="h-4 w-4" />Print</Button>
          {manage && draft && <Button variant="secondary" loading={rebuild.isPending} onClick={() => rebuild.mutate(inv.job_id)}>Rebuild from job</Button>}
          {manage && draft && <Button disabled={dirty} loading={finalise.isPending} onClick={() => void onFinalise()}>Finalise invoice</Button>}
          {can("payment.record") && inv.status === "FINALISED" && Number(inv.outstanding) > 0 && <Button onClick={() => setPaying(true)}>Record payment</Button>}
          {manage && inv.status === "FINALISED" && (
            <Button variant="danger" onClick={async () => {
              const r = await confirm({ title: `Cancel ${inv.invoice_number}?`, message: "The invoice number is kept on record as cancelled, customer links stop working, and a corrected invoice can then be issued. Recorded payments must be voided first.", danger: true, confirmLabel: "Cancel invoice", reason: { label: "Reason for cancellation" } });
              if (r.ok) cancel.mutate(r.reason);
            }}>Cancel invoice</Button>
          )}
        </>}
      />
      <div className="space-y-4">
        {draft && <Alert tone="info">This is a draft. You can change any rate, apply a discount or add your own items below, then finalise.</Alert>}
        {inv.status === "CANCELLED" && <Alert tone="error">Cancelled on {fmtDateTime(inv.cancelled_at)}: {inv.cancel_reason}</Alert>}
        <InvoiceDocument
          watermark={draft ? "DRAFT" : inv.status === "CANCELLED" ? "CANCELLED" : undefined}
          invoice={{ ...inv, date: inv.finalised_at ?? inv.created_at, customer_mobile: mobileDisplay(inv.customer_mobile) }}
          renderDiscount={manage && draft ? (_line, index) => {
            const line = inv.lines[index];
            return <input aria-label={`Discount for ${line.description}`} className="input no-print ml-auto w-24 text-right" inputMode="decimal" value={discounts[line.id] ?? line.discount_amount} onChange={(e) => setDiscounts((d) => ({ ...d, [line.id]: e.target.value }))} />;
          } : undefined}
          renderRate={manage && draft ? (_line, index) => {
            const line = inv.lines[index];
            return <input aria-label={`Rate for ${line.description}`} className="input no-print ml-auto w-28 text-right" inputMode="decimal" value={rates[line.id] ?? line.unit_price} onChange={(e) => setRates((r) => ({ ...r, [line.id]: e.target.value }))} />;
          } : undefined}
        />
        {dirty && (
          <div className="no-print flex justify-end gap-2">
            <Button variant="secondary" onClick={() => { setDiscounts({}); setRates({}); }}>Discard changes</Button>
            <Button disabled={!ratesValid} loading={saveEdits.isPending} onClick={() => saveEdits.mutate(undefined)}>Save changes</Button>
          </div>
        )}
        {manage && draft && <AddItemCard invoice={inv} onDone={refresh} />}
        {inv.status !== "DRAFT" && (
          <div className="no-print space-y-4">
            {inv.status === "FINALISED" && can("delivery.manage") && <DeliveryPanel invoice={inv} />}
            <Card title="Payments" actions={<span className="text-sm text-slate-600">Paid {rupees(inv.amount_paid)} · Outstanding <strong className={Number(inv.outstanding) > 0 ? "text-red-700" : "text-emerald-700"}>{rupees(inv.outstanding)}</strong></span>}>
              {inv.payments.length === 0 ? <EmptyState title="No payments recorded" /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-900/[0.07]">
                    <thead><tr><th className="th">Reference</th><th className="th">Date</th><th className="th">Method</th><th className="th text-right">Amount</th><th className="th">Recorded by</th><th className="th" /></tr></thead>
                    <tbody className="divide-y divide-slate-900/[0.05]">
                      {inv.payments.map((p) => (
                        <tr key={p.id} className={p.voided_at ? "text-slate-400 line-through" : ""}>
                          <td className="td">{p.reference}{p.external_reference && <span className="block text-xs text-slate-500">{p.external_reference}</span>}</td>
                          <td className="td">{fmtDateTime(p.paid_at)}</td>
                          <td className="td">{label(p.method)}</td>
                          <td className="td text-right tabular-nums">{rupees(p.amount)}</td>
                          <td className="td">{p.recorded_by.full_name}{p.voided_at && <span className="block text-xs no-underline">Voided: {p.void_reason}</span>}</td>
                          <td className="td text-right">
                            {can("payment.record") && !p.voided_at && inv.status === "FINALISED" && (
                              <Button size="sm" variant="ghost" onClick={async () => {
                                const r = await confirm({ title: `Void payment ${p.reference}?`, message: `${rupees(p.amount)} will be added back to the outstanding balance. The entry stays in the audit trail.`, danger: true, confirmLabel: "Void payment", reason: { label: "Reason" } });
                                if (r.ok) voidPayment.mutate({ id: p.id, reason: r.reason });
                              }}>Void</Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
              {livePayments.length > 0 && Number(inv.outstanding) === 0 && <p className="mt-2 text-sm font-medium text-emerald-700">Paid in full.</p>}
            </Card>
          </div>
        )}
      </div>
      {paying && <PaymentModal invoice={inv} onClose={() => setPaying(false)} />}
    </>
  );
}

const D_KEYS = ["status", "channel", "kind"] as const;

export function Deliveries() {
  const features = useFeatures();
  const navigate = useNavigate();
  const { values, page, set } = useListParams(D_KEYS);
  const q = useQuery({ queryKey: ["deliveries", values, page], queryFn: () => get<Page<Delivery>>("/deliveries", { ...values, page, page_size: 25 }), placeholderData: keepPreviousData, refetchInterval: 15_000 });
  const columns = useMemo<ColumnDef<Delivery>[]>(() => [
    { accessorKey: "created_at", header: "Queued", cell: ({ row }) => fmtDateTime(row.original.created_at) },
    { accessorKey: "kind", header: "Message", cell: ({ row }) => label(row.original.kind) },
    { accessorKey: "channel", header: "Channel", cell: ({ row }) => channelLabel(row.original.channel) },
    { accessorKey: "destination", header: "Destination", cell: ({ row }) => row.original.destination || "-" },
    { id: "status", accessorFn: (d) => d.display_status, header: "Status", cell: ({ row }) => <StatusBadge status={row.original.display_status} /> },
    { accessorKey: "attempt_count", header: "Attempts" },
    { accessorKey: "last_error", header: "Last error", enableSorting: false, cell: ({ row }) => <span className="text-xs text-red-700">{row.original.last_error ?? ""}</span> },
    { accessorKey: "trigger", header: "Trigger", cell: ({ row }) => label(row.original.trigger) },
  ], []);
  return (
    <>
      <PageHeader title="Invoice Delivery" subtitle={`${["Email", features.sms && "SMS", features.whatsapp && "WhatsApp"].filter(Boolean).join(", ")} messages to customers: invoices${features.whatsapp ? ", payment reminders and service reminders" : ""}. Open an invoice row to retry or resend from the invoice.`} />
      <Card>
        <div className="mb-4 flex flex-wrap gap-3">
          <Field label="Status" className="w-full sm:w-56">
            {(id) => <select id={id} className="input" value={values.status} onChange={(e) => set({ status: e.target.value })}><option value="">All</option>{["FAILED", "PENDING", "QUEUED", "RETRY_SCHEDULED", "SENT", "DELIVERED", "SKIPPED", "CANCELLED"].map((s) => <option key={s} value={s}>{label(s)}</option>)}</select>}
          </Field>
          <Field label="Channel" className="w-full sm:w-40">
            {(id) => <select id={id} className="input" value={values.channel} onChange={(e) => set({ channel: e.target.value })}><option value="">All</option><option value="EMAIL">Email</option>{features.sms && <option value="SMS">SMS</option>}{features.whatsapp && <option value="WHATSAPP">WhatsApp</option>}</select>}
          </Field>
          {features.whatsapp && <Field label="Message" className="w-full sm:w-52">
            {(id) => <select id={id} className="input" value={values.kind} onChange={(e) => set({ kind: e.target.value })}><option value="">All</option>{["INVOICE", "PAYMENT_REMINDER", "SERVICE_REMINDER"].map((k) => <option key={k} value={k}>{label(k)}</option>)}</select>}
          </Field>}
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No deliveries match these filters"
          onRowClick={(d) => { if (d.invoice_id) navigate(`/invoices/${d.invoice_id}`); }} pagination={{ page, pageSize: 25, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
    </>
  );
}
