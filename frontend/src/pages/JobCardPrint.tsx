import { useQuery } from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { useParams } from "react-router-dom";
import { Button, ErrorState, Spinner } from "@/components/ui";
import { JOB_TYPE_LABEL, fmtDateTime, label, mobileDisplay } from "@/lib/format";
import { get } from "@/services/api";
import type { Centre, JobDetail } from "@/types";

const FUEL: Record<string, string> = { EMPTY: "Empty", QUARTER: "1/4", HALF: "1/2", THREE_QUARTER: "3/4", FULL: "Full" };

function Row({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div className="flex border-b border-slate-200 py-1.5 text-sm">
      <dt className="w-40 shrink-0 font-medium text-slate-600">{term}</dt>
      <dd className="whitespace-pre-wrap text-slate-900">{children || "-"}</dd>
    </div>
  );
}

export default function JobCardPrint() {
  const jobId = Number(useParams().id);
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => get<JobDetail>(`/jobs/${jobId}`) });
  const centre = useQuery({ queryKey: ["centre"], queryFn: () => get<Centre>("/centre") });
  if (job.isLoading || centre.isLoading) return <Spinner />;
  if (job.error || !job.data) return <ErrorState error={job.error} />;
  const j = job.data;
  const c = centre.data;
  return (
    <div className="min-h-dvh p-4 print:bg-white print:p-0">
      <div className="no-print mx-auto mb-3 flex max-w-3xl justify-end">
        <Button onClick={() => window.print()}><Printer className="h-4 w-4" />Print</Button>
      </div>
      <article className="print-area mx-auto max-w-3xl rounded-2xl bg-white p-5 shadow-xl shadow-slate-900/10 sm:p-8">
        <header className="flex items-start justify-between border-b-2 border-brand-700 pb-3">
          <div>
            <h1 className="text-lg font-bold text-brand-700">{c?.name}</h1>
            <p className="text-xs whitespace-pre-wrap text-slate-600">{c?.address}</p>
            <p className="text-xs text-slate-600">{[c?.phone, c?.email].filter(Boolean).join(" | ")}</p>
            {c?.gstin && <p className="text-xs text-slate-600">GSTIN: {c.gstin}</p>}
          </div>
          <div className="text-right">
            <p className="text-xl font-bold tracking-wide text-brand-700">JOB CARD</p>
            <p className="text-base font-semibold">{j.job_number}</p>
            <p className="text-xs text-slate-600">{fmtDateTime(j.visit_at)}</p>
          </div>
        </header>
        <div className="mt-4 grid gap-x-8 sm:grid-cols-2 print:grid-cols-2">
          <dl>
            <Row term="Customer">{j.customer.name}</Row>
            <Row term="Mobile">{mobileDisplay(j.customer.mobile)}</Row>
            <Row term="Address">{j.customer.billing_address}</Row>
          </dl>
          <dl>
            <Row term="Registration no.">{j.vehicle.registration_number}</Row>
            <Row term="Vehicle model">{j.vehicle.model.name}</Row>
            <Row term="Chassis / VIN">{j.vehicle.vin}</Row>
            <Row term="Engine no.">{j.vehicle.engine_number}</Row>
            <Row term="Odometer">{j.odometer} km</Row>
            <Row term="Fuel level">{FUEL[j.fuel_level]}</Row>
          </dl>
        </div>
        <dl className="mt-3">
          <Row term="Customer complaints">{j.complaints}</Row>
          <Row term="Vehicle condition">{j.condition_notes}</Row>
          <Row term="Assigned mechanic">{j.assigned_mechanic?.full_name}</Row>
          <Row term="Job type">{JOB_TYPE_LABEL[j.job_type] ?? j.job_type}</Row>
          <Row term="Priority">{label(j.priority)}</Row>
          <Row term="Estimated completion">{fmtDateTime(j.estimated_completion_at)}</Row>
        </dl>
        {j.labour.length > 0 && (
          <section className="mt-4">
            <h2 className="mb-1 text-sm font-semibold text-slate-800">Labour operations</h2>
            <ul className="list-inside list-disc text-sm">{j.labour.map((l) => <li key={l.id}>{l.description} ({Number(l.estimated_hours)} h)</li>)}</ul>
          </section>
        )}
        <section className="mt-4">
          <h2 className="mb-1 text-sm font-semibold text-slate-800">Workshop notes</h2>
          <div className="h-24 rounded border border-slate-300" />
        </section>
        <p className="mt-4 text-xs text-slate-600">
          I authorise the above service centre to carry out the inspection and the work I approve, and to road-test the vehicle as required.
        </p>
        <footer className="mt-12 grid grid-cols-2 gap-10 text-center text-xs text-slate-600">
          <div className="border-t border-slate-400 pt-1">Customer signature</div>
          <div className="border-t border-slate-400 pt-1">Service Manager</div>
        </footer>
      </article>
    </div>
  );
}
