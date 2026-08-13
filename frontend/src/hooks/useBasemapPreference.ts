/**
 * Persisted basemap choice, shared across every project page.
 *
 * It is one `useState` rather than a global store because exactly one
 * `MapView` is ever mounted at a time in this app -- there is nothing to keep
 * in sync between instances. localStorage is still the source of truth so the
 * choice survives navigation and reloads.
 */

import { useCallback, useState } from 'react';

const STORAGE_KEY = 'gisportfolio.basemap';
const DEFAULT_BASEMAP = 'osm';

export function useBasemapPreference(): [string, (id: string) => void] {
  const [id, setId] = useState<string>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? DEFAULT_BASEMAP;
    } catch {
      return DEFAULT_BASEMAP;
    }
  });

  const update = useCallback((next: string) => {
    setId(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* localStorage unavailable (private browsing, quota) -- the choice
       * still applies for this session via React state. */
    }
  }, []);

  return [id, update];
}
