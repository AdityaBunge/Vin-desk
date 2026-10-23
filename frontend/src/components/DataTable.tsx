import {
  type ColumnDef,
  type SortingState,
  type Table,
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ChevronLeft, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useIsCompact } from "@/hooks/useMediaQuery";
import { Button, EmptyState, ErrorState, Spinner, cx } from "./ui";

interface Props<T> {
  columns: ColumnDef<T, any>[]; // eslint-disable-line @typescript-eslint/no-explicit-any
  data: T[] | undefined;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  emptyTitle?: string;
  emptyHint?: string;
  /** Server-side pagination. Sorting is applied to the rows of the current page. */
  pagination?: { page: number; pageSize: number; total: number; onPage: (page: number) => void };
  /** Server-side sorting: when given, header clicks call this instead of sorting locally. */
  serverSort?: { sort: string; order: "asc" | "desc"; onChange: (sort: string, order: "asc" | "desc") => void };
  onRowClick?: (row: T) => void;
}

/** Phones: each row becomes a card. The first column is the card title, the rest are labelled pairs. */
function CardList<T>({ table, loading, onRowClick }: { table: Table<T>; loading?: boolean; onRowClick?: (row: T) => void }) {
  const headers = Object.fromEntries(table.getFlatHeaders().map((h) => [h.column.id, h]));
  return (
    <ul className={cx("space-y-2", loading && "opacity-60")}>
      {table.getRowModel().rows.map((row) => {
        const [first, ...rest] = row.getVisibleCells();
        const clickable = !!onRowClick;
        return (
          <li key={row.id}>
            <div role={clickable ? "button" : undefined} tabIndex={clickable ? 0 : undefined}
              onClick={clickable ? () => onRowClick(row.original) : undefined}
              onKeyDown={clickable ? (e) => { if (e.key === "Enter" && e.target === e.currentTarget) onRowClick(row.original); } : undefined}
              className={cx("rounded-xl border border-slate-900/[0.06] bg-white/55 p-3.5 text-sm",
                clickable && "cursor-pointer transition-colors hover:bg-white/85 active:bg-white")}>
              {first && <div className="font-medium text-slate-900">{flexRender(first.column.columnDef.cell, first.getContext())}</div>}
              {rest.length > 0 && (
                <dl className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-2.5">
                  {rest.map((cell) => {
                    const header = headers[cell.column.id];
                    const heading = header && !header.isPlaceholder ? flexRender(cell.column.columnDef.header, header.getContext()) : null;
                    const hasHeading = typeof cell.column.columnDef.header === "string" ? cell.column.columnDef.header.trim() !== "" : !!cell.column.columnDef.header;
                    return (
                      <div key={cell.id} className={cx("min-w-0", !hasHeading && "col-span-2")}>
                        {hasHeading && <dt className="text-[11px] font-medium tracking-wide text-slate-500 uppercase">{heading}</dt>}
                        <dd className="mt-0.5 break-words text-slate-800">{flexRender(cell.column.columnDef.cell, cell.getContext())}</dd>
                      </div>
                    );
                  })}
                </dl>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function DataTable<T>({ columns, data, loading, error, onRetry, emptyTitle = "Nothing to show", emptyHint, pagination, serverSort, onRowClick }: Props<T>) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const compact = useIsCompact();
  const table = useReactTable({
    data: data ?? [],
    columns,
    state: { sorting: serverSort ? [{ id: serverSort.sort, desc: serverSort.order === "desc" }] : sorting },
    manualSorting: !!serverSort,
    onSortingChange: (updater) => {
      const current = serverSort ? [{ id: serverSort.sort, desc: serverSort.order === "desc" }] : sorting;
      const next = typeof updater === "function" ? updater(current) : updater;
      if (serverSort) {
        const first = next[0] ?? { id: serverSort.sort, desc: serverSort.order !== "desc" };
        serverSort.onChange(first.id, first.desc ? "desc" : "asc");
      } else setSorting(next);
    },
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  if (error) return <ErrorState error={error} onRetry={onRetry} />;
  if (loading && !data) return <Spinner />;
  if (!data?.length) return <EmptyState title={emptyTitle} hint={emptyHint} />;

  const pages = pagination ? Math.max(1, Math.ceil(pagination.total / pagination.pageSize)) : 1;
  return (
    <div>
      {compact ? <CardList table={table} loading={loading} onRowClick={onRowClick} /> : (
        <div className="-mx-4 overflow-x-auto sm:-mx-5">
          <table className="min-w-full">
            <thead>
              {table.getHeaderGroups().map((group) => (
                <tr key={group.id} className="border-b border-slate-900/[0.07]">
                  {group.headers.map((header) => {
                    const sortable = header.column.getCanSort();
                    const dir = header.column.getIsSorted();
                    return (
                      <th key={header.id} scope="col" className="th first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5" aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}>
                        {sortable ? (
                          <button type="button" className="inline-flex items-center gap-1 uppercase transition-colors hover:text-slate-800" onClick={header.column.getToggleSortingHandler()}>
                            {flexRender(header.column.columnDef.header, header.getContext())}
                            {dir === "asc" && <ArrowUp className="h-3 w-3" aria-hidden />}
                            {dir === "desc" && <ArrowDown className="h-3 w-3" aria-hidden />}
                          </button>
                        ) : (
                          flexRender(header.column.columnDef.header, header.getContext())
                        )}
                      </th>
                    );
                  })}
                </tr>
              ))}
            </thead>
            <tbody className={cx("divide-y divide-slate-900/[0.05]", loading && "opacity-60")}>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id} className={cx("transition-colors", onRowClick ? "cursor-pointer hover:bg-white/70" : "hover:bg-white/40")}
                  onClick={onRowClick ? () => onRowClick(row.original) : undefined}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id} className="td first:pl-4 last:pr-4 sm:first:pl-5 sm:last:pr-5">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {pagination && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-slate-900/[0.06] pt-3 text-sm text-slate-500">
          <span className="tabular-nums">
            {(pagination.page - 1) * pagination.pageSize + 1}-{Math.min(pagination.page * pagination.pageSize, pagination.total)} of {pagination.total}
          </span>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" disabled={pagination.page <= 1} onClick={() => pagination.onPage(pagination.page - 1)} aria-label="Previous page">
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="tabular-nums">Page {pagination.page} of {pages}</span>
            <Button variant="secondary" size="sm" disabled={pagination.page >= pages} onClick={() => pagination.onPage(pagination.page + 1)} aria-label="Next page">
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
