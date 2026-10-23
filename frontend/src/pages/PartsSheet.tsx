import { useQuery } from "@tanstack/react-query";
import { ExternalLink, RefreshCw } from "lucide-react";
import { useState } from "react";
import { Alert, Button, EmptyState, PageHeader, Spinner } from "@/components/ui";
import { get } from "@/services/api";

/** The Google Sheet the parts catalogue is synced from, embedded so staff can edit it here. */
export default function PartsSheet() {
  const sheet = useQuery({ queryKey: ["parts-sheet"], queryFn: () => get<{ url: string; sync_seconds: number }>("/parts-sheet"), retry: false });
  const [reloads, setReloads] = useState(0);

  if (sheet.isLoading) return <Spinner />;
  if (!sheet.data) return <EmptyState title="No parts sheet is set up" hint="Set PARTS_SHEET_URL in the server configuration to the Google Sheet link." />;

  const { url, sync_seconds } = sheet.data;
  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Parts Sheet"
        subtitle={`Changes made here reach the Parts Catalogue within about ${Math.round(sync_seconds)} seconds.`}
        actions={<>
          <Button variant="secondary" onClick={() => setReloads((n) => n + 1)}><RefreshCw className="h-4 w-4" aria-hidden />Reload</Button>
          <a href={url} target="_blank" rel="noreferrer" tabIndex={-1}><Button><ExternalLink className="h-4 w-4" aria-hidden />Open in Google Sheets</Button></a>
        </>}
      />
      <div className="mb-3">
        <Alert tone="info">
          To edit, be signed in to Google with an account that can edit the sheet. If Google asks to allow cookies, click Allow.
          Stock of existing parts is not taken from the sheet; keep the header row unchanged.
        </Alert>
      </div>
      <iframe
        key={reloads}
        src={url}
        title="Parts sheet"
        className="min-h-[70vh] w-full flex-1 rounded-2xl border border-slate-900/10 bg-white"
        allow="clipboard-read; clipboard-write; storage-access"
      />
    </div>
  );
}
