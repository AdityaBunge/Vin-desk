import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BellRing, Mail, MessageCircle, MessageSquare } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Alert, Button, Card, StatusBadge, useConfirm, useToast } from "@/components/ui";
import { useFeatures } from "@/hooks/useFeatures";
import { channelLabel, fmtDateTime, label } from "@/lib/format";
import { post } from "@/services/api";
import type { Channel, Delivery, Invoice } from "@/types";

const ACTIVE = ["PENDING", "QUEUED", "RETRY_SCHEDULED"];

function explain(d: Delivery): string {
  switch (d.display_status) {
    case "PENDING": return "Queued; the delivery worker will send it shortly.";
    case "QUEUED": return "Being sent now.";
    case "RETRY_SCHEDULED": return `Temporary failure. Next automatic attempt at ${fmtDateTime(d.next_attempt_at)}.`;
    case "SENT": return "Accepted by the provider. Waiting for a delivery receipt.";
    case "DELIVERY_STATUS_UNKNOWN": return "Accepted by the provider. This provider does not confirm delivery.";
    case "SIMULATED": return "Development simulator: no real message was sent to the customer.";
    case "DELIVERED": return `Delivery confirmed by the provider at ${fmtDateTime(d.delivered_at)}.`;
    case "SKIPPED": return "Not sent: the customer has opted out of this channel.";
    case "CANCELLED": return "Cancelled before sending.";
    default: return "";
  }
}

const ICONS = { EMAIL: Mail, SMS: MessageSquare, WHATSAPP: MessageCircle };

function useRefresh(invoice: Invoice) {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: ["invoice", invoice.id] });
    void queryClient.invalidateQueries({ queryKey: ["deliveries"] });
    void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };
}

function ChannelCard({ invoice, channel, jobs }: { invoice: Invoice; channel: Channel; jobs: Delivery[] }) {
  const toast = useToast();
  const confirm = useConfirm();
  const [showHistory, setShowHistory] = useState(false);
  const latest = jobs.at(-1);
  const Icon = ICONS[channel];
  const name = channelLabel(channel);
  const refresh = useRefresh(invoice);
  const retry = useMutation({ mutationFn: (id: number) => post(`/deliveries/${id}/retry`), onSuccess: () => { refresh(); toast.success(`${name} retry queued`); }, onError: (e) => toast.error(e) });
  const resend = useMutation({
    mutationFn: () => post(`/invoices/${invoice.id}/resend`, { channel, confirm: true }),
    onSuccess: () => { refresh(); toast.success(`${name} resend queued`); }, onError: (e) => toast.error(e),
  });
  const inProgress = jobs.some((j) => ACTIVE.includes(j.status));
  const onResend = async () => {
    const r = await confirm({
      title: `Resend invoice by ${name}?`,
      message: <>The customer will receive another {name.toLowerCase()} for {invoice.invoice_number}{latest?.destination ? <> at <strong>{latest.destination}</strong> (current contact details are used)</> : null}. Other channels are not affected.</>,
      confirmLabel: `Resend ${name}`,
    });
    if (r.ok) resend.mutate();
  };
  return (
    <div className="rounded-xl border border-slate-900/[0.07] bg-white/45 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-800"><Icon className="h-4 w-4" aria-hidden />{name}</span>
        {latest ? <StatusBadge status={latest.display_status} /> : <span className="text-xs text-slate-500">Not sent</span>}
      </div>
      {latest && (
        <div className="mt-2 space-y-1 text-sm text-slate-700">
          <p>To: <span className="font-medium">{latest.destination || "no contact on record"}</span></p>
          <p className="text-xs text-slate-500">{explain(latest)}</p>
          {latest.last_error && <Alert tone="error">{latest.last_error}</Alert>}
          <p className="text-xs text-slate-500">
            {latest.attempt_count} attempt(s){latest.provider ? ` via ${latest.provider}` : ""}{latest.last_attempt_at ? ` · last ${fmtDateTime(latest.last_attempt_at)}` : ""} · {latest.trigger === "MANUAL" ? "manual resend" : "automatic"}
          </p>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {latest?.status === "FAILED" && <Button size="sm" loading={retry.isPending} onClick={() => retry.mutate(latest.id)}>Retry {name}</Button>}
        <Button size="sm" variant="secondary" disabled={inProgress} loading={resend.isPending} onClick={() => void onResend()}>Resend {name}</Button>
        {jobs.length > 0 && <Button size="sm" variant="ghost" onClick={() => setShowHistory((s) => !s)}>{showHistory ? "Hide" : "Show"} history</Button>}
      </div>
      {showHistory && <History jobs={jobs} manual="Manual resend" />}
    </div>
  );
}

function History({ jobs, manual }: { jobs: Delivery[]; manual: string }) {
  return (
    <ol className="mt-3 space-y-2 border-t border-slate-900/[0.07] pt-2 text-xs text-slate-600">
      {[...jobs].reverse().map((j) => (
        <li key={j.id}>
          <p className="font-medium text-slate-800">{fmtDateTime(j.created_at)} · {j.trigger === "MANUAL" ? manual : "Automatic"} to {j.destination || "-"} · {label(j.display_status)}</p>
          <ul className="ml-3 list-disc">
            {j.attempts.map((a) => <li key={a.id}>Attempt {a.attempt_number} at {fmtDateTime(a.finished_at)}: {label(a.outcome)}{a.error ? ` - ${a.error}` : ""}</li>)}
            {j.attempts.length === 0 && <li>{j.last_error ?? "No provider attempt yet"}</li>}
          </ul>
        </li>
      ))}
    </ol>
  );
}

/** WhatsApp payment reminders for this invoice: automatic ones (Admin > Settings) and a manual send. */
function PaymentReminders({ invoice, jobs, enabled }: { invoice: Invoice; jobs: Delivery[]; enabled: boolean }) {
  const toast = useToast();
  const confirm = useConfirm();
  const refresh = useRefresh(invoice);
  const [showHistory, setShowHistory] = useState(false);
  const latest = jobs.at(-1);
  const outstanding = Number(invoice.outstanding) > 0;
  const send = useMutation({
    mutationFn: () => post(`/invoices/${invoice.id}/payment-reminder`),
    onSuccess: () => { refresh(); toast.success("Payment reminder queued"); }, onError: (e) => toast.error(e),
  });
  const onSend = async () => {
    const r = await confirm({
      title: "Send a payment reminder on WhatsApp?",
      message: <>The customer will receive a WhatsApp reminder of the outstanding balance on {invoice.invoice_number}, with the invoice link.</>,
      confirmLabel: "Send reminder",
    });
    if (r.ok) send.mutate();
  };
  return (
    <div className="mt-3 rounded-xl border border-slate-900/[0.07] bg-white/45 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-sm font-semibold text-slate-800"><BellRing className="h-4 w-4" aria-hidden />Payment reminders (WhatsApp)</span>
        {latest ? <StatusBadge status={latest.display_status} /> : <span className="text-xs text-slate-500">None sent</span>}
      </div>
      <p className="mt-2 text-xs text-slate-500">
        {outstanding ? `${jobs.length} reminder(s) so far${latest ? `, last ${fmtDateTime(latest.created_at)}` : ""}. Automatic reminders stop once the invoice is paid.` : "Paid in full: no reminders are sent."}
      </p>
      {latest?.status === "FAILED" && latest.last_error && <div className="mt-2"><Alert tone="error">{latest.last_error}</Alert></div>}
      <div className="mt-3 flex flex-wrap gap-2">
        {latest?.status === "FAILED" && <RetryButton invoice={invoice} job={latest} />}
        {enabled && outstanding && <Button size="sm" variant="secondary" disabled={jobs.some((j) => ACTIVE.includes(j.status))} loading={send.isPending} onClick={() => void onSend()}>Send payment reminder</Button>}
        {jobs.length > 0 && <Button size="sm" variant="ghost" onClick={() => setShowHistory((s) => !s)}>{showHistory ? "Hide" : "Show"} history</Button>}
      </div>
      {showHistory && <History jobs={jobs} manual="Sent by staff" />}
    </div>
  );
}

function RetryButton({ invoice, job }: { invoice: Invoice; job: Delivery }) {
  const toast = useToast();
  const refresh = useRefresh(invoice);
  const retry = useMutation({ mutationFn: () => post(`/deliveries/${job.id}/retry`), onSuccess: () => { refresh(); toast.success("Retry queued"); }, onError: (e) => toast.error(e) });
  return <Button size="sm" loading={retry.isPending} onClick={() => retry.mutate()}>Retry</Button>;
}

export function DeliveryPanel({ invoice }: { invoice: Invoice }) {
  const features = useFeatures();
  const toast = useToast();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [newLink, setNewLink] = useState<string | null>(null);
  const link = invoice.links.filter((l) => l.usable).at(-1);
  const reissue = useMutation({
    mutationFn: () => post<{ url: string; expires_at: string }>(`/invoices/${invoice.id}/link`),
    onSuccess: (data) => { setNewLink(data.url); void queryClient.invalidateQueries({ queryKey: ["invoice", invoice.id] }); toast.success("New secure link issued; earlier links no longer work"); },
    onError: (e) => toast.error(e),
  });
  const simulated = invoice.delivery_jobs.some((d) => d.simulated);
  const invoiceJobs = invoice.delivery_jobs.filter((d) => d.kind === "INVOICE");
  const reminders = invoice.delivery_jobs.filter((d) => d.kind === "PAYMENT_REMINDER");
  // A channel that is turned off queues no rows, so its card shows only for older invoices.
  const channels = (["EMAIL", "SMS", "WHATSAPP"] as const).filter((ch) =>
    ch === "EMAIL" || (ch === "SMS" ? features.sms : features.whatsapp) || invoiceJobs.some((d) => d.channel === ch));
  return (
    <Card title="Delivery to customer" actions={<Link className="text-sm font-medium text-brand-700 hover:underline" to={`/customers?customer=${invoice.customer_id}`}>Correct contact details</Link>}>
      {simulated && <div className="mb-3"><Alert tone="warn">Customer messages are running on the <strong>development simulator</strong>. Messages are written to the server's dev outbox and are not sent to the customer.</Alert></div>}
      <div className={channels.length > 2 ? "grid gap-3 lg:grid-cols-3" : channels.length > 1 ? "grid gap-3 lg:grid-cols-2" : "grid gap-3"}>
        {channels.map((ch) => <ChannelCard key={ch} invoice={invoice} channel={ch} jobs={invoiceJobs.filter((d) => d.channel === ch)} />)}
      </div>
      {(features.whatsapp || reminders.length > 0) && <PaymentReminders invoice={invoice} jobs={reminders} enabled={features.whatsapp} />}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-900/[0.07] pt-3 text-sm text-slate-700">
        <span>
          Secure customer link: {link ? <>valid until <strong>{fmtDateTime(link.expires_at)}</strong>, opened {link.access_count} time(s)</> : <span className="font-medium text-amber-700">expired or revoked - resend to issue a new one</span>}
        </span>
        <Button size="sm" variant="secondary" loading={reissue.isPending} onClick={async () => {
          const r = await confirm({ title: "Replace the customer link?", message: "All links already sent for this invoice stop working. Resend the invoice afterwards so the customer gets the new link.", confirmLabel: "Revoke and issue new link", danger: true });
          if (r.ok) reissue.mutate();
        }}>Revoke &amp; reissue link</Button>
      </div>
      {newLink && <div className="mt-2"><Alert tone="success">New link (shown once): <a className="break-all underline" href={newLink} target="_blank" rel="noreferrer">{newLink}</a></Alert></div>}
    </Card>
  );
}
