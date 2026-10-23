/** Direct billing: the Service Manager bills a vehicle without the inspection and workshop steps. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CarFront, Receipt, Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Alert, Button, Field, Modal, StatusBadge, useToast } from "@/components/ui";
import { mobileDisplay, normaliseRegistration } from "@/lib/format";
import { get, post } from "@/services/api";
import type { Invoice, Lookup } from "@/types";

const FUEL: [string, string][] = [["EMPTY", "Empty"], ["QUARTER", "1/4"], ["HALF", "1/2"], ["THREE_QUARTER", "3/4"], ["FULL", "Full"]];

export function DirectBillModal({ onClose }: { onClose: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [registration, setRegistration] = useState("");
  const [found, setFound] = useState<Lookup | null>(null);
  const [searching, setSearching] = useState(false);
  const [v, setV] = useState({ description: "", odometer: "", fuel_level: "HALF", override_reason: "" });

  const done = (inv: Invoice) => {
    for (const k of ["dashboard", "jobs", "invoices", "job"]) void queryClient.invalidateQueries({ queryKey: [k] });
    toast.success("Draft invoice ready - add the items, then finalise");
    onClose();
    navigate(`/invoices/${inv.id}`);
  };
  const billNew = useMutation({
    mutationFn: () => post<Invoice>(`/vehicles/${found!.vehicle!.id}/direct-bill`, {
      description: v.description, odometer: Number(v.odometer), fuel_level: v.fuel_level, override_reason: v.override_reason || null,
    }),
    onSuccess: done, onError: (e) => toast.error(e),
  });
  const billJob = useMutation({
    mutationFn: (jobId: number) => post<Invoice>(`/jobs/${jobId}/direct-bill`, { description: v.description }),
    onSuccess: done, onError: (e) => toast.error(e),
  });

  const search = async (e: FormEvent) => {
    e.preventDefault();
    if (normaliseRegistration(registration).length < 4) return;
    setSearching(true);
    try {
      const r = await get<Lookup>("/vehicles/lookup", { registration });
      setFound(r);
      if (r.vehicle) setV((x) => ({ ...x, odometer: String(r.vehicle!.odometer ?? "") }));
    } catch (err) {
      toast.error(err);
    } finally {
      setSearching(false);
    }
  };

  const vehicle = found?.vehicle;
  const active = found?.active_jobs ?? [];
  const describeOk = v.description.trim().length >= 3;
  const newOk = describeOk && /^\d{1,7}$/.test(v.odometer) && (active.length === 0 || v.override_reason.trim().length >= 3);

  return (
    <Modal open wide title="Bill a vehicle directly" onClose={onClose}
      footer={vehicle ? <>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button disabled={!newOk} loading={billNew.isPending} onClick={() => billNew.mutate()}>
          <Receipt className="h-4 w-4" />{active.length ? "Open a new job and bill it" : "Create bill"}
        </Button>
      </> : undefined}>
      <div className="space-y-4">
        <p className="text-sm text-slate-600">
          For quick jobs that skip inspection and workshop work, such as a wash, a small fitment or a parts sale.
          A job card is recorded and a draft invoice opens, where you add the items and rates and then finalise.
        </p>
        <form onSubmit={search} className="flex items-end gap-2" role="search">
          <Field label="Vehicle registration number" className="flex-1">
            {(id) => <input id={id} className="input uppercase" autoFocus placeholder="MH12AB1234" value={registration} onChange={(e) => { setRegistration(e.target.value); setFound(null); }} />}
          </Field>
          <Button type="submit" variant="secondary" loading={searching}><Search className="h-4 w-4" />Find</Button>
        </form>

        {found && !vehicle && (
          <Alert tone="warn">
            No vehicle with registration <strong>{found.registration_number}</strong>.{" "}
            <Link className="font-medium underline" to={`/reception/new?registration=${encodeURIComponent(found.registration_number)}`} onClick={onClose}>Register it first</Link>, then bill it.
          </Alert>
        )}

        {vehicle && (<>
          <div className="flex items-center gap-3 rounded-xl border border-slate-900/[0.07] bg-white/60 p-3">
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-500/10 text-brand-600"><CarFront className="h-5 w-5" aria-hidden /></span>
            <div className="min-w-0 text-sm">
              <p className="font-semibold text-slate-900">{vehicle.registration_number} · {vehicle.model.name}</p>
              <p className="text-slate-500">{vehicle.customer.name} · {mobileDisplay(vehicle.customer.mobile)}{vehicle.customer.email ? ` · ${vehicle.customer.email}` : ""}</p>
            </div>
          </div>

          <Field label="What was done" required hint="Shown on the job card; add the billable items on the invoice next.">
            {(id, d) => <textarea id={id} aria-describedby={d} rows={2} className="input" placeholder="e.g. Body wash and polish; fitted wiper blades" value={v.description} onChange={(e) => setV({ ...v, description: e.target.value })} />}
          </Field>

          {active.length > 0 && (
            <div className="space-y-2 rounded-xl border border-amber-500/25 bg-amber-50/70 p-3">
              <p className="text-sm font-medium text-amber-900">This vehicle already has an open job card. Bill that job directly:</p>
              {active.map((j) => (
                <div key={j.id} className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-white/80 p-2 text-sm">
                  <span>{j.job_number} · <StatusBadge status={j.status} /></span>
                  <Button size="sm" disabled={!describeOk} loading={billJob.isPending && billJob.variables === j.id} onClick={() => billJob.mutate(j.id)}>Bill this job</Button>
                </div>
              ))}
              <p className="text-xs text-amber-900/80">Or open a separate job card below (a reason is required).</p>
            </div>
          )}

          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="Odometer (km)" required>{(id) => <input id={id} className="input" inputMode="numeric" value={v.odometer} onChange={(e) => setV({ ...v, odometer: e.target.value })} />}</Field>
            <Field label="Fuel level">
              {(id) => <select id={id} className="input" value={v.fuel_level} onChange={(e) => setV({ ...v, fuel_level: e.target.value })}>{FUEL.map(([k, t]) => <option key={k} value={k}>{t}</option>)}</select>}
            </Field>
            {active.length > 0 && (
              <Field label="Reason for a separate job" required>{(id) => <input id={id} className="input" value={v.override_reason} onChange={(e) => setV({ ...v, override_reason: e.target.value })} />}</Field>
            )}
          </div>
        </>)}
      </div>
    </Modal>
  );
}
