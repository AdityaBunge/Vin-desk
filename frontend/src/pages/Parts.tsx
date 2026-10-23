import { zodResolver } from "@hookform/resolvers/zod";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Plus } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { DataTable } from "@/components/DataTable";
import { Alert, Button, Card, Field, Modal, PageHeader, StatusBadge, useToast } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { useListParams } from "@/hooks/useListParams";
import { fmtDateTime, label, qty, rupees } from "@/lib/format";
import { get, post, put } from "@/services/api";
import type { Category, Movement, Page, Part, Supplier, TaxRate, VehicleModel } from "@/types";
import { type PartValues, partSchema } from "@/validation/schemas";

function PartFormModal({ part, onClose }: { part: Part | null; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const categories = useQuery({ queryKey: ["part-categories"], queryFn: () => get<Category[]>("/part-categories") });
  const taxes = useQuery({ queryKey: ["tax-rates"], queryFn: () => get<TaxRate[]>("/tax-rates") });
  const suppliers = useQuery({ queryKey: ["suppliers"], queryFn: () => get<Supplier[]>("/suppliers") });
  const models = useQuery({ queryKey: ["vehicle-models"], queryFn: () => get<VehicleModel[]>("/vehicle-models") });
  const { register, handleSubmit, formState: { errors } } = useForm<PartValues>({
    resolver: zodResolver(partSchema),
    defaultValues: {
      sku: part?.sku ?? "", name: part?.name ?? "", description: part?.description ?? "", category_id: String(part?.category?.id ?? ""),
      purchase_cost: part?.purchase_cost ?? "0", selling_price: part?.selling_price ?? "", tax_rate_id: String(part?.tax_rate?.id ?? ""),
      reorder_threshold: part?.reorder_threshold ?? "0", supplier_id: String(part?.supplier?.id ?? ""), storage_location: part?.storage_location ?? "",
      hsn_code: part?.hsn_code ?? "", unit: part?.unit ?? "NO", is_active: part?.is_active ?? true, compatible_model_ids: part?.compatible_models.map((m) => String(m.id)) ?? [],
    },
  });
  const save = useMutation({
    mutationFn: (v: PartValues) => {
      const body = {
        ...v, category_id: v.category_id ? Number(v.category_id) : null, tax_rate_id: v.tax_rate_id ? Number(v.tax_rate_id) : null,
        supplier_id: v.supplier_id ? Number(v.supplier_id) : null, compatible_model_ids: v.compatible_model_ids.map(Number),
      };
      return part ? put(`/parts/${part.id}`, body) : post("/parts", body);
    },
    onSuccess: () => { void queryClient.invalidateQueries({ queryKey: ["parts"] }); toast.success(part ? "Part updated" : "Part created"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const options = (items: { id: number; name: string }[] | undefined, none: string) => (<>
    <option value="">{none}</option>
    {items?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}
  </>);
  return (
    <Modal open wide title={part ? `Edit ${part.sku}` : "New part"} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button type="submit" form="part-form" loading={save.isPending}>Save part</Button></>}>
      <form id="part-form" onSubmit={handleSubmit((v) => save.mutate(v))} noValidate className="grid gap-3 sm:grid-cols-2">
        <Field label="Part number (SKU)" required error={errors.sku?.message}>{(id) => <input id={id} className="input uppercase" {...register("sku")} />}</Field>
        <Field label="Part name" required error={errors.name?.message}>{(id) => <input id={id} className="input" {...register("name")} />}</Field>
        <Field label="Description" className="sm:col-span-2">{(id) => <textarea id={id} rows={2} className="input" {...register("description")} />}</Field>
        <Field label="Category">{(id) => <select id={id} className="input" {...register("category_id")}>{options(categories.data, "Uncategorised")}</select>}</Field>
        <Field label="Supplier">{(id) => <select id={id} className="input" {...register("supplier_id")}>{options(suppliers.data, "No supplier")}</select>}</Field>
        <Field label="Purchase cost (₹)" error={errors.purchase_cost?.message}>{(id) => <input id={id} className="input" inputMode="decimal" {...register("purchase_cost")} />}</Field>
        <Field label="Selling price (₹)" required error={errors.selling_price?.message}>{(id) => <input id={id} className="input" inputMode="decimal" {...register("selling_price")} />}</Field>
        <Field label="Tax rate">{(id) => <select id={id} className="input" {...register("tax_rate_id")}>{options(taxes.data, "No tax")}</select>}</Field>
        <Field label="Reorder threshold" error={errors.reorder_threshold?.message}>{(id) => <input id={id} className="input" inputMode="decimal" {...register("reorder_threshold")} />}</Field>
        <Field label="Storage location">{(id) => <input id={id} className="input" {...register("storage_location")} />}</Field>
        <Field label="HSN code" error={errors.hsn_code?.message} hint="Printed on the GST invoice, e.g. 27101980">{(id, d) => <input id={id} aria-describedby={d} className="input" inputMode="numeric" {...register("hsn_code")} />}</Field>
        <Field label="Unit on invoice" required error={errors.unit?.message} hint="The 'per' column: NO, Nos, SET, Ltr...">{(id, d) => <input id={id} aria-describedby={d} className="input" list="part-units" {...register("unit")} />}</Field>
        <datalist id="part-units">{["NO", "Nos", "SET", "PCS", "Ltr", "Kg", "Mtr"].map((u) => <option key={u} value={u} />)}</datalist>
        <label className="flex items-center gap-2 self-end pb-2 text-sm"><input type="checkbox" {...register("is_active")} />Active</label>
        <fieldset className="sm:col-span-2">
          <legend className="mb-1 text-sm font-medium text-slate-700">Compatible vehicle models</legend>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {models.data?.map((m) => <label key={m.id} className="flex items-center gap-2"><input type="checkbox" value={m.id} {...register("compatible_model_ids")} />{m.name}</label>)}
          </div>
        </fieldset>
      </form>
    </Modal>
  );
}

type StockAction = "receive" | "adjust" | "write-off";
function StockModal({ part, onClose }: { part: Part; onClose: () => void }) {
  const toast = useToast();
  const queryClient = useQueryClient();
  const [action, setAction] = useState<StockAction>("receive");
  const [quantity, setQuantity] = useState("");
  const [reason, setReason] = useState("");
  const history = useQuery({ queryKey: ["movements", "part", part.id], queryFn: () => get<Page<Movement>>("/inventory/movements", { part_id: part.id, page_size: 6 }) });
  const run = useMutation({
    mutationFn: () => post(`/parts/${part.id}/${action}`, action === "adjust" ? { delta: quantity, reason } : { quantity, reason }),
    onSuccess: () => { for (const k of ["parts", "movements", "dashboard"]) void queryClient.invalidateQueries({ queryKey: [k] }); toast.success("Stock updated"); onClose(); },
    onError: (e) => toast.error(e),
  });
  const n = Number(quantity);
  const valid = quantity !== "" && Number.isFinite(n) && (action === "adjust" ? n !== 0 : n > 0) && (action === "receive" || reason.trim().length >= 3);
  return (
    <Modal open title={`Stock - ${part.sku}`} onClose={onClose}
      footer={<><Button variant="secondary" onClick={onClose}>Cancel</Button><Button disabled={!valid} loading={run.isPending} onClick={() => run.mutate()}>Record</Button></>}>
      <div className="space-y-3">
        <Alert tone="info">{part.name}: {qty(part.stock.qty_on_hand)} on hand, {qty(part.stock.qty_reserved)} reserved, <strong>{qty(part.stock.qty_available)} available</strong></Alert>
        <Field label="Movement type">
          {(id) => (
            <select id={id} className="input" value={action} onChange={(e) => setAction(e.target.value as StockAction)}>
              <option value="receive">Stock received</option><option value="adjust">Stock adjustment (after count)</option><option value="write-off">Damaged / written off</option>
            </select>
          )}
        </Field>
        <Field label={action === "adjust" ? "Adjustment (+ or -)" : "Quantity"} required hint={action === "adjust" ? "Use a negative number to reduce stock" : undefined}>
          {(id, d) => <input id={id} aria-describedby={d} className="input w-40" inputMode="decimal" value={quantity} onChange={(e) => setQuantity(e.target.value)} />}
        </Field>
        <Field label="Reason / reference" required={action !== "receive"}>{(id) => <input id={id} className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder={action === "receive" ? "GRN or supplier invoice no." : ""} />}</Field>
        <div>
          <h3 className="mb-1 text-sm font-semibold text-slate-800">Recent movements</h3>
          <ul className="text-xs text-slate-600">
            {history.data?.items.map((m) => <li key={m.id}>{fmtDateTime(m.created_at)} · {label(m.movement_type)} {qty(m.quantity)} → {qty(m.on_hand_after)} on hand · {m.performed_by.full_name}</li>)}
            {history.data?.items.length === 0 && <li>No movements yet</li>}
          </ul>
        </div>
      </div>
    </Modal>
  );
}

const KEYS = ["q", "category_id", "model_id", "low_stock", "include_inactive"] as const;
const PAGE_SIZE = 20;

const text = (key: keyof Part, header: string): ColumnDef<Part> => ({
  id: key, header, accessorFn: (p) => p[key] ?? "", cell: ({ row }) => <span className="whitespace-nowrap">{String(row.original[key] ?? "") || "-"}</span>,
});
const number = (key: "sheet_closing_qty" | "sheet_closing_value" | "sheet_actual_qty", header: string, format: (v: string) => string): ColumnDef<Part> => ({
  id: key, header, accessorFn: (p) => (p[key] == null ? -Infinity : Number(p[key])),
  cell: ({ row }) => <span className="whitespace-nowrap tabular-nums">{row.original[key] == null ? "-" : format(row.original[key]!)}</span>,
});
/** The parts sheet's columns, in the sheet's order (Part Number and Description come first). */
const SHEET_COLUMNS: ColumnDef<Part>[] = [
  text("dms_bin", "BIN"), text("dms_category", "Category"), text("movement_class", "Movement"),
  text("abc_class", "ABC"), text("hml_class", "HML"), text("ris_class", "RIS"),
  number("sheet_closing_qty", "Closing Qty.", qty), number("sheet_closing_value", "Closing Value", rupees),
  text("storage_location", "BIN NUMBER"), number("sheet_actual_qty", "ACTUAL QUANTITY", qty),
];
/** Price and live stock, for roles that do not see the sheet's columns. */
const STOCK_COLUMNS = (modelCount: number | undefined): ColumnDef<Part>[] => [
  { id: "price", accessorFn: (p) => Number(p.selling_price), header: "Selling price", cell: ({ row }) => <span className="tabular-nums">{rupees(row.original.selling_price)}</span> },
  { id: "available", accessorFn: (p) => Number(p.stock.qty_available), header: "Available", cell: ({ row }) => {
    const p = row.original;
    return <span className="flex items-center gap-2 font-semibold tabular-nums">{qty(p.stock.qty_available)}{Number(p.stock.qty_available) <= 0 && <StatusBadge status="UNAVAILABLE" />}</span>;
  } },
  { id: "models", header: "Fits", enableSorting: false, cell: ({ row }) => <span className="text-xs text-slate-600">{row.original.compatible_models.length >= (modelCount ?? 99) ? "All models" : row.original.compatible_models.map((m) => m.name.replace("Force ", "")).join(", ") || "-"}</span> },
];

export default function Parts() {
  const { can } = useAuth();
  const { values, page, set } = useListParams(KEYS);
  const [search, setSearch] = useState(values.q);
  const [editing, setEditing] = useState<Part | "new" | null>(null);
  const [stocking, setStocking] = useState<Part | null>(null);
  useEffect(() => {
    const t = setTimeout(() => search !== values.q && set({ q: search }), 350);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps
  const q = useQuery({ queryKey: ["parts", "list", values, page], queryFn: () => get<Page<Part>>("/parts", { ...values, page, page_size: PAGE_SIZE }), placeholderData: keepPreviousData });
  const categories = useQuery({ queryKey: ["part-categories"], queryFn: () => get<Category[]>("/part-categories") });
  const models = useQuery({ queryKey: ["vehicle-models"], queryFn: () => get<VehicleModel[]>("/vehicle-models") });
  const manage = can("parts.manage");
  const adjust = can("inventory.adjust");

  const sheetColumns = can("parts.manage", "inventory.read");

  const columns = useMemo<ColumnDef<Part>[]>(() => [
    { accessorKey: "sku", header: "Part number", cell: ({ row }) => <span className="font-medium whitespace-nowrap">{row.original.sku}{!row.original.is_active && <span className="ml-2 text-xs text-slate-500">(inactive)</span>}</span> },
    { accessorKey: "name", header: "Part description", cell: ({ row }) => <span className="block min-w-48">{row.original.name}<br /><span className="text-xs text-slate-500">{row.original.category?.name ?? "Uncategorised"}{!sheetColumns && row.original.storage_location ? ` · bin ${row.original.storage_location}` : ""}</span></span> },
    ...(sheetColumns ? SHEET_COLUMNS : STOCK_COLUMNS(models.data?.length)),
    ...(manage || adjust ? [{ id: "cost", accessorFn: (p: Part) => Number(p.purchase_cost), header: "Cost", cell: ({ row }: { row: { original: Part } }) => <span className="tabular-nums">{rupees(row.original.purchase_cost)}</span> } as ColumnDef<Part>] : []),
    ...(manage || adjust ? [{ id: "actions", header: "", enableSorting: false, cell: ({ row }: { row: { original: Part } }) => (
      <span className="flex justify-end gap-2">
        {adjust && <Button size="sm" variant="secondary" onClick={() => setStocking(row.original)}>Stock</Button>}
        {manage && <Button size="sm" variant="ghost" onClick={() => setEditing(row.original)}>Edit</Button>}
      </span>
    ) } as ColumnDef<Part>] : []),
  ], [manage, adjust, sheetColumns, models.data]);

  return (
    <>
      <PageHeader title="Parts Catalogue"
        subtitle={sheetColumns
          ? "The parts sheet's columns, as last synced."
          : "Available quantity = on hand - reserved."}
        actions={manage && <Button onClick={() => setEditing("new")}><Plus className="h-4 w-4" />New part</Button>} />
      <Card>
        <div className="mb-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <Field label="Search" className="lg:col-span-2">{(id) => <input id={id} type="search" className="input" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Part number or name" />}</Field>
          <Field label="Category">
            {(id) => <select id={id} className="input" value={values.category_id} onChange={(e) => set({ category_id: e.target.value })}><option value="">All categories</option>{categories.data?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>}
          </Field>
          <Field label="Fits model">
            {(id) => <select id={id} className="input" value={values.model_id} onChange={(e) => set({ model_id: e.target.value })}><option value="">Any model</option>{models.data?.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}</select>}
          </Field>
          <div className="flex flex-col justify-end gap-1 pb-1 text-sm text-slate-700">
            <label className="flex items-center gap-2"><input type="checkbox" checked={values.low_stock === "true"} onChange={(e) => set({ low_stock: e.target.checked ? "true" : "" })} />Low stock only</label>
            {manage && <label className="flex items-center gap-2"><input type="checkbox" checked={values.include_inactive === "true"} onChange={(e) => set({ include_inactive: e.target.checked ? "true" : "" })} />Show inactive</label>}
          </div>
        </div>
        <DataTable columns={columns} data={q.data?.items} loading={q.isFetching} error={q.error} onRetry={() => void q.refetch()} emptyTitle="No parts match these filters"
          pagination={{ page, pageSize: PAGE_SIZE, total: q.data?.total ?? 0, onPage: (p) => set({ page: p }) }} />
      </Card>
      {editing && <PartFormModal part={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {stocking && <StockModal part={stocking} onClose={() => setStocking(null)} />}
    </>
  );
}
