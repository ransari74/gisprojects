import { useMemo, useState } from 'react';

import { BarChart } from '@/components/charts/BarChart';
import { fmtInt, fmtOne } from '@/components/charts/chartkit';
import { LineChart } from '@/components/charts/LineChart';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery } from '@/hooks/useApi';
import { DOMAINS, STATUS } from '@/styles/theme';

interface TransportSummary {
  segment_count: number;
  network_km: number;
  mean_congestion: number;
  mean_speed_limit: number;
  total_aadt: number;
  total_accidents: number;
  bike_lane_pct: number;
  route_count: number;
  stop_count: number;
  daily_ridership: number;
  mean_headway_min: number;
  accessible_stop_pct: number;
}

interface ClassRow {
  highway_class: string;
  segments: number;
  length_km: number;
  mean_aadt: number;
  mean_congestion: number;
  accidents: number;
  accidents_per_km: number;
}

interface HourRow {
  hour: number;
  vehicles: number;
  mean_vehicles: number;
  mean_speed: number;
  segments: number;
}

interface CongestionRow {
  id: number;
  name: string;
  highway_class: string;
  congestion_index: number;
  aadt: number;
  peak_speed_kmh: number;
  maxspeed_kmh: number;
  speed_loss_pct: number;
  accidents: number;
}

interface Ridership {
  byMode: Array<{ mode: string; routes: number; ridership: number; length_km: number; mean_headway_min: number; riders_per_km: number }>;
  topRoutes: Array<{ route_code: string; route_name: string; mode: string; ridership: number; headway_min: number }>;
}

interface Accessibility {
  byModeAndTime: Array<{ mode: string; minutes: number; catchments: number; mean_area_km2: number; mean_population: number; mean_jobs: number }>;
  walk15Coverage: { total_population: number; covered_population: number; covered_pct: number };
}

const ROAD_CLASSES = [
  { value: '', label: 'All classes' },
  { value: 'motorway', label: 'Motorway' },
  { value: 'trunk', label: 'Trunk' },
  { value: 'primary', label: 'Primary' },
  { value: 'secondary', label: 'Secondary' },
  { value: 'residential', label: 'Residential' },
];

const INITIAL_VIEW = { center: [5.10, 52.09] as [number, number], zoom: 13.6 };
const OVERLAY_IDS = ['protected_areas', 'waterways'];

export function TransportProject() {
  const [colorBy, setColorBy] = useState('congestion_index');
  const [classFilter, setClassFilter] = useState('');
  const [isoMode, setIsoMode] = useState('walk');

  const summary = useApiQuery<TransportSummary>(['transport', 'summary'], '/transport/summary');
  const byClass = useApiQuery<ClassRow[]>(['transport', 'by-class'], '/transport/network-by-class');
  const hourly = useApiQuery<HourRow[]>(
    ['transport', 'hourly', classFilter],
    `/transport/hourly-profile${classFilter ? `?highway_class=${classFilter}` : ''}`,
  );
  const congestion = useApiQuery<CongestionRow[]>(['transport', 'congestion'], '/transport/congestion-ranking?limit=12');
  const ridership = useApiQuery<Ridership>(['transport', 'ridership'], '/transport/transit-ridership');
  const access = useApiQuery<Accessibility>(['transport', 'access'], '/transport/accessibility');

  const hourlySeries = useMemo(
    () => [
      {
        name: 'vehicles counted',
        points: (hourly.data ?? []).map((h) => ({ x: h.hour, y: h.vehicles })),
      },
    ],
    [hourly.data],
  );

  // Speed is a different unit from volume, so it gets its own chart rather
  // than a second y-axis on the volume chart.
  const speedSeries = useMemo(
    () => [
      {
        name: 'mean speed (km/h)',
        points: (hourly.data ?? []).map((h) => ({ x: h.hour, y: h.mean_speed })),
      },
    ],
    [hourly.data],
  );

  const isoRows = useMemo(
    () => (access.data?.byModeAndTime ?? []).filter((r) => r.mode === isoMode),
    [access.data, isoMode],
  );

  const s = summary.data;
  const colorOverrides = useMemo(() => ({ transport_roads: colorBy }), [colorBy]);
  const tileFilters = useMemo(
    () => ({
      transport_isochrones: { filter_mode: isoMode, filter_minutes: '15' },
      ...(classFilter ? { transport_roads: { filter_highway_class: classFilter } } : {}),
    }),
    [isoMode, classFilter],
  );

  return (
    <ProjectShell
      project="transport"
      title="Multimodal Transport Network Analytics"
      tagline="Road congestion, transit ridership and walk-time accessibility across the Utrecht network"
      defaultLayers={['transport_roads', 'transport_stops']}
      initialView={INITIAL_VIEW}
      overlayIds={OVERLAY_IDS}
      colorOverrides={colorOverrides}
      tileFilters={tileFilters}
      controls={
        <>
          <Selector
            label="Colour roads by"
            value={colorBy}
            onChange={setColorBy}
            options={[
              { value: 'congestion_index', label: 'Congestion index' },
              { value: 'highway_class', label: 'Road class' },
              { value: 'aadt', label: 'Daily traffic' },
            ]}
          />
          <Selector label="Filter road class" value={classFilter} onChange={setClassFilter} options={ROAD_CLASSES} />
          <Selector
            label="Isochrone mode"
            value={isoMode}
            onChange={setIsoMode}
            options={[
              { value: 'walk', label: 'Walk' },
              { value: 'bike', label: 'Bike' },
              { value: 'transit', label: 'Transit' },
              { value: 'car', label: 'Car' },
            ]}
          />
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile label="Network" value={fmtInt(s.network_km)} unit=" km" hint={`${fmtInt(s.segment_count)} segments`} />
          <StatTile label="Mean congestion" value={fmtOne(s.mean_congestion * 100)} unit="%" />
          <StatTile label="Transit ridership" value={fmtInt(s.daily_ridership)} unit=" /day" hint={`${s.route_count} routes`} />
          <StatTile label="Bike-lane coverage" value={`${fmtOne(s.bike_lane_pct)}%`} hint="of network length" />
          <StatTile
            label="Accessible stops"
            value={`${fmtOne(s.accessible_stop_pct)}%`}
            hint={`${fmtInt(s.stop_count)} stops`}
            accent={s.accessible_stop_pct > 70 ? STATUS.good : STATUS.warning}
          />
        </StatRow>
      )}

      {hourlySeries[0].points.length > 0 && (
        <>
          <LineChart
            title={`Hourly traffic profile${classFilter ? ` — ${classFilter}` : ''}`}
            subtitle="Vehicles counted per hour across all instrumented segments, one work week"
            series={hourlySeries}
            area
            yFormat={(v) => fmtInt(v)}
            xFormat={(v) => `${String(v).padStart(2, '0')}:00`}
            height={250}
            note="Two peaks, at roughly 08:00 and 17:00 — the commuter signature."
          />
          <LineChart
            title="Mean speed through the day"
            subtitle="Same segments, same week — speed is a different unit, so it gets its own axis rather than sharing the volume chart"
            series={speedSeries}
            yFormat={(v) => `${fmtOne(v)} km/h`}
            xFormat={(v) => `${String(v).padStart(2, '0')}:00`}
            height={220}
            note="Speed troughs line up with the volume peaks — the same congestion, seen from the other side."
          />
        </>
      )}

      {byClass.data && (
        <BarChart
          title="Network length by road class"
          subtitle="Where the kilometres actually are"
          data={byClass.data.map((r) => ({
            category: r.highway_class,
            value: r.length_km,
            secondary: {
              label: 'traffic',
              value: `${fmtInt(r.mean_aadt)} AADT · congestion ${fmtOne(r.mean_congestion * 100)}%`,
            },
          }))}
          colorDomain={DOMAINS.highwayClass}
          monochrome={false}
          horizontal
          height={320}
          valueFormat={(v) => `${fmtOne(v)} km`}
          valueLabel="length"
        />
      )}

      {congestion.data && (
        <BarChart
          title="Most congested corridors"
          subtitle="Ranked by congestion index; the tooltip shows how much peak speed is lost"
          data={congestion.data.map((r) => ({
            category: `${r.name} (${r.highway_class})`,
            value: r.congestion_index * 100,
            secondary: {
              label: 'speed loss',
              value: `${fmtOne(r.speed_loss_pct)}% · ${fmtInt(r.aadt)} AADT · ${r.accidents} accidents`,
            },
          }))}
          horizontal
          height={340}
          valueFormat={(v) => `${fmtOne(v)}%`}
          valueLabel="congestion"
        />
      )}

      {ridership.data && (
        <BarChart
          title="Transit ridership by mode"
          subtitle="Daily boardings, and how efficiently each mode carries them per route-km"
          data={ridership.data.byMode.map((m) => ({
            category: m.mode,
            value: m.ridership,
            secondary: {
              label: 'intensity',
              value: `${fmtInt(m.riders_per_km)} riders/km · ${m.routes} routes · ${fmtOne(m.mean_headway_min)} min headway`,
            },
          }))}
          colorDomain={DOMAINS.transitMode}
          monochrome={false}
          valueFormat={fmtInt}
          valueLabel="daily boardings"
          height={230}
        />
      )}

      {access.data && (
        <>
          <StatRow>
            <StatTile
              label="Population within a 15-minute walk of transit"
              value={`${access.data.walk15Coverage.covered_pct}%`}
              hint={`${fmtInt(access.data.walk15Coverage.covered_population)} of ${fmtInt(access.data.walk15Coverage.total_population)} residents`}
            />
          </StatRow>
          {isoRows.length > 0 && (
            <BarChart
              title={`Population reachable — ${isoMode}`}
              subtitle="Mean residents inside the catchment, by travel-time cut-off"
              data={isoRows.map((r) => ({
                category: `${r.minutes} min`,
                value: r.mean_population,
                secondary: {
                  label: 'catchment',
                  value: `${fmtOne(r.mean_area_km2)} km² · ${fmtInt(r.mean_jobs)} jobs`,
                },
              }))}
              valueFormat={fmtInt}
              valueLabel="mean population reached"
              height={220}
              note="Catchments grow with the square of travel time, so each step up the axis is worth far more than the one before it."
            />
          )}
        </>
      )}
    </ProjectShell>
  );
}
