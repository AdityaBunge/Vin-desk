import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, EmptyState, ErrorState, PageHeader, Spinner, cx } from "@/components/ui";
import { useAuth } from "@/hooks/useAuth";
import { fmtDateTime } from "@/lib/format";
import { get, post } from "@/services/api";
import type { Notification, Page } from "@/types";

export default function Notifications() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { can } = useAuth();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const q = useQuery({
    queryKey: ["notifications", "list", unreadOnly, page],
    queryFn: () => get<Page<Notification>>("/notifications", { unread_only: unreadOnly, page, page_size: 20 }),
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["notifications"] });
  const markAll = useMutation({ mutationFn: () => post("/notifications/read-all"), onSuccess: refresh });
  const markOne = useMutation({ mutationFn: (id: number) => post(`/notifications/${id}/read`), onSuccess: refresh });

  /** Where a notification leads, limited to pages this role can open. */
  const target = (n: Notification): string | null => {
    if (!n.entity_id) return null;
    if (n.entity_type === "service_job" && can("job.read_all", "job.read_assigned")) return `/jobs/${n.entity_id}`;
    if (n.entity_type === "service_job" && can("inventory.read")) return "/parts-requests?open_only=true";
    if (n.entity_type === "parts_request" && can("inventory.read")) return "/parts-requests?open_only=true";
    if (n.entity_type === "purchase_request" && can("inventory.read")) return "/purchase-requests";
    if (n.entity_type === "invoice" && can("invoice.read")) return `/invoices/${n.entity_id}`;
    if (n.entity_type === "vehicle" && can("delivery.manage")) return "/deliveries?kind=SERVICE_REMINDER&status=FAILED";
    if (n.entity_type === "part" && can("parts.read")) return "/parts?low_stock=true";
    return null;
  };
  const open = (n: Notification) => {
    if (!n.is_read) markOne.mutate(n.id);
    const to = target(n);
    if (to) navigate(to);
  };
  const pages = Math.max(1, Math.ceil((q.data?.total ?? 0) / 20));
  return (
    <>
      <PageHeader title="Notifications" subtitle="Internal workshop notifications for your role."
        actions={<>
          <label className="flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1); }} />Unread only</label>
          <Button variant="secondary" loading={markAll.isPending} onClick={() => markAll.mutate()}>Mark all as read</Button>
        </>} />
      <Card>
        {q.isLoading ? <Spinner /> : q.error ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !q.data?.items.length ? <EmptyState title="No notifications" /> : (<>
          <ul className="divide-y divide-slate-900/[0.05]">
            {q.data.items.map((n) => (
              <li key={n.id}>
                <button type="button" onClick={() => open(n)} className={cx("flex w-full items-start gap-3 px-2 py-3 text-left hover:bg-white/60", !n.is_read && "bg-brand-500/[0.07]")}>
                  <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", n.is_read ? "bg-transparent" : "bg-brand-600")} aria-label={n.is_read ? "Read" : "Unread"} />
                  <span className="min-w-0 flex-1">
                    <span className={cx("block text-sm text-slate-900", !n.is_read && "font-semibold")}>{n.title}</span>
                    {n.message && <span className="block text-sm text-slate-600">{n.message}</span>}
                    <span className="block text-xs text-slate-400">{fmtDateTime(n.created_at)}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center justify-end gap-2 text-sm text-slate-600">
            <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
            Page {page} of {pages}
            <Button size="sm" variant="secondary" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
          </div>
        </>)}
      </Card>
    </>
  );
}
