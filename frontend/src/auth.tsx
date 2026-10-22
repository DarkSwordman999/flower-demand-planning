import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorizedHandler } from "./api";

export interface User {
  id: number;
  login: string;
  full_name: string;
  role: string;
  role_name: string;
  location_id: number | null;
}

interface AuthState {
  user: User | null;
  ready: boolean;
  login: (login: string, password: string) => Promise<void>;
  logout: () => void;
  can: (...roles: string[]) => boolean;
}

const Ctx = createContext<AuthState>(null as unknown as AuthState);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(logout);
    if (!getToken()) {
      setReady(true);
      return;
    }
    api
      .get<User>("/api/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, [logout]);

  const login = async (login: string, password: string) => {
    const form = new URLSearchParams({ username: login, password });
    const r = await api.post<{ access_token: string; user: User }>("/api/auth/token", form);
    setToken(r.access_token);
    setUser(r.user);
  };

  const can = (...roles: string[]) => !!user && (user.role === "admin" || roles.length === 0 || roles.includes(user.role));

  return <Ctx.Provider value={{ user, ready, login, logout, can }}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
