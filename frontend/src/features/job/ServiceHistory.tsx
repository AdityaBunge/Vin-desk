import { Link } from "react-router-dom";
import { EmptyState, StatusBadge } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { fmtDate, qty, rupees } from "@/lib/format";
import type { HistoryEntry } from "@/types";

export function ServiceHistory({ entries }: { entries: HistoryEntry[] | undefined }) {
  const { can } = useAuth();
  if (!entries?.length) return <EmptyState title="No previous visits" hint="This is the first recorded visit for this vehicle." />;
  return (
    <ol className="space-y-3">
      {entries.map((h) => (
        <li key={h.job_id} className="rounded-xl border border-slate-900/[0.07] bg-white/45 p-3 text-sm">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-medium text-slate-900">
              {can("job.read_all") ? <Link className="text-brand-700 hover:underline" to={`/jobs/${h.job_id}`}>{h.job_number}</Link> : h.job_number}
              <span className="ml-2 font-normal text-slate-500">{fmtDate(h.visit_at)} · {h.odometer} km{h.mechanic ? ` · ${h.mechanic}` : ""}</span>
            </p>
            <div className="flex items-center gap-2">
              {h.invoice_number && <span className="text-xs text-slate-500">{h.invoice_number} · {rupees(h.invoice_total)}</span>}
              <StatusBadge status={h.status} />
            </div>
          </div>
          <p className="mt-1 text-slate-700"><span className="font-medium">Complaint:</span> {h.complaints}</p>
          {h.diagnostic_findings && <p className="text-slate-700"><span className="font-medium">Diagnosis:</span> {h.diagnostic_findings}</p>}
          {h.recommended_repairs && <p className="text-slate-700"><span className="font-medium">Recommended:</span> {h.recommended_repairs}</p>}
          {h.spare_parts_notes && <p className="whitespace-pre-wrap text-slate-700"><span className="font-medium">Spare parts noted:</span> {h.spare_parts_notes}</p>}
          {h.repairs_completed && <p className="text-slate-700"><span className="font-medium">Repairs:</span> {h.repairs_completed}</p>}
          {(h.labour.length > 0 || h.parts.length > 0) && (
            <p className="mt-1 text-xs text-slate-500">
              {[...h.labour, ...h.parts.map((p) => `${p.name} x ${qty(p.quantity)}`)].join(" · ")}
            </p>
          )}
        </li>
      ))}
    </ol>
  );
}
