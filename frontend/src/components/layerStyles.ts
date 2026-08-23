/**
 * Translates a LayerSpec's styleHint into MapLibre paint properties.
 *
 * Kept apart from MapView so the styling rules -- which colour scale a layer
 * gets, how wide its lines are, how a building extrudes -- are readable on
 * their own and testable without a map instance.
 */

import type { LayerInfo } from '@/api/types';
import {
  CATEGORICAL,
  CHROME,
  DIVERGING,
  divergingExpression,
  DOMAINS,
  type DomainKey,
  matchExpression,
  type Mode,
  sequentialExpression,
} from '@/styles/theme';

export interface PaintSpec {
  suffix: string;
  type: 'fill' | 'line' | 'circle' | 'fill-extrusion';
  paint: Record<string, unknown>;
  layout?: Record<string, unknown>;
}

/** Which fixed domain a categorical column draws its colours from. */
const COLUMN_DOMAIN: Record<string, DomainKey> = {
  crop_type: 'cropType',
  soil_texture: 'soilTexture',
  canal_type: 'canalType',
  land_use: 'landUse',
  zone_category: 'zoneCategory',
  boundary_type: 'boundaryType',
  mode: 'travelMode',
  highway_class: 'highwayClass',
  building_type: 'buildingType',
  line_type: 'lineType',
  landcover_class: 'landcoverClass',
  landcover_prev: 'landcoverClass',
  from_class: 'landcoverClass',
  to_class: 'landcoverClass',
  change_type: 'changeType',
  water_type: 'waterType',
  platform: 'platform',
  risk_class: 'riskClass',
  soil_type: 'soilTexture',
};

/**
 * Signed columns that get the diverging ramp instead of the sequential one,
 * with the value that means "no change" at the neutral midpoint.
 */
const DIVERGING_RANGE: Record<string, [number, number, number]> = {
  // Negative is subsidence. Zero is stable ground, and it is a real boundary
  // rather than just the bottom of the scale.
  velocity_mm_yr: [-18, 4, 0],
  cumulative_mm: [-110, 24, 0],
  // Temperature relative to the study-area mean: the sign is the heat island.
  lst_anomaly_c: [-6, 6, 0],
  // How far an index moved between the two epochs.
  ndvi_delta: [-0.8, 0.8, 0],
};

/**
 * Per-layer overrides, for columns whose name is shared but whose value set is
 * not. `mode` means car/transit/bike/walk on a commute flow or an isochrone,
 * but bus/tram/metro/rail/ferry on a transit route or stop -- colouring both
 * from one domain mislabels the legend and mis-colours the map.
 */
const LAYER_COLUMN_DOMAIN: Record<string, DomainKey> = {
  'transport_transit_routes.mode': 'transitMode',
  'transport_stops.mode': 'transitMode',
};

function domainFor(layerName: string, column: string): DomainKey | undefined {
  return LAYER_COLUMN_DOMAIN[`${layerName}.${column}`] ?? COLUMN_DOMAIN[column];
}

/** Observed value ranges, used to anchor the sequential ramps. */
const NUMERIC_RANGE: Record<string, [number, number]> = {
  // Most fields are grassland or cereals; the sugarbeet tail would otherwise
  // push every other crop into the first ramp step.
  yield_t_ha: [0, 50],
  ndvi_mean: [0.1, 0.95],
  soil_ph: [4, 8.5],
  soil_organic_c: [10, 120],
  area_ha: [0, 12],
  value_per_m2: [200, 3200],
  assessed_value: [0, 5_000_000],
  lot_area_m2: [0, 8000],
  year_built: [1600, 2026],
  density_km2: [0, 9_000],
  population: [0, 25_000],
  median_income: [16_000, 82_000],
  deprivation_index: [0, 100],
  congestion_index: [0, 1],
  aadt: [0, 90_000],
  minutes: [5, 30],
  height_m: [3, 45],
  elevation_m: [-3, 50],
  band_min_m: [-10, 45],
  trips: [0, 4000],
  capacity_m3s: [0, 26],
  daily_boardings: [0, 12_000],
  population_reached: [0, 40_000],
  // Remote sensing. Spectral indices are bounded to their physically possible
  // range rather than the observed one, so the ramp means the same thing on
  // every scene instead of restretching itself when the data changes.
  ndvi: [-0.2, 0.95],
  ndwi: [-0.6, 0.8],
  ndbi: [-0.6, 0.5],
  nbr: [-0.5, 0.95],
  lst_c: [14, 30],
  albedo: [0, 0.45],
  imperviousness_pct: [0, 100],
  tree_cover_pct: [0, 100],
  cloud_pct: [0, 100],
  coherence: [0.3, 1],
  confidence: [0.4, 1],
  resolution_m: [10, 30],
  // Spread of settlement along a corridor -- the line-width channel on the
  // deformation profiles.
  differential_mm_yr: [0, 12],
};

/**
 * Per-layer numeric overrides, the numeric counterpart to
 * `LAYER_COLUMN_DOMAIN`. `area_ha` is a farm field of a few hectares in the
 * agriculture project but a flood footprint of a hundred-plus here, and one
 * shared range would flatten whichever layer it was not chosen for.
 */
const LAYER_NUMERIC_RANGE: Record<string, [number, number]> = {
  'rs_change.area_ha': [0, 50],
  'rs_water.area_ha': [0, 260],
  'rs_index_cells.area_ha': [0, 30],
  // On a building this is how tall it stands; on a persistent scatterer it is
  // the ground elevation the reflector sits at.
  'rs_subsidence.height_m': [-3, 50],
};

function numericRangeFor(layerName: string, column: string): [number, number] | undefined {
  return LAYER_NUMERIC_RANGE[`${layerName}.${column}`] ?? NUMERIC_RANGE[column];
}

function colorExpression(layerName: string, column: string | undefined, mode: Mode): unknown {
  if (!column) return CATEGORICAL[mode][0];

  const domainKey = domainFor(layerName, column);
  if (domainKey) return matchExpression(column, domainKey, mode);

  const diverging = DIVERGING_RANGE[column];
  if (diverging) return divergingExpression(column, diverging[0], diverging[1], mode, diverging[2]);

  const range = numericRangeFor(layerName, column);
  if (range) return sequentialExpression(column, range[0], range[1]);

  // Unknown column: fall back to slot 1 rather than inventing a scale.
  return CATEGORICAL[mode][0];
}

/**
 * Line width scaled by road importance, so the hierarchy stays legible as the
 * map zooms out.
 *
 * `scale` is baked into the output stops rather than applied with a `*`
 * wrapper: MapLibre only allows a `zoom` expression at the top level of a
 * `step`/`interpolate`, so multiplying the whole expression makes the style
 * invalid and the layer is silently dropped.
 */
function roadWidthExpression(scale = 1): unknown {
  const byClass = (thick: number, thin: number): unknown => [
    'interpolate',
    ['linear'],
    ['coalesce', ['get', 'functional_class'], 7],
    1,
    thick * scale,
    7,
    thin * scale,
  ];
  return [
    'interpolate',
    ['exponential', 1.6],
    ['zoom'],
    7,
    ['case', ['<=', ['coalesce', ['get', 'functional_class'], 7], 2], 1.2 * scale, 0.3 * scale],
    11,
    byClass(3.2, 0.6),
    15,
    byClass(10, 1.8),
    18,
    byClass(22, 4),
  ];
}

export function buildPaint(
  info: LayerInfo,
  mode: Mode,
  colorByOverride?: string,
  opacityOverride?: number,
): PaintSpec[] {
  const hint = info.styleHint ?? {};
  const chrome = CHROME[mode];
  const colorBy = colorByOverride ?? hint.colorBy;
  const color = colorExpression(info.name, colorBy, mode);
  const type = hint.type ?? (info.geomKind === 'line' ? 'line' : info.geomKind === 'point' ? 'circle' : 'fill');

  if (type === 'fill-extrusion') {
    const heightCol = hint.heightBy ?? 'height_m';
    return [
      {
        suffix: 'extrusion',
        type: 'fill-extrusion',
        paint: {
          'fill-extrusion-color': color,
          'fill-extrusion-height': ['coalesce', ['get', heightCol], 3],
          // Sitting the base on the sampled terrain elevation keeps buildings
          // planted on the DEM instead of floating above or sinking into it.
          'fill-extrusion-base': ['coalesce', ['get', 'min_height_m'], 0],
          'fill-extrusion-opacity': opacityOverride ?? 0.88,
          'fill-extrusion-vertical-gradient': true,
        },
      },
    ];
  }

  if (type === 'circle') {
    const sizeCol = hint.widthBy;
    const range = sizeCol ? NUMERIC_RANGE[sizeCol] : undefined;
    return [
      {
        suffix: 'circle',
        type: 'circle',
        paint: {
          'circle-color': color,
          'circle-radius':
            sizeCol && range
              ? [
                  'interpolate',
                  ['linear'],
                  ['zoom'],
                  10,
                  ['interpolate', ['linear'], ['coalesce', ['get', sizeCol], range[0]], range[0], 2.5, range[1], 7],
                  16,
                  ['interpolate', ['linear'], ['coalesce', ['get', sizeCol], range[0]], range[0], 4, range[1], 16],
                ]
              : ['interpolate', ['linear'], ['zoom'], 10, 3, 16, 7],
          'circle-opacity': opacityOverride ?? 0.9,
          // A 2px surface ring keeps overlapping markers separable.
          'circle-stroke-width': 1.6,
          'circle-stroke-color': chrome.surface,
        },
      },
    ];
  }

  if (type === 'line') {
    const isRoad = info.name === 'transport_roads';
    const widthCol = hint.widthBy;
    const widthRange = widthCol ? NUMERIC_RANGE[widthCol] : undefined;

    let width: unknown;
    if (isRoad) {
      width = roadWidthExpression();
    } else if (widthCol && widthRange) {
      width = [
        'interpolate',
        ['linear'],
        ['coalesce', ['get', widthCol], widthRange[0]],
        widthRange[0],
        0.8,
        widthRange[1],
        6,
      ];
    } else {
      width = ['interpolate', ['linear'], ['zoom'], 8, 0.8, 14, 2.6, 18, 5];
    }

    const specs: PaintSpec[] = [];
    // A casing under the main stroke gives every line a 2px surface gap from
    // whatever sits beneath it -- the map equivalent of the stacked-bar spacer.
    if (isRoad) {
      specs.push({
        suffix: 'casing',
        type: 'line',
        paint: {
          'line-color': chrome.surface,
          'line-width': roadWidthExpression(1.9),
          'line-opacity': 0.65,
        },
        layout: { 'line-cap': 'round', 'line-join': 'round' },
      });
    }
    specs.push({
      suffix: 'line',
      type: 'line',
      paint: {
        'line-color': color,
        'line-width': width,
        'line-opacity': opacityOverride ?? 0.92,
      },
      layout: { 'line-cap': 'round', 'line-join': 'round' },
    });
    return specs;
  }

  // Default: polygon fill with a hairline outline.
  return [
    {
      suffix: 'fill',
      type: 'fill',
      paint: {
        'fill-color': color,
        'fill-opacity': opacityOverride ?? 0.62,
      },
    },
    {
      suffix: 'outline',
      type: 'line',
      paint: {
        'line-color': chrome.surface,
        'line-width': ['interpolate', ['linear'], ['zoom'], 10, 0.3, 16, 1.2],
        'line-opacity': 0.75,
      },
    },
  ];
}

/** Legend entries for a layer, so identity never rests on colour alone. */
export interface LegendEntry {
  label: string;
  color: string;
}

export function buildLegend(
  info: LayerInfo,
  mode: Mode,
  colorByOverride?: string,
): {
  title: string;
  kind: 'categorical' | 'sequential' | 'diverging';
  entries: LegendEntry[];
  range?: [number, number];
} | null {
  const colorBy = colorByOverride ?? info.styleHint?.colorBy;
  if (!colorBy) return null;

  const domainKey = domainFor(info.name, colorBy);
  if (domainKey) {
    const domain = DOMAINS[domainKey];
    return {
      title: colorBy.replace(/_/g, ' '),
      kind: 'categorical',
      entries: domain.map((value, i) => ({
        label: value.replace(/_/g, ' '),
        color: CATEGORICAL[mode][i] ?? CHROME[mode].textMuted,
      })),
    };
  }

  const diverging = DIVERGING_RANGE[colorBy];
  if (diverging) {
    // A diverging scale has no class list, but it does have three points worth
    // naming -- the two poles and what the neutral middle means. Spelling those
    // out is what stops the map reading as "some colours".
    const poles = DIVERGING[mode];
    return {
      title: colorBy.replace(/_/g, ' '),
      kind: 'diverging',
      entries: [
        { label: String(diverging[0]), color: poles.high },
        { label: String(diverging[2]), color: poles.mid },
        { label: `+${diverging[1]}`, color: poles.low },
      ],
      range: [diverging[0], diverging[1]],
    };
  }

  const range = numericRangeFor(info.name, colorBy);
  if (!range) return null;
  return {
    title: colorBy.replace(/_/g, ' '),
    kind: 'sequential',
    entries: [],
    range,
  };
}
