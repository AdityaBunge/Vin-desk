import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, Pencil, Printer, Receipt } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { Alert, Button, Card, DescriptionList, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, Tabs, useConfirm, useToast } from "@/components/ui";
import { BillingTab, EstimateTab, PartsTab } from "@/features/job/ManagerTabs";
import { InspectionTab, WorkTab } from "@/features/job/MechanicTabs";
import { ServiceHistory } from "@/features/job/ServiceHistory";
import { useJobMutation } from "@/features/job/shared";
import { useAuth, useViewStatus } from "@/hooks/useAuth";
import { JOB_TYPE_LABEL, fmtDateTime, label, mobileDisplay } from "@/lib/format";
import { api, get, getBlob, patch, post } from "@/services/api";
import type { HistoryEntry, JobDetail as Job, UserRef } from "@/types";

/** Statuses from which the manager may skip the remaining workshop steps and bill straight away. */
const DIRECT_BILL_FROM = ["RECEIVED", "AWAITING_ASSIGNMENT", "INSPECTION_IN_PROGRESS", "AWAITING_PARTS", "READY_FOR_SERVICE", "IN_SERVICE"];

const FUEL: Record<string, string> = { EMPTY: "Empty", QUARTER: "1/4", HALF: "1/2", THREE_QUARTER: "3/4", FULL: "Full" };

/** What the signed-in user should do next on this job, if anything. */
function nextAction(job: Job, role: string): string | null {
  const s = job.status;
  if (role === "SERVICE_MANAGER") {
    if (s === "AWAITING_ASSIGNMENT") return "Assign this job to a mechanic.";
    if (s === "INSPECTION_IN_PROGRESS") return "Record the mechanic's inspection: recommended repairs and spare parts, then submit it (Inspection tab).";
    if (s === "AWAITING_PARTS") return "Waiting for inventory to confirm the spare parts (Parts tab).";
    if (s === "READY_FOR_SERVICE") return "Parts are ready - start the service when the mechanic begins (Work tab).";
    if (s === "IN_SERVICE") return job.returned_for_rework ? "Returned for further work - complete it again when the mechanic has finished (Work tab)." : "When the mechanic finishes, record the completion (Work tab). Add any extra parts there.";
    if (s === "READY_FOR_BILLING") return "Prepare and finalise the invoice, then mark the vehicle ready (Billing tab).";
    if (s === "READY_FOR_DELIVERY") return "Record payment and the vehicle handover (Billing tab).";
  }
  return null;
}

function Photos({ job }: { job: Job }) {
  const { can, user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [urls, setUrls] = useState<Record<number, string>>({});
  const [busy, setBusy] = useState(false);
  const canUpload = !["COMPLETED", "CANCELLED"].includes(job.status) && (can("reception.manage") || job.assigned_mechanic?.id === user?.id);
  const ids = job.photos.map((p) => p.id).join(",");
  useEffect(() => {
    let alive = true;
    const created: string[] = [];
    // Photos need the Authorization header, so they are fetched as blobs rather than <img src>.
    void Promise.all(job.photos.map(async (p) => {
      const url = URL.createObjectURL(await getBlob(`/jobs/${job.id}/photos/${p.id}`));
      created.push(url);
      return [p.id, url] as const;
    })).then((pairs) => alive && setUrls(Object.fromEntries(pairs))).catch(() => undefined);
    return () => { alive = false; created.forEach((u) => URL.revokeObjectURL(u)); };
  }, [job.id, ids]); // eslint-disable-line react-hooks/exhaustive-deps

  const upload = async (file: File) => {
    const form = new FormData();
    form.append("file", file);
    setBusy(true);
    try {
      await api(`/jobs/${job.id}/photos`, { method: "POST", formData: form });
      await queryClient.invalidateQueries({ queryKey: ["job", job.id] });
      toast.success("Photograph added");
    } catch (e) {
      toast.error(e);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  };
  return (
    <Card title="Photographs" actions={canUpload && (<>
      <input ref={input} type="file" accept="image/jpeg,image/png,image/webp" capture="environment" className="hidden" aria-label="Add photograph"
        onChange={(e) => e.target.files?.[0] && void upload(e.target.files[0])} />
      <Button variant="secondary" size="sm" loading={busy} onClick={() => input.current?.click()}><Camera className="h-4 w-4" />Add photo</Button>
    </>)}>
      {job.photos.length === 0 ? <EmptyState title="No photographs" hint="JPEG, PNG or WebP, up to 5 MB each." /> : (
        <ul className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {job.photos.map((p) => (
            <li key={p.id}>
              {urls[p.id] ? (
                <a href={urls[p.id]} target="_blank" rel="noreferrer"><img src={urls[p.id]} alt={p.original_name} className="h-28 w-full rounded-xl border border-slate-900/[0.07] bg-white/45 object-cover" /></a>
              ) : <div className="h-28 animate-pulse rounded-xl bg-slate-500/10" />}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function Overview({ job }: { job: Job }) {
  const history = useQuery({ queryKey: ["job", job.id, "history"], queryFn: () => get<HistoryEntry[]>(`/jobs/${job.id}/history`) });
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        <Card title="Job card">
          <DescriptionList items={[
            ["Customer", job.customer.name],
            ["Mobile", mobileDisplay(job.customer.mobile)],
            ["Vehicle", `${job.vehicle.registration_number} · ${job.vehicle.model.name}`],
            ["Chassis / VIN", job.vehicle.vin],
            ["Visit date", fmtDateTime(job.visit_at)],
            ["Estimated completion", fmtDateTime(job.estimated_completion_at)],
            ["Odometer", `${job.odometer} km`],
            ["Fuel level", FUEL[job.fuel_level] ?? job.fuel_level],
            ["Job type", JOB_TYPE_LABEL[job.job_type] ?? job.job_type],
            ["Priority", <StatusBadge key="p" status={job.priority} />],
            ["Assigned mechanic", job.assigned_mechanic?.full_name ?? "Not assigned"],
            ["Customer complaints", job.complaints],
            ["Vehicle condition notes", job.condition_notes],
          ]} />
          {job.active_job_override_reason && <div className="mt-3"><Alert tone="warn">Opened while another job was active: {job.active_job_override_reason}</Alert></div>}
        </Card>
        <Photos job={job} />
        <Card title="Previous service history">
          {history.isLoading ? <Spinner /> : history.error ? <ErrorState error={history.error} /> : <ServiceHistory entries={history.data} />}
        </Card>
      </div>
      <Card title="Timeline">
        <ol className="relative space-y-4 border-l border-slate-900/10 pl-5">
          {[...job.events].reverse().map((e, i) => (
            <li key={e.id} className="relative">
              <span className={`absolute top-1.5 -left-[25px] h-2.5 w-2.5 rounded-full ring-4 ring-white/70 ${i === 0 ? "bg-brand-500" : "bg-slate-300"}`} aria-hidden />
              <p className="text-sm text-slate-800">{e.message}</p>
              <p className="text-xs text-slate-500">{e.actor?.full_name ?? "System"} · {fmtDateTime(e.created_at)}</p>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

function AssignModal({ job, open, onClose }: { job: Job; open: boolean; onClose: () => void }) {
  const mechanics = useQuery({ queryKey: ["mechanics"], queryFn: () => get<UserRef[]>("/mechanics"), enabled: open });
  const [mechanicId, setMechanicId] = useState("");
  const assign = useJobMutation(job.id, () => post(`/jobs/${job.id}/assign`, { mechanic_id: Number(mechanicId) }), "Mechanic assigned");
  return (
    <Modal open={open} title={job.assigned_mechanic ? "Reassign mechanic" : "Assign mechanic"} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!mechanicId} loading={assign.isPending} onClick={() => assign.mutate(undefined, { onSuccess: onClose })}>Assign</Button>
      </>}>
      <Field label="Mechanic" required>
        {(id) => (
          <select id={id} className="input" value={mechanicId} onChange={(e) => setMechanicId(e.target.value)}>
            <option value="">Select mechanic</option>
            {mechanics.data?.filter((m) => m.id !== job.assigned_mechanic?.id).map((m) => <option key={m.id} value={m.id}>{m.full_name}</option>)}
          </select>
        )}
      </Field>
    </Modal>
  );
}

function EditJobModal({ job, onClose }: { job: Job; onClose: () => void }) {
  const toLocal = (iso: string | null) => {
    if (!iso) return "";
    const d = new Date(iso);
    return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
  };
  const [v, setV] = useState({
    odometer: String(job.odometer), fuel_level: job.fuel_level, priority: job.priority, job_type: job.job_type, complaints: job.complaints,
    condition_notes: job.condition_notes, estimated_completion_at: toLocal(job.estimated_completion_at),
  });
  const save = useJobMutation(job.id, () => patch(`/jobs/${job.id}`, {
    ...v, odometer: Number(v.odometer), estimated_completion_at: v.estimated_completion_at ? new Date(v.estimated_completion_at).toISOString() : null,
  }), "Job card updated");
  const valid = /^\d{1,7}$/.test(v.odometer) && v.complaints.trim().length >= 3;
  return (
    <Modal open wide title={`Edit job card ${job.job_number}`} onClose={onClose}
      footer={<>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: onClose })}>Save changes</Button>
      </>}>
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Odometer (km)" required>{(id) => <input id={id} className="input" inputMode="numeric" value={v.odometer} onChange={(e) => setV({ ...v, odometer: e.target.value })} />}</Field>
          <Field label="Fuel level">
            {(id) => <select id={id} className="input" value={v.fuel_level} onChange={(e) => setV({ ...v, fuel_level: e.target.value })}>{Object.entries(FUEL).map(([k, text]) => <option key={k} value={k}>{text}</option>)}</select>}
          </Field>
          <Field label="Job type">
            {(id) => <select id={id} className="input" value={v.job_type} onChange={(e) => setV({ ...v, job_type: e.target.value })}>{Object.entries(JOB_TYPE_LABEL).map(([k, text]) => <option key={k} value={k}>{text}</option>)}</select>}
          </Field>
          <Field label="Priority">
            {(id) => <select id={id} className="input" value={v.priority} onChange={(e) => setV({ ...v, priority: e.target.value })}>{["LOW", "NORMAL", "HIGH", "URGENT"].map((p) => <option key={p} value={p}>{label(p)}</option>)}</select>}
          </Field>
          <Field label="Estimated completion">{(id) => <input id={id} type="datetime-local" className="input" value={v.estimated_completion_at} onChange={(e) => setV({ ...v, estimated_completion_at: e.target.value })} />}</Field>
        </div>
        <Field label="Customer complaints" required>{(id) => <textarea id={id} rows={3} className="input" value={v.complaints} onChange={(e) => setV({ ...v, complaints: e.target.value })} />}</Field>
        <Field label="Vehicle condition notes">{(id) => <textarea id={id} rows={2} className="input" value={v.condition_notes} onChange={(e) => setV({ ...v, condition_notes: e.target.value })} />}</Field>
        <p className="text-xs text-slate-500">Changes are recorded on the job timeline and in the audit log. Customer and vehicle details are edited under Customers &amp; Vehicles.</p>
      </div>
    </Modal>
  );
}

export default function JobDetail() {
  const jobId = Number(useParams().id);
  const { user, can } = useAuth();
  const viewStatus = useViewStatus();
  const confirm = useConfirm();
  const [params, setParams] = useSearchParams();
  const [assignOpen, setAssignOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const q = useQuery({ queryKey: ["job", jobId], queryFn: () => get<Job>(`/jobs/${jobId}`), enabled: Number.isFinite(jobId) });
  const withReason = (path: string, message: string) => (reason: string) => post(`/jobs/${jobId}/${path}`, { reason }).then(() => message);
  const hold = useJobMutation<string>(jobId, withReason("hold", ""), "Job put on hold");
  const resume = useJobMutation(jobId, () => post(`/jobs/${jobId}/resume`), "Job resumed");
  const cancel = useJobMutation<string>(jobId, withReason("cancel", ""), "Job cancelled");
  const giveBack = useJobMutation<string>(jobId, withReason("return-to-mechanic", ""), "Job returned to the mechanic");
  const navigate = useNavigate();
  const directBill = useJobMutation<string>(jobId, (description) => post<{ id: number }>(`/jobs/${jobId}/direct-bill`, { description }).then((inv) => navigate(`/invoices/${inv.id}`)),
    "Draft invoice ready - add the items, then finalise");
  const onDirectBill = async () => {
    const r = await confirm({
      title: "Bill this job directly?",
      message: "The remaining inspection and workshop steps are skipped and a draft invoice opens, where you add the items and rates. Any stock issued must be recorded as used or returned first.",
      confirmLabel: "Bill directly", reason: { label: "What was done" },
    });
    if (r.ok) directBill.mutate(r.reason);
  };

  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error ?? new Error("Job not found")} onRetry={() => void q.refetch()} />;
  const job = q.data;
  const isManager = can("job.manage");
  const closed = ["COMPLETED", "CANCELLED"].includes(job.status);
  const tabs = [
    { key: "overview", label: "Overview" },
    { key: "inspection", label: "Inspection" },
    { key: "parts", label: "Parts", badge: job.parts_requests.flatMap((r) => r.lines).filter((l) => l.is_short || l.alt_status === "PROPOSED").length },
    ...(can("estimate.manage") ? [{ key: "estimate", label: "Estimate" }] : []),
    { key: "work", label: "Work" },
    ...(can("invoice.read") ? [{ key: "billing", label: "Billing" }] : []),
  ];
  const tab = tabs.some((t) => t.key === params.get("tab")) ? params.get("tab")! : "overview";
  const action = nextAction(job, user?.role_code ?? "");
  const ask = async (title: string, message: string, mutate: (reason: string) => void, danger = false) => {
    const r = await confirm({ title, message, danger, reason: { label: "Reason" } });
    if (r.ok) mutate(r.reason);
  };

  return (
    <>
      <PageHeader
        title={<span className="flex flex-wrap items-center gap-2">{job.job_number} <StatusBadge status={viewStatus(job.status)} />{job.returned_for_rework && job.status === "IN_SERVICE" && <StatusBadge status="FAIL" />}</span>}
        subtitle={`${job.vehicle.registration_number} · ${job.vehicle.model.name} · ${job.customer.name}`}
        actions={<>
          {can("reception.manage") && !closed && <Button variant="secondary" onClick={() => setEditOpen(true)}><Pencil className="h-4 w-4" />Edit job card</Button>}
          {can("job.assign") && !closed && !["READY_FOR_BILLING", "READY_FOR_DELIVERY"].includes(job.status) && (
            <Button variant="secondary" onClick={() => setAssignOpen(true)}>{job.assigned_mechanic ? "Reassign" : "Assign mechanic"}</Button>
          )}
          {isManager && job.status === "READY_FOR_BILLING" && !job.invoices.some((i) => i.status === "FINALISED") && (
            <Button variant="secondary" onClick={() => void ask("Return job to the mechanic?", "The mechanic is notified with your reason and the job goes back to In service.", giveBack.mutate)}>Return to mechanic</Button>
          )}
          {isManager && job.status === "ON_HOLD" && <Button variant="secondary" loading={resume.isPending} onClick={() => resume.mutate()}>Resume</Button>}
          {isManager && !closed && !["ON_HOLD", "READY_FOR_DELIVERY"].includes(job.status) && (
            <Button variant="secondary" onClick={() => void ask("Put this job on hold?", "Work pauses until the job is resumed.", hold.mutate)}>Hold</Button>
          )}
          {isManager && !closed && job.status !== "READY_FOR_DELIVERY" && (
            <Button variant="danger" onClick={() => void ask("Cancel this job?", "Reserved parts are released. This cannot be undone.", cancel.mutate, true)}>Cancel job</Button>
          )}
          {can("invoice.manage") && DIRECT_BILL_FROM.includes(job.status) && (
            <Button variant="secondary" loading={directBill.isPending} onClick={() => void onDirectBill()}><Receipt className="h-4 w-4" />Bill directly</Button>
          )}
          <Link to={`/jobs/${job.id}/print`} target="_blank"><Button variant="secondary"><Printer className="h-4 w-4" />Print job card</Button></Link>
        </>}
      />
      <div className="mb-4 space-y-2">
        {action && <Alert tone="info"><strong>Next:</strong> {action}</Alert>}
        {job.status === "ON_HOLD" && <Alert tone="warn">On hold: {job.hold_reason}</Alert>}
        {job.status === "CANCELLED" && <Alert tone="error">Cancelled: {job.cancel_reason}</Alert>}
      </div>
      <Tabs tabs={tabs} active={tab} onChange={(key) => setParams({ tab: key }, { replace: true })} />
      {tab === "overview" && <Overview job={job} />}
      {tab === "inspection" && <InspectionTab job={job} />}
      {tab === "parts" && <PartsTab job={job} />}
      {tab === "estimate" && <EstimateTab job={job} />}
      {tab === "work" && <WorkTab job={job} />}
      {tab === "billing" && <BillingTab job={job} />}
      <AssignModal job={job} open={assignOpen} onClose={() => setAssignOpen(false)} />
      {editOpen && <EditJobModal job={job} onClose={() => setEditOpen(false)} />}
      <p className="mt-6 text-xs text-slate-400">Status: {label(job.status)} · opened {fmtDateTime(job.created_at)}</p>
    </>
  );
}
