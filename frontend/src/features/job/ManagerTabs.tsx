/** Service-Manager parts of the job card: parts oversight, estimates, billing. */
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Card, EmptyState, Field, Modal, StatusBadge, useConfirm } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { fmtDate, fmtDateTime, label, qty, rupees } from "@/lib/format";
import { ApiError, patch, post } from "@/services/api";
import type { Estimate, Invoice, PartsLine } from "@/types";
import { LineHeading, LineQuantities, type TabProps, useJobMutation } from "./shared";

function LineEditModal({ jobId, line, onClose }: { jobId: number; line: PartsLine; onClose: () => void }) {
  // Quantity is fixed once stores have reserved or issued stock against the line.
  const qtyLocked = Number(line.qty_reserved) > 0 || Number(line.qty_issued) > 0;
  const [v, setV] = useState({ quantity: String(Number(line.qty_requested)), urgency: line.urgency, notes: line.notes });
  const save = useJobMutation(jobId, () => patch(`/parts-request-lines/${line.id}`, { ...(qtyLocked ? {} : { quantity: v.quantity }), urgency: v.urgency, notes: v.notes }), "Request line updated");
  return (
    <Modal open title={`Edit request - ${line.part.sku}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!(Number(v.quantity) > 0)} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save changes</Button>
      </>}>
      <div className="space-y-3">
        <p className="text-sm text-slate-700">{line.part.name}</p>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Quantity" hint={qtyLocked ? "Fixed: stock is already reserved or issued. Request more as a new line." : undefined}>
            {(id, d) => <input id={id} aria-describedby={d} className="input" inputMode="decimal" disabled={qtyLocked} value={v.quantity} onChange={(e) => setV({ ...v, quantity: e.target.value })} />}
          </Field>
          <Field label="Urgency">
            {(id) => <select id={id} className="input" value={v.urgency} onChange={(e) => setV({ ...v, urgency: e.target.value })}>{["LOW", "NORMAL", "HIGH", "URGENT"].map((u) => <option key={u} value={u}>{label(u)}</option>)}</select>}
          </Field>
        </div>
        <Field label="Notes for inventory">{(id) => <textarea id={id} rows={2} className="input" value={v.notes} onChange={(e) => setV({ ...v, notes: e.target.value })} />}</Field>
      </div>
    </Modal>
  );
}

export function PartsTab({ job }: TabProps) {
  const { can } = useAuth();
  const [editingLine, setEditingLine] = useState<PartsLine | null>(null);
  const jobOpen = !["COMPLETED", "CANCELLED"].includes(job.status);
  const confirm = useConfirm();
  const decide = useJobMutation<{ id: number; approve: boolean }>(job.id, ({ id, approve }) => post(`/parts-request-lines/${id}/alternative-decision`, { approve }), "Decision recorded");
  const cancel = useJobMutation<{ id: number; reason: string }>(job.id, ({ id, reason }) => post(`/parts-request-lines/${id}/cancel`, { reason }), "Request line cancelled");
  const isMechanic = can("job.work") && !!job.assigned_mechanic; // the manager records work for the mechanic
  return (
    <div className="space-y-4">
      {job.inspection?.spare_parts_notes?.trim() && (() => {
        const insp = job.inspection;
        const when = `${fmtDateTime(insp.spare_parts_done_at)}${insp.spare_parts_done_note ? ` - ${insp.spare_parts_done_note}` : ""}`;
        const status: Record<string, [string, string]> = {
          PENDING: ["PENDING", "Sent to inventory. The job waits for parts until inventory staff check the shelf."],
          AVAILABLE: ["AVAILABLE", `Inventory confirmed available ${when}. The parts below are billed on the invoice.`],
          UNAVAILABLE: ["UNAVAILABLE", `Inventory: not available ${when}. The job waits until they confirm, or the list is changed.`],
          DONE: ["FULFILLED", `Handled by inventory ${when}.`],
        };
        const [badge, text] = status[insp.spare_parts_status] ?? ["", "This list goes to inventory when the inspection is submitted."];
        return (
          <Card title="Spare parts noted by the mechanic" actions={badge ? <StatusBadge status={badge} /> : null}>
            <p className="text-sm whitespace-pre-wrap text-slate-800">{insp.spare_parts_notes}</p>
            <p className="mt-2 text-xs text-slate-500">{text}</p>
            {job.manual_parts.length > 0 && (
              <div className="mt-3 overflow-x-auto">
                <table className="min-w-full text-sm">
                  <thead><tr className="border-b border-slate-900/[0.07]">{["Part", "Qty", "Rate", "HSN", "Tax"].map((h) => <th key={h} scope="col" className="th">{h}</th>)}</tr></thead>
                  <tbody className="divide-y divide-slate-900/[0.05]">
                    {job.manual_parts.map((m) => (
                      <tr key={m.id}>
                        <td className="td">{m.description}</td>
                        <td className="td tabular-nums">{qty(m.quantity)} {m.unit}</td>
                        <td className="td tabular-nums">{rupees(m.unit_price)}</td>
                        <td className="td">{m.hsn_code || "-"}</td>
                        <td className="td">{m.tax_rate ? `${qty(m.tax_rate.rate)}%` : "None"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        );
      })()}
      {job.parts_requests.length === 0 && !job.inspection?.spare_parts_notes?.trim() && <Card><EmptyState title="No parts have been requested from inventory for this job" /></Card>}
      {job.parts_requests.map((req) => (
        <Card key={req.id} title={<span className="flex flex-wrap items-center gap-2">{req.request_number} <StatusBadge status={req.status} />{req.is_additional && <span className="text-xs font-normal text-amber-700">additional work</span>}</span>}
          actions={<span className="text-xs text-slate-500">{req.requested_by.full_name} · {fmtDateTime(req.created_at)}</span>}>
          {req.notes && <p className="mb-3 text-sm text-slate-600">Note: {req.notes}</p>}
          <ul className="divide-y divide-slate-900/[0.05]">
            {req.lines.map((line) => {
              const canCancel = line.status !== "CANCELLED" && Number(line.qty_issued) - Number(line.qty_returned) === 0
                && (can("job.manage") || isMechanic);
              return (
                <li key={line.id} className="space-y-1.5 py-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <LineHeading line={line} />
                    <span className="flex gap-1">
                    {isMechanic && jobOpen && line.status !== "CANCELLED" && <Button variant="ghost" size="sm" onClick={() => setEditingLine(line)}>Edit</Button>}
                    {canCancel && (
                      <Button variant="ghost" size="sm" onClick={async () => {
                        const r = await confirm({ title: `Cancel request for ${line.part.sku}?`, message: "Any reservation on this line is released back to stock.", danger: true, confirmLabel: "Cancel line", reason: { label: "Reason" } });
                        if (r.ok) cancel.mutate({ id: line.id, reason: r.reason });
                      }}>Cancel line</Button>
                    )}
                    </span>
                  </div>
                  <LineQuantities line={line} />
                  {line.notes && <p className="text-xs text-slate-500">Mechanic: {line.notes}</p>}
                  {line.is_short && (
                    <Alert tone="warn">
                      Short by {qty(Number(line.qty_outstanding) - Number(line.qty_reserved))}.
                      {line.expected_restock_date && ` Restock expected ${fmtDate(line.expected_restock_date)}.`} {line.inventory_notes}
                    </Alert>
                  )}
                  {line.alt_part && line.alt_status === "PROPOSED" && (
                    <Alert tone="info">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <span>Inventory proposes <strong>{line.alt_part.sku} · {line.alt_part.name}</strong> ({rupees(line.alt_part.selling_price)}) as an alternative. {line.alt_notes}</span>
                        {can("alternative.approve") && (
                          <span className="flex gap-2">
                            <Button size="sm" loading={decide.isPending} onClick={() => decide.mutate({ id: line.id, approve: true })}>Approve</Button>
                            <Button size="sm" variant="secondary" onClick={() => decide.mutate({ id: line.id, approve: false })}>Reject</Button>
                          </span>
                        )}
                      </div>
                    </Alert>
                  )}
                  {line.cancel_reason && <p className="text-xs text-slate-500">Cancelled: {line.cancel_reason}</p>}
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
      {editingLine && <LineEditModal jobId={job.id} line={editingLine} onClose={() => setEditingLine(null)} />}
    </div>
  );
}

function EstimateDoc({ est, jobId }: { est: Estimate; jobId: number }) {
  const editable = est.status === "DRAFT";
  const [discounts, setDiscounts] = useState<Record<number, string>>({});
  const save = useJobMutation(jobId, () => patch(`/estimates/${est.id}`, { discounts: Object.entries(discounts).map(([id, v]) => ({ line_id: Number(id), discount_amount: v || "0" })) }), "Estimate updated");
  return (
    <Card title={<span className="flex items-center gap-2">Estimate v{est.version} {est.status === "SUPERSEDED" && <StatusBadge status={est.status} />}</span>}
      actions={<>
        <span className="text-xs text-slate-500">Prepared {fmtDateTime(est.created_at)}</span>
        {est.status !== "SUPERSEDED" && <Button size="sm" variant="secondary" className="no-print" onClick={() => window.print()}>Print</Button>}
      </>}>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-900/[0.07]">
          <thead><tr><th className="th">Item</th><th className="th text-right">Qty</th><th className="th text-right">Rate</th><th className="th text-right">Discount</th><th className="th text-right">Tax</th><th className="th text-right">Amount</th></tr></thead>
          <tbody className="divide-y divide-slate-900/[0.05]">
            {est.lines.map((l) => (
              <tr key={l.id}>
                <td className="td"><span className="text-xs text-slate-500">{l.line_type === "LABOUR" ? "Labour" : "Part"} · {l.code}</span><br />{l.description}</td>
                <td className="td text-right tabular-nums">{qty(l.quantity)}</td>
                <td className="td text-right tabular-nums">{rupees(l.unit_price)}</td>
                <td className="td text-right tabular-nums">
                  {editable ? <input aria-label={`Discount for ${l.description}`} className="input ml-auto w-24 text-right" inputMode="decimal" value={discounts[l.id] ?? l.discount_amount} onChange={(e) => setDiscounts((d) => ({ ...d, [l.id]: e.target.value }))} /> : rupees(l.discount_amount)}
                </td>
                <td className="td text-right tabular-nums">{rupees(l.tax_amount)} <span className="text-xs text-slate-500">({qty(l.tax_rate)}%)</span></td>
                <td className="td text-right font-medium tabular-nums">{rupees(l.line_total)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <dl className="mt-3 ml-auto max-w-xs space-y-1 text-sm">
        {[["Labour", est.subtotal_labour], ["Parts", est.subtotal_parts], ["Discount", est.discount_total], ["Tax", est.tax_total]].map(([k, v]) => (
          <div key={k} className="flex justify-between"><dt className="text-slate-600">{k}</dt><dd className="tabular-nums">{rupees(v)}</dd></div>
        ))}
        <div className="flex justify-between border-t border-slate-900/[0.07] pt-1 text-base font-semibold"><dt>Estimated total</dt><dd className="tabular-nums">{rupees(est.total)}</dd></div>
      </dl>
      {est.terms && <p className="mt-3 text-xs text-slate-500">{est.terms}</p>}
      {editable && Object.keys(discounts).length > 0 && (
        <div className="no-print mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDiscounts({})}>Discard</Button>
          <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => setDiscounts({}) })}>Save discounts</Button>
        </div>
      )}
    </Card>
  );
}

export function EstimateTab({ job }: TabProps) {
  const create = useJobMutation(job.id, () => post(`/jobs/${job.id}/estimates`), "Estimate prepared");
  const canCreate = ["INSPECTION_IN_PROGRESS", "AWAITING_PARTS", "READY_FOR_SERVICE", "IN_SERVICE"].includes(job.status);
  return (
    <div className="space-y-4">
      {canCreate && (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-700">
              {job.estimates.length === 0
                ? "Optional: prepare a quote for the customer from the current labour and requested parts. Work does not wait for it."
                : "Prepare an updated quote from the job's current labour and parts. Earlier versions are kept."}
            </p>
            <Button loading={create.isPending} onClick={() => create.mutate()}>{job.estimates.length ? "Update estimate" : "Prepare estimate"}</Button>
          </div>
        </Card>
      )}
      {job.estimates.length === 0 && !canCreate && <Card><EmptyState title="No estimate was prepared for this job" /></Card>}
      {[...job.estimates].reverse().map((est) => <EstimateDoc key={est.id} est={est} jobId={job.id} />)}
    </div>
  );
}

export function BillingTab({ job }: TabProps) {
  const navigate = useNavigate();
  const confirm = useConfirm();
  const live = job.invoices.find((i) => i.status !== "CANCELLED");
  const [received, setReceived] = useState("");
  const [notes, setNotes] = useState("");
  const [allowOutstanding, setAllowOutstanding] = useState(false);
  const prepare = useJobMutation(job.id, async () => {
    const inv = await post<Invoice>(`/jobs/${job.id}/invoice`);
    navigate(`/invoices/${inv.id}`);
  });
  const ready = useJobMutation(job.id, () => post(`/jobs/${job.id}/ready-for-delivery`), "Vehicle marked ready for delivery");
  const handover = useJobMutation(job.id, () => post(`/jobs/${job.id}/handover`, { received_by: received, notes, allow_outstanding: allowOutstanding }), "Handover recorded; job completed");
  const outstanding = Number(live?.outstanding ?? 0);
  return (
    <div className="space-y-4">
      {job.status === "READY_FOR_BILLING" && !live && job.billing_blockers.length > 0 && (
        <Alert tone="warn">
          <p className="font-medium">This job cannot be invoiced yet:</p>
          <ul className="list-inside list-disc">{job.billing_blockers.map((b) => <li key={b}>{b}</li>)}</ul>
        </Alert>
      )}
      <Card title="Invoice">
        {job.invoices.length === 0 ? (
          <EmptyState title="No invoice yet" hint={job.status === "READY_FOR_BILLING" ? "Review labour and parts, then prepare the invoice." : "The invoice can be prepared once the mechanic completes the work."} />
        ) : (
          <ul className="divide-y divide-slate-900/[0.05]">
            {job.invoices.map((inv) => (
              <li key={inv.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                <Link className="font-medium text-brand-700 hover:underline" to={`/invoices/${inv.id}`}>{inv.invoice_number ?? "Draft invoice"}</Link>
                <span className="flex items-center gap-2">
                  <span className="tabular-nums">{rupees(inv.total)}</span>
                  <StatusBadge status={inv.status} />
                  {inv.status === "FINALISED" && <StatusBadge status={inv.payment_status} />}
                </span>
              </li>
            ))}
          </ul>
        )}
        {job.status === "READY_FOR_BILLING" && (!live || live.status === "DRAFT") && (
          <div className="mt-3 flex justify-end">
            <Button disabled={job.billing_blockers.length > 0} loading={prepare.isPending} onClick={() => prepare.mutate()}>
              {live ? "Open draft invoice" : "Prepare invoice"}
            </Button>
          </div>
        )}
      </Card>
      {job.status === "READY_FOR_BILLING" && live?.status === "FINALISED" && (
        <Card title="Delivery">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-700">Invoice {live.invoice_number} is finalised. Mark the vehicle ready when it can be collected.</p>
            <Button loading={ready.isPending} onClick={() => ready.mutate()}>Mark ready for delivery</Button>
          </div>
        </Card>
      )}
      {job.status === "READY_FOR_DELIVERY" && (
        <Card title="Vehicle handover">
          <div className="space-y-3">
            {outstanding > 0 && (
              <Alert tone="warn">
                Outstanding balance on {live?.invoice_number}: <strong>{rupees(outstanding)}</strong>.{" "}
                <Link className="underline" to={`/invoices/${live?.id}`}>Record payment</Link>
                <label className="mt-2 flex items-center gap-2"><input type="checkbox" checked={allowOutstanding} onChange={(e) => setAllowOutstanding(e.target.checked)} />Hand over with the balance outstanding (authorised credit)</label>
              </Alert>
            )}
            <div className="grid gap-3 lg:grid-cols-2">
              <Field label="Vehicle received by" required>{(id) => <input id={id} className="input" value={received} onChange={(e) => setReceived(e.target.value)} placeholder="Name of the person collecting" />}</Field>
              <Field label="Handover notes">{(id) => <input id={id} className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Keys, documents, old parts returned..." />}</Field>
            </div>
            <div className="flex justify-end">
              <Button disabled={!received.trim() || (outstanding > 0 && !allowOutstanding)} loading={handover.isPending} onClick={async () => {
                const r = await confirm({ title: "Confirm vehicle handover", message: `Record that ${job.vehicle.registration_number} was handed over to ${received}? This completes the job.`, confirmLabel: "Record handover" });
                if (r.ok) handover.mutate(undefined, { onError: (e) => { if (e instanceof ApiError && e.code === "OUTSTANDING_BALANCE") setAllowOutstanding(false); } });
              }}>Record handover</Button>
            </div>
          </div>
        </Card>
      )}
      {job.status === "COMPLETED" && (
        <Alert tone="success">Handed over to <strong>{job.handover_to}</strong> on {fmtDateTime(job.delivered_at)}.{job.handover_notes ? ` ${job.handover_notes}` : ""}</Alert>
      )}
    </div>
  );
}
