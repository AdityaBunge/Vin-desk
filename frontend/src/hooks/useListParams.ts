import { useCallback, useMemo } from "react";
import { useSearchParams } from "react-router-dom";

/** List filters kept in the URL, so filtered views can be linked, bookmarked and survive reloads. */
export function useListParams<K extends string>(keys: readonly K[]) {
  const [params, setParams] = useSearchParams();
  const values = useMemo(() => {
    const out = {} as Record<K, string>;
    for (const key of keys) out[key] = params.get(key) ?? "";
    return out;
  }, [params, keys]);
  const page = Math.max(1, Number(params.get("page")) || 1);

  const set = useCallback((patch: Partial<Record<K | "page", string | number>>) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (!("page" in patch)) next.delete("page"); // any filter change returns to the first page
      for (const [key, value] of Object.entries(patch)) {
        if (value === "" || value === undefined || value === null || (key === "page" && Number(value) <= 1)) next.delete(key);
        else next.set(key, String(value));
      }
      return next;
    }, { replace: true });
  }, [setParams]);

  return { values, page, set };
}
