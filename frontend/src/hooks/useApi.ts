/** Typed React Query hooks over the backend. */

import { useQuery, type UseQueryOptions } from '@tanstack/react-query';

import { apiGet } from '@/api/client';
import type {
  BasemapSpec,
  Capabilities,
  DatasetSource,
  OverlaySpec,
  ProjectSummary,
  StudyArea,
  TerrainTileConfig,
} from '@/api/types';

/** Reference data changes only when the ETL re-runs, so cache it hard. */
const STATIC = { staleTime: 30 * 60 * 1000, gcTime: 60 * 60 * 1000 };
/** Analytics are recomputed per request but are stable within a session. */
const ANALYTICS = { staleTime: 5 * 60 * 1000 };

export function useApiQuery<T>(
  key: readonly unknown[],
  path: string,
  options?: Partial<UseQueryOptions<T, Error, T, readonly unknown[]>>,
) {
  return useQuery<T, Error, T, readonly unknown[]>({
    queryKey: key,
    queryFn: () => apiGet<T>(path),
    ...ANALYTICS,
    ...options,
  });
}

export const useCapabilities = () =>
  useApiQuery<Capabilities>(['capabilities'], '/tiles/capabilities', STATIC);

export const useStudyArea = () =>
  useApiQuery<StudyArea>(['study-area'], '/meta/study-area', STATIC);

export const useProjectCatalogue = () =>
  useApiQuery<ProjectSummary[]>(['projects'], '/meta/projects', STATIC);

export const useDatasetSources = (project?: string) =>
  useApiQuery<DatasetSource[]>(
    ['sources', project ?? 'all'],
    project ? `/meta/sources?project=${project}` : '/meta/sources',
    STATIC,
  );

export const useTerrainConfig = (enabled = true) =>
  useApiQuery<TerrainTileConfig>(['terrain-config'], '/terrain/terrain-tiles', {
    ...STATIC,
    enabled,
  });

export const useBasemaps = () =>
  useApiQuery<BasemapSpec[]>(['basemaps'], '/meta/basemaps', STATIC);

export const useOverlays = () =>
  useApiQuery<OverlaySpec[]>(['overlays'], '/meta/overlays', STATIC);
