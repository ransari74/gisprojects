/**
 * Chart and map colour tokens.
 *
 * These values are not hand-picked. The categorical order was validated with
 * the data-viz palette validator in both modes:
 *
 *   light, adjacent pairs : worst CVD ΔE 9.1, worst normal-vision ΔE 19.6
 *   dark,  adjacent pairs : worst CVD ΔE 8.4, worst normal-vision ΔE 19.3
 *   first three slots also clear the stricter ALL-PAIRS gate in both modes
 *     (light CVD ΔE 9.2 / normal 24.0; dark CVD ΔE 9.4 / normal 20.9)
 *
 * Consequences we honour elsewhere in the code:
 *
 *  - Forms where every series can sit beside every other (scatter, bubble)
 *    cap at THREE categorical series. Past three we fold to "Other" or facet.
 *  - Slots 3, 4 and 5 fall below 3:1 against the light surface, so any chart
 *    using them ships visible labels or a table view -- colour never carries
 *    identity alone.
 *  - Sequential encodings use ONE hue light-to-dark; diverging uses the
 *    blue/red pair with a neutral grey midpoint. Never a rainbow ramp.
 */

export type Mode = 'light' | 'dark';

/** Fixed categorical order. Assign by index; never cycle, never re-order. */
export const CATEGORICAL: Record<Mode, string[]> = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
};

/** Maximum categorical series for an all-pairs form (scatter, bubble, map fill). */
export const ALL_PAIRS_SERIES_CAP = 3;

/** Single-hue blue ramp, light to dark, for continuous magnitude. */
export const SEQUENTIAL_BLUE = [
  '#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7',
  '#3987e5', '#2a78d6', '#256abf', '#1c5cab', '#184f95', '#104281', '#0d366b',
];

/** Ordinal ramps must stay clear of the surface: start at step 250 on light. */
export const SEQUENTIAL_BLUE_ORDINAL_LIGHT = SEQUENTIAL_BLUE.slice(3);
export const SEQUENTIAL_BLUE_ORDINAL_DARK = SEQUENTIAL_BLUE.slice(0, 11);

/** Diverging: two poles that read as opposite, neutral grey at the middle. */
export const DIVERGING = {
  light: { low: '#2a78d6', mid: '#f0efec', high: '#e34948' },
  dark: { low: '#3987e5', mid: '#383835', high: '#e66767' },
};

/** Reserved for state. Never reused as "series 4"; always ships with a label. */
export const STATUS = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
};

export const CHROME: Record<Mode, Record<string, string>> = {
  light: {
    surface: '#fcfcfb',
    page: '#f9f9f7',
    textPrimary: '#0b0b0b',
    textSecondary: '#52514e',
    textMuted: '#898781',
    grid: '#e1e0d9',
    axis: '#c3c2b7',
    border: 'rgba(11,11,11,0.10)',
    success: '#006300',
  },
  dark: {
    surface: '#1a1a19',
    page: '#0d0d0d',
    textPrimary: '#ffffff',
    textSecondary: '#c3c2b7',
    textMuted: '#898781',
    grid: '#2c2c2a',
    axis: '#383835',
    border: 'rgba(255,255,255,0.10)',
    success: '#0ca30c',
  },
};

export function currentMode(): Mode {
  if (typeof document !== 'undefined') {
    const stamped = document.documentElement.dataset.theme;
    if (stamped === 'dark' || stamped === 'light') return stamped;
  }
  if (typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches) {
    return 'dark';
  }
  return 'light';
}

/**
 * Stable colour for a named category.
 *
 * Colour follows the entity, not its rank: the index comes from a fixed domain
 * list, so filtering a category out never repaints the survivors.
 */
export function categoricalFor(domain: readonly string[], value: string, mode: Mode): string {
  const idx = domain.indexOf(value);
  const palette = CATEGORICAL[mode];
  // Past the eighth slot we do not invent a hue -- the caller should have
  // folded the tail into "Other". Falling back to muted ink makes that visible.
  if (idx < 0 || idx >= palette.length) return CHROME[mode].textMuted;
  return palette[idx];
}

/** Sample the sequential ramp at t in [0, 1]. */
export function sequentialAt(t: number): string {
  const clamped = Math.max(0, Math.min(1, Number.isFinite(t) ? t : 0));
  const idx = Math.round(clamped * (SEQUENTIAL_BLUE.length - 1));
  return SEQUENTIAL_BLUE[idx];
}

// ---------------------------------------------------------------------------
// Fixed domains for the map layers, so colour assignment is stable across
// filters and across the map/chart boundary.
// ---------------------------------------------------------------------------
export const DOMAINS = {
  cropType: ['grassland', 'maize', 'wheat', 'potato', 'sugarbeet', 'barley', 'rapeseed'],
  soilTexture: ['peat', 'clay', 'clay loam', 'loam', 'sandy loam', 'sand'],
  canalType: ['primary', 'secondary', 'tertiary', 'drainage'],
  landUse: ['residential', 'mixed', 'retail', 'office', 'industrial', 'civic', 'vacant'],
  zoneCategory: ['residential', 'commercial', 'mixed', 'industrial', 'agricultural', 'open_space'],
  boundaryType: ['lot_line', 'easement', 'right_of_way', 'setback', 'disputed'],
  travelMode: ['car', 'transit', 'bike', 'walk'],
  transitMode: ['bus', 'tram', 'metro', 'rail', 'ferry'],
  highwayClass: [
    'motorway', 'trunk', 'primary', 'secondary', 'tertiary',
    'residential', 'service', 'cycleway', 'footway',
  ],
  buildingType: [
    'residential', 'commercial', 'office', 'retail',
    'industrial', 'civic', 'school', 'hospital',
  ],
  lineType: ['stream', 'river', 'ridge', 'valley'],
} as const;

export type DomainKey = keyof typeof DOMAINS;

/**
 * MapLibre `match` expression colouring a categorical field.
 *
 * Categories past slot 8 collapse to muted ink rather than getting a
 * generated hue -- the legend labels them, and the click popup names every
 * feature, so identity never rests on colour alone.
 */
export function matchExpression(field: string, domainKey: DomainKey, mode: Mode): unknown[] {
  const domain = DOMAINS[domainKey];
  const expr: unknown[] = ['match', ['get', field]];
  domain.forEach((value, i) => {
    expr.push(value, CATEGORICAL[mode][i] ?? CHROME[mode].textMuted);
  });
  expr.push(CHROME[mode].textMuted); // default
  return expr;
}

/**
 * MapLibre interpolate expression for a continuous field.
 *
 * Map fills draw from the ORDINAL sub-range of the ramp, not the full
 * sequential range. The palest sequential steps are designed to recede toward
 * the chart surface, which is right for a heatmap cell but wrong for a polygon
 * fill sitting on a basemap -- there the lightest features simply vanish.
 * Starting at step 250 keeps every fill clear of the surface.
 */
export function sequentialExpression(field: string, min: number, max: number): unknown[] {
  const ramp = SEQUENTIAL_BLUE_ORDINAL_LIGHT;
  const expr: unknown[] = ['interpolate', ['linear'], ['coalesce', ['get', field], min]];
  for (let i = 0; i < ramp.length; i += 1) {
    const t = i / (ramp.length - 1);
    expr.push(min + (max - min) * t, ramp[i]);
  }
  return expr;
}

/** The colours a map legend should show for a continuous field. */
export const MAP_SEQUENTIAL_RAMP = SEQUENTIAL_BLUE_ORDINAL_LIGHT;
