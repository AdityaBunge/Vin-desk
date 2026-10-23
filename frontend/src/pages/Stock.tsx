import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { DataTable } from "@/components/DataTable";
import { Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, useConfirm, useToast } from "@/components/ui";
import { PartPicker } from "@/features/job/shared";
import { useAuth } from "@/hooks/useAuth";
import { useListParams } from "@/hooks/useListParams";
import { fmtDateTime, label, qty, rupees } from "@/lib/format";
import { get, post, put } from "@/services/api";
import type { Movement, Page, Part, PurchaseRequest, Supplier } from "@/types";

const MOVEMENT_TYPES = ["RECEIVED", "RESERVED", "ISSUED", "RETURNED", "RESERVATION_RELEASED", "ADJUSTMENT", "WRITE_OFF"];
const M_KEYS = ["q", "movement_type", "date_from", "date_to"] as const;

export function StockMovements() {
  const { values, page, set } = useListParams(M_KEYS);
  const q = useQuery({
    queryKey: ["movements", "list", values, page],
    queryFn: () => get<Page<Movement>>("/inventory/movements", { ...values, date_to: values.date_to ? `${values.date_to}T23:59:59` : "", page, page_size: 25 }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<Movement>[]>(() => [
    { accessorKey: "created_at", header: "When", cell: ({ row }) => fmtDateTime(row.original.created_at) },
    { id: "part", accessorFn: (m) => m.part.sku, header: "Part", cell: ({ row }) => <><span className="font-medium">{row.original.part.sku}</span><br /><span className="text-xs text-slate-500">{row.original.part.name}</span></> },
    { accessorKey: "movement_type", header: "Movement", cell: ({ row }) => label(row.original.movement_type) },
    { id: "quantity", accessorFn: (m) => Number(m.quantity), header: "Qty", cell: ({ row }) => <span className="font-semibold tabular-nums">{qty(row.original.quantity)}</span> },
    { id: "after", header: "On hand / reserved after", enableSorting: false, cell: ({ row }) => <span className="tabular-nums">{qty(row.original.on_hand_after)} / {qty(row.original.reserved_after)}</span> },
    { accessorKey: "job_number", header: "Job card", cell: ({ row }) => row.original.job_number ?? "-" },
    { accessorKey: "reason", header: "Reason", enableSorting: false, cell: ({ row }) => <span className="text-xs text-slate-600">{row.original.reason || "-"}</span> },
    { id: "by", accessorFn: (m) => m.performed_by.full_name, header: "By" },
  ], []);
  return (
    <>
      <PageHeader title="Stock Movements" subtitle="Every stock change, who made it and when. This log cannot be edited." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Part">{(id) => <input id={id} type="search" className="input" defaultValue={values.q} onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value })} placeholder="Part number or name, then Enter" />}</Field>
          <Field label="Movement type">
            {(id) => <select id={id} className="input" value={values.movement_type} onChange={(e) => set({ movement_type: e.target.value })}><option value="">All types</option>{MOVEMENT_TYPES.map((t) => <option key={t} value={t}>{label(t)}</option>)}</select>}
          </Field>
          <Field label="From">{(id) => <input id={id} type="date" className="input" value={values.date_from} onChange={(e) => set({ date_from: e.target.value })} />}</Field>
          <Field label="To">{(id) => <input id={id} type="date" className="input" value={values.date_to} onChange={(e) => set({ date_to: e.target.value })} />}</Field>
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No stock movements found"
          pagination={{ page, pageSize: 25, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
    </>
  );
}

type PickedPart = Pick<Part, "id" | "sku" | "name"> & Partial<Part>;
interface DraftLine { part: PickedPart; quantity: string }

function PurchaseRequestForm({ existing, onClose }: { existing?: PurchaseRequest; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => get<Supplier[]>("/suppliers") });
  const [lines, setLines] = useState<DraftLine[]>(() => (existing?.lines ?? []).map((l) => ({ part: l.part, quantity: String(Number(l.quantity)) })));
  const [supplierId, setSupplierId] = useState(String(existing?.supplier?.id ?? ""));
  const [notes, setNotes] = useState(existing?.notes ?? "");
  const create = useMutation({
    mutationFn: () => {
      const body = { supplier_id: supplierId ? Number(supplierId) : null, notes, lines: lines.map((l) => ({ part_id: l.part.id, quantity: l.quantity })) };
      return existing ? put(`/purchase-requests/${existing.id}`, body) : post("/purchase-requests", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["purchase-requests"] }); void queryClient.invalidateQueries({ queryKey: ["dashboard"] }); toast.success(existing ? "Purchase request updated" : "Purchase request sent for approval"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const valid = lines.length > 0 && lines.every((l) => Number(l.quantity) > 0);
  return (
    <Modal open wide title={existing ? `Edit ${existing.pr_number}` : "New purchase request"} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>{existing ? "Save changes" : "Submit for approval"}</Button></>}>
      <div className="space-y-3">
        <PartPicker onPick={(part) => setLines((ls) => [...ls, { part, quantity: String(Math.max(Number(part.reorder_threshold ?? 1), 1)) }])} exclude={lines.map((l) => l.part.id)} />
        {lines.length === 0 ? <p className="text-sm text-slate-500">Search and add the parts to be purchased.</p> : (
          <ul className="divide-y divide-slate-900/[0.05] rounded-xl border border-slate-900/[0.07] bg-white/45">
            {lines.map((l, i) => (
              <li key={l.part.id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
                <span><span className="font-medium">{l.part.sku}</span> · {l.part.name} {l.part.stock && <span className="text-xs text-slate-500">({qty(l.part.stock.qty_available)} available, cost {rupees(l.part.purchase_cost)})</span>}</span>
                <span className="flex items-center gap-2">
                  <label className="sr-only" htmlFor={`pr-qty-${l.part.id}`}>Quantity for {l.part.sku}</label>
                  <input id={`pr-qty-${l.part.id}`} className="input w-24" inputMode="decimal" value={l.quantity} onChange={(e) => setLines((ls) => ls.map((x, n) => (n === i ? { ...x, quantity: e.target.value } : x)))} />
                  <Button size="sm" variant="ghost" aria-label={`Remove ${l.part.sku}`} onClick={() => setLines((ls) => ls.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></Button>
                </span>
              </li>
            ))}
          </ul>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Supplier">{(id) => <select id={id} className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}><option value="">Not specified</option>{suppliers.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}</select>}</Field>
          <Field label="Notes">{(id) => <input id={id} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. needed for SC-2026-0004" />}</Field>
        </div>
      </div>
    </Modal>
  );
}

const P_KEYS = ["status"] as const;
const PR_STATUSES = ["PENDING_APPROVAL", "APPROVED", "PARTIALLY_RECEIVED", "RECEIVED", "REJECTED"];

export function PurchaseRequests() {
  const { can, user } = useAuth();
  const toast = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const { values, page, set } = useListParams(P_KEYS);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<PurchaseRequest | null>(null);
  const q = useQuery({ queryKey: ["purchase-requests", values, page], queryFn: () => get<Page<PurchaseRequest>>("/purchase-requests", { ...values, page, page_size: 10 }), placeholderData: keepPreviousData });
  const act = useMutation({
    mutationFn: ({ id, path, body }: { id: number; path: string; body: unknown }) => post(`/purchase-requests/${id}/${path}`, body),
    onSuccess: () => { for (const k of ["purchase-requests", "dashboard", "parts", "movements"]) void queryClient.invalidateQueries({ queryKey: [k] }); toast.success("Purchase request updated"); },
    onError: (e) => toast.error(e),
  });
  const decide = async (pr: PurchaseRequest, approve: boolean) => {
    const total = pr.lines.reduce((sum, l) => sum + Number(l.quantity) * Number(l.unit_cost), 0);
    const r = await confirm({
      title: `${approve ? "Approve" : "Reject"} ${pr.pr_number}?`, message: `${pr.lines.length} line(s), estimated cost ${rupees(total)}.`,
      danger: !approve, confirmLabel: approve ? "Approve" : "Reject", reason: approve ? undefined : { label: "Reason for rejection" },
    });
    if (r.ok) act.mutate({ id: pr.id, path: "decision", body: { approve, notes: r.reason } });
  };
  const receive = async (pr: PurchaseRequest) => {
    const r = await confirm({ title: `Receive stock for ${pr.pr_number}?`, message: "All outstanding quantities on this request are added to stock.", confirmLabel: "Receive stock" });
    if (r.ok) act.mutate({ id: pr.id, path: "receive", body: {} });
  };
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 10));
  return (
    <>
      <PageHeader title="Purchase Requests" subtitle="Raised by inventory staff, approved by the Service Manager."
        actions={can("purchase.create") && <Button onClick={() => setCreating(true)}><Plus className="h-4 w-4" />New purchase request</Button>} />
      <Card className="mb-4">
        <Field label="Status" className="w-full sm:w-64">
          {(id) => <select id={id} className="input" value={values.status.includes(",") ? "" : values.status} onChange={(e) => set({ status: e.target.value })}><option value="">All statuses</option>{PR_STATUSES.map((s) => <option key={s} value={s}>{label(s)}</option>)}</select>}
        </Field>
      </Card>
      {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data?.items.length ? <Card><EmptyState title="No purchase requests" /></Card> : (
        <div className="space-y-4">
          {q.data.items.map((pr) => (
            <Card key={pr.id} title={<span className="flex items-center gap-2">{pr.pr_number}<StatusBadge status={pr.status} /></span>}
              actions={<>
                <span className="text-xs text-slate-500">{pr.created_by.full_name} · {fmtDateTime(pr.created_at)}</span>
                {can("purchase.create") && pr.status === "PENDING_APPROVAL" && <Button size="sm" variant="secondary" onClick={() => setEditing(pr)}>Edit</Button>}
                {can("purchase.approve") && pr.status === "PENDING_APPROVAL" && pr.created_by.id !== user?.id && (<>
                  <Button size="sm" variant="secondary" onClick={() => void decide(pr, false)}>Reject</Button>
                  <Button size="sm" onClick={() => void decide(pr, true)}>Approve</Button>
                </>)}
                {can("inventory.adjust") && ["APPROVED", "PARTIALLY_RECEIVED"].includes(pr.status) && <Button size="sm" onClick={() => void receive(pr)}>Receive stock</Button>}
              </>}>
              <p className="mb-2 text-sm text-slate-600">
                Supplier: {pr.supplier?.name ?? "not specified"}{pr.notes && ` · ${pr.notes}`}
                {pr.decided_by && ` · ${label(pr.status === "REJECTED" ? "REJECTED" : "APPROVED")} by ${pr.decided_by.full_name} on ${fmtDateTime(pr.decided_at)}${pr.decision_notes ? ` (${pr.decision_notes})` : ""}`}
              </p>
              <table className="min-w-full divide-y divide-slate-900/[0.07]">
                <thead><tr><th className="th">Part</th><th className="th text-right">Ordered</th><th className="th text-right">Received</th><th className="th text-right">Unit cost</th></tr></thead>
                <tbody className="divide-y divide-slate-900/[0.05]">
                  {pr.lines.map((l) => (
                    <tr key={l.id}><td className="td">{l.part.sku} · {l.part.name}</td><td className="td text-right tabular-nums">{qty(l.quantity)}</td><td className="td text-right tabular-nums">{qty(l.qty_received)}</td><td className="td text-right tabular-nums">{rupees(l.unit_cost)}</td></tr>
                  ))}
                </tbody>
              </table>
            </Card>
          ))}
          <div className="flex items-center justify-end gap-2 text-sm text-slate-600">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => set({ page: page - 1 })}>Previous</Button>
            Page {page} of {pages}
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => set({ page: page + 1 })}>Next</Button>
          </div>
        </div>
      )}
      {creating && <PurchaseRequestForm onClose={() => setCreating(false)} />}
      {editing && <PurchaseRequestForm key={editing.id} existing={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
