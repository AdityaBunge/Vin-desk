import type { ReactNode } from "react";
import { money, qty } from "@/lib/format";
import type { Centre, DocLine, HsnSummaryRow, TaxBreakdownRow } from "@/types";

export interface InvoiceView {
  centre: Partial<Centre>;
  invoice_number: string | null;
  date: string | null;
  job_number: string;
  customer_name: string;
  customer_mobile?: string | null;
  customer_email?: string | null;
  customer_gstin?: string | null;
  billing_address?: string;
  vehicle_registration: string;
  vehicle_model: string;
  lines: Omit<DocLine, "id">[];
  subtotal_labour: string;
  subtotal_parts: string;
  discount_total: string;
  taxable_total?: string;
  tax_total: string;
  tax_breakdown: TaxBreakdownRow[];
  hsn_summary?: HsnSummaryRow[];
  round_off?: string;
  total: string;
  total_in_words?: string;
  tax_in_words?: string;
  amount_paid: string;
  outstanding: string;
  payment_status: string;
  terms?: string;
  notes?: string;
}

const GST_STATES: Record<string, string> = {
  "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh", "05": "Uttarakhand", "06": "Haryana",
  "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh", "10": "Bihar", "19": "West Bengal", "20": "Jharkhand", "21": "Odisha",
  "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat", "27": "Maharashtra", "29": "Karnataka", "30": "Goa",
  "32": "Kerala", "33": "Tamil Nadu", "36": "Telangana", "37": "Andhra Pradesh",
};
const stateOf = (gstin?: string | null) => (gstin && GST_STATES[gstin.slice(0, 2)] ? [GST_STATES[gstin.slice(0, 2)], gstin.slice(0, 2)] : null);

/** dd-Mon-yy, as printed on dealer invoices. */
function shortDate(value: string | null): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "-";
  return `${String(d.getDate()).padStart(2, "0")}-${d.toLocaleString("en-GB", { month: "short" })}-${String(d.getFullYear()).slice(2)}`;
}

/** GST summary rows; older invoices without HSN data fall back to the per-rate breakdown. */
function summaryRows(invoice: InvoiceView): HsnSummaryRow[] {
  if (invoice.hsn_summary) return invoice.hsn_summary;
  return invoice.tax_breakdown.map((t) => ({
    hsn_code: "", rate: t.rate, taxable: t.taxable, tax: t.tax, cgst: t.cgst, sgst: t.sgst,
    cgst_rate: String(Number(t.rate) / 2), sgst_rate: String(Number(t.rate) / 2),
  }));
}

const B = "border-slate-800";

/** GST tax invoice in the standard Indian dealer layout, shared by the staff preview and the customer's secure page. */
export function InvoiceDocument({ invoice, watermark, renderDiscount, renderRate }: {
  invoice: InvoiceView; watermark?: string;
  renderDiscount?: (line: Omit<DocLine, "id">, index: number) => ReactNode;
  /** Draft editing: replaces the Rate cell (shown for labour too while editing). */
  renderRate?: (line: Omit<DocLine, "id">, index: number) => ReactNode;
}) {
  const c = invoice.centre;
  const split = c.gst_split_intra_state !== false;
  const centreState = stateOf(c.gstin) ?? (c.state_name ? [c.state_name, c.state_code ?? ""] : null);
  const partyState = stateOf(invoice.customer_gstin) ?? centreState;
  // Parts first, then labour, keeping the original index for discount editing.
  const lines = invoice.lines.map((l, i) => [l, i] as const).sort(([a], [b]) => Number(a.line_type === "LABOUR") - Number(b.line_type === "LABOUR"));
  const showDiscount = !!renderDiscount || invoice.lines.some((l) => Number(l.discount_amount) > 0);
  const rows = summaryRows(invoice);
  const cgst = rows.reduce((sum, r) => sum + Number(r.cgst ?? 0), 0);
  const taxable = invoice.taxable_total ?? String(Number(invoice.subtotal_labour) + Number(invoice.subtotal_parts) - Number(invoice.discount_total));
  const roundOff = Number(invoice.round_off ?? 0);
  const cols = showDiscount ? 8 : 7;

  return (
    <article className="print-area relative overflow-hidden rounded-2xl border border-white bg-white p-4 text-[13px] text-slate-900 shadow-xl shadow-slate-900/10 sm:p-8">
      {watermark && <div aria-hidden className="pointer-events-none absolute inset-0 flex items-center justify-center text-7xl font-black tracking-widest text-red-600/10 select-none">{watermark}</div>}
      <div className="flex justify-between gap-4 text-xs sm:text-[13px]">
        <div>
          <p>Invoice No. <strong>{invoice.invoice_number ?? "Draft"}</strong></p>
          <p>Ref. No. {invoice.job_number}</p>
        </div>
        <p>Dated <strong>{shortDate(invoice.date)}</strong></p>
      </div>

      <header className="mt-3 text-center text-xs leading-relaxed sm:text-[13px]">
        <h2 className="text-base font-bold">{c.name}</h2>
        {c.address && <p className="whitespace-pre-line">{c.address}</p>}
        {c.gstin && <p>GSTIN/UIN: {c.gstin}</p>}
        {centreState && <p>State Name : {centreState[0]}, Code : {centreState[1]}</p>}
        {(c.phone || c.email) && <p>{[c.phone && `Phone : ${c.phone}`, c.email && `E-Mail : ${c.email}`].filter(Boolean).join("   ")}</p>}
        {c.other_registration && <p>{c.other_registration}</p>}
        <p className="mt-3 text-base font-bold">Tax Invoice</p>
      </header>

      <div className="mx-auto mt-3 w-fit max-w-full text-xs leading-relaxed sm:text-[13px]">
        <p>Party : <strong>{invoice.customer_name}</strong></p>
        {invoice.billing_address && <p className="whitespace-pre-line">{invoice.billing_address}</p>}
        {invoice.customer_gstin && <p>GSTIN/UIN : {invoice.customer_gstin}</p>}
        {partyState && <p>State Name : {partyState[0]}, Code : {partyState[1]}</p>}
        <p>Vehicle : {invoice.vehicle_registration} ({invoice.vehicle_model})</p>
      </div>

      <div className="mt-3 overflow-x-auto">
        <table className={`w-full min-w-[640px] border ${B} text-xs sm:text-[13px]`}>
          <thead>
            <tr className={`border-b ${B} text-center`}>
              {["Sl No.", "Description of Goods and Services", "HSN/SAC", "Quantity", "Rate", "per", ...(showDiscount ? ["Disc."] : []), "Amount"].map((h) => (
                <th key={h} scope="col" className={`border-r ${B} px-2 py-1.5 font-normal last:border-r-0`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {lines.map(([l, i], n) => {
              const labour = l.line_type === "LABOUR";
              const amount = Number(l.quantity) * Number(l.unit_price) - Number(l.discount_amount);
              return (
                <tr key={i} className="align-top">
                  <td className={`border-r ${B} px-2 py-1`}>{n + 1}</td>
                  <td className={`border-r ${B} px-2 py-1 font-semibold uppercase`}>{l.description}{renderRate && l.is_custom && <span className="no-print ml-2 text-[10px] font-normal text-brand-600 normal-case">added</span>}</td>
                  <td className={`border-r ${B} px-2 py-1`}>{l.hsn_code}</td>
                  <td className={`border-r ${B} px-2 py-1 text-right font-semibold whitespace-nowrap`}>{labour ? "" : `${qty(l.quantity)} ${l.unit ?? ""}`.trim()}</td>
                  <td className={`border-r ${B} px-2 py-1 text-right tabular-nums`}>{renderRate ? renderRate(l, i) : labour ? "" : money(l.unit_price)}</td>
                  <td className={`border-r ${B} px-2 py-1`}>{labour ? "" : l.unit}</td>
                  {showDiscount && <td className={`border-r ${B} px-2 py-1 text-right tabular-nums`}>{renderDiscount ? renderDiscount(l, i) : Number(l.discount_amount) > 0 ? money(l.discount_amount) : ""}</td>}
                  <td className="px-2 py-1 text-right font-semibold tabular-nums">{money(amount)}</td>
                </tr>
              );
            })}
            {invoice.lines.length === 0 && <tr><td colSpan={cols} className="px-2 py-4 text-center text-slate-500">No chargeable items</td></tr>}
            {(
              [
                ["", taxable, true],
                ...(split ? [["CGST", String(cgst), false], ["SGST", String(Number(invoice.tax_total) - cgst), false]] : Number(invoice.tax_total) ? [["IGST", invoice.tax_total, false]] : []),
                ...(roundOff ? [["Round Off", invoice.round_off ?? "0", false]] : []),
              ] as [string, string, boolean][]
            ).map(([name, value, rule]) => (
              <tr key={name || "subtotal"}>
                <td className={`border-r ${B}`} />
                <td className={`border-r ${B} px-2 py-1 text-right font-bold italic`}>{name}</td>
                {Array.from({ length: cols - 3 }, (_, k) => <td key={k} className={`border-r ${B}`} />)}
                <td className={`px-2 py-1 text-right tabular-nums ${rule ? `border-t ${B}` : ""}`}>{roundOff < 0 && name === "Round Off" ? "(-)" : ""}{money(Math.abs(Number(value)))}</td>
              </tr>
            ))}
            <tr className="h-10">{Array.from({ length: cols }, (_, k) => <td key={k} className={`border-r ${B} last:border-r-0`} />)}</tr>
            <tr className={`border-t ${B} font-bold`}>
              <td className={`border-r ${B}`} />
              <td className={`border-r ${B} px-2 py-1.5 text-right`}>Total</td>
              {Array.from({ length: cols - 3 }, (_, k) => <td key={k} className={`border-r ${B}`} />)}
              <td className="px-2 py-1.5 text-right text-sm whitespace-nowrap tabular-nums sm:text-base">₹ {money(invoice.total)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="mt-1 flex justify-between text-xs">
        <span>Amount Chargeable (in words)</span>
        <span className="italic">E. &amp; O.E</span>
      </div>
      {invoice.total_in_words && <p className="font-bold">{invoice.total_in_words}</p>}

      <div className="mt-2 overflow-x-auto">
        <table className={`w-full min-w-[560px] border ${B} text-[11px] sm:text-xs`}>
          <caption className="sr-only">Tax summary by HSN/SAC</caption>
          <thead className="text-center">
            <tr className={`border-b ${B}`}>
              <th scope="col" rowSpan={2} className={`border-r ${B} px-2 py-1 font-normal`}>HSN/SAC</th>
              <th scope="col" rowSpan={2} className={`border-r ${B} px-2 py-1 font-normal`}>Taxable Value</th>
              {split ? (<>
                <th scope="colgroup" colSpan={2} className={`border-r ${B} px-2 py-1 font-normal`}>CGST</th>
                <th scope="colgroup" colSpan={2} className={`border-r ${B} px-2 py-1 font-normal`}>SGST/UTGST</th>
              </>) : <th scope="colgroup" colSpan={2} className={`border-r ${B} px-2 py-1 font-normal`}>Integrated Tax</th>}
              <th scope="col" rowSpan={2} className="px-2 py-1 font-normal">Total Tax Amount</th>
            </tr>
            <tr className={`border-b ${B}`}>
              {(split ? ["Rate", "Amount", "Rate", "Amount"] : ["Rate", "Amount"]).map((h, k) => <th key={k} scope="col" className={`border-r ${B} px-2 py-1 font-normal`}>{h}</th>)}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {rows.map((r) => (
              <tr key={`${r.hsn_code}-${r.rate}`} className={`border-b ${B}`}>
                <td className={`border-r ${B} px-2 py-0.5`}>{r.hsn_code}</td>
                <td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(r.taxable)}</td>
                {split ? (<>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{qty(r.cgst_rate)}%</td>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(r.cgst ?? 0)}</td>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{qty(r.sgst_rate)}%</td>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(r.sgst ?? 0)}</td>
                </>) : (<>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{qty(r.rate)}%</td>
                  <td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(r.tax)}</td>
                </>)}
                <td className="px-2 py-0.5 text-right">{money(r.tax)}</td>
              </tr>
            ))}
            <tr className="font-bold">
              <td className={`border-r ${B} px-2 py-0.5 text-right`}>Total</td>
              <td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(taxable)}</td>
              {split ? (<>
                <td className={`border-r ${B}`} /><td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(cgst)}</td>
                <td className={`border-r ${B}`} /><td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(Number(invoice.tax_total) - cgst)}</td>
              </>) : (<><td className={`border-r ${B}`} /><td className={`border-r ${B} px-2 py-0.5 text-right`}>{money(invoice.tax_total)}</td></>)}
              <td className="px-2 py-0.5 text-right">{money(invoice.tax_total)}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div className="mt-2 space-y-0.5 text-xs sm:text-[13px]">
        {invoice.tax_in_words && <p>Tax Amount (in words) : <strong>{invoice.tax_in_words}</strong></p>}
        {c.pan && <p>Company&apos;s PAN : <strong>{c.pan}</strong></p>}
      </div>

      <div className="mt-4 flex flex-col justify-between gap-4 text-xs sm:flex-row">
        <div className="max-w-md space-y-1">
          <p className="underline">Declaration</p>
          <p>{c.declaration || "We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct."}</p>
          {invoice.terms && <p><strong>Terms:</strong> {invoice.terms}</p>}
          {invoice.notes && <p><strong>Notes:</strong> {invoice.notes}</p>}
        </div>
        <div className="flex flex-col items-end justify-between gap-10 text-right">
          <p className="font-bold">for {c.name}</p>
          <p>Authorised Signatory</p>
        </div>
      </div>
      <p className="mt-4 text-center text-xs underline">This is a Computer Generated Invoice</p>
    </article>
  );
}
