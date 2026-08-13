import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import { apiGet, getRefreshToken, login as apiLogin, logout as apiLogout } from '@/api/client';
import type { Me, ProjectKey } from '@/api/types';

interface AuthState {
  user: Me | null;
  loading: boolean;
  error: string | null;
  signIn: (email: string, password: string) => Promise<void>;
  signOut: () => Promise<void>;
  /** True when the user holds the permission, or is a superuser. */
  can: (permission: string) => boolean;
  canOpen: (project: ProjectKey) => boolean;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadUser = useCallback(async () => {
    try {
      setUser(await apiGet<Me>('/auth/me'));
      setError(null);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // A stored refresh token means the session may still be resumable, so try
    // to restore it before rendering the login screen.
    if (getRefreshToken()) {
      void loadUser();
    } else {
      setLoading(false);
    }
  }, [loadUser]);

  const signIn = useCallback(
    async (email: string, password: string) => {
      setError(null);
      try {
        await apiLogin(email, password);
        await loadUser();
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Sign in failed';
        setError(message);
        throw err;
      }
    },
    [loadUser],
  );

  const signOut = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo<AuthState>(() => {
    const permissions = new Set(user?.permissions ?? []);
    const projects = new Set(user?.projects ?? []);
    return {
      user,
      loading,
      error,
      signIn,
      signOut,
      can: (permission) => Boolean(user?.is_superuser) || permissions.has(permission),
      canOpen: (project) => Boolean(user?.is_superuser) || projects.has(project),
    };
  }, [user, loading, error, signIn, signOut]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used inside an AuthProvider');
  return ctx;
}
