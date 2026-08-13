/** Shapes returned by the FastAPI backend. */

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface Me {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  roles: string[];
  permissions: string[];
  projects: ProjectKey[];
}

export type ProjectKey = 'agriculture' | 'parcel' | 'demographics' | 'transport' | 'terrain';

export type GeomKind = 'polygon' | 'line' | 'point';

export interface StyleHint {
  type?: 'fill' | 'line' | 'circle' | 'fill-extrusion';
  colorBy?: string;
  widthBy?: string;
  heightBy?: string;
  scheme?: string;
}

export interface LayerInfo {
  name: string;
  title: string;
  geomKind: GeomKind;
  minZoom: number;
  maxZoom: number;
  columns: string[];
  filterable: string[];
  rangeFilterable: string[];
  styleHint: StyleHint;
  description: string;
  tileUrl: string;
}

export interface ProjectCapability {
  key: ProjectKey;
  title: string;
  tagline: string;
  accent: string;
  icon: string;
  layers: LayerInfo[];
}

export interface Capabilities {
  projects: ProjectCapability[];
  tileExtent: number;
}

export interface StudyArea {
  code: string | null;
  name: string;
  country?: string;
  bbox: [number, number, number, number];
  center: [number, number];
  zoom: number;
}

export interface ProjectSummary {
  key: ProjectKey;
  title: string;
  tagline: string;
  accent: string;
  icon: string;
  accessible: boolean;
}

export interface DatasetSource {
  project: string;
  layer: string;
  dataset_name: string;
  provider: string | null;
  license: string | null;
  source_url: string | null;
  fetched_at: string | null;
  feature_count: number | null;
  notes: string | null;
}

export interface FeatureCollection {
  type: 'FeatureCollection';
  features: GeoFeature[];
  totalCount: number;
  limit: number;
  offset: number;
  layer: string;
}

export interface GeoFeature {
  type: 'Feature';
  id: number;
  geometry: GeoJSON.Geometry | null;
  properties: Record<string, unknown>;
}

export interface HistogramBin {
  bin: number;
  x0: number;
  x1: number;
  count: number;
}

export interface Histogram {
  column: string;
  min: number;
  max: number;
  count: number;
  mean: number;
  median: number;
  stddev: number;
  bins: HistogramBin[];
}

export interface ScatterPoint {
  id: number;
  x: number;
  y: number;
  y_index?: number;
  size?: number;
  [key: string]: unknown;
}

export interface CorrelationResult {
  xColumn: string;
  points: ScatterPoint[];
  pearson_r: number | null;
  pearson_r_indexed?: number | null;
  r_squared_indexed?: number | null;
  r_squared?: number | null;
  slope: number | null;
  intercept: number | null;
  n: number;
  yIndexNote?: string;
  cropType?: string | null;
}

export interface BasemapLayer {
  tiles: string[];
  tileSize: number;
  maxZoom: number;
}

export interface BasemapSpec {
  id: string;
  name: string;
  description: string;
  attribution: string;
  /** "roads" is shown desaturated so the app's own data reads clearly on top;
   * "imagery" is shown at full colour since the imagery is usually the point. */
  kind: 'roads' | 'imagery';
  layers: BasemapLayer[];
}

export interface LandCoverClass {
  code: number;
  label: string;
  colorHex: string;
}

export interface OverlaySpec {
  id: string;
  name: string;
  description: string;
  attribution: string;
  projects: ProjectKey[];
  tiles: string[];
  tileSize: number;
  maxZoom: number;
  defaultOpacity: number;
  legend: LandCoverClass[];
  /** Shown instead of a legend for a continuous or pre-styled overlay. */
  legendNote: string;
}

export interface TerrainTileConfig {
  source: {
    type: 'raster-dem';
    tiles: string[];
    encoding: 'terrarium' | 'mapbox';
    tileSize: number;
    maxzoom: number;
    attribution: string;
  };
  defaultExaggeration: number;
  skyDefaults: { sunIntensity: number; horizonBlend: number };
}
