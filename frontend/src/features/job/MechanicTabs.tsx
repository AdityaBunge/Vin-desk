/** Workshop parts of the job card (recorded by the Service Manager for the mechanic): inspection, parts, completion. */
import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { Alert, Button, Card, DescriptionList, EmptyState, Field, Modal, useConfirm } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { fmtDateTime, qty } from "@/lib/format";
import { patch, post, put } from "@/services/api";
import type { Completion } from "@/types";
import { type InspectionValues, inspectionSchema } from "@/validation/schemas";
import { LineHeading, LineQuantities, SparePartsInput, type TabProps, activeLines, useJobMutation } from "./shared";

/** The Service Manager records the inspection and work for the assigned mechanic (mechanics do not sign in). */
function useIsAssignedMechanic(job: TabProps["job"]) {
  const { can } = useAuth();
  return can("job.work") && !!job.assigned_mechanic;
}

/** Fields of older, longer inspections; shown read-only when they contain something. */
const LEGACY_FIELDS: [keyof NonNullable<TabProps["job"]["inspection"]>, string][] = [
  ["initial_observations", "Initial observations"],
  ["diagnostic_findings", "Diagnostic findings"],
  ["safety_observations", "Safety-related observations"],
  ["additional_recommendations", "Additional work recommendations"],
  ["mechanic_notes", "Mechanic notes"],
];

/** During service the mechanic picks any extra parts needed; inventory checks the shelf. */
function AdditionalPartsCard({ job }: TabProps) {
  const [text, setText] = useState("");
  const send = useJobMutation(job.id, () => post(`/jobs/${job.id}/additional-parts`, { text }), "Sent to inventory to check");
  return (
    <Card title="Need more parts?">
      <Field label="Parts needed" hint="Search the parts catalogue and set the quantity. Inventory checks the shelf and the parts are added to the bill.">
        {(_, d) => <SparePartsInput value={text} onChange={setText} describedBy={d} />}
      </Field>
      <div className="mt-3 flex justify-end">
        <Button disabled={text.trim().length < 2} loading={send.isPending} onClick={() => send.mutate(undefined, { onSuccess: () => setText("") })}>Send to inventory</Button>
      </div>
    </Card>
  );
}

export function InspectionTab({ job }: TabProps) {
  const mine = useIsAssignedMechanic(job);
  const inspecting = mine && job.status === "INSPECTION_IN_PROGRESS";
  const open = !["COMPLETED", "CANCELLED"].includes(job.status);
  // After submission the findings stay correctable.
  const [correcting, setCorrecting] = useState(false);
  const editable = inspecting || (mine && open && correcting);
  const confirm = useConfirm();
  const insp = job.inspection;
  const { register, handleSubmit, reset, watch, setValue, formState: { isDirty, errors } } = useForm<InspectionValues>({
    resolver: zodResolver(inspectionSchema),
    defaultValues: { recommended_repairs: "", spare_parts_notes: "", priority: "NORMAL" },
  });
  useEffect(() => {
    if (insp) reset({ recommended_repairs: insp.recommended_repairs, spare_parts_notes: insp.spare_parts_notes, priority: insp.priority as InspectionValues["priority"] });
  }, [insp, reset]);
  const save = useJobMutation<InspectionValues>(job.id, (v) => put(`/jobs/${job.id}/inspection`, v), "Inspection saved");
  const submit = useJobMutation(job.id, () => post(`/jobs/${job.id}/inspection/submit`), "Inspection submitted to the Service Manager");

  const onSubmitInspection = async () => {
    const { ok } = await confirm({
      title: "Submit inspection?",
      message: "The spare parts list goes to inventory to check. You can still correct the inspection later with Edit findings.",
      confirmLabel: "Submit inspection",
    });
    if (ok) submit.mutate();
  };

  return (
    <div className="space-y-4">
      <Card title="Customer complaints"><p className="text-sm whitespace-pre-wrap text-slate-800">{job.complaints}</p></Card>
      <Card title="Inspection and diagnosis" actions={<>
        {insp?.submitted_at && <span className="text-xs text-slate-500">Submitted {fmtDateTime(insp.submitted_at)}</span>}
        {mine && open && !inspecting && insp && (
          <Button size="sm" variant="secondary" onClick={() => setCorrecting((c) => !c)}>{correcting ? "Cancel editing" : "Edit findings"}</Button>
        )}
      </>}>
        {editable ? (
          <form onSubmit={handleSubmit((v) => save.mutate(v, { onSuccess: () => setCorrecting(false) }))} className="space-y-3">
            <div className="grid gap-3 lg:grid-cols-2">
              <Field label="Recommended repairs" required error={errors.recommended_repairs?.message} hint="Required before the inspection can be submitted">
                {(id, d) => <textarea id={id} aria-describedby={d} rows={6} className="input" {...register("recommended_repairs")} />}
              </Field>
              <Field label="Spare parts required" error={errors.spare_parts_notes?.message} hint="Search the parts catalogue and set the quantity. Sent to inventory when you submit the inspection.">
                {(_, d) => <SparePartsInput value={watch("spare_parts_notes")} describedBy={d}
                  onChange={(text) => setValue("spare_parts_notes", text, { shouldDirty: true, shouldValidate: true })} />}
              </Field>
            </div>
            <div className="flex justify-end">
              <Button type="submit" variant="secondary" loading={save.isPending} disabled={!isDirty}>Save inspection</Button>
            </div>
          </form>
        ) : insp ? (
          <DescriptionList items={[
            ["Recommended repairs", insp.recommended_repairs],
            ["Spare parts required", insp.spare_parts_notes],
            ...LEGACY_FIELDS.filter(([name]) => String(insp[name] ?? "").trim()).map(([name, text]) => [text, String(insp[name])] as [string, string]),
          ]} />
        ) : (
          <EmptyState title="Inspection not started" hint={job.assigned_mechanic ? "The assigned mechanic has not recorded findings yet." : "Assign a mechanic to begin the inspection."} />
        )}
      </Card>
      {inspecting && (
        <div className="flex flex-wrap items-center justify-end gap-3">
          {isDirty && <span className="text-sm text-amber-700">Save your changes before submitting.</span>}
          <Button disabled={isDirty} loading={submit.isPending} onClick={() => void onSubmitInspection()}>Submit inspection</Button>
        </div>
      )}
    </div>
  );
}

function CompletionEditModal({ jobId, completion, onClose }: { jobId: number; completion: Completion; onClose: () => void }) {
  const [v, setV] = useState({ repairs_completed: completion.repairs_completed, outstanding_issues: completion.outstanding_issues, final_observations: completion.final_observations });
  const save = useJobMutation(jobId, () => patch(`/jobs/${jobId}/completions/${completion.id}`, v), "Completion report updated");
  return (
    <Modal open wide title="Edit completion report" onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={v.repairs_completed.trim().length < 3} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save changes</Button>
      </>}>
      <div className="space-y-3">
        <Field label="Repairs completed" required>{(id) => <textarea id={id} rows={3} className="input" value={v.repairs_completed} onChange={(e) => setV({ ...v, repairs_completed: e.target.value })} />}</Field>
        <Field label="Outstanding issues">{(id) => <textarea id={id} rows={2} className="input" value={v.outstanding_issues} onChange={(e) => setV({ ...v, outstanding_issues: e.target.value })} />}</Field>
        <Field label="Final observations">{(id) => <textarea id={id} rows={2} className="input" value={v.final_observations} onChange={(e) => setV({ ...v, final_observations: e.target.value })} />}</Field>
        <p className="text-xs text-slate-500">Hours and parts used are part of the bill; to change them the job must be returned to you by the Service Manager.</p>
      </div>
    </Modal>
  );
}

export function WorkTab({ job }: TabProps) {
  const mine = useIsAssignedMechanic(job);
  const [editingCompletion, setEditingCompletion] = useState<Completion | null>(null);
  const jobOpen = !["COMPLETED", "CANCELLED"].includes(job.status);
  const lines = activeLines(job).filter((l) => Number(l.qty_issued) > 0);
  const labour = job.labour.filter((l) => l.approval_status === "APPROVED");
  const [used, setUsed] = useState<Record<number, string>>({});
  const [text, setText] = useState({ repairs_completed: "", outstanding_issues: "", final_observations: "" });
  const start = useJobMutation(job.id, () => post(`/jobs/${job.id}/start-service`), "Service started");
  const complete = useJobMutation(job.id, () => post(`/jobs/${job.id}/complete`, {
    ...text,
    parts: lines.map((l) => ({ line_id: l.id, qty_consumed: used[l.id] ?? l.qty_consumed ?? String(Number(l.qty_issued) - Number(l.qty_returned)) })),
  }), "Work completed - ready for billing");
  const inService = mine && job.status === "IN_SERVICE";
  const partsPending = ["PENDING", "UNAVAILABLE"].includes(job.inspection?.spare_parts_status ?? "");

  return (
    <div className="space-y-4">
      {job.returned_for_rework && job.status === "IN_SERVICE" && (
        <Alert tone="error">
          <strong>Returned for further work.</strong>{" "}
          {job.events.filter((e) => e.to_status === "IN_SERVICE").at(-1)?.message}
        </Alert>
      )}
      {mine && job.status === "READY_FOR_SERVICE" && (
        <Card title="Ready for service">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-slate-700">All required parts have been issued.</p>
            <Button loading={start.isPending} onClick={() => start.mutate()}>Start service</Button>
          </div>
        </Card>
      )}
      {mine && job.status === "AWAITING_PARTS" && <Alert tone="warn">Waiting for inventory to confirm the spare parts. See the Parts tab.</Alert>}
      {inService && (<>
        {labour.length > 0 && (
          <Card title="Labour operations">
            <ul className="space-y-1 text-sm">{labour.map((l) => <li key={l.id}>{l.code} · {l.description} <span className="text-slate-500">({qty(l.estimated_hours)} h)</span></li>)}</ul>
            <p className="mt-2 text-xs text-slate-500">Labour is fixed once the service has started.</p>
          </Card>
        )}
        <AdditionalPartsCard job={job} />
        {partsPending && (
          <Alert tone={job.inspection?.spare_parts_status === "UNAVAILABLE" ? "error" : "warn"}>
            {job.inspection?.spare_parts_status === "UNAVAILABLE"
              ? <>Inventory says some parts are not available: {job.inspection?.spare_parts_done_note}</>
              : <>Waiting for inventory to confirm the parts you asked for. You can complete the work once they are confirmed.</>}
          </Alert>
        )}
        <Card title="Record work completion">
          <div className="space-y-4">
            <div>
              <h3 className="mb-2 text-sm font-semibold text-slate-800">Parts actually consumed</h3>
              {lines.length === 0 ? <p className="text-sm text-slate-500">No stock parts were issued for this job.</p> : (
                <ul className="space-y-2">
                  {lines.map((l) => {
                    const max = Number(l.qty_issued) - Number(l.qty_returned);
                    return (
                      <li key={l.id} className="flex flex-wrap items-center justify-between gap-3 text-sm">
                        <span>{l.part.sku} · {l.part.name} <span className="text-slate-500">(issued {qty(max)})</span></span>
                        <label className="flex items-center gap-2">Quantity used
                          <input className="input w-24" inputMode="decimal" value={used[l.id] ?? l.qty_consumed ?? String(max)} onChange={(e) => setUsed((u) => ({ ...u, [l.id]: e.target.value }))} />
                        </label>
                      </li>
                    );
                  })}
                </ul>
              )}
              <p className="mt-2 text-xs text-slate-500">Hand any unused parts back to inventory; they must be returned to stock before the job can be billed.</p>
            </div>
            <Field label="Repairs completed" required>{(id) => <textarea id={id} rows={3} className="input" value={text.repairs_completed} onChange={(e) => setText({ ...text, repairs_completed: e.target.value })} />}</Field>
            <div className="grid gap-3 lg:grid-cols-2">
              <Field label="Outstanding issues">{(id) => <textarea id={id} rows={2} className="input" value={text.outstanding_issues} onChange={(e) => setText({ ...text, outstanding_issues: e.target.value })} />}</Field>
              <Field label="Final observations">{(id) => <textarea id={id} rows={2} className="input" value={text.final_observations} onChange={(e) => setText({ ...text, final_observations: e.target.value })} />}</Field>
            </div>
            <div className="flex justify-end">
              <Button disabled={text.repairs_completed.trim().length < 3 || partsPending} loading={complete.isPending} onClick={() => complete.mutate()}>Mark work complete</Button>
            </div>
          </div>
        </Card>
      </>)}
      <Card title="Completion records">
        {job.completions.length === 0 ? <EmptyState title="Work has not been completed yet" /> : (
          <ol className="space-y-3">
            {[...job.completions].reverse().map((c) => (
              <li key={c.id} className="rounded-xl border border-slate-900/[0.07] bg-white/45 p-3">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <p className="text-xs text-slate-500">{c.mechanic.full_name} · {fmtDateTime(c.completed_at)}</p>
                  {mine && jobOpen && <Button size="sm" variant="ghost" onClick={() => setEditingCompletion(c)}>Edit</Button>}
                </div>
                <DescriptionList items={[["Repairs completed", c.repairs_completed], ["Outstanding issues", c.outstanding_issues], ["Final observations", c.final_observations]]} />
              </li>
            ))}
          </ol>
        )}
      </Card>
      {editingCompletion && <CompletionEditModal jobId={job.id} completion={editingCompletion} onClose={() => setEditingCompletion(null)} />}
      {!inService && lines.length > 0 && (
        <Card title="Parts issued to this job">
          <ul className="space-y-2">{lines.map((l) => <li key={l.id}><LineHeading line={l} /><LineQuantities line={l} /></li>)}</ul>
        </Card>
      )}
    </div>
  );
}
