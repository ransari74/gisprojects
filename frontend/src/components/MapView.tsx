import maplibregl, { type Map as MlMap, type MapGeoJSONFeature } from 'maplibre-gl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, ensureAccessToken, tileUrlTemplate } from '@/api/client';
import type { LayerInfo, StudyArea, TerrainTileConfig } from '@/api/types';
import { BasemapSwitcher } from './BasemapSwitcher';
import { useBasemaps, useOverlays } from '@/hooks/useApi';
import { useBasemapPreference } from '@/hooks/useBasemapPreference';
import { CHROME, currentMode, type Mode } from '@/styles/theme';
import { buildPaint } from './layerStyles';

import 'maplibre-gl/dist/maplibre-gl.css';

export interface ActiveLayer {
  info: LayerInfo;
  visible: boolean;
  /** `filter_x` / `min_x` / `max_x` params forwarded to the tile endpoint. */
  filters?: Record<string, string>;
  /** Overrides the styleHint's default colour column. */
  colorBy?: string;
  opacity?: number;
}

interface MapViewProps {
  layers: ActiveLayer[];
  studyArea: StudyArea | null;
  /** Enables 3D terrain + a pitched camera (the terrain project). */
  terrain?: TerrainTileConfig | null;
  terrainExaggeration?: number;
  pitch?: number;
  bearing?: number;
  onFeatureClick?: (feature: MapGeoJSONFeature | null) => void;
  className?: string;
  /**
   * Where to open the camera. Layers declare a minZoom, so a project whose
   * primary layer only appears at z14 (parcels, buildings) must not open
   * fitted to a 25 km study area -- it would render an empty map. Passing a
   * center/zoom here overrides the fit.
   */
  initialView?: { center?: [number, number]; zoom: number } | null;
  /**
   * Raster reference overlays to offer for this map (e.g. ESA WorldCover on
   * the agriculture project), drawn above the basemap and below the
   * project's own vector layers. Off by default; the user opts in per layer.
   */
  overlayIds?: string[];
}

/** A DEM tile covering the study area, used only to test reachability. */
const DEM_PROBE = { z: 8, x: 131, y: 84 };

const EMPTY_STYLE: maplibregl.StyleSpecification = {
  version: 8,
  sources: {},
  layers: [],
  glyphs: 'https://fonts.openmaptiles.org/{fontstack}/{range}.pbf',
};

export function MapView({
  layers,
  studyArea,
  terrain = null,
  terrainExaggeration = 1.5,
  pitch = 0,
  bearing = 0,
  onFeatureClick,
  className,
  initialView = null,
  overlayIds = [],
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<Mode>(currentMode);
  // Set when the third-party DEM cannot be reached and we drop back to 2D.
  const [terrainFailed, setTerrainFailed] = useState(false);
  // Set when the selected basemap's tiles repeatedly fail to load.
  const [basemapNotice, setBasemapNotice] = useState<string | null>(null);

  const { data: basemapList } = useBasemaps();
  const { data: overlayList } = useOverlays();
  const [basemapId, setBasemapId] = useBasemapPreference();

  const activeBasemap = useMemo(
    () => basemapList?.find((b) => b.id === basemapId) ?? basemapList?.[0] ?? null,
    [basemapList, basemapId],
  );
  const activeOverlays = useMemo(
    () => (overlayList ?? []).filter((o) => overlayIds.includes(o.id)),
    [overlayList, overlayIds],
  );
  const [overlayState, setOverlayState] = useState<Record<string, { visible: boolean; opacity: number }>>({});

  // Layer ids we own, so a re-render removes exactly what it added.
  const ownedRef = useRef<{ sources: Set<string>; layers: Set<string> }>({
    sources: new Set(),
    layers: new Set(),
  });
  // Basemap and overlay layers we own, tracked separately so switching one
  // never disturbs the other's bookkeeping.
  const basemapOwnedRef = useRef<{ sources: string[]; layers: string[] }>({ sources: [], layers: [] });
  const overlayOwnedRef = useRef<Map<string, { source: string; layer: string }>>(new Map());

  const chrome = CHROME[mode];

  /** Bottommost currently-tracked data layer -- everything else (basemap,
   * overlay) is inserted directly below it, so switching a basemap live never
   * covers the project's own vector layers. Undefined when no data layer is
   * on the map yet, in which case a new layer simply appends on top. */
  const firstDataLayerId = useCallback((): string | undefined => ownedRef.current.layers.values().next().value, []);

  // --- init -----------------------------------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: EMPTY_STYLE,
      center: studyArea?.center ?? [5.1214, 52.0907],
      zoom: studyArea?.zoom ?? 11,
      pitch,
      bearing,
      maxZoom: 19,
      attributionControl: false,
      // MapLibre issues tile requests itself, so the bearer token is attached
      // here rather than through a fetch wrapper. The token is read from the
      // in-memory cache each time, so a refresh is picked up automatically.
      transformRequest: (url, resourceType) => {
        if (resourceType === 'Tile' && url.includes(`${API_BASE}/tiles/`)) {
          const token = latestTokenRef.current;
          if (token) return { url, headers: { Authorization: `Bearer ${token}` } };
        }
        return { url };
      },
    });

    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'bottom-left');
    // No customAttribution here: each raster source below carries its own
    // `attribution`, and MapLibre's control aggregates whatever is currently
    // visible on its own -- so it updates correctly as the user switches
    // basemaps or toggles an overlay, with nothing to keep in sync by hand.
    map.addControl(new maplibregl.AttributionControl({ compact: true }), 'bottom-right');

    map.on('load', () => setReady(true));

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      setReady(false);
    };
    // Intentionally mount-once: subsequent prop changes are handled by the
    // effects below rather than by tearing the map down and rebuilding it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Keep a token handy for transformRequest, which cannot be async.
  const latestTokenRef = useRef<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const sync = async () => {
      const token = await ensureAccessToken();
      if (!cancelled) latestTokenRef.current = token;
    };
    void sync();
    // Refresh well inside the token lifetime so tiles never carry a stale one.
    const timer = window.setInterval(() => void sync(), 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  // --- theme ----------------------------------------------------------------
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setMode(currentMode());
    mq.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => {
      mq.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);

  // --- basemap ----------------------------------------------------------------
  // Re-synced whenever the chosen basemap or the theme changes. Layers are
  // inserted with beforeId = the bottommost data layer (or appended, if none
  // is on the map yet), so a live switch never covers the project's own data
  // -- see firstDataLayerId above.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready || !activeBasemap) return;

    for (const layerId of basemapOwnedRef.current.layers) {
      if (map.getLayer(layerId)) map.removeLayer(layerId);
    }
    for (const sourceId of basemapOwnedRef.current.sources) {
      if (map.getSource(sourceId)) map.removeSource(sourceId);
    }
    basemapOwnedRef.current = { sources: [], layers: [] };
    setBasemapNotice(null);

    if (!map.getLayer('basemap-background')) {
      map.addLayer(
        { id: 'basemap-background', type: 'background', paint: { 'background-color': chrome.page } },
        firstDataLayerId(),
      );
    } else {
      map.setPaintProperty('basemap-background', 'background-color', chrome.page);
    }

    const beforeId = firstDataLayerId();
    let errorCount = 0;

    activeBasemap.layers.forEach((layer, i) => {
      const sourceId = `basemap-${i}`;
      const layerId = `basemap-layer-${i}`;
      map.addSource(sourceId, {
        type: 'raster',
        tiles: layer.tiles,
        tileSize: layer.tileSize,
        maxzoom: layer.maxZoom,
        attribution: activeBasemap.attribution,
      });
      map.addLayer(
        {
          id: layerId,
          type: 'raster',
          source: sourceId,
          paint:
            // Roads basemaps are context, not content: desaturated and dimmed
            // so the project's own data carries the colour. Imagery is shown
            // at full strength -- seeing it is usually the point.
            activeBasemap.kind === 'roads'
              ? {
                  'raster-opacity': mode === 'dark' ? 0.35 : 0.55,
                  'raster-saturation': -0.7,
                  'raster-contrast': mode === 'dark' ? -0.2 : 0,
                }
              : { 'raster-opacity': 1 },
        },
        beforeId,
      );
      basemapOwnedRef.current.sources.push(sourceId);
      basemapOwnedRef.current.layers.push(layerId);
    });

    // A raster tile 404/CORS failure just leaves that one tile blank, unlike
    // the terrain DEM (which blanks the whole map) -- so there is no need to
    // probe first. A note after a real burst of failures is enough to tell
    // the user their choice did not load rather than leaving them guessing.
    const ownSources = new Set(basemapOwnedRef.current.sources);
    const onError = (event: { error?: Error; sourceId?: string }) => {
      if (!event.sourceId || !ownSources.has(event.sourceId)) return;
      errorCount += 1;
      if (errorCount === 6) {
        setBasemapNotice(
          `"${activeBasemap.name}" tiles are not loading. Try a different basemap from the switcher.`,
        );
      }
    };
    map.on('error', onError);
    return () => {
      map.off('error', onError);
    };
  }, [ready, activeBasemap, mode, chrome.page, firstDataLayerId]);

  // --- overlays -----------------------------------------------------------
  // Default each overlay to its server-provided opacity and off (opt-in);
  // only set once per overlay so a user toggling it doesn't get reset.
  useEffect(() => {
    if (!overlayList) return;
    setOverlayState((prev) => {
      const next = { ...prev };
      let changed = false;
      for (const overlay of overlayList) {
        if (!(overlay.id in next)) {
          next[overlay.id] = { visible: false, opacity: overlay.defaultOpacity };
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, [overlayList]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const wanted = new Set(
      activeOverlays.filter((o) => overlayState[o.id]?.visible).map((o) => o.id),
    );

    for (const [id, owned] of overlayOwnedRef.current) {
      if (!wanted.has(id)) {
        if (map.getLayer(owned.layer)) map.removeLayer(owned.layer);
        if (map.getSource(owned.source)) map.removeSource(owned.source);
        overlayOwnedRef.current.delete(id);
      }
    }

    for (const overlay of activeOverlays) {
      const state = overlayState[overlay.id];
      if (!state?.visible) continue;

      const sourceId = `overlay-${overlay.id}`;
      const layerId = `overlay-layer-${overlay.id}`;
      if (!overlayOwnedRef.current.has(overlay.id)) {
        // WMS raster source: MapLibre substitutes {bbox-epsg-3857} per tile
        // itself, so this needs no proxy -- the overlay's WMS server is
        // queried directly, the same as any other raster tile source.
        map.addSource(sourceId, {
          type: 'raster',
          tiles: overlay.tiles,
          tileSize: overlay.tileSize,
          maxzoom: overlay.maxZoom,
          attribution: overlay.attribution,
        });
        map.addLayer(
          {
            id: layerId,
            type: 'raster',
            source: sourceId,
            paint: { 'raster-opacity': state.opacity },
          },
          firstDataLayerId(),
        );
        overlayOwnedRef.current.set(overlay.id, { source: sourceId, layer: layerId });
      } else if (map.getLayer(layerId)) {
        map.setPaintProperty(layerId, 'raster-opacity', state.opacity);
      }
    }
  }, [ready, activeOverlays, overlayState, firstDataLayerId]);

  // --- fit to study area ----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    if (initialView) {
      map.jumpTo({
        center: initialView.center ?? studyArea?.center ?? [5.1214, 52.0907],
        zoom: initialView.zoom,
      });
      return;
    }
    if (studyArea) map.fitBounds(studyArea.bbox, { padding: 40, duration: 600, maxZoom: 14 });
  }, [ready, studyArea, initialView]);

  // --- camera ---------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.easeTo({ pitch, bearing, duration: 700 });
  }, [ready, pitch, bearing]);

  // --- 3D terrain -----------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

    const TERRAIN_SOURCE = 'terrain-dem';
    if (!terrain) {
      if (map.getTerrain()) map.setTerrain(null);
      if (map.getSource(TERRAIN_SOURCE)) {
        try {
          map.removeSource(TERRAIN_SOURCE);
        } catch {
          /* still referenced during a style change; harmless */
        }
      }
      return;
    }

    // Probe the DEM before switching terrain on.
    //
    // MapLibre renders a terrain-enabled map through the DEM's depth buffer.
    // If those tiles never arrive -- third-party host down, blocked by a proxy,
    // offline -- it has no mesh to draw against and paints nothing at all: the
    // buildings vanish along with the terrain. Reacting to the error event is
    // not enough, because the failure surfaces as a fetch rejection inside the
    // worker rather than a map error with a sourceId. Checking first makes the
    // outcome deterministic: terrain is only enabled once we know it can load.
    let cancelled = false;
    const probeUrl = terrain.source.tiles[0]
      .replace('{z}', String(DEM_PROBE.z))
      .replace('{x}', String(DEM_PROBE.x))
      .replace('{y}', String(DEM_PROBE.y));

    const enableTerrain = async () => {
      let reachable = false;
      try {
        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 6000);
        const resp = await fetch(probeUrl, { signal: controller.signal, mode: 'cors' });
        window.clearTimeout(timer);
        reachable = resp.ok;
      } catch {
        reachable = false;
      }
      if (cancelled || !mapRef.current) return;

      if (!reachable) {
        setTerrainFailed(true);
        return;
      }

      if (!map.getSource(TERRAIN_SOURCE)) {
        map.addSource(TERRAIN_SOURCE, {
          type: 'raster-dem',
          tiles: terrain.source.tiles,
          encoding: terrain.source.encoding,
          tileSize: terrain.source.tileSize,
          maxzoom: terrain.source.maxzoom,
          attribution: terrain.source.attribution,
        });
      }
      map.setTerrain({ source: TERRAIN_SOURCE, exaggeration: terrainExaggeration });
      setTerrainFailed(false);
    };

    void enableTerrain();
    return () => {
      cancelled = true;
    };
  }, [ready, terrain, terrainExaggeration]);

  // --- data layers ----------------------------------------------------------
  // Content-based, not reference-based: `layers` is rebuilt by ProjectShell's
  // useMemo on every render where any prop -- including ones this map does not
  // care about -- produces a new array reference. Depending on that reference
  // directly would re-run this effect (and, worse, call setTiles() on a vector
  // source that may still be mid-initialisation from a PREVIOUS redundant run,
  // which is what was surfacing as a MapLibre AbortError). layerSignature is a
  // full serialisation of everything the effect below actually reads, so it is
  // the correct dependency; the array itself is read from a ref that is kept
  // current every render, without being a dependency.
  const layerSignature = useMemo(
    () =>
      JSON.stringify(
        layers.map((l) => [l.info.name, l.visible, l.filters, l.colorBy, l.opacity]),
      ),
    [layers],
  );
  const layersRef = useRef(layers);
  layersRef.current = layers;

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    const layers = layersRef.current;

    const owned = ownedRef.current;
    const wanted = new Set(layers.filter((l) => l.visible).map((l) => l.info.name));

    // Remove layers we own that are no longer wanted.
    for (const layerId of [...owned.layers]) {
      const sourceName = layerId.split('__')[0];
      if (!wanted.has(sourceName)) {
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        owned.layers.delete(layerId);
      }
    }
    for (const sourceId of [...owned.sources]) {
      if (!wanted.has(sourceId)) {
        if (map.getSource(sourceId)) map.removeSource(sourceId);
        owned.sources.delete(sourceId);
      }
    }

    // Draw order: polygons underneath, then lines, then points on top, so a
    // large fill never buries the network drawn over it.
    const drawOrder: Record<string, number> = { polygon: 0, line: 1, point: 2 };
    const ordered = layers
      .filter((l) => l.visible)
      .sort((a, b) => drawOrder[a.info.geomKind] - drawOrder[b.info.geomKind]);

    for (const active of ordered) {
      const { info } = active;
      const sourceId = info.name;
      const tiles = tileUrlTemplate(info.name, active.filters);

      const existing = map.getSource(sourceId) as maplibregl.VectorTileSource | undefined;
      if (existing) {
        // Changing filters changes the tile URL; setTiles re-fetches without
        // tearing down the layers stacked on this source.
        if (existing.tiles?.[0] !== tiles) existing.setTiles([tiles]);
      } else {
        map.addSource(sourceId, {
          type: 'vector',
          tiles: [tiles],
          minzoom: info.minZoom,
          maxzoom: Math.min(info.maxZoom, 16),
        });
        owned.sources.add(sourceId);
      }

      for (const spec of buildPaint(info, mode, active.colorBy, active.opacity)) {
        const layerId = `${info.name}__${spec.suffix}`;
        if (map.getLayer(layerId)) map.removeLayer(layerId);
        map.addLayer({
          id: layerId,
          type: spec.type,
          source: sourceId,
          'source-layer': info.name,
          minzoom: info.minZoom,
          paint: spec.paint as never,
          ...(spec.layout ? { layout: spec.layout as never } : {}),
        } as never);
        owned.layers.add(layerId);
      }
    }
  }, [ready, layerSignature, mode]);

  // --- click popups ---------------------------------------------------------
  const handleClick = useCallback(
    (event: maplibregl.MapMouseEvent) => {
      const map = mapRef.current;
      if (!map) return;
      const ids = [...ownedRef.current.layers].filter((id) => map.getLayer(id));
      const hits = ids.length ? map.queryRenderedFeatures(event.point, { layers: ids }) : [];
      const feature = hits[0] ?? null;

      popupRef.current?.remove();
      if (feature) {
        popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '320px' })
          .setLngLat(event.lngLat)
          .setHTML(renderPopup(feature, chrome))
          .addTo(map);
      }
      onFeatureClick?.(feature);
    },
    [onFeatureClick, chrome],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;
    map.on('click', handleClick);
    const onEnter = () => {
      map.getCanvas().style.cursor = 'pointer';
    };
    const onLeave = () => {
      map.getCanvas().style.cursor = '';
    };
    map.on('mouseenter', onEnter);
    map.on('mouseleave', onLeave);
    return () => {
      map.off('click', handleClick);
      map.off('mouseenter', onEnter);
      map.off('mouseleave', onLeave);
    };
  }, [ready, handleClick]);

  return (
    <>
      <div ref={containerRef} className={className ?? 'map-canvas'} />

      {basemapList && (
        <BasemapSwitcher
          basemaps={basemapList}
          activeId={activeBasemap?.id ?? basemapId}
          onChange={setBasemapId}
          overlays={activeOverlays}
          overlayState={overlayState}
          onOverlayChange={(id, patch) =>
            setOverlayState((prev) => ({ ...prev, [id]: { ...prev[id], ...patch } }))
          }
        />
      )}

      {terrainFailed && (
        <div className="map-notice" role="status" style={{ background: chrome.surface, borderColor: chrome.border }}>
          <strong style={{ color: chrome.textPrimary }}>3D terrain unavailable</strong>
          <span style={{ color: chrome.textSecondary }}>
            The elevation tiles could not be reached, so the map is showing the building model on a
            flat surface. Everything else is unaffected.
          </span>
        </div>
      )}
      {basemapNotice && (
        <div className="map-notice" role="status" style={{ background: chrome.surface, borderColor: chrome.border }}>
          <strong style={{ color: chrome.textPrimary }}>Basemap unavailable</strong>
          <span style={{ color: chrome.textSecondary }}>{basemapNotice}</span>
        </div>
      )}
    </>
  );
}

const HIDDEN_PROPS = new Set(['geom', 'osm_id']);

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value.toLocaleString() : value.toLocaleString(undefined, {
      maximumFractionDigits: 3,
    });
  }
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value);
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
}

function renderPopup(feature: MapGeoJSONFeature, chrome: Record<string, string>): string {
  const entries = Object.entries(feature.properties ?? {})
    .filter(([k, v]) => !HIDDEN_PROPS.has(k) && v !== null && v !== '')
    .slice(0, 14);

  const rows = entries
    .map(
      ([key, value]) =>
        `<tr><th style="text-align:left;font-weight:500;color:${chrome.textSecondary};padding:2px 10px 2px 0;white-space:nowrap">${escapeHtml(
          key.replace(/_/g, ' '),
        )}</th><td style="text-align:right;color:${chrome.textPrimary};font-variant-numeric:tabular-nums">${escapeHtml(
          formatValue(value),
        )}</td></tr>`,
    )
    .join('');

  const title = feature.sourceLayer?.replace(/_/g, ' ') ?? 'Feature';
  return `<div style="font:13px/1.45 system-ui,-apple-system,'Segoe UI',sans-serif;color:${chrome.textPrimary}">
      <div style="font-weight:600;margin-bottom:6px;text-transform:capitalize">${escapeHtml(title)}</div>
      <table style="border-collapse:collapse;width:100%">${rows}</table>
    </div>`;
}
