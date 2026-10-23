import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useId, useState } from "react";
import { StatusBadge, useToast } from "@/components/ui";
import { qty, rupees } from "@/lib/format";
import { get } from "@/services/api";
import type { JobDetail, Page, Part, PartsLine } from "@/types";

/** Mutation that refreshes the job (and anything derived from it) on success. */
export function useJobMutation<TVars = void>(jobId: number, fn: (vars: TVars) => Promise<unknown>, successMessage?: string) {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: fn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
      for (const key of ["dashboard", "jobs", "notifications", "parts-requests", "parts", "invoice"]) {
        void queryClient.invalidateQueries({ queryKey: [key] });
      }
      if (successMessage) toast.success(successMessage);
    },
    onError: (e) => toast.error(e),
  });
}

export interface TabProps {
  job: JobDetail;
}

export function activeLines(job: JobDetail): PartsLine[] {
  return job.parts_requests.flatMap((r) => r.lines).filter((l) => l.status !== "CANCELLED" && l.approval_status !== "REJECTED");
}

/** Search-as-you-type part selector showing live availability. */
export function PartPicker({ onPick, exclude = [], placeholder = "Search part number or name", initialTerm = "", onAddTyped }: {
  onPick: (part: Part) => void; exclude?: number[]; placeholder?: string; initialTerm?: string;
  onAddTyped?: (text: string) => void; // offers "add as written" for parts not in the catalogue
}) {
  const [term, setTerm] = useState(initialTerm);
  const inputId = useId();
  const results = useQuery({
    queryKey: ["parts", "picker", term],
    queryFn: () => get<Page<Part>>("/parts", { q: term, page_size: 8 }),
    enabled: term.trim().length >= 2,
  });
  const items = results.data?.items.filter((p) => !exclude.includes(p.id)) ?? [];
  return (
    <div>
      <label className="sr-only" htmlFor={inputId}>Search parts</label>
      <input id={inputId} className="input" placeholder={placeholder} value={term} onChange={(e) => setTerm(e.target.value)} autoComplete="off" />
      {term.trim().length >= 2 && (
        <ul className="mt-1 max-h-56 divide-y divide-slate-900/[0.05] overflow-y-auto rounded-xl border border-slate-900/[0.07] bg-white text-sm shadow-lg shadow-slate-900/10">
          {results.isLoading && <li className="px-3 py-2 text-slate-500">Searching...</li>}
          {!results.isLoading && items.length === 0 && <li className="px-3 py-2 text-slate-500">No matching parts</li>}
          {items.map((p) => {
            const available = Number(p.stock.qty_available);
            return (
              <li key={p.id}>
                <button type="button" className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left hover:bg-brand-50"
                  onClick={() => { onPick(p); setTerm(""); }}>
                  <span><span className="font-medium">{p.sku}</span> · {p.name}</span>
                  <span className="flex shrink-0 items-center gap-2 text-xs text-slate-500">
                    {rupees(p.selling_price)}
                    <span className={available > 0 ? "font-medium text-emerald-700" : "font-medium text-red-700"}>
                      {available > 0 ? `${qty(available)} available` : "Out of stock"}
                    </span>
                  </span>
                </button>
              </li>
            );
          })}
          {onAddTyped && !results.isLoading && (
            <li>
              <button type="button" className="w-full px-3 py-2 text-left text-slate-600 hover:bg-brand-50" onClick={() => { onAddTyped(term.trim()); setTerm(""); }}>
                Not in the catalogue? Add &ldquo;{term.trim()}&rdquo; as written
              </button>
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

/** One line of a spare parts list. Catalogue parts are written "SKU · Name - qty" so inventory
 *  can match them to the catalogue; anything else is kept as written. */
interface SpareLine { sku: string | null; name: string; quantity: string }

const CATALOGUE_LINE = /^(\S+) · (.+?) - (\d+(?:\.\d+)?)$/;
const WRITTEN_LINE = /^(.*?)\s*[-x×:]\s*(\d+(?:\.\d+)?)\s*[A-Za-z]*$/;

export function parseSpareLines(text: string): SpareLine[] {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((line) => {
    const c = CATALOGUE_LINE.exec(line);
    if (c) return { sku: c[1]!, name: c[2]!, quantity: c[3]! };
    const w = WRITTEN_LINE.exec(line);
    return { sku: null, name: w ? w[1]! : line, quantity: w ? w[2]! : "1" };
  });
}

const formatSpareLines = (lines: SpareLine[]) =>
  lines.map((l) => `${l.sku ? `${l.sku} · ` : ""}${l.name} - ${Number(l.quantity) > 0 ? Number(l.quantity) : 1}`).join("\n");

/** Spare parts list built by searching the parts catalogue; the value is the text sent to inventory. */
export function SparePartsInput({ value, onChange, describedBy }: { value: string; onChange: (text: string) => void; describedBy?: string }) {
  // Rows are kept here so a quantity being typed ("", "1.") survives; the text is re-read only
  // when it changes from outside (form loaded or reset).
  const [state, setState] = useState(() => ({ text: value, lines: parseSpareLines(value) }));
  const lines = state.text === value ? state.lines : parseSpareLines(value);
  if (state.text !== value) setState({ text: value, lines });
  const set = (next: SpareLine[]) => {
    const text = formatSpareLines(next);
    setState({ text, lines: next });
    onChange(text);
  };
  const add = (line: SpareLine) => {
    const same = lines.findIndex((l) => (line.sku ? l.sku === line.sku : !l.sku && l.name.toLowerCase() === line.name.toLowerCase()));
    if (same >= 0) set(lines.map((l, i) => (i === same ? { ...l, quantity: String((Number(l.quantity) || 0) + 1) } : l)));
    else set([...lines, line]);
  };
  return (
    <div className="space-y-2" aria-describedby={describedBy}>
      <PartPicker placeholder="Search the parts catalogue by part number or name"
        onPick={(p) => add({ sku: p.sku, name: p.name, quantity: "1" })}
        onAddTyped={(text) => text.length >= 2 && add({ sku: null, name: text, quantity: "1" })} />
      {lines.length > 0 && (
        <ul className="divide-y divide-slate-900/[0.05] rounded-xl border border-slate-900/[0.07] bg-white/60 text-sm">
          {lines.map((l, i) => (
            <li key={`${l.sku ?? l.name}-${i}`} className="flex items-center gap-2 px-3 py-1.5">
              <span className="min-w-0 flex-1">
                {l.sku ? <><span className="font-medium">{l.sku}</span> · {l.name}</> : <>{l.name} <span className="text-xs text-amber-700">(not in catalogue)</span></>}
              </span>
              <label className="sr-only" htmlFor={`spare-qty-${i}`}>Quantity of {l.name}</label>
              <input id={`spare-qty-${i}`} className="input h-8 w-16 text-center" inputMode="decimal" value={l.quantity}
                onChange={(e) => set(lines.map((x, n) => (n === i ? { ...x, quantity: e.target.value.replace(/[^\d.]/g, "") } : x)))} />
              <button type="button" className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Remove ${l.name}`}
                onClick={() => set(lines.filter((_, n) => n !== i))}><Trash2 className="h-4 w-4" /></button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function LineQuantities({ line }: { line: PartsLine }) {
  const cells: [string, string | null][] = [
    ["Requested", line.qty_requested], ["Reserved", line.qty_reserved], ["Issued", line.qty_issued],
    ["Outstanding", line.qty_outstanding], ["Returned", line.qty_returned], ["Used", line.qty_consumed],
  ];
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600">
      {cells.map(([name, value]) => (
        <div key={name} className="flex gap-1">
          <dt>{name}:</dt>
          <dd className={name === "Outstanding" && Number(value) > 0 ? "font-semibold text-amber-700" : "font-semibold text-slate-900"}>{qty(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

export function LineHeading({ line }: { line: PartsLine }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="text-sm font-medium text-slate-900">{line.part.sku} · {line.part.name}</span>
      <StatusBadge status={line.status} />
      {line.urgency !== "NORMAL" && <StatusBadge status={line.urgency} />}
      {line.original_part && <span className="text-xs text-slate-500">(alternative for {line.original_part.sku})</span>}
    </div>
  );
}
