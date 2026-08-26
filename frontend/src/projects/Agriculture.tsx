import { useCallback, useMemo, useState } from 'react';

import type { MapGeoJSONFeature } from 'maplibre-gl';

import type { CorrelationResult } from '@/api/types';
import { BarChart } from '@/components/charts/BarChart';
import { fmtInt, fmtOne, fmtTwo } from '@/components/charts/chartkit';
import { LineChart, type Series } from '@/components/charts/LineChart';
import { EmptyState, StatRow, StatTile } from '@/components/charts/Primitives';
import { ScatterPlot } from '@/components/charts/ScatterPlot';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery } from '@/hooks/useApi';
import { DOMAINS } from '@/styles/theme';

interface AgriSummary {
  field_count: number;
  total_area_ha: number;
  mean_field_ha: number;
  mean_yield: number;
  mean_ph: number;
  mean_soc: number;
  mean_ndvi: number;
  irrigated_fields: number;
  organic_fields: number;
  crop_types: number;
}

interface YieldByCrop {
  crop_type: string;
  fields: number;
  area_ha: number;
  mean_yield: number;
  median: number;
  p25: number;
  p75: number;
}

interface NdviRow {
  date: string;
  series: string;
  ndvi: number;
  lower: number;
  upper: number;
}

interface SimilarFields {
  year: number;
  query: {
    id: number; field_code: string; farm_name: string | null; crop_type: string;
    soil_texture: string; area_ha: number; yield_t_ha: number; ndvi_mean: number;
    irrigated: boolean; organic: boolean; declared_crop: string; pixel_count: number;
  };
  matches: Array<{
    id: number; field_code: string; farm_name: string | null; crop_type: string;
    soil_texture: string; area_ha: number; yield_t_ha: number; ndvi_mean: number;
    irrigated: boolean; organic: boolean; similarity: number;
  }>;
  cropAgreement: number;
  soilAgreement: number;
}

interface CropClassification {
  year: number;
  labelsPerClass: number;
  accuracy: number;
  classCount: number;
  parcelCount: number;
  smallestClass: number;
  curve: Array<{
    labelsPerClass: number; accuracy: number; labelsUsed: number;
    evaluatedOn: number; saturated: boolean;
  }>;
  perClass: Array<{ crop: string; support: number; recall: number; precision: number }>;
  confusion: Array<{ actual: string; predicted: string; count: number }>;
}

interface Rotation {
  pairCount: number;
  changedCount: number;
  unchangedCount: number;
  meanChanged: number | null;
  meanUnchanged: number | null;
  separability: number;
  changedHistogram: Array<{ x0: number; x1: number; count: number }>;
  unchangedHistogram: Array<{ x0: number; x1: number; count: number }>;
  byCrop: Array<{ from_crop: string; transitions: number; rotated_pct: number }>;
}

interface IrrigationCoverage {
  total_fields: number;
  served_fields: number;
  total_area_ha: number;
  served_area_ha: number;
  served_area_pct: number;
  canal_km: number;
  buffer_m: number;
}

const SOIL_COLUMNS = [
  { value: 'soil_organic_c', label: 'Soil organic carbon (g/kg)' },
  { value: 'soil_ph', label: 'Soil pH' },
  { value: 'soil_clay_pct', label: 'Clay fraction (%)' },
  { value: 'soil_sand_pct', label: 'Sand fraction (%)' },
  { value: 'slope_deg', label: 'Slope (degrees)' },
  { value: 'elevation_m', label: 'Elevation (m)' },
  { value: 'ndvi_mean', label: 'Mean NDVI' },
];

// Hoisted rather than inline: these never depend on component state, so a
// fresh object/array literal on every render would needlessly invalidate the
// memoised layer list downstream (ProjectShell's `active`, MapView's data
// layer sync effect) on every unrelated re-render.
const INITIAL_VIEW = { center: [5.1214, 52.0907] as [number, number], zoom: 10.4 };
const OVERLAY_IDS = ['esa_worldcover', 'soilgrids_ph', 'soilgrids_soc', 'protected_areas', 'waterways'];

const LABEL_BUDGETS = [
  { value: '3', label: '3 per crop' },
  { value: '8', label: '8 per crop' },
  { value: '20', label: '20 per crop' },
  { value: '60', label: '60 per crop' },
];

export function AgricultureProject() {
  const [soilColumn, setSoilColumn] = useState('soil_organic_c');
  const [colorBy, setColorBy] = useState('yield_t_ha');
  const [labelBudget, setLabelBudget] = useState('20');
  const [selectedField, setSelectedField] = useState<number | null>(null);

  const summary = useApiQuery<AgriSummary>(['agri', 'summary'], '/agriculture/summary');
  const byCrop = useApiQuery<YieldByCrop[]>(['agri', 'yield-by-crop'], '/agriculture/yield-by-crop');
  const scatter = useApiQuery<CorrelationResult>(
    ['agri', 'scatter', soilColumn],
    `/agriculture/soil-yield-correlation?x=${soilColumn}&limit=1200`,
  );
  const ndvi = useApiQuery<NdviRow[]>(['agri', 'ndvi'], '/agriculture/ndvi-timeseries');
  const irrigation = useApiQuery<IrrigationCoverage>(
    ['agri', 'irrigation'],
    '/agriculture/irrigation-coverage?buffer_m=250',
  );
  const similar = useApiQuery<SimilarFields>(
    ['agri', 'similar', selectedField ?? 0],
    `/agriculture/similar-fields?field_id=${selectedField ?? 0}&limit=12`,
    { enabled: selectedField !== null },
  );
  const classification = useApiQuery<CropClassification>(
    ['agri', 'classification', labelBudget],
    `/agriculture/crop-classification?labels_per_class=${labelBudget}`,
  );
  const rotation = useApiQuery<Rotation>(['agri', 'rotation'], '/agriculture/rotation');

  const ndviSeries: Series[] = useMemo(() => {
    const rows = ndvi.data ?? [];
    const byName = new Map<string, Series>();
    for (const row of rows) {
      if (!byName.has(row.series)) byName.set(row.series, { name: row.series, points: [] });
      byName.get(row.series)!.points.push({
        x: new Date(row.date),
        y: row.ndvi,
        lower: row.lower,
        upper: row.upper,
      });
    }
    // Four lines is the direct-label limit; the rest would need a legend-only
    // read, so keep the four largest crops and drop the tail.
    return [...byName.values()]
      .sort((a, b) => b.points.length - a.points.length)
      .slice(0, 4);
  }, [ndvi.data]);

  // The map hands back the clicked feature; only parcels carry an embedding,
  // so a click on a canal clears the selection rather than querying for one.
  const handleFeatureClick = useCallback((feature: MapGeoJSONFeature | null) => {
    if (!feature || feature.source !== 'agri_fields') {
      setSelectedField(null);
      return;
    }
    // ST_AsMVT promotes the id column to the feature *id* and drops it from
    // the property bag, so `feature.id` is where it lives -- not
    // `properties.feature_id`, which is always undefined here.
    const id = feature.id;
    setSelectedField(typeof id === 'number' ? id : Number(id) || null);
  }, []);

  const highlight = useMemo(() => {
    const ids = (similar.data?.matches ?? []).map((m) => m.id);
    if (selectedField === null) return null;
    return { layer: 'agri_fields', ids: [selectedField, ...ids] };
  }, [selectedField, similar.data]);

  const curveSeries: Series[] = useMemo(
    () => [
      {
        name: 'held-out accuracy',
        points: (classification.data?.curve ?? []).map((c) => ({
          x: c.labelsPerClass,
          y: c.accuracy,
        })),
      },
    ],
    [classification.data],
  );

  const s = summary.data;
  const colorOverrides = useMemo(() => ({ agri_fields: colorBy }), [colorBy]);

  return (
    <ProjectShell
      project="agriculture"
      title="Agricultural Land & Soil Intelligence"
      tagline="Field-level soil chemistry, land cover and yield modelling across the Utrecht polder and Heuvelrug"
      defaultLayers={['agri_fields', 'agri_canals']}
      // Fields sit in the rural ring, so keep the whole study area in view.
      initialView={INITIAL_VIEW}
      overlayIds={OVERLAY_IDS}
      colorOverrides={colorOverrides}
      onFeatureClick={handleFeatureClick}
      highlight={highlight}
      controls={
        <>
          <Selector
            label="Colour fields by"
            value={colorBy}
            onChange={setColorBy}
            options={[
              { value: 'yield_t_ha', label: 'Yield (t/ha)' },
              { value: 'crop_type', label: 'Crop type' },
              { value: 'soil_texture', label: 'Soil texture' },
              { value: 'soil_ph', label: 'Soil pH' },
              { value: 'ndvi_mean', label: 'Mean NDVI' },
            ]}
          />
          <Selector
            label="Soil driver"
            value={soilColumn}
            onChange={setSoilColumn}
            options={SOIL_COLUMNS}
          />
          <Selector
            label="Training labels"
            value={labelBudget}
            onChange={setLabelBudget}
            options={LABEL_BUDGETS}
          />
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile label="Fields" value={s.field_count} />
          <StatTile label="Total area" value={s.total_area_ha} unit=" ha" />
          <StatTile label="Mean soil pH" value={s.mean_ph} hint={`SOC ${fmtOne(s.mean_soc)} g/kg`} />
          <StatTile label="Mean NDVI" value={s.mean_ndvi} hint={`${s.crop_types} crop types`} />
          <StatTile
            label="Irrigated"
            value={`${Math.round((100 * s.irrigated_fields) / s.field_count)}%`}
            hint={`${s.organic_fields} organic fields`}
          />
        </StatRow>
      )}

      {byCrop.data && (
        <BarChart
          title="Yield by crop"
          subtitle="Mean yield per crop across all declared parcels"
          data={byCrop.data.map((r) => ({
            category: r.crop_type,
            value: r.mean_yield,
            secondary: { label: 'area', value: `${fmtInt(r.area_ha)} ha · ${r.fields} fields` },
          }))}
          colorDomain={DOMAINS.cropType}
          monochrome={false}
          valueFormat={(v) => `${fmtOne(v)} t/ha`}
          valueLabel="mean yield"
          note="Crops are coloured to match the map's crop-type view, so the same crop is the same colour in both."
        />
      )}

      {scatter.data && scatter.data.points.length > 0 && (
        <ScatterPlot
          title={`Soil driver vs relative yield`}
          subtitle={
            `Each point is one field. Yield is expressed as a share of its own crop's mean, ` +
            `which removes the crop mix from the comparison.`
          }
          data={scatter.data.points.map((p) => ({
            x: p.x,
            y: p.y_index ?? p.y,
            label: String(p.field_code ?? ''),
            group: String(p.crop_type ?? ''),
            size: typeof p.size === 'number' ? p.size : undefined,
          }))}
          xLabel={SOIL_COLUMNS.find((c) => c.value === soilColumn)?.label ?? soilColumn}
          yLabel="yield index (1.0 = crop average)"
          yFormat={fmtTwo}
          yReference={1}
          note={
            <>
              Raw correlation across all crops: <strong>r = {fmtTwo(scatter.data.pearson_r ?? 0)}</strong>.
              After indexing each field against its own crop:{' '}
              <strong>r = {fmtTwo(scatter.data.pearson_r_indexed ?? 0)}</strong>{' '}
              (R² = {fmtTwo(scatter.data.r_squared_indexed ?? 0)}, n = {scatter.data.n.toLocaleString()}).
              {soilColumn === 'soil_ph' &&
                ' pH acts through an optimum near 6.5, so a linear coefficient understates a real effect — a curve, not a line, is the right model here.'}
            </>
          }
        />
      )}

      {ndviSeries.length > 0 ? (
        <LineChart
          title="Seasonal NDVI by crop"
          subtitle="Sentinel-2 style 10-day composites through the 2024 growing season; band shows the 10th–90th percentile"
          series={ndviSeries}
          isTime
          yFormat={fmtTwo}
          height={300}
          note="Canopy greenness peaks in June for cereals and later for maize and sugarbeet — the phenology separates the crops."
        />
      ) : (
        <EmptyState message="No NDVI observations loaded." />
      )}


      {/* ---- AlphaEarth satellite embeddings ---- */}
      <div className="figure" style={{ borderColor: 'transparent', padding: 0 }}>
        <h2 className="section-heading">Satellite embedding search</h2>
        <p className="section-note">
          Every parcel carries a 64-number AlphaEarth vector summarising its whole year of
          Sentinel-1, Sentinel-2 and Landsat observations. The vectors are unit length, so the
          cosine between two of them is a single dot product — "find fields like this one" is a
          SQL expression, not a model call.
        </p>
      </div>

      {selectedField === null ? (
        <EmptyState message="Click any field on the map to find the parcels most similar to it." />
      ) : similar.data ? (
        <div className="figure" style={{ background: 'transparent' }}>
          <div className="figure-head">
            <div>
              <div className="figure-title">Fields most like {similar.data.query.field_code}</div>
              <p className="figure-subtitle">
                {similar.data.query.crop_type} on {similar.data.query.soil_texture},{' '}
                {fmtOne(similar.data.query.area_ha)} ha · ranked by cosine similarity in {similar.data.year}
              </p>
            </div>
          </div>
          <StatRow>
            <StatTile
              label="Top-12 share the crop"
              value={`${Math.round(100 * similar.data.cropAgreement)}%`}
              hint="never told the crop — inferred from imagery alone"
            />
            <StatTile
              label="Top-12 share the soil"
              value={`${Math.round(100 * similar.data.soilAgreement)}%`}
              hint={`query parcel is ${similar.data.query.soil_texture}`}
            />
          </StatRow>
          <table className="data-table">
            <thead>
              <tr>
                <th>Similarity</th><th>Field</th><th>Crop</th><th>Soil</th>
                <th className="num">Area</th><th className="num">Yield</th>
              </tr>
            </thead>
            <tbody>
              {similar.data.matches.map((m) => (
                <tr key={m.id}>
                  <td className="num">{fmtTwo(m.similarity)}</td>
                  <td>{m.field_code}</td>
                  <td>{m.crop_type}</td>
                  <td>{m.soil_texture}</td>
                  <td className="num">{fmtOne(m.area_ha)} ha</td>
                  <td className="num">{fmtOne(m.yield_t_ha)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="figure-note">
            The selected parcel and its matches are outlined on the map. Similarity is agronomic,
            not geographic — matches are scattered across the study area, because the embedding
            encodes what the land does through the season rather than where it sits.
          </p>
        </div>
      ) : (
        <EmptyState message="Loading similar fields…" />
      )}

      {classification.data && curveSeries[0].points.length > 0 && (
        <LineChart
          title="How little supervision the embedding needs"
          subtitle={`Held-out crop-classification accuracy against the number of labelled parcels per crop, ${classification.data.year}`}
          series={curveSeries}
          yFormat={(v) => `${fmtOne(v)}%`}
          xFormat={(v) => `${v}`}
          height={260}
          note={
            <>
              Seven labelled parcels — one per crop — already classify{' '}
              <strong>{fmtOne(classification.data.curve[0]?.accuracy ?? 0)}%</strong> of the
              remaining {fmtInt(classification.data.curve[0]?.evaluatedOn ?? 0)} correctly against a
              14% random baseline, and the curve flattens near{' '}
              <strong>{fmtOne(classification.data.curve[classification.data.curve.length - 1]?.accuracy ?? 0)}%</strong>.
              That flat tail is the honest limit: past{' '}
              {classification.data.smallestClass} labels there are none left to add for the rarest
              crop. Accuracy is measured only on parcels the classifier never saw.
            </>
          }
        />
      )}

      {classification.data && classification.data.perClass.length > 0 && (
        <BarChart
          title={`Per-crop recall at ${classification.data.labelsPerClass} labels`}
          subtitle="Share of each crop's parcels the classifier recovers"
          data={classification.data.perClass.map((c) => ({
            category: c.crop,
            value: c.recall,
            secondary: {
              label: 'precision',
              value: `${fmtOne(c.precision)}% · ${fmtInt(c.support)} parcels`,
            },
          }))}
          colorDomain={DOMAINS.cropType}
          monochrome={false}
          horizontal
          height={260}
          valueFormat={(v) => `${fmtOne(v)}%`}
          valueLabel="recall"
          note={
            classification.data.confusion.length > 0 ? (
              <>
                The errors are not random. The largest confusions are{' '}
                {classification.data.confusion.slice(0, 3).map((c, i) => (
                  <span key={`${c.actual}-${c.predicted}`}>
                    {i > 0 ? ', ' : ''}
                    <strong>{c.actual.replace(/_/g, ' ')} → {c.predicted.replace(/_/g, ' ')}</strong>
                  </span>
                ))}
                {' '}— crops that share a sowing window and a canopy shape, and therefore share a
                region of the embedding space.
              </>
            ) : undefined
          }
        />
      )}

      {rotation.data && (
        <BarChart
          title="How often each crop is rotated"
          subtitle="Share of consecutive-year pairs where the declared crop changed"
          data={rotation.data.byCrop.map((c) => ({
            category: c.from_crop,
            value: c.rotated_pct,
            secondary: { label: 'pairs', value: `${fmtInt(c.transitions)} transitions` },
          }))}
          colorDomain={DOMAINS.cropType}
          monochrome={false}
          horizontal
          height={250}
          valueFormat={(v) => `${fmtOne(v)}%`}
          valueLabel="rotated"
          note={
            <>
              Detected from the imagery alone, year-over-year embedding similarity separates a
              rotated parcel from an unrotated one with an AUC of{' '}
              <strong>{fmtTwo(rotation.data.separability)}</strong> (mean cosine{' '}
              {fmtTwo(rotation.data.meanChanged ?? 0)} rotated against{' '}
              {fmtTwo(rotation.data.meanUnchanged ?? 0)} unchanged). The means sit closer than you
              might expect because a parcel keeps its soil, drainage and shape through a rotation —
              which is exactly why the distributions, not the averages, are what to read.
              Grassland barely moves: Dutch dairy pasture is semi-permanent.
            </>
          }
        />
      )}

      {irrigation.data && (
        <StatRow>
          <StatTile
            label="Field area within 250 m of a canal"
            value={`${irrigation.data.served_area_pct}%`}
            hint={`${fmtInt(irrigation.data.served_area_ha)} of ${fmtInt(irrigation.data.total_area_ha)} ha`}
          />
          <StatTile label="Fields served" value={irrigation.data.served_fields} hint={`of ${irrigation.data.total_fields}`} />
          <StatTile label="Canal network" value={irrigation.data.canal_km} unit=" km" />
        </StatRow>
      )}
    </ProjectShell>
  );
}
