import { useMemo, useState } from 'react';

import { BarChart } from '@/components/charts/BarChart';
import { fmtInt, fmtOne, fmtTwo } from '@/components/charts/chartkit';
import { Histogram } from '@/components/charts/Histogram';
import { LineChart, type Series } from '@/components/charts/LineChart';
import { EmptyState, StatRow, StatTile } from '@/components/charts/Primitives';
import { ScatterPlot } from '@/components/charts/ScatterPlot';
import { StackedBar } from '@/components/charts/StackedBar';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery } from '@/hooks/useApi';
import { DOMAINS, STATUS } from '@/styles/theme';

interface RsSummary {
  scene_count: number;
  usable_scenes: number;
  platform_count: number;
  mean_cloud_pct: number;
  first_acquired: string;
  last_acquired: string;
  cell_count: number;
  mean_ndvi: number;
  mean_lst_c: number;
  max_lst_c: number;
  mean_impervious_pct: number;
  changed_cells: number;
  changed_area_ha: number;
  total_area_ha: number;
  uhi_delta_c: number;
  ps_count: number;
  mean_velocity_mm_yr: number;
  fastest_subsidence_mm_yr: number;
  points_over_5mm: number;
  mean_coherence: number;
  permanent_water_ha: number;
  peak_flood_ha: number;
  water_observations: number;
}

interface SceneInventory {
  byMonth: Array<{ month: string; platform: string; scenes: number; usable: number; mean_cloud_pct: number }>;
  byPlatform: Array<{
    platform: string; sensor: string; scenes: number; usable: number;
    mean_cloud_pct: number; resolution_m: number;
  }>;
}

interface IndexPoint {
  date: string;
  series: string;
  value: number;
  lower: number;
  upper: number;
}

interface ChangeMatrix {
  transitions: Array<{ from_class: string; to_class: string; cells: number; area_ha: number; mean_ndvi_delta: number }>;
  net: Array<{ landcover_class: string; gained_ha: number; lost_ha: number; net_ha: number }>;
  byType: Array<{ change_type: string; polygons: number; area_ha: number; mean_confidence: number; mean_ndvi_delta: number }>;
}

interface HeatIsland {
  xColumn: string;
  points: Array<{ id: number; x: number; y: number; anomaly: number; group_name: string; label: string }>;
  pearson_r: number | null;
  r_squared: number | null;
  slope: number | null;
  intercept: number | null;
  n: number;
  byClass: Array<{
    landcover_class: string; cells: number; mean_lst_c: number;
    mean_anomaly_c: number; mean_ndvi: number; mean_impervious_pct: number;
  }>;
}

interface Subsidence {
  bySoil: Array<{
    soil_type: string; points: number; mean_velocity_mm_yr: number; fastest_mm_yr: number;
    median_mm_yr: number; mean_cumulative_mm: number; mean_coherence: number;
  }>;
  byRisk: Array<{ risk_class: string; points: number; mean_velocity_mm_yr: number }>;
  byLandUse: Array<{ land_use: string; points: number; mean_velocity_mm_yr: number; mean_cumulative_mm: number }>;
  /** Optional so an older API that predates this field degrades to a
   * missing panel rather than taking the whole page down. */
  profiles?: Array<{
    profile_code: string; name: string; asset_type: string; risk_class: string;
    dominant_soil: string; length_km: number; mean_velocity_mm_yr: number;
    min_velocity_mm_yr: number; differential_mm_yr: number; ps_count: number;
  }>;
}

interface IndexDistribution {
  column: string;
  min: number;
  max: number;
  bins: Array<{ x0: number; x1: number; count: number; meanLstC: number }>;
}

interface WaterRow {
  date: string;
  water_type: string;
  source: string;
  area_ha: number;
  mean_confidence: number;
}

const INDEX_OPTIONS = [
  { value: 'ndvi', label: 'NDVI — vegetation' },
  { value: 'ndwi', label: 'NDWI — water' },
  { value: 'ndbi', label: 'NDBI — built-up' },
  { value: 'nbr', label: 'NBR — burn / biomass' },
];

const HEAT_DRIVERS = [
  { value: 'ndvi', label: 'NDVI (vegetation)' },
  { value: 'imperviousness_pct', label: 'Impervious cover (%)' },
  { value: 'ndbi', label: 'NDBI (built-up index)' },
  { value: 'tree_cover_pct', label: 'Tree cover (%)' },
  { value: 'albedo', label: 'Albedo' },
];

const MAP_COLOUR_OPTIONS = [
  { value: 'ndvi', label: 'NDVI' },
  { value: 'lst_c', label: 'Land surface temperature' },
  { value: 'lst_anomaly_c', label: 'Temperature anomaly' },
  { value: 'landcover_class', label: 'Land cover class' },
  { value: 'ndbi', label: 'NDBI (built-up)' },
  { value: 'imperviousness_pct', label: 'Impervious cover' },
];

// Hoisted so these never become fresh references on an unrelated re-render --
// MapView's data-layer effect keys off the layer list, and a new object every
// render makes it resync a source that is still initialising.
const INITIAL_VIEW = { center: [5.1214, 52.0907] as [number, number], zoom: 10.6 };
const OVERLAY_IDS = ['esa_worldcover', 'protected_areas', 'waterways'];

const INDEX_LABEL: Record<string, string> = {
  ndvi: 'NDVI', ndwi: 'NDWI', ndbi: 'NDBI', nbr: 'NBR', lst_c: 'LST (°C)',
};

export function RemoteSensingProject() {
  const [index, setIndex] = useState('ndvi');
  const [heatDriver, setHeatDriver] = useState('ndvi');
  const [colorBy, setColorBy] = useState('ndvi');

  const summary = useApiQuery<RsSummary>(['rs', 'summary'], '/remote-sensing/summary');
  const inventory = useApiQuery<SceneInventory>(['rs', 'inventory'], '/remote-sensing/scene-inventory');
  const series = useApiQuery<IndexPoint[]>(
    ['rs', 'timeseries', index],
    `/remote-sensing/index-timeseries?index=${index}`,
  );
  const change = useApiQuery<ChangeMatrix>(['rs', 'change'], '/remote-sensing/change-matrix');
  const heat = useApiQuery<HeatIsland>(
    ['rs', 'heat', heatDriver],
    `/remote-sensing/heat-island?x=${heatDriver}&limit=1500`,
  );
  const subsidence = useApiQuery<Subsidence>(['rs', 'subsidence'], '/remote-sensing/subsidence');
  const distribution = useApiQuery<IndexDistribution>(
    ['rs', 'distribution', index],
    `/remote-sensing/index-distribution?index=${index}&bins=24`,
  );
  const water = useApiQuery<WaterRow[]>(['rs', 'water'], '/remote-sensing/water-extent');

  const indexSeries: Series[] = useMemo(() => {
    const byName = new Map<string, Series>();
    for (const row of series.data ?? []) {
      if (!byName.has(row.series)) byName.set(row.series, { name: row.series, points: [] });
      byName.get(row.series)!.points.push({
        x: new Date(row.date), y: row.value, lower: row.lower, upper: row.upper,
      });
    }
    // Four lines is the direct-label limit. Keep the classes whose phenology
    // actually differs -- water and bare are flat lines that say nothing here.
    return ['cropland', 'grassland', 'tree_cover', 'built_up']
      .map((k) => byName.get(k))
      .filter((s): s is Series => Boolean(s));
  }, [series.data]);

  // Acquisitions per month summed across platforms, which is the number that
  // answers "could I have built a monthly composite from this archive".
  const monthlyUsable: Series[] = useMemo(() => {
    const total = new Map<string, number>();
    const usable = new Map<string, number>();
    for (const row of inventory.data?.byMonth ?? []) {
      total.set(row.month, (total.get(row.month) ?? 0) + row.scenes);
      usable.set(row.month, (usable.get(row.month) ?? 0) + row.usable);
    }
    const months = [...total.keys()].sort();
    const toPoints = (m: Map<string, number>) =>
      months.map((month) => ({ x: new Date(`${month}-01T00:00:00Z`), y: m.get(month) ?? 0 }));
    return [
      { name: 'acquired', points: toPoints(total) },
      { name: 'usable (cloud < 30%)', points: toPoints(usable) },
    ];
  }, [inventory.data]);

  // The transition matrix as a stacked bar: one bar per origin class, split by
  // where that land ended up. Cells that did not change are dropped -- they
  // would dwarf every real transition and flatten the whole chart.
  const transitionRows = useMemo(() => {
    const byFrom = new Map<string, Record<string, number | string>>();
    for (const t of change.data?.transitions ?? []) {
      if (t.from_class === t.to_class) continue;
      const row = byFrom.get(t.from_class) ?? { from: t.from_class.replace(/_/g, ' ') };
      row[t.to_class.replace(/_/g, ' ')] = t.area_ha;
      byFrom.set(t.from_class, row);
    }
    return [...byFrom.values()];
  }, [change.data]);

  const transitionKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const row of transitionRows) {
      for (const k of Object.keys(row)) if (k !== 'from') keys.add(k);
    }
    return [...keys].sort();
  }, [transitionRows]);

  const waterSeries: Series[] = useMemo(() => {
    const rows = water.data ?? [];
    const dates = [...new Set(rows.map((r) => r.date))].sort();
    const types = [...new Set(rows.map((r) => r.water_type))];
    const lookup = new Map(rows.map((r) => [`${r.date}|${r.water_type}`, r.area_ha]));
    // Every series carries every date, defaulting to zero. A pass that found no
    // flooding measured zero hectares of it -- it is not a gap in the record,
    // and dropping the date would collapse the flood series to a single point
    // and hide the fact that the other passes looked and saw nothing.
    return types.map((water_type) => ({
      name: water_type,
      points: dates.map((date) => ({
        x: new Date(date),
        y: lookup.get(`${date}|${water_type}`) ?? 0,
      })),
    }));
  }, [water.data]);

  const colorOverrides = useMemo(() => ({ rs_index_cells: colorBy }), [colorBy]);

  const s = summary.data;
  const heatDriverLabel = HEAT_DRIVERS.find((d) => d.value === heatDriver)?.label ?? heatDriver;
  const usablePct = s && s.scene_count > 0 ? (100 * s.usable_scenes) / s.scene_count : 0;

  return (
    <ProjectShell
      project="remote_sensing"
      title="Remote Sensing & Change Detection"
      tagline="Spectral indices, land-cover change, urban heat and InSAR ground motion over the Utrecht study area"
      defaultLayers={['rs_index_cells', 'rs_change', 'rs_profiles']}
      initialView={INITIAL_VIEW}
      overlayIds={OVERLAY_IDS}
      colorOverrides={colorOverrides}
      controls={
        <>
          <Selector label="Colour grid by" value={colorBy} onChange={setColorBy} options={MAP_COLOUR_OPTIONS} />
          <Selector label="Spectral index" value={index} onChange={setIndex} options={INDEX_OPTIONS} />
          <Selector label="Heat driver" value={heatDriver} onChange={setHeatDriver} options={HEAT_DRIVERS} />
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile
            label="Usable scenes"
            value={`${fmtInt(s.usable_scenes)} / ${fmtInt(s.scene_count)}`}
            hint={`${fmtOne(usablePct)}% of the archive · mean cloud ${fmtOne(s.mean_cloud_pct)}%`}
            accent={usablePct < 40 ? STATUS.warning : STATUS.good}
          />
          <StatTile
            label="Urban heat island"
            value={`+${fmtTwo(s.uhi_delta_c)}`}
            unit=" °C"
            hint="built-up vs everything else"
          />
          <StatTile
            label="Land changed"
            value={`${fmtOne((100 * s.changed_area_ha) / s.total_area_ha)}%`}
            hint={`${fmtInt(s.changed_area_ha)} of ${fmtInt(s.total_area_ha)} ha`}
          />
          <StatTile
            label="Mean ground motion"
            value={fmtTwo(s.mean_velocity_mm_yr)}
            unit=" mm/yr"
            hint={`${fmtInt(s.points_over_5mm)} of ${fmtInt(s.ps_count)} scatterers below −5 mm/yr`}
            accent={STATUS.warning}
          />
          <StatTile
            label="Peak flood extent"
            value={fmtInt(s.peak_flood_ha)}
            unit=" ha"
            hint={`over ${fmtInt(s.permanent_water_ha)} ha of permanent water`}
          />
        </StatRow>
      )}

      {monthlyUsable[0]?.points.length > 0 && (
        <LineChart
          title="What the archive actually yields"
          subtitle="Scenes acquired each month against the subset clear enough to use"
          series={monthlyUsable}
          isTime
          yFormat={(v) => fmtInt(v)}
          height={230}
          note={
            "Every satellite passes on schedule; the usable line is the one that moves. Cloud " +
            "removes most of the optical archive over the Netherlands, and the winter gap is " +
            "where an optical-only study loses the months it most needs — which is the case for " +
            "the radar layers in this project."
          }
        />
      )}

      {inventory.data && (
        <BarChart
          title="Archive by platform"
          subtitle="Acquisitions in the study period, and how many cleared the 30% cloud threshold"
          data={inventory.data.byPlatform.map((p) => ({
            category: p.platform,
            value: p.scenes,
            secondary: {
              label: 'usable',
              value: `${p.usable} of ${p.scenes} · ${p.sensor} @ ${fmtInt(p.resolution_m)} m · mean cloud ${fmtOne(p.mean_cloud_pct)}%`,
            },
          }))}
          colorDomain={DOMAINS.platform}
          monochrome={false}
          horizontal
          height={230}
          valueFormat={fmtInt}
          valueLabel="scenes acquired"
          note="Sentinel-1 is radar, so its cloud figure is zero by construction and every pass is usable — the reason it carries the water and ground-motion layers here."
        />
      )}

      {indexSeries.length > 0 ? (
        <LineChart
          title={`Seasonal ${INDEX_LABEL[index] ?? index} by land cover`}
          subtitle="Ten-day composites through 2024; band shows the 10th–90th percentile within each class"
          series={indexSeries}
          isTime
          yFormat={fmtTwo}
          height={300}
          note={
            index === 'ndvi'
              ? 'Cropland swings from bare soil to closed canopy and back inside one season; woodland barely moves and built-up land is flat all year. That separation is why a single-date classification is unreliable and a time series is worth building.'
              : 'Each class carries its own seasonal signature, which is what lets a classifier separate them from the shape of the curve rather than from one date.'
          }
        />
      ) : (
        <EmptyState message="No index observations loaded." />
      )}

      {distribution.data && distribution.data.bins.length > 0 && (
        <Histogram
          title={`${INDEX_LABEL[index] ?? index} distribution across the grid`}
          subtitle="The spread the map's colour ramp is stretched over"
          bins={distribution.data.bins}
          xLabel={INDEX_LABEL[index] ?? index}
          xFormat={fmtTwo}
          height={230}
          note="A bimodal shape is the signature of two distinct surface types sharing the study area — here vegetated ground against sealed ground."
        />
      )}

      {heat.data && heat.data.points.length > 0 && (
        <ScatterPlot
          title="Urban heat island"
          subtitle="One point per grid cell: land surface temperature against a surface-cover driver"
          data={heat.data.points.map((p) => ({
            x: p.x,
            y: p.y,
            label: p.label,
            group: p.group_name.replace(/_/g, ' '),
          }))}
          xLabel={heatDriverLabel}
          yLabel="land surface temperature (°C)"
          yFormat={(v) => `${fmtOne(v)} °C`}
          height={320}
          note={
            <>
              Pearson r = <strong>{fmtTwo(heat.data.pearson_r ?? 0)}</strong>, R² ={' '}
              <strong>{fmtTwo(heat.data.r_squared ?? 0)}</strong> over {fmtInt(heat.data.n)} cells;
              slope <strong>{fmtTwo(heat.data.slope ?? 0)}</strong> °C per unit.{' '}
              {heatDriver === 'ndvi'
                ? 'Vegetation cools by evapotranspiration, so the relationship runs negative — greener ground is measurably colder ground.'
                : 'Sealed surfaces store the day’s heat and release it slowly, so the relationship runs positive.'}{' '}
              This is surface temperature from the thermal band, which sits several degrees above
              the air temperature a weather station reports.
            </>
          }
        />
      )}

      {heat.data && heat.data.byClass.length > 0 && (
        <BarChart
          title="Temperature anomaly by land cover"
          subtitle="Departure from the study-area mean surface temperature"
          data={heat.data.byClass.map((c) => ({
            category: c.landcover_class.replace(/_/g, ' '),
            value: c.mean_anomaly_c,
            secondary: {
              label: 'absolute',
              value: `${fmtOne(c.mean_lst_c)} °C · NDVI ${fmtTwo(c.mean_ndvi)} · ${fmtOne(c.mean_impervious_pct)}% sealed`,
            },
          }))}
          horizontal
          height={240}
          valueFormat={(v) => `${v > 0 ? '+' : ''}${fmtTwo(v)} °C`}
          valueLabel="anomaly"
          note="Woodland and open water sit below the mean, built-up land well above it. The gap between the two ends is the heat island, measured rather than asserted."
        />
      )}

      {transitionRows.length > 0 && (
        <StackedBar
          title="Land-cover transitions"
          subtitle="Where each class's land ended up, baseline epoch to comparison epoch; unchanged ground is excluded"
          data={transitionRows}
          categoryKey="from"
          keys={transitionKeys}
          valueFormat={(v) => `${fmtInt(v)} ha`}
          height={300}
          note="Read a bar as: of the land that was this class and changed, this is what it became. Grass and arable trade back and forth as rotation; the flow into built-up is the one that does not come back."
        />
      )}

      {change.data && change.data.byType.length > 0 && (
        <BarChart
          title="Change by process"
          subtitle="Detected change areas grouped by the transition they represent"
          data={change.data.byType.map((t) => ({
            category: t.change_type.replace(/_/g, ' '),
            value: t.area_ha,
            secondary: {
              label: 'detections',
              value: `${t.polygons} polygons · mean confidence ${fmtTwo(t.mean_confidence)} · ΔNDVI ${fmtTwo(t.mean_ndvi_delta)}`,
            },
          }))}
          colorDomain={DOMAINS.changeType}
          monochrome={false}
          height={240}
          valueFormat={(v) => `${fmtInt(v)} ha`}
          valueLabel="area changed"
          note="Rotation between grass and arable is the largest gross signal any two-epoch land-cover diff picks up, but urbanisation is the larger net one — separating those is exactly what the transition matrix above is for."
        />
      )}

      {subsidence.data && (
        <>
          <BarChart
            title="Ground motion by soil type"
            subtitle="InSAR persistent-scatterer velocity; negative is subsidence"
            data={subsidence.data.bySoil.map((r) => ({
              category: r.soil_type,
              value: r.mean_velocity_mm_yr,
              secondary: {
                label: 'detail',
                value: `median ${fmtTwo(r.median_mm_yr)} · fastest ${fmtTwo(r.fastest_mm_yr)} mm/yr · ${fmtInt(r.points)} scatterers`,
              },
            }))}
            horizontal
            height={210}
            valueFormat={(v) => `${fmtTwo(v)} mm/yr`}
            valueLabel="mean velocity"
            note="Drained peat oxidises and compacts, so the western polder sinks roughly an order of magnitude faster than the glacial sand of the Heuvelrug ridge in the east. This is the one analysis here with a specifically Dutch answer."
          />
          <BarChart
            title="Ground motion by land use"
            subtitle="Where the movement has something built on top of it"
            data={subsidence.data.byLandUse.map((r) => ({
              category: r.land_use,
              value: r.mean_cumulative_mm,
              secondary: {
                label: 'rate',
                value: `${fmtTwo(r.mean_velocity_mm_yr)} mm/yr over ${fmtInt(r.points)} scatterers`,
              },
            }))}
            height={210}
            valueFormat={(v) => `${fmtOne(v)} mm`}
            valueLabel="cumulative displacement"
            note="Persistent scatterers need a stable reflector, so coverage is dense over built-up ground and sparse over farmland — a real limitation of the technique, not of this dataset."
          />
          {(subsidence.data.profiles?.length ?? 0) > 0 && (
            <BarChart
              title="Infrastructure at risk from differential settlement"
              subtitle="Corridors ranked by how unevenly the ground moves along them, not by how fast"
              data={(subsidence.data.profiles ?? []).slice(0, 10).map((p) => ({
                category: p.name,
                value: p.differential_mm_yr,
                secondary: {
                  label: 'profile',
                  value: `${p.asset_type} · ${fmtOne(p.length_km)} km · mean ${fmtTwo(p.mean_velocity_mm_yr)} mm/yr · mostly ${p.dominant_soil}`,
                },
              }))}
              horizontal
              height={300}
              valueFormat={(v) => `${fmtTwo(v)} mm/yr`}
              valueLabel="differential settlement"
              note="A structure sinking uniformly is far less of a problem than one sinking unevenly — it is the difference along a corridor that opens joints and cracks embankments. The worst cases here are the routes that cross from polder peat onto the sand ridge, where the two ends settle at different rates."
            />
          )}
        </>
      )}

      {waterSeries.length > 0 && (
        <LineChart
          title="Water extent through the year"
          subtitle="Open water delineated from Sentinel-1 backscatter on each pass"
          series={waterSeries}
          isTime
          yFormat={(v) => `${fmtInt(v)} ha`}
          height={240}
          note="Permanent water is the reference level and barely moves. The February excursion is the inundation signal — and it is visible precisely because radar is unaffected by the weather that produced it."
        />
      )}
    </ProjectShell>
  );
}
