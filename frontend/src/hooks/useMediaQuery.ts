import { useEffect, useState } from "react";

/** True while the media query matches. Falls back to false where matchMedia is unavailable (tests, old browsers). */
export function useMediaQuery(query: string): boolean {
  const get = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia(query).matches;
  const [matches, setMatches] = useState(get);
  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const mql = window.matchMedia(query);
    const onChange = () => setMatches(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

/** Phones and small tablets in portrait: lists render as cards instead of wide tables. */
export const useIsCompact = () => useMediaQuery("(max-width: 767px)");
