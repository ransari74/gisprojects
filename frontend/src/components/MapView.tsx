import maplibregl, { type Map as MlMap, type MapGeoJSONFeature } from 'maplibre-gl';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import { API_BASE, ensureAccessToken, tileUrlTemplate } from '@/api/client';
import type { LayerInfo, StudyArea, TerrainTileConfig } from '@/api/types';
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
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [ready, setReady] = useState(false);
  const [mode, setMode] = useState<Mode>(currentMode);
  // Set when the third-party DEM cannot be reached and we drop back to 2D.
  const [terrainFailed, setTerrainFailed] = useState(false);

  // Layer ids we own, so a re-render removes exactly what it added.
  const ownedRef = useRef<{ sources: Set<string>; layers: Set<string> }>({
    sources: new Set(),
    layers: new Set(),
  });

  const chrome = CHROME[mode];

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
    map.addControl(
      new maplibregl.AttributionControl({ compact: true, customAttribution: BASEMAP_ATTRIBUTION }),
      'bottom-right',
    );

    map.on('load', () => {
      addBasemap(map, mode);
      setReady(true);
    });

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
  const layerSignature = useMemo(
    () =>
      JSON.stringify(
        layers.map((l) => [l.info.name, l.visible, l.filters, l.colorBy, l.opacity]),
      ),
    [layers],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !ready) return;

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
  }, [ready, layerSignature, mode, layers]);

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
      {terrainFailed && (
        <div className="map-notice" role="status" style={{ background: chrome.surface, borderColor: chrome.border }}>
          <strong style={{ color: chrome.textPrimary }}>3D terrain unavailable</strong>
          <span style={{ color: chrome.textSecondary }}>
            The elevation tiles could not be reached, so the map is showing the building model on a
            flat surface. Everything else is unaffected.
          </span>
        </div>
      )}
    </>
  );
}

const BASEMAP_ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

function addBasemap(map: MlMap, mode: Mode) {
  map.addSource('osm', {
    type: 'raster',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    tileSize: 256,
    maxzoom: 19,
    attribution: BASEMAP_ATTRIBUTION,
  });
  map.addLayer({
    id: 'basemap-background',
    type: 'background',
    paint: { 'background-color': mode === 'dark' ? '#12161c' : '#eef1f4' },
  });
  map.addLayer({
    id: 'basemap',
    type: 'raster',
    source: 'osm',
    paint: {
      // The basemap is context, not content: desaturated and dimmed so the
      // project's own data carries the colour.
      'raster-opacity': mode === 'dark' ? 0.35 : 0.55,
      'raster-saturation': -0.7,
      'raster-contrast': mode === 'dark' ? -0.2 : 0,
    },
  });
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
