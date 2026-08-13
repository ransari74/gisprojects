import { useMemo, useState } from 'react';

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

export function AgricultureProject() {
  const [soilColumn, setSoilColumn] = useState('soil_organic_c');
  const [colorBy, setColorBy] = useState('yield_t_ha');

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

  const s = summary.data;

  return (
    <ProjectShell
      project="agriculture"
      title="Agricultural Land & Soil Intelligence"
      tagline="Field-level soil chemistry, land cover and yield modelling across the Utrecht polder and Heuvelrug"
      defaultLayers={['agri_fields', 'agri_canals']}
      // Fields sit in the rural ring, so keep the whole study area in view.
      initialView={{ center: [5.1214, 52.0907], zoom: 10.4 }}
      colorOverrides={{ agri_fields: colorBy }}
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
