import { useQuery } from "@tanstack/react-query";
import { get } from "@/services/api";

/** Optional features switched on in the server configuration (e.g. SMS, WhatsApp). Defaults to "off" until loaded. */
export function useFeatures() {
  const q = useQuery({ queryKey: ["features"], queryFn: () => get<{ sms: boolean; whatsapp: boolean; parts_sheet: boolean }>("/features"), staleTime: 10 * 60_000 });
  return { sms: q.data?.sms ?? false, whatsapp: q.data?.whatsapp ?? false, partsSheet: q.data?.parts_sheet ?? false };
}
