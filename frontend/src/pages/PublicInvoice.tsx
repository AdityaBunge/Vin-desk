import { useMutation, useQuery } from "@tanstack/react-query";
import { FileDown, Printer, ShieldCheck, Star } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Spinner, errorText } from "@/components/ui";
import { InvoiceDocument, type InvoiceView } from "@/features/invoice/InvoiceDocument";
import { rupees } from "@/lib/format";
import { ApiError, get, post } from "@/services/api";

interface Feedback { rating: number; comment: string }
type PublicInvoiceData = Omit<InvoiceView, "date"> & { invoice_date: string; feedback: Feedback | null };

const RATING_WORDS = ["", "Poor", "Not good", "Okay", "Good", "Excellent"];

/** 1-5 stars and an optional comment; the customer can change it later. */
function FeedbackCard({ token, centre, saved }: { token: string; centre: string; saved: Feedback | null }) {
  const [rating, setRating] = useState(saved?.rating ?? 0);
  const [hover, setHover] = useState(0);
  const [comment, setComment] = useState(saved?.comment ?? "");
  const [sent, setSent] = useState<Feedback | null>(saved);
  const send = useMutation({
    mutationFn: () => post<Feedback>(`/public/invoices/${encodeURIComponent(token)}/feedback`, { rating, comment }),
    onSuccess: setSent,
  });
  const shown = hover || rating;
  const unchanged = sent && sent.rating === rating && sent.comment === comment.trim();
  return (
    <section className="no-print glass-strong mt-4 rounded-2xl p-5" aria-labelledby="feedback-title">
      <h2 id="feedback-title" className="text-base font-semibold text-slate-900">How was your visit to {centre}?</h2>
      <div className="mt-3 flex items-center gap-1" role="radiogroup" aria-label="Rating out of 5" onMouseLeave={() => setHover(0)}>
        {[1, 2, 3, 4, 5].map((n) => (
          <button key={n} type="button" role="radio" aria-checked={rating === n} aria-label={`${n} star${n > 1 ? "s" : ""} - ${RATING_WORDS[n]}`}
            className="rounded-lg p-1 transition-transform hover:scale-110" onMouseEnter={() => setHover(n)} onClick={() => setRating(n)}>
            <Star className={n <= shown ? "h-8 w-8 fill-amber-400 text-amber-500" : "h-8 w-8 text-slate-300"} aria-hidden />
          </button>
        ))}
        <span className="ml-2 text-sm text-slate-600">{RATING_WORDS[shown]}</span>
      </div>
      <label htmlFor="feedback-comment" className="mt-3 block text-sm font-medium text-slate-700">Anything we should know? (optional)</label>
      <textarea id="feedback-comment" rows={3} maxLength={1000} className="input mt-1" value={comment} onChange={(e) => setComment(e.target.value)} />
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <Button disabled={!rating || !!unchanged} loading={send.isPending} onClick={() => send.mutate()}>{sent ? "Update feedback" : "Send feedback"}</Button>
        {unchanged && <p role="status" className="text-sm text-emerald-700">Thank you for your feedback.</p>}
        {send.error && <p role="alert" className="text-sm text-red-700">{errorText(send.error)}</p>}
      </div>
    </section>
  );
}

/** Customer-facing invoice page opened from the emailed / texted secure link. No sign-in. */
export default function PublicInvoice() {
  const { token = "" } = useParams();
  const q = useQuery({
    queryKey: ["public-invoice", token],
    queryFn: () => get<PublicInvoiceData>(`/public/invoices/${encodeURIComponent(token)}`),
    retry: false,
    staleTime: Infinity,
  });
  const expired = q.error instanceof ApiError && q.error.status === 410;
  return (
    <div className="min-h-dvh p-4 print:bg-white print:p-0">
      <div className="mx-auto max-w-4xl">
        {q.isLoading && <Spinner label="Loading your invoice..." />}
        {q.error && (
          <div role="alert" className="mx-auto mt-16 max-w-md glass-strong rounded-2xl p-8 text-center">
            <h1 className="text-lg font-semibold text-slate-900">{expired ? "This invoice link has expired" : "This invoice link is not valid"}</h1>
            <p className="mt-2 text-sm text-slate-600">
              {q.error instanceof ApiError && q.error.status === 429
                ? "Too many attempts. Please wait a minute and try again."
                : "Please contact the service centre and ask them to send you a new link."}
            </p>
          </div>
        )}
        {q.data && (<>
          <div className="no-print mb-3 flex flex-wrap items-center justify-between gap-2">
            <p className="flex items-center gap-1.5 text-xs text-slate-600"><ShieldCheck className="h-4 w-4 text-emerald-600" aria-hidden />Secure invoice link from {q.data.centre.name}. Please do not share it.</p>
            <div className="flex gap-2">
              <a href={`/api/public/invoices/${encodeURIComponent(token)}/pdf`} target="_blank" rel="noreferrer">
                <Button variant="secondary"><FileDown className="h-4 w-4" />Download PDF</Button>
              </a>
              <Button onClick={() => window.print()}><Printer className="h-4 w-4" />Print</Button>
            </div>
          </div>
          {Number(q.data.amount_paid) > 0 && (
            <p className="no-print mb-3 text-sm text-slate-700">
              Paid <strong>{rupees(q.data.amount_paid)}</strong> · Balance due{" "}
              <strong className={Number(q.data.outstanding) > 0 ? "text-red-700" : "text-emerald-700"}>{rupees(q.data.outstanding)}</strong>
            </p>
          )}
          <InvoiceDocument invoice={{ ...q.data, date: q.data.invoice_date }} />
          <FeedbackCard token={token} centre={q.data.centre.name ?? "us"} saved={q.data.feedback ?? null} />
          <p className="no-print mt-4 text-center text-sm text-slate-600">Thank you for choosing {q.data.centre.name}.</p>
        </>)}
      </div>
    </div>
  );
}
