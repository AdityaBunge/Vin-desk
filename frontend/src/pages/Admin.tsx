import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";
import { DataTable } from "@/components/DataTable";
import { Alert, Button, Card, EmptyState, ErrorState, Field, Modal, PageHeader, Spinner, StatusBadge, Tabs, useToast } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useListParams } from "@/hooks/useListParams";
import { ROLE_LABEL, fmtDateTime, label } from "@/lib/format";
import { get, patch, post, put } from "@/services/api";
import type { AuditEntry, Page, TaxRate, User } from "@/types";
import { type UserValues, userSchema } from "@/validation/schemas";

// --- Users ------------------------------------------------------------------------------

function UserModal({ user, onClose }: { user: User | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const { user: me } = useAuth();
  const { register, handleSubmit, setError, formState: { errors } } = useForm<UserValues>({
    resolver: zodResolver(userSchema),
    defaultValues: { email: user?.email ?? "", full_name: user?.full_name ?? "", phone: user?.phone ?? "", role_code: user?.role_code ?? "MECHANIC", password: "", is_active: user?.is_active ?? true },
  });
  const save = useMutation({
    mutationFn: (v: UserValues) => user
      ? patch(`/users/${user.id}`, { full_name: v.full_name, phone: v.phone || null, role_code: v.role_code, is_active: v.is_active, ...(v.password ? { password: v.password } : {}) })
      : post("/users", { email: v.email, full_name: v.full_name, phone: v.phone || null, role_code: v.role_code, password: v.password }),
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["users"] }); toast.success(user ? "User updated" : "User created"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const submit = (v: UserValues) => {
    if (!user && !v.password) return setError("password", { message: "Set an initial password" });
    save.mutate(v);
  };
  const self = user?.id === me?.id;
  return (
    <Modal open title={user ? `Edit ${user.full_name}` : "New user"} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="user-form" loading={save.isPending}>Save</Button></>}>
      <form id="user-form" onSubmit={handleSubmit(submit)} noValidate className="space-y-3">
        <Field label="Email (sign-in name)" required error={errors.email?.message}>{(id) => <input id={id} type="email" className="input" disabled={!!user} autoComplete="off" {...register("email")} />}</Field>
        <Field label="Full name" required error={errors.full_name?.message}>{(id) => <input id={id} className="input" {...register("full_name")} />}</Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Phone">{(id) => <input id={id} className="input" {...register("phone")} />}</Field>
          <Field label="Role" required hint={self ? "You cannot change your own role" : undefined}>
            {(id, d) => <select id={id} aria-describedby={d} className="input" disabled={self} {...register("role_code")}>{Object.entries(ROLE_LABEL).map(([code, text]) => <option key={code} value={code}>{text}</option>)}</select>}
          </Field>
        </div>
        <Field label={user ? "New password" : "Initial password"} required={!user} error={errors.password?.message} hint={user ? "Leave blank to keep the current password" : "At least 10 characters"}>
          {(id, d) => <input id={id} aria-describedby={d} type="password" className="input" autoComplete="new-password" {...register("password")} />}
        </Field>
        {user && <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={self} {...register("is_active")} />Account active</label>}
      </form>
    </Modal>
  );
}

export function Users() {
  const q = useQuery({ queryKey: ["users"], queryFn: () => get<User[]>("/users") });
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const columns = useMemo<ColumnDef<User>[]>(() => [
    { accessorKey: "full_name", header: "Name", cell: ({ row }) => <span className="font-medium">{row.original.full_name}{row.original.is_demo && <span className="ml-2 rounded bg-amber-100 px-1.5 text-xs text-amber-800">demo</span>}</span> },
    { accessorKey: "email", header: "Email" },
    { accessorKey: "role_code", header: "Role", cell: ({ row }) => ROLE_LABEL[row.original.role_code] },
    { accessorKey: "is_active", header: "Status", cell: ({ row }) => <StatusBadge status={row.original.is_active ? "APPROVED" : "CANCELLED"} /> },
    { accessorKey: "last_login_at", header: "Last sign-in", cell: ({ row }) => fmtDateTime(row.original.last_login_at) },
    { id: "actions", header: "", enableSorting: false, cell: ({ row }) => <div className="text-right"><Button size="sm" variant="ghost" onClick={() => setEditing(row.original)}>Edit</Button></div> },
  ], []);
  return (
    <>
      <PageHeader title="Users & Roles" subtitle="Create accounts, assign one of the four roles, or deactivate access. Changes are audited."
        actions={<Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />New user</Button>} />
      <Card>
        <DataTable columns={columns} data={q.data} loading={q.isLoading} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No users" />
      </Card>
      <Card title="Role permissions" className="mt-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          {([
            ["Service Manager", "Reception, job cards, assignment, estimates, invoices, payments, invoice delivery, purchase approvals, reports."],
            ["Mechanic", "Assigned jobs only: inspection, labour, parts requests, completion. Cannot issue stock or invoice."],
            ["Inventory Staff", "Parts catalogue, stock, fulfilment of parts requests, purchase requests. Cannot approve own purchases or touch invoices."],
            ["Administrator", "Users, master data, settings and audit log. No access to billing or stock operations."],
          ] as const).map(([role, text]) => <div key={role}><dt className="font-semibold text-slate-800">{role}</dt><dd className="text-slate-600">{text}</dd></div>)}
        </dl>
      </Card>
      {editing && <UserModal user={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </>
  );
}

// --- Master data ------------------------------------------------------------------------

type Row = Record<string, string | number | boolean | null> & { id: number; is_active: boolean };
interface FieldDef { name: string; label: string; type?: "text" | "number" | "select" | "textarea"; required?: boolean; options?: { value: string; label: string }[] }
interface Resource { key: string; label: string; path: string; fields: FieldDef[]; columns: [string, string][] }

function ResourceModal({ resource, row, onClose }: { resource: Resource; row: Row | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(resource.fields.map((f) => [f.name, row?.[f.name] == null ? "" : String(row[f.name])])));
  const [active, setActive] = useState(row?.is_active ?? true);
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = { is_active: active };
      for (const f of resource.fields) body[f.name] = f.type === "select" ? (values[f.name] ? Number(values[f.name]) : null) : f.type === "number" && f.name === "sort_order" ? Number(values[f.name] || 0) : values[f.name];
      return row ? put(`${resource.path}/${row.id}`, body) : post(resource.path, body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: [resource.path.slice(1)] }); void queryClient.invalidateQueries({ queryKey: ["master", resource.key] }); toast.success(`${resource.label} saved`); onClose(); },
    onError: (e) => toast.error(e),
  });
  const valid = resource.fields.every((f) => !f.required || values[f.name]?.trim());
  return (
    <Modal open title={`${row ? "Edit" : "New"} ${resource.label.toLowerCase()}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!valid} loading={save.isPending} onClick={() => save.mutate()}>Save</Button></>}>
      <div className="space-y-3">
        {resource.fields.map((f) => (
          <Field key={f.name} label={f.label} required={f.required}>
            {(id) => f.type === "select" ? (
              <select id={id} className="input" value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })}>
                <option value="">None</option>
                {f.options?.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : f.type === "textarea" ? (
              <textarea id={id} rows={2} className="input" value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
            ) : (
              <input id={id} className="input" inputMode={f.type === "number" ? "decimal" : undefined} value={values[f.name]} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
            )}
          </Field>
        ))}
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />Active</label>
        {row && !active && <p className="text-xs text-slate-500">Inactive items stay on existing records but can no longer be selected.</p>}
      </div>
    </Modal>
  );
}

function ResourceTable({ resource }: { resource: Resource }) {
  const q = useQuery({ queryKey: ["master", resource.key], queryFn: () => get<Row[]>(resource.path, { include_inactive: true }) });
  const [editing, setEditing] = useState<Row | "new" | null>(null);
  return (
    <Card title={resource.label + "s"} actions={<Button size="sm" onClick={() => setEditing("new")}><Plus className="h-4 w-4" />Add</Button>}>
      {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data?.length ? <EmptyState title="Nothing configured yet" /> : (
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-900/[0.07]">
            <thead className="border-b border-slate-900/[0.07]"><tr>{resource.columns.map(([, text]) => <th key={text} className="th">{text}</th>)}<th className="th">Status</th><th className="th" /></tr></thead>
            <tbody className="divide-y divide-slate-900/[0.05]">
              {q.data.map((row) => (
                <tr key={row.id} className={row.is_active ? "" : "text-slate-400"}>
                  {resource.columns.map(([key]) => <td key={key} className="td">{String((key.includes(".") ? (row[key.split(".")[0]] as unknown as Record<string, unknown> | null)?.[key.split(".")[1]] : row[key]) ?? "-")}</td>)}
                  <td className="td">{row.is_active ? "Active" : "Inactive"}</td>
                  <td className="td text-right"><Button size="sm" variant="ghost" onClick={() => setEditing(row)}>Edit</Button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {editing && <ResourceModal resource={resource} row={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

export function MasterData() {
  const [params, setParams] = useSearchParams();
  const taxes = useQuery({ queryKey: ["master", "tax"], queryFn: () => get<TaxRate[]>("/tax-rates", { include_inactive: true }) });
  const taxOptions = (taxes.data ?? []).filter((t) => t.is_active).map((t) => ({ value: String(t.id), label: t.name }));
  const resources: Resource[] = [
    { key: "models", label: "Vehicle model", path: "/vehicle-models", fields: [{ name: "name", label: "Model name", required: true }, { name: "sort_order", label: "Display order", type: "number" }], columns: [["name", "Model"], ["sort_order", "Order"]] },
    { key: "categories", label: "Parts category", path: "/part-categories", fields: [{ name: "name", label: "Category name", required: true }], columns: [["name", "Category"]] },
    { key: "labour", label: "Labour operation", path: "/labour-operations", fields: [
      { name: "code", label: "Code", required: true }, { name: "name", label: "Operation", required: true }, { name: "description", label: "Description", type: "textarea" },
      { name: "default_hours", label: "Standard hours", type: "number", required: true }, { name: "hourly_rate", label: "Labour rate per hour (₹)", type: "number", required: true },
      { name: "tax_rate_id", label: "Tax rate", type: "select", options: taxOptions },
      { name: "sac_code", label: "SAC code (blank = the default in Settings)" },
    ], columns: [["code", "Code"], ["name", "Operation"], ["default_hours", "Hours"], ["hourly_rate", "Rate/hour"], ["tax_rate.name", "Tax"], ["sac_code", "SAC"]] },
    { key: "tax", label: "Tax rate", path: "/tax-rates", fields: [{ name: "name", label: "Name", required: true }, { name: "rate", label: "Rate (%)", type: "number", required: true }], columns: [["name", "Tax"], ["rate", "Rate %"]] },
  ];
  const tab = resources.some((r) => r.key === params.get("tab")) ? params.get("tab")! : "models";
  return (
    <>
      <PageHeader title="Master Data" subtitle="Configurable lists used across the application. Deactivate rather than delete, so history stays intact." />
      <Tabs tabs={resources.map((r) => ({ key: r.key, label: r.label + "s" }))} active={tab} onChange={(key) => setParams({ tab: key }, { replace: true })} />
      <ResourceTable key={tab} resource={resources.find((r) => r.key === tab)!} />
    </>
  );
}

// --- Settings ---------------------------------------------------------------------------

interface SettingsData {
  values: Record<string, string | number | boolean>;
  providers: {
    environment: string;
    email: { provider: string; simulated: boolean; smtp_host: string; smtp_port: number; smtp_security: string; smtp_username_configured: boolean; smtp_password_configured: boolean; sender_address: string };
    sms: { provider: string; simulated: boolean; auth_key_configured: boolean };
    whatsapp: { provider: string; enabled: boolean; simulated: boolean; access_token_configured: boolean; phone_number_id_configured: boolean; app_secret_configured: boolean; verify_token_configured: boolean };
    webhook_secret_configured: boolean;
    public_base_url_env: string;
  };
}
const SETTING_GROUPS: { title: string; hint?: string; fields: [string, string, ("text" | "number" | "textarea" | "bool")?][] }[] = [
  { title: "Service centre", hint: "Printed on job cards and invoices.", fields: [
    ["centre_name", "Business name"], ["centre_name_with_fy", "Add the financial year after the name (e.g. F.Y:26-27 - (from 1-Apr-26)), changing every 1 April", "bool"], ["centre_phone", "Phone"], ["centre_email", "Email"], ["centre_gstin", "GSTIN"],
    ["centre_pan", "Company PAN"], ["centre_state_name", "State name"], ["centre_state_code", "GST state code (e.g. 27)"],
    ["centre_other_registration", "Other registration / tax identifier"], ["centre_address", "Address", "textarea"],
  ] },
  { title: "Numbering and billing", fields: [
    ["job_number_prefix", "Job card prefix (A-Z)"], ["invoice_number_prefix", "Invoice prefix (A-Z)"], ["max_discount_percent", "Maximum discount per line (%)", "number"],
    ["gst_split_intra_state", "Show GST as CGST + SGST", "bool"], ["default_labour_sac", "Default SAC code for labour (998714 = motor vehicle repair)"],
    ["invoice_terms", "Invoice terms", "textarea"], ["invoice_declaration", "Invoice declaration", "textarea"], ["estimate_terms", "Estimate terms", "textarea"],
  ] },
  { title: "Invoice delivery", hint: "Non-secret settings. Credentials are set only through server environment variables.", fields: [
    ["email_sender_name", "Email sender display name"], ["sms_sender_id", "SMS sender ID (DLT header)"], ["sms_template_id", "SMS template ID (DLT-approved)"],
    ["sms_dlt_entity_id", "DLT principal entity ID"], ["public_base_url", "Public application URL (https://...)"], ["invoice_link_expiry_days", "Invoice link validity (days)", "number"],
    ["delivery_max_attempts", "Automatic delivery attempts", "number"], ["delivery_backoff_base_seconds", "First retry delay (seconds, doubles each time)", "number"],
    ["manual_resend_limit_per_hour", "Manual resends per invoice per channel per hour", "number"],
  ] },
  { title: "WhatsApp", hint: "Template names exactly as approved in WhatsApp Manager (see docs/deployment.md for the values each template receives). Reminders go to customers who allowed WhatsApp messages.", fields: [
    ["whatsapp_invoice_template", "Invoice template (with a PDF document header)"], ["whatsapp_payment_reminder_template", "Payment reminder template"],
    ["whatsapp_service_reminder_template", "Service reminder template"], ["whatsapp_template_language", "Template language code (e.g. en, en_US, hi)"],
    ["payment_reminder_enabled", "Send payment reminders automatically", "bool"], ["payment_reminder_after_days", "First payment reminder (days after the invoice)", "number"],
    ["payment_reminder_every_days", "Repeat payment reminder every (days)", "number"], ["payment_reminder_max", "Automatic payment reminders per invoice", "number"],
    ["service_reminder_enabled", "Send service-due reminders automatically", "bool"], ["service_reminder_days_before", "Service reminder (days before the due date)", "number"],
    ["service_interval_days", "Service interval (days after the last visit)", "number"],
  ] },
];

function simulatedNames(p: SettingsData["providers"]): string {
  const names = [p.email.simulated && "Email", p.sms.simulated && "SMS", p.whatsapp.simulated && "WhatsApp"].filter(Boolean) as string[];
  const list = names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names.at(-1)}` : names[0];
  return `${list} ${names.length > 1 ? "are" : "is"}`;
}

export function Settings() {
  const toast = useToast();
  const queryClient = useQueryClient();
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsData>("/settings") });
  const [values, setValues] = useState<Record<string, string | number | boolean>>({});
  useEffect(() => { if (q.data) setValues(q.data.values); }, [q.data]);
  const changed = q.data ? Object.keys(values).filter((k) => values[k] !== q.data!.values[k]) : [];
  const save = useMutation({
    mutationFn: () => put<SettingsData>("/settings", Object.fromEntries(changed.map((k) => [k, typeof q.data!.values[k] === "number" ? Number(values[k]) : values[k]]))),
    onSuccess: (data) => { queryClient.setQueryData(["settings"], data); void queryClient.invalidateQueries({ queryKey: ["centre"] }); toast.success("Settings saved"); },
    onError: (e) => toast.error(e),
  });
  if (q.isLoading) return <Spinner />;
  if (q.error || !q.data) return <ErrorState error={q.error} onRetry={() => void q.refetch()} />;
  const p = q.data.providers;
  const yesNo = (ok: boolean) => <span className={ok ? "font-medium text-emerald-700" : "font-medium text-amber-700"}>{ok ? "configured" : "not set"}</span>;
  return (
    <>
      <PageHeader title="Settings" subtitle="Service-centre details, numbering, tax display and communication settings."
        actions={<Button disabled={changed.length === 0} loading={save.isPending} onClick={() => save.mutate()}>Save changes{changed.length ? ` (${changed.length})` : ""}</Button>} />
      <div className="space-y-4">
        {(p.email.simulated || p.sms.simulated || p.whatsapp.simulated) && (
          <Alert tone="warn">
            {simulatedNames(p)} using the <strong>development simulator</strong>: invoice messages are written to the server's dev outbox and are <strong>not sent to customers</strong>. Production refuses to start in this state.
          </Alert>
        )}
        <Card title="Communication providers (read-only - set through server environment)">
          <div className="grid gap-4 text-sm sm:grid-cols-2">
            <dl className="space-y-1">
              <dt className="font-semibold text-slate-800">Email</dt>
              <dd>Provider: <strong>{p.email.provider}</strong>{p.email.simulated && " (simulator)"}</dd>
              <dd>SMTP endpoint: {p.email.smtp_host ? `${p.email.smtp_host}:${p.email.smtp_port} (${p.email.smtp_security})` : "not set"}</dd>
              <dd>Sender address: {p.email.sender_address || "not set"}</dd>
              <dd>SMTP username: {yesNo(p.email.smtp_username_configured)} · password: {yesNo(p.email.smtp_password_configured)}</dd>
            </dl>
            <dl className="space-y-1">
              <dt className="font-semibold text-slate-800">SMS</dt>
              <dd>Provider: <strong>{p.sms.provider}</strong>{p.sms.simulated && " (simulator)"}</dd>
              <dd>Provider auth key: {yesNo(p.sms.auth_key_configured)}</dd>
              <dd>Delivery-receipt webhook secret: {yesNo(p.webhook_secret_configured)}</dd>
              <dd>Environment: {p.environment} · default public URL: {p.public_base_url_env}</dd>
            </dl>
            <dl className="space-y-1">
              <dt className="font-semibold text-slate-800">WhatsApp</dt>
              <dd>Provider: <strong>{p.whatsapp.provider}</strong>{p.whatsapp.simulated && " (simulator)"}</dd>
              <dd>Access token: {yesNo(p.whatsapp.access_token_configured)} · phone number ID: {yesNo(p.whatsapp.phone_number_id_configured)}</dd>
              <dd>Status webhook app secret: {yesNo(p.whatsapp.app_secret_configured)} · verify token: {yesNo(p.whatsapp.verify_token_configured)}</dd>
            </dl>
          </div>
          <p className="mt-3 text-xs text-slate-500">Passwords, API keys and secrets are never shown here or returned by the API.</p>
        </Card>
        {SETTING_GROUPS.map((group) => (
          <Card key={group.title} title={group.title}>
            {group.hint && <p className="mb-3 text-sm text-slate-600">{group.hint}</p>}
            <div className="grid gap-3 sm:grid-cols-2">
              {group.fields.map(([key, text, type = "text"]) => type === "bool" ? (
                <label key={key} className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" checked={!!values[key]} onChange={(e) => setValues({ ...values, [key]: e.target.checked })} />{text}</label>
              ) : (
                <Field key={key} label={text} className={type === "textarea" ? "sm:col-span-2" : undefined}>
                  {(id) => type === "textarea"
                    ? <textarea id={id} rows={2} className="input" value={String(values[key] ?? "")} onChange={(e) => setValues({ ...values, [key]: e.target.value })} />
                    : <input id={id} className="input" inputMode={type === "number" ? "numeric" : undefined} value={String(values[key] ?? "")} onChange={(e) => setValues({ ...values, [key]: type === "number" ? (e.target.value === "" ? "" : Number(e.target.value)) : e.target.value })} />}
                </Field>
              ))}
            </div>
          </Card>
        ))}
      </div>
    </>
  );
}

// --- Audit log --------------------------------------------------------------------------

const A_KEYS = ["q", "action", "entity_type", "date_from", "date_to"] as const;

export function AuditLog() {
  const { values, page, set } = useListParams(A_KEYS);
  const [detail, setDetail] = useState<AuditEntry | null>(null);
  const q = useQuery({
    queryKey: ["audit", values, page],
    queryFn: () => get<Page<AuditEntry>>("/audit-logs", { ...values, date_to: values.date_to ? `${values.date_to}T23:59:59` : "", page, page_size: 50 }),
    placeholderData: keepPreviousData,
  });
  const columns = useMemo<ColumnDef<AuditEntry>[]>(() => [
    { accessorKey: "created_at", header: "When", cell: ({ row }) => fmtDateTime(row.original.created_at) },
    { accessorKey: "actor_email", header: "User", cell: ({ row }) => <>{row.original.actor_email}<br /><span className="text-xs text-slate-500">{ROLE_LABEL[row.original.actor_role] ?? label(row.original.actor_role)}</span></> },
    { accessorKey: "action", header: "Action", cell: ({ row }) => <code className="text-xs">{row.original.action}</code> },
    { accessorKey: "summary", header: "Summary", enableSorting: false },
    { id: "entity", header: "Record", enableSorting: false, cell: ({ row }) => <span className="text-xs text-slate-600">{row.original.entity_type}{row.original.entity_id ? ` #${row.original.entity_id}` : ""}</span> },
  ], []);
  return (
    <>
      <PageHeader title="Audit Log" subtitle="Append-only record of sign-ins, configuration changes, approvals, stock adjustments, invoices and payments." />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Search">{(id) => <input id={id} type="search" className="input" defaultValue={values.q} onKeyDown={(e) => e.key === "Enter" && set({ q: e.currentTarget.value })} placeholder="Summary or user, then Enter" />}</Field>
          <Field label="Action contains">{(id) => <input id={id} className="input" defaultValue={values.action} onKeyDown={(e) => e.key === "Enter" && set({ action: e.currentTarget.value })} placeholder="e.g. invoice, payment" />}</Field>
          <Field label="Record type">
            {(id) => <select id={id} className="input" value={values.entity_type} onChange={(e) => set({ entity_type: e.target.value })}><option value="">All</option>{["user", "service_job", "estimate", "invoice", "payment", "part", "purchase_request", "parts_request_line", "customer", "vehicle", "settings", "report"].map((t) => <option key={t} value={t}>{label(t)}</option>)}</select>}
          </Field>
          <Field label="From">{(id) => <input id={id} type="date" className="input" value={values.date_from} onChange={(e) => set({ date_from: e.target.value })} />}</Field>
          <Field label="To">{(id) => <input id={id} type="date" className="input" value={values.date_to} onChange={(e) => set({ date_to: e.target.value })} />}</Field>
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No audit entries match these filters"
          onRowClick={setDetail} pagination={{ page, pageSize: 50, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
      <Modal open={!!detail} title={detail?.action ?? ""} onClose={() => setDetail(null)} footer={<Button variant="secondary" onClick={() => setDetail(null)}>Close</Button>}>
        {detail && (
          <div className="space-y-2 text-sm">
            <p>{detail.summary}</p>
            <p className="text-xs text-slate-500">{detail.actor_email} · {fmtDateTime(detail.created_at)} · {detail.entity_type}{detail.entity_id ? ` #${detail.entity_id}` : ""}</p>
            {detail.details && <pre className="overflow-x-auto rounded-xl bg-slate-500/[0.06] p-3 text-xs">{JSON.stringify(detail.details, null, 2)}</pre>}
          </div>
        )}
      </Modal>
    </>
  );
}
