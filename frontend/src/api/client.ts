/**
 * API client with automatic access-token refresh.
 *
 * The access token is short-lived and lives only in memory; the refresh token
 * is the one persisted. That means a stolen localStorage value still cannot be
 * used to call the API directly without going through /auth/refresh, which
 * rotates and burns the token it was given.
 */

import type { TokenResponse } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api';
const REFRESH_STORAGE_KEY = 'gisportfolio.refresh';

let accessToken: string | null = null;
let accessTokenExpiry = 0;
/** In-flight refresh, shared so concurrent 401s trigger exactly one call. */
let refreshInFlight: Promise<string | null> | null = null;

type Listener = () => void;
const listeners = new Set<Listener>();

function notify() {
  listeners.forEach((l) => l());
}

export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getAccessToken(): string | null {
  return accessToken;
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_STORAGE_KEY);
}

export function setTokens(tokens: TokenResponse | null) {
  if (tokens) {
    accessToken = tokens.access_token;
    // Refresh a minute early so a request never races the expiry.
    accessTokenExpiry = Date.now() + (tokens.expires_in - 60) * 1000;
    localStorage.setItem(REFRESH_STORAGE_KEY, tokens.refresh_token);
  } else {
    accessToken = null;
    accessTokenExpiry = 0;
    localStorage.removeItem(REFRESH_STORAGE_KEY);
  }
  notify();
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = getRefreshToken();
  if (!refresh) return null;

  // Collapse concurrent refreshes: the backend rotates refresh tokens, so two
  // parallel calls would burn each other's replacement and log the user out.
  if (refreshInFlight) return refreshInFlight;

  refreshInFlight = (async () => {
    try {
      const resp = await fetch(`${API_BASE}/auth/refresh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refresh }),
      });
      if (!resp.ok) {
        setTokens(null);
        return null;
      }
      const tokens = (await resp.json()) as TokenResponse;
      setTokens(tokens);
      return tokens.access_token;
    } catch {
      setTokens(null);
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();

  return refreshInFlight;
}

/** Returns a valid access token, refreshing proactively if it is about to expire. */
export async function ensureAccessToken(): Promise<string | null> {
  if (accessToken && Date.now() < accessTokenExpiry) return accessToken;
  return refreshAccessToken();
}

interface RequestOptions extends RequestInit {
  /** Set false for endpoints that must not trigger a refresh loop. */
  retryOnUnauthorized?: boolean;
}

export async function apiFetch(path: string, options: RequestOptions = {}): Promise<Response> {
  const { retryOnUnauthorized = true, ...init } = options;
  const token = await ensureAccessToken();

  const headers = new Headers(init.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const url = path.startsWith('http') ? path : `${API_BASE}${path}`;
  let resp = await fetch(url, { ...init, headers });

  if (resp.status === 401 && retryOnUnauthorized) {
    const fresh = await refreshAccessToken();
    if (fresh) {
      headers.set('Authorization', `Bearer ${fresh}`);
      resp = await fetch(url, { ...init, headers });
    }
  }
  return resp;
}

export async function apiGet<T>(path: string): Promise<T> {
  const resp = await apiFetch(path);
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, detail?.detail ?? resp.statusText, detail);
  }
  return (await resp.json()) as T;
}

export async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const resp = await apiFetch(path, { method: 'POST', body: JSON.stringify(body) });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, detail?.detail ?? resp.statusText, detail);
  }
  return (await resp.json()) as T;
}

export async function login(email: string, password: string): Promise<TokenResponse> {
  const resp = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) {
    const detail = await resp.json().catch(() => ({ detail: 'Login failed' }));
    throw new ApiError(resp.status, detail?.detail ?? 'Login failed', detail);
  }
  const tokens = (await resp.json()) as TokenResponse;
  setTokens(tokens);
  return tokens;
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken();
  if (refresh && accessToken) {
    await apiFetch('/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refresh }),
      retryOnUnauthorized: false,
    }).catch(() => undefined);
  }
  setTokens(null);
}

/** Absolute tile URL template for MapLibre, which needs a full URL. */
export function tileUrlTemplate(layerName: string, params?: Record<string, string>): string {
  const base = API_BASE.startsWith('http') ? API_BASE : `${window.location.origin}${API_BASE}`;
  const query = params && Object.keys(params).length ? `?${new URLSearchParams(params)}` : '';
  return `${base}/tiles/${layerName}/{z}/{x}/{y}.mvt${query}`;
}

export { API_BASE };
