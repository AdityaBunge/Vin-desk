import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ClipboardList, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, useToast } from "@/components/ui";
import { LineHeading, LineQuantities, PartPicker } from "@/features/job/shared";
import { useAuth } from "@/hooks/useAuth";
import { useListParams } from "@/hooks/useListParams";
import { fmtDate, fmtDateTime, label, qty, rupees } from "@/lib/format";
import { get, post } from "@/services/api";
import type { Page, Part, PartsLine, PartsRequest, SparePartsList, TaxRate } from "@/types";

type Action = "reserve" | "issue" | "return" | "unavailable" | "alternative";
const TITLES: Record<Action, string> = {
  reserve: "Reserve stock", issue: "Issue to job", return: "Return unused stock", unavailable: "Record shortage", alternative: "Propose alternative part",
};

function LineActionModal({ line, action, onClose }: { line: PartsLine; action: Action; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const remaining = Number(line.qty_requested) - Number(line.qty_issued);
  const defaults: Record<Action, number> = {
    reserve: remaining - Number(line.qty_reserved), issue: remaining, return: Number(line.qty_unreconciled), unavailable: 0, alternative: 0,
  };
  const [quantity, setQuantity] = useState(String(Math.max(defaults[action], 0)));
  const [notes, setNotes] = useState("");
  const [date, setDate] = useState("");
  const [alt, setAlt] = useState<Part | null>(null);
  const stock = useQuery({
    queryKey: ["parts", "stock", line.part.sku],
    queryFn: () => get<Page<Part>>("/parts", { q: line.part.sku, page_size: 5 }),
    select: (d) => d.items.find((p) => p.id === line.part.id)?.stock,
  });
  const run = useMutation({
    mutationFn: () => {
      const base = `/parts-request-lines/${line.id}`;
      if (action === "unavailable") return post(`${base}/unavailable`, { expected_restock_date: date || null, notes });
      if (action === "alternative") return post(`${base}/alternative`, { part_id: alt?.id, notes });
      return post(`${base}/${action}`, { quantity, reason: notes });
    },
    onSuccess: () => {
      for (const key of ["parts-requests", "parts", "dashboard", "movements", "job"]) void queryClient.invalidateQueries({ queryKey: [key] });
      toast.success(`${TITLES[action]}: done`);
      onClose();
    },
    onError: (e) => toast.error(e),
  });
  const needsQty = ["reserve", "issue", "return"].includes(action);
  const valid = needsQty ? Number(quantity) > 0 : action === "alternative" ? !!alt : true;
  return (
    <Modal open title={`${TITLES[action]} - ${line.part.sku}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid} loading={run.isPending} onClick={() => run.mutate()}>{TITLES[action]}</Button>
      </>}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{line.part.name}</p>
        <LineQuantities line={line} />
        {stock.data && action !== "return" && (
          <Alert tone={Number(stock.data.qty_available) > 0 ? "info" : "warn"}>
            In stock: {qty(stock.data.qty_on_hand)} on hand, {qty(stock.data.qty_reserved)} reserved, <strong>{qty(stock.data.qty_available)} available</strong>
            {line.part.storage_location && ` · bin ${line.part.storage_location}`}
          </Alert>
        )}
        {needsQty && <Field label="Quantity" required>{(id) => <input id={id} className="input w-32" inputMode="decimal" autoFocus value={quantity} onChange={(e) => setQuantity(e.target.value)} />}</Field>}
        {action === "unavailable" && <Field label="Expected restock date">{(id) => <input id={id} type="date" className="input w-48" value={date} onChange={(e) => setDate(e.target.value)} />}</Field>}
        {action === "alternative" && (alt ? (
          <Alert tone="success">Alternative: <strong>{alt.sku}</strong> · {alt.name} ({qty(alt.stock.qty_available)} available) <button type="button" className="ml-2 underline" onClick={() => setAlt(null)}>Change</button></Alert>
        ) : <PartPicker onPick={setAlt} exclude={[line.part.id]} placeholder="Search for the alternative part" />)}
        {action !== "reserve" && action !== "issue" && <Field label={action === "return" ? "Reason" : "Notes"}>{(id) => <textarea id={id} rows={2} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} />}</Field>}
        {action === "alternative" && <p className="text-xs text-slate-500">The Service Manager must approve the alternative before it can be issued.</p>}
      </div>
    </Modal>
  );
}

function RequestCard({ req, onAction }: { req: PartsRequest; onAction: (line: PartsLine, action: Action) => void }) {
  const { can } = useAuth();
  const fulfil = can("inventory.fulfil");
  return (
    <Card title={<span className="flex flex-wrap items-center gap-2">{req.request_number}<StatusBadge status={req.status} />{req.is_additional && <span className="text-xs font-normal text-amber-700">additional work</span>}</span>}
      actions={<span className="text-xs text-slate-500">{req.requested_by.full_name} · {fmtDateTime(req.created_at)}</span>}>
      {req.job && (
        <p className="mb-2 text-sm text-slate-700">
          Job {can("job.read_all") ? <Link className="font-medium text-brand-700 hover:underline" to={`/jobs/${req.job.id}?tab=parts`}>{req.job.job_number}</Link> : <span className="font-medium">{req.job.job_number}</span>}
          {" · "}{req.job.registration_number} ({req.job.model_name}) · mechanic {req.job.mechanic_name ?? "unassigned"} · <StatusBadge status={req.job.status} />
        </p>
      )}
      {req.notes && <p className="mb-2 text-sm text-slate-600">Note: {req.notes}</p>}
      <ul className="divide-y divide-slate-900/[0.05]">
        {req.lines.map((line) => {
          const open = line.status !== "CANCELLED";
          const outstanding = Number(line.qty_outstanding);
          return (
            <li key={line.id} className="space-y-1.5 py-3">
              <LineHeading line={line} />
              <LineQuantities line={line} />
              {line.notes && <p className="text-xs text-slate-500">Mechanic: {line.notes}</p>}
              {line.is_short && <p className="text-xs text-amber-800">Shortage recorded{line.expected_restock_date ? `, restock expected ${fmtDate(line.expected_restock_date)}` : ""}. {line.inventory_notes}</p>}
              {line.alt_part && <p className="text-xs text-slate-600">Alternative {line.alt_part.sku}: <StatusBadge status={line.alt_status} /></p>}
              {fulfil && open && (
                <div className="flex flex-wrap gap-2 pt-1">
                  {outstanding - Number(line.qty_reserved) > 0 && <Button size="sm" variant="secondary" onClick={() => onAction(line, "reserve")}>Reserve</Button>}
                  {outstanding > 0 && (
                    <Button size="sm" onClick={() => onAction(line, "issue")}>Issue</Button>
                  )}
                  {outstanding > 0 && <Button size="sm" variant="secondary" onClick={() => onAction(line, "unavailable")}>Record shortage</Button>}
                  {outstanding > 0 && Number(line.qty_issued) === 0 && line.alt_status !== "PROPOSED" && <Button size="sm" variant="secondary" onClick={() => onAction(line, "alternative")}>Propose alternative</Button>}
                  {Number(line.qty_unreconciled) > 0 && <Button size="sm" variant="secondary" onClick={() => onAction(line, "return")}>Return unused</Button>}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

/** A catalogue part matched to a written line: its rate and tax are what gets billed. */
interface CatalogueMatch { id: number; sku: string; name: string; rate: string; tax_rate: string; unit: string }
interface CheckRow {
  description: string; quantity: string; unit: string; unit_price: string; hsn_code: string; tax_rate_id: string;
  part: CatalogueMatch | null; byHand?: boolean; // byHand: not in the catalogue, rate typed in
  sku?: string; // part number of a line picked from the catalogue ("SKU · Name - qty")
}

/** "Front brake pad set - 2" -> description + quantity; anything else is kept as the description.
 *  "SKU · Name - 2" (picked from the catalogue) also gives the part number. */
export function parseWrittenList(notes: string, defaultTax: string): CheckRow[] {
  return notes.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
    const m = /^(.*?)\s*[-x×:]\s*(\d+(?:\.\d+)?)\s*([A-Za-z]*)$/.exec(line);
    const written = m ? m[1] : line;
    const picked = /^(\S+) · (.+)$/.exec(written);
    return {
      description: (picked ? picked[2] : written).slice(0, 160), quantity: m ? m[2] : "1", unit: m?.[3] || "NO", unit_price: "", hsn_code: "",
      tax_rate_id: defaultTax, part: null, ...(picked ? { sku: picked[1] } : {}),
    };
  });
}

const fromCatalogue = (p: Part): CatalogueMatch => ({
  id: p.id, sku: p.sku, name: p.name, rate: p.selling_price, tax_rate: p.tax_rate?.rate ?? "0", unit: p.unit || "NO",
});

/** Inventory checks the shelf: picks each written part from the catalogue (its rate, HSN and GST
 *  are billed automatically) or, for a part not in the catalogue, types the rate. Or marks the
 *  list as not available. Stock levels are not changed. */
function CheckListModal({ list, onClose }: { list: SparePartsList; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const taxes = useQuery({ queryKey: ["tax-rates"], queryFn: () => get<TaxRate[]>("/tax-rates") });
  const defaultTax = String(taxes.data?.find((t) => Number(t.rate) === 18)?.id ?? "");
  const [rows, setRows] = useState<CheckRow[] | null>(null);
  const [note, setNote] = useState(list.done_note);
  const written = parseWrittenList(list.unconfirmed || (list.parts.length ? "" : list.notes), defaultTax);
  // Lines picked from the catalogue name their part number: look those parts up to pre-match them.
  const skus = [...new Set(written.flatMap((r) => (r.sku ? [r.sku] : [])))];
  const matches = useQuery({
    queryKey: ["parts", "match", skus],
    queryFn: async () => {
      const pages = await Promise.all(skus.map((sku) => get<Page<Part>>("/parts", { q: sku, page_size: 5 })));
      return new Map(pages.flatMap((p) => p.items).map((p) => [p.sku, p]));
    },
    enabled: skus.length > 0,
  });
  // Already confirmed parts, followed by the lines inventory has not checked yet.
  const current: CheckRow[] = rows ?? [
    ...list.parts.map((p) => ({
      description: p.description, quantity: qty(p.quantity), unit: p.unit, unit_price: p.unit_price, hsn_code: p.hsn_code, tax_rate_id: String(p.tax_rate_id ?? ""),
      part: p.part ? { id: p.part.id, sku: p.part.sku, name: p.part.name, rate: p.unit_price, tax_rate: p.tax_rate?.rate ?? "0", unit: p.unit } : null,
      byHand: !p.part,
    })),
    ...written.map((r) => {
      const found = r.sku ? matches.data?.get(r.sku) : undefined;
      return found ? { ...r, part: fromCatalogue(found) } : r;
    }),
  ];
  const taxPercent = (r: CheckRow) => Number(r.part ? r.part.tax_rate : taxes.data?.find((t) => String(t.id) === (r.tax_rate_id || defaultTax))?.rate ?? 0);
  const amount = (r: CheckRow) => {
    const rate = r.part ? r.part.rate : r.byHand ? r.unit_price : "";
    return rate.trim() === "" || !(Number(r.quantity) > 0) ? null : Number(r.quantity) * Number(rate) * (1 + taxPercent(r) / 100);
  };
  const total = current.reduce((sum, r) => sum + (amount(r) ?? 0), 0);
  const update = (i: number, patch: Partial<CheckRow>) => setRows(current.map((r, n) => (n === i ? { ...r, ...patch } : r)));
  const done = (message: string) => {
    for (const key of ["spare-parts-lists", "parts-requests", "dashboard", "job", "notifications"]) void queryClient.invalidateQueries({ queryKey: [key] });
    toast.success(message);
    onClose();
  };
  const available = useMutation({
    mutationFn: () => post(`/jobs/${list.job_id}/spare-parts-list/available`, {
      note, lines: current.map(({ part, byHand: _, ...r }) => part
        ? { part_id: part.id, description: part.name, quantity: r.quantity }
        : { ...r, tax_rate_id: (r.tax_rate_id || defaultTax) ? Number(r.tax_rate_id || defaultTax) : null }),
    }),
    onSuccess: () => done("Marked available - the parts will be billed on the invoice"),
    onError: (e) => toast.error(e),
  });
  const unavailable = useMutation({
    mutationFn: () => post(`/jobs/${list.job_id}/spare-parts-list/unavailable`, { note }),
    onSuccess: () => done("Marked not available - the mechanic and manager have been told"),
    onError: (e) => toast.error(e),
  });
  const rowsValid = current.length > 0 && current.every((r) => Number(r.quantity) > 0 && (r.part ? true :
    r.byHand && r.description.trim() && r.unit_price.trim() !== "" && Number(r.unit_price) >= 0 && /^(\d{4,8})?$/.test(r.hsn_code.trim())));
  const unmatched = current.filter((r) => !r.part && !r.byHand).length;
  return (
    <Modal open wide title={`Check spare parts - ${list.job_number}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        {list.status !== "AVAILABLE" && (
          <Button variant="danger" disabled={note.trim().length < 3} loading={unavailable.isPending} onClick={() => unavailable.mutate()}>Not available</Button>
        )}
        <Button disabled={!rowsValid} loading={available.isPending} onClick={() => available.mutate()}>
          {list.status === "AVAILABLE" ? "Save changes" : "Available"}
        </Button>
      </>}>
      <div className="space-y-4">
        <div className="rounded-xl bg-amber-400/10 p-3 ring-1 ring-amber-500/20">
          <p className="text-xs font-medium text-amber-900">Written by {list.mechanic_name ?? "the mechanic"} · {list.registration_number} ({list.model_name})</p>
          <p className="mt-1 text-sm whitespace-pre-wrap text-slate-900">{list.notes}</p>
        </div>
        <div>
          <p className="text-[13px] font-medium text-slate-700">Parts found on the shelf</p>
          <p className="mb-2 text-xs text-slate-500">Pick each part from the stock catalogue. Its rate, HSN and GST are billed automatically on the customer&apos;s invoice.</p>
          <ul className="space-y-2">
            {current.map((r, i) => r.part || !r.byHand ? (
              <li key={i} className="grid grid-cols-6 items-end gap-2 rounded-xl border border-slate-900/[0.07] bg-white/45 p-2 sm:grid-cols-[minmax(10rem,1fr)_4.5rem_7rem_7rem_2.25rem]">
                {r.part ? (
                  <div className="col-span-6 sm:col-span-1">
                    <p className="text-[13px] font-medium text-slate-700">Part</p>
                    <p className="flex flex-wrap items-center gap-x-2 py-2 text-sm">
                      <span><span className="font-medium">{r.part.sku}</span> · {r.part.name}</span>
                      <button type="button" className="text-xs text-brand-700 underline" onClick={() => update(i, { part: null })}>Change</button>
                    </p>
                  </div>
                ) : (
                  <div className="col-span-6 sm:col-span-1">
                    <p className="text-[13px] font-medium text-slate-700">Written: <span className="font-normal">{r.description || "-"}</span></p>
                    <PartPicker initialTerm={r.sku ?? r.description} placeholder="Search the catalogue for this part"
                      onPick={(p) => update(i, { part: fromCatalogue(p), byHand: false })} />
                    <button type="button" className="mt-1 text-xs text-slate-500 underline" onClick={() => update(i, { byHand: true })}>Not in the catalogue? Enter the rate by hand</button>
                  </div>
                )}
                <Field label="Qty" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="decimal" value={r.quantity} onChange={(e) => update(i, { quantity: e.target.value })} />}</Field>
                <div className="col-span-2 sm:col-span-1">
                  <p className="text-[13px] font-medium text-slate-700">Rate</p>
                  <p className="py-2 text-sm tabular-nums">{r.part ? <>{rupees(r.part.rate)} <span className="text-xs text-slate-500">+{qty(r.part.tax_rate)}%</span></> : "-"}</p>
                </div>
                <div className="col-span-1 sm:col-span-1">
                  <p className="text-[13px] font-medium text-slate-700">Amount</p>
                  <p className="py-2 text-sm font-medium tabular-nums">{amount(r) === null ? "-" : rupees(amount(r)!)}</p>
                </div>
                <div className="col-span-1 flex justify-end pb-1">
                  <Button variant="ghost" size="sm" aria-label={`Remove ${r.part?.name || r.description || "row"}`} onClick={() => setRows(current.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></Button>
                </div>
              </li>
            ) : (
              <li key={i} className="grid grid-cols-6 items-end gap-2 rounded-xl border border-slate-900/[0.07] bg-white/45 p-2 sm:grid-cols-[minmax(8rem,1fr)_4.5rem_5.5rem_6.5rem_7rem_6rem_2.25rem]">
                <Field label="Part (not in catalogue)" className="col-span-6 sm:col-span-1">{(id) => <input id={id} className="input" value={r.description} onChange={(e) => update(i, { description: e.target.value })} />}</Field>
                <Field label="Qty" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="decimal" value={r.quantity} onChange={(e) => update(i, { quantity: e.target.value })} />}</Field>
                <Field label="Unit" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" list="manual-units" value={r.unit} onChange={(e) => update(i, { unit: e.target.value })} />}</Field>
                <Field label="Rate (₹)" className="col-span-2 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="decimal" value={r.unit_price} onChange={(e) => update(i, { unit_price: e.target.value })} />}</Field>
                <Field label="HSN" className="col-span-3 sm:col-span-1">{(id) => <input id={id} className="input" inputMode="numeric" value={r.hsn_code} onChange={(e) => update(i, { hsn_code: e.target.value })} />}</Field>
                <Field label="Tax" className="col-span-2 sm:col-span-1">
                  {(id) => (
                    <select id={id} className="input" value={r.tax_rate_id || defaultTax} onChange={(e) => update(i, { tax_rate_id: e.target.value })}>
                      <option value="">None</option>
                      {taxes.data?.map((t) => <option key={t.id} value={t.id}>{qty(t.rate)}%</option>)}
                    </select>
                  )}
                </Field>
                <div className="col-span-1 flex justify-end pb-1">
                  <Button variant="ghost" size="sm" aria-label={`Remove ${r.description || "row"}`} onClick={() => setRows(current.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></Button>
                </div>
                <button type="button" className="col-span-6 justify-self-start text-xs text-brand-700 underline sm:col-span-7" onClick={() => update(i, { byHand: false })}>Pick from the catalogue instead</button>
              </li>
            ))}
          </ul>
          <datalist id="manual-units">{["NO", "Nos", "SET", "PCS", "Ltr", "Kg", "Mtr"].map((u) => <option key={u} value={u} />)}</datalist>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <Button size="sm" variant="secondary"
              onClick={() => setRows([...current, { description: "", quantity: "1", unit: "NO", unit_price: "", hsn_code: "", tax_rate_id: defaultTax, part: null }])}>
              <Plus className="h-4 w-4" />Add part
            </Button>
            <p className="text-sm text-slate-700">
              {unmatched > 0 && <span className="mr-3 text-xs text-amber-700">{unmatched} part(s) still to pick</span>}
              Parts total (incl. GST): <span className="font-semibold tabular-nums">{rupees(total)}</span>
            </p>
          </div>
        </div>
        <Field label="Note" hint="Required for Not available: say which parts are missing and when they are expected.">
          {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className="input" value={note} onChange={(e) => setNote(e.target.value)} />}
        </Field>
      </div>
    </Modal>
  );
}

function SparePartsLists() {
  const { can } = useAuth();
  const [open, setOpen] = useState<SparePartsList | null>(null);
  const q = useQuery({ queryKey: ["spare-parts-lists"], queryFn: () => get<SparePartsList[]>("/spare-parts-lists"), refetchInterval: 30_000 });
  if (!q.data?.length) return null;
  return (
    <Card className="mb-4" title={<span className="flex items-center gap-2"><ClipboardList className="h-4 w-4 text-amber-600" aria-hidden />Spare parts lists from mechanics <span className="rounded-full bg-amber-400/20 px-2 text-xs text-amber-800">{q.data.length}</span></span>}>
      <ul className="grid gap-3 md:grid-cols-2">
        {q.data.map((list) => (
          <li key={list.job_id} className="flex flex-col gap-2 rounded-xl border border-amber-500/25 bg-amber-400/[0.06] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span className="flex items-center gap-2 font-medium text-slate-900">
                {list.job_number} · {list.registration_number}
                {list.status === "UNAVAILABLE" && <StatusBadge status="UNAVAILABLE" />}
              </span>
              <span className="text-xs text-slate-500">{list.mechanic_name ?? "Unassigned"} · {fmtDateTime(list.submitted_at)}</span>
            </div>
            <p className="flex-1 text-sm whitespace-pre-wrap text-slate-800">{list.notes}</p>
            {list.status === "UNAVAILABLE" && list.done_note && <p className="text-xs text-red-700">Not available: {list.done_note}</p>}
            {can("inventory.fulfil") && <div><Button size="sm" onClick={() => setOpen(list)}>{list.status === "UNAVAILABLE" ? "Check again" : "Check availability"}</Button></div>}
          </li>
        ))}
      </ul>
      {open && <CheckListModal list={open} onClose={() => setOpen(null)} />}
    </Card>
  );
}

const KEYS = ["status", "open_only", "q"] as const;
const STATUSES = ["PENDING", "PARTIALLY_FULFILLED", "UNAVAILABLE", "FULFILLED", "CANCELLED"];

export default function PartsRequests() {
  const { values, page, set } = useListParams(KEYS);
  const [selected, setSelected] = useState<{ line: PartsLine; action: Action } | null>(null);
  const q = useQuery({
    queryKey: ["parts-requests", values, page],
    queryFn: () => get<Page<PartsRequest>>("/parts-requests", { ...values, page, page_size: 10 }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 10));
  return (
    <>
      <PageHeader title="Parts Requests" subtitle="Requests from mechanics. Requesting does not move stock; reserving and issuing do." />
      <SparePartsLists />
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Search" className="w-full sm:w-64">{(id) => <input id={id} type="search" className="input" defaultValue={values.q} onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value })} placeholder="Request or job number, then Enter" />}</Field>
          <Field label="Status" className="w-full sm:w-56">
            {(id) => (
              <select id={id} className="input" value={values.status.includes(",") ? "" : values.status} onChange={(e) => set({ status: e.target.value })}>
                <option value="">All statuses</option>
                {STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </select>
            )}
          </Field>
          <label className="flex items-center gap-2 pb-2 text-sm text-slate-700">
            <input type="checkbox" checked={values.open_only === "true"} onChange={(e) => set({ open_only: e.target.checked ? "true" : "" })} />Open requests only
          </label>
        </div>
      </Card>
      {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data?.items.length ? (
        <Card><EmptyState title="No parts requests" hint="New requests from mechanics appear here automatically." /></Card>
      ) : (
        <div className="space-y-4">
          {q.data.items.map((req) => <RequestCard key={req.id} req={req} onAction={(line, action) => setSelected({ line, action })} />)}
          <div className="flex items-center justify-between text-sm text-slate-600">
            <span>{q.data.total} request(s)</span>
            <span className="flex items-center gap-2">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => set({ page: page - 1 })}>Previous</Button>
              Page {page} of {pages}
              <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => set({ page: page + 1 })}>Next</Button>
            </span>
          </div>
        </div>
      )}
      {selected && <LineActionModal line={selected.line} action={selected.action} onClose={() => setSelected(null)} />}
    </>
  );
}
