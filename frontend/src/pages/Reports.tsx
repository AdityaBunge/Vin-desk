import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button, Card, EmptyState, ErrorState, Field, PageHeader, Spinner, StatusBadge, useToast, cx } from "@/components/ui";
import { fmtDate, fmtDateTime, label, money, todayISO } from "@/lib/format";
import { get, openFile } from "@/services/api";
import type { Report, ReportColumn } from "@/types";

const TITLES: Record<string, string> = {
  "jobs-daily": "Daily service jobs", "jobs-monthly": "Monthly service jobs", revenue: "Revenue and outstanding payments",
  "outstanding-invoices": "Outstanding invoices", "parts-consumption": "Parts consumption", "low-stock": "Low-stock items",
  "unavailable-parts": "Unavailable parts", "jobs-waiting-parts": "Jobs waiting for parts", "technician-workload": "Technician workload",
  turnaround: "Average turnaround time", "repeat-visits": "Repeat visits", "delivery-rates": "Invoice delivery success rates",
  "email-failures": "Email delivery failures", "sms-failures": "SMS delivery failures", "whatsapp-failures": "WhatsApp delivery failures",
};
const SERIES_COLOURS = ["#1e3a5f", "#d97706", "#059669"];

function cell(column: ReportColumn, value: string | number | null) {
  if (value === null || value === undefined || value === "") return "-";
  switch (column.type) {
    case "money": return `₹ ${money(value)}`;
    case "date": return fmtDate(String(value));
    case "datetime": return fmtDateTime(String(value));
    case "status": return <StatusBadge status={String(value)} />;
    case "number": return Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 });
    default: return String(value);
  }
}

export default function Reports() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [from, setFrom] = useState(todayISO(-29));
  const [to, setTo] = useState(todayISO());
  const [exporting, setExporting] = useState(false);
  const list = useQuery({ queryKey: ["reports"], queryFn: () => get<{ name: string; uses_date_range: boolean }[]>("/reports") });
  const name = params.get("report") ?? list.data?.[0]?.name ?? "";
  const meta = list.data?.find((r) => r.name === name);
  const q = useQuery({
    queryKey: ["report", name, from, to],
    queryFn: () => get<Report>(`/reports/${name}`, { date_from: from, date_to: to }),
    enabled: !!meta && from <= to,
    placeholderData: keepPreviousData,
  });
  const report = q.data;
  const chartData = report?.chart ? report.rows.map((r) => {
    const out: Record<string, string | number> = { [report.chart!.x]: String(r[report.chart!.x] ?? "") };
    for (const s of report.chart!.series) out[s] = Number(r[s] ?? 0);
    return out;
  }) : [];
  const exportCsv = async () => {
    setExporting(true);
    try {
      await openFile(`/reports/${name}`, { date_from: from, date_to: to, format: "csv" }, `${name}_${from}_${to}.csv`);
    } catch (e) {
      toast.error(e);
    } finally {
      setExporting(false);
    }
  };

  return (
    <>
      <PageHeader title="Reports" subtitle="Figures are calculated from live data for the selected period (India time)." />
      <div className="grid gap-4 lg:grid-cols-4">
        <Card className="h-fit lg:col-span-1">
          {list.isLoading ? <Spinner /> : (
            <nav aria-label="Reports"><ul className="space-y-0.5">
              {list.data?.map((r) => (
                <li key={r.name}>
                  <button type="button" onClick={() => setParams({ report: r.name })} aria-current={r.name === name ? "page" : undefined}
                    className={cx("w-full rounded-xl px-3 py-2 text-left text-sm transition-colors", r.name === name ? "bg-white font-medium text-brand-700 shadow-sm ring-1 ring-slate-900/5" : "text-slate-600 hover:bg-white/60 hover:text-slate-900")}>
                    {TITLES[r.name] ?? r.name}
                  </button>
                </li>
              ))}
            </ul></nav>
          )}
        </Card>
        <div className="space-y-4 lg:col-span-3">
          <Card>
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div className="flex flex-wrap gap-3">
                <Field label="From">{(id) => <input id={id} type="date" className="input" disabled={!meta?.uses_date_range} value={from} max={to} onChange={(e) => setFrom(e.target.value)} />}</Field>
                <Field label="To">{(id) => <input id={id} type="date" className="input" disabled={!meta?.uses_date_range} value={to} min={from} onChange={(e) => setTo(e.target.value)} />}</Field>
                {meta && !meta.uses_date_range && <p className="self-end pb-2 text-xs text-slate-500">This report shows the current position.</p>}
              </div>
              <Button variant="secondary" disabled={!report?.rows.length} loading={exporting} onClick={() => void exportCsv()}><Download className="h-4 w-4" />Export CSV</Button>
            </div>
          </Card>
          {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : report && (<>
            {Object.keys(report.summary).length > 0 && (
              <div className="grid grid-cols-2 gap-3 md:grid-cols-3">
                {Object.entries(report.summary).map(([key, value]) => (
                  <div key={key} className="glass rounded-xl p-3">
                    <p className="text-xs text-slate-500">{label(key)}</p>
                    <p className="text-lg font-semibold tabular-nums">
                      {value === null ? "-" : /total|revenue|collected|outstanding/.test(key) && !/^(invoices|jobs)/.test(key) ? `₹ ${money(value)}` : Number(value).toLocaleString("en-IN")}
                    </p>
                  </div>
                ))}
              </div>
            )}
            {report.chart && chartData.length > 0 && (
              <Card title={report.title}>
                <div className="h-64" role="img" aria-label={`Chart: ${report.title}`}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                      <XAxis dataKey={report.chart.x} tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} width={70} />
                      <Tooltip formatter={(v: number) => v.toLocaleString("en-IN")} />
                      <Legend formatter={(v: string) => label(v)} />
                      {report.chart.series.map((s, i) => <Bar key={s} dataKey={s} name={s} fill={SERIES_COLOURS[i % SERIES_COLOURS.length]} stackId={name === "revenue" ? "a" : undefined} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            )}
            <Card title={`${report.title} (${report.rows.length})`}>
              {report.rows.length === 0 ? <EmptyState title="No data for this period" /> : (
                <div className="overflow-x-auto">
                  <table className="min-w-full divide-y divide-slate-900/[0.07]">
                    <thead className="border-b border-slate-900/[0.07]"><tr>{report.columns.map((c) => <th key={c.key} scope="col" className={cx("th", ["number", "money"].includes(c.type) && "text-right")}>{c.label}</th>)}</tr></thead>
                    <tbody className="divide-y divide-slate-900/[0.05]">
                      {report.rows.map((row, i) => (
                        <tr key={i}>{report.columns.map((c) => <td key={c.key} className={cx("td", ["number", "money"].includes(c.type) && "text-right tabular-nums")}>{cell(c, row[c.key])}</td>)}</tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Card>
          </>)}
        </div>
      </div>
    </>
  );
}
