import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { post, refreshSession, setAccessToken, setSessionLostHandler } from "@/services/api";
import type { Me, TokenResponse } from "@/types";

interface AuthState {
  user: Me | null;
  /** True until the initial silent session restore has finished. */
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  can: (...permissions: string[]) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const queryClient = useQueryClient();

  useEffect(() => {
    let active = true;
    refreshSession().then((session) => {
      if (!active) return;
      setUser(session?.user ?? null);
      setLoading(false);
    });
    setSessionLostHandler(() => {
      setAccessToken(null);
      setUser(null);
    });
    return () => {
      active = false;
      setSessionLostHandler(null);
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const session = await post<TokenResponse>("/auth/login", { email, password });
    setAccessToken(session.access_token);
    queryClient.clear();
    setUser(session.user);
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      await post("/auth/logout");
    } finally {
      setAccessToken(null);
      setUser(null);
      queryClient.clear(); // never show one user's cached data to the next
    }
  }, [queryClient]);

  const value = useMemo<AuthState>(() => ({
    user,
    loading,
    login,
    logout,
    // UI convenience only: every permission is enforced again by the API.
    can: (...permissions) => !!user && permissions.some((p) => user.permissions.includes(p)),
  }), [user, loading, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

/** Mechanics see work they have handed to the Service Manager as completed. */
const MECHANIC_DONE = ["READY_FOR_BILLING", "READY_FOR_DELIVERY", "COMPLETED"];
export function useViewStatus() {
  const { user } = useAuth();
  return (status: string) => (user?.role_code === "MECHANIC" && MECHANIC_DONE.includes(status) ? "COMPLETED" : status);
}
