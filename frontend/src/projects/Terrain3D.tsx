import { useMemo, useState } from 'react';

import { BarChart } from '@/components/charts/BarChart';
import { fmtInt, fmtOne } from '@/components/charts/chartkit';
import { Histogram } from '@/components/charts/Histogram';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { ProfileChart, type ProfilePoint } from '@/components/charts/ProfileChart';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery, useTerrainConfig } from '@/hooks/useApi';
import { DOMAINS } from '@/styles/theme';

interface TerrainSummary {
  building_count: number;
  mean_height_m: number;
  max_height_m: number;
  median_height_m: number;
  mean_levels: number;
  footprint_ha: number;
  built_volume_mm3: number;
  mean_solar_kwh_m2: number;
  mean_shadow_index: number;
  min_elev_m: number;
  max_elev_m: number;
  contour_count: number;
}

interface HeightDist {
  min: number;
  max: number;
  bins: Array<{ x0: number; x1: number; count: number; meanLevels: number }>;
}

interface TypeRow {
  building_type: string;
  buildings: number;
  mean_height_m: number;
  max_height_m: number;
  footprint_ha: number;
  volume_mm3: number;
  mean_solar: number;
  mean_shadow: number;
}

interface Hypsometry {
  label: string;
  min_m: number;
  max_m: number;
  color_hex: string;
  area_km2: number;
  share_pct: number;
  cumulative_pct: number;
}

interface Profile {
  transectId: string | null;
  available: string[];
  points: ProfilePoint[];
}

interface SolarRow {
  id: number;
  name: string | null;
  building_type: string;
  height_m: number;
  footprint_m2: number;
  solar_kwh_m2: number;
  annual_mwh: number;
  energy_class: string;
}

export function Terrain3DProject() {
  const [exaggeration, setExaggeration] = useState('2.5');
  const [colorBy, setColorBy] = useState('height_m');
  const [transect, setTransect] = useState<string | null>(null);

  const terrainConfig = useTerrainConfig();
  const summary = useApiQuery<TerrainSummary>(['terrain', 'summary'], '/terrain/summary');
  const heights = useApiQuery<HeightDist>(['terrain', 'heights'], '/terrain/height-distribution?bins=22');
  const byType = useApiQuery<TypeRow[]>(['terrain', 'by-type'], '/terrain/by-type');
  const hypso = useApiQuery<Hypsometry[]>(['terrain', 'hypso'], '/terrain/hypsometry');
  const profile = useApiQuery<Profile>(
    ['terrain', 'profile', transect ?? 'default'],
    `/terrain/profile${transect ? `?transect_id=${encodeURIComponent(transect)}` : ''}`,
  );
  const solar = useApiQuery<SolarRow[]>(['terrain', 'solar'], '/terrain/solar-ranking?limit=12');

  const transectOptions = useMemo(
    () =>
      (profile.data?.available ?? []).map((t) => ({
        value: t,
        label: t.replace(/^T\d+-/, '').replace(/_/g, ' '),
      })),
    [profile.data?.available],
  );

  const s = summary.data;

  return (
    <ProjectShell
      project="terrain"
      title="3D Terrain & Urban Massing"
      tagline="Extruded building model draped over Copernicus DEM terrain — polder below sea level in the west, the Utrechtse Heuvelrug ridge in the east"
      defaultLayers={['terrain_buildings', 'terrain_contours']}
      // Building footprints tile from z14, and the extrusions only read as
      // a city model close in.
      initialView={{ center: [5.1214, 52.0907], zoom: 14.6 }}
      colorOverrides={{ terrain_buildings: colorBy }}
      terrain={terrainConfig.data ?? null}
      terrainExaggeration={Number(exaggeration)}
      pitch={58}
      controls={
        <>
          <Selector
            label="Colour buildings by"
            value={colorBy}
            onChange={setColorBy}
            options={[
              { value: 'height_m', label: 'Height' },
              { value: 'building_type', label: 'Building type' },
              { value: 'year_built', label: 'Year built' },
            ]}
          />
          <Selector
            label="Terrain exaggeration"
            value={exaggeration}
            onChange={setExaggeration}
            options={[
              { value: '1', label: '1× (true scale)' },
              { value: '1.5', label: '1.5×' },
              { value: '2.5', label: '2.5×' },
              { value: '4', label: '4×' },
            ]}
          />
          {transectOptions.length > 0 && (
            <Selector
              label="Transect"
              value={transect ?? profile.data?.transectId ?? transectOptions[0].value}
              onChange={setTransect}
              options={transectOptions}
            />
          )}
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile label="Buildings" value={s.building_count} />
          <StatTile label="Median height" value={s.median_height_m} unit=" m" hint={`tallest ${fmtOne(s.max_height_m)} m`} />
          <StatTile label="Built volume" value={fmtOne(s.built_volume_mm3)} unit=" Mm³" />
          <StatTile label="Relief" value={`${fmtOne(s.min_elev_m)} – ${fmtOne(s.max_elev_m)}`} unit=" m" hint="above NAP" />
          <StatTile label="Mean roof solar" value={fmtInt(s.mean_solar_kwh_m2)} unit=" kWh/m²" />
        </StatRow>
      )}

      {profile.data && profile.data.points.length > 1 && (
        <ProfileChart
          title="Terrain and skyline transect"
          subtitle="West-to-east section: terrain surface with the built massing layered on top"
          points={profile.data.points}
          note="The ground climbs roughly 45 m from the western polder onto the ice-pushed Heuvelrug ridge — the whole relief of the province in one section."
        />
      )}

      {heights.data && heights.data.bins.length > 0 && (
        <Histogram
          title="Building height distribution"
          subtitle="How the city's massing is actually distributed"
          bins={heights.data.bins}
          xLabel="height (m)"
          xFormat={(v) => `${fmtOne(v)} m`}
          markers={s ? [{ value: s.median_height_m, label: `median ${fmtOne(s.median_height_m)} m` }] : []}
          note="A long right tail: most of the stock is low-rise, and a handful of towers set the maximum."
        />
      )}

      {byType.data && (
        <>
          <BarChart
            title="Built volume by building type"
            subtitle="Where the city's mass sits, by use class"
            data={byType.data.map((r) => ({
              category: r.building_type,
              value: r.volume_mm3,
              secondary: {
                label: 'stock',
                value: `${fmtInt(r.buildings)} buildings · mean ${fmtOne(r.mean_height_m)} m`,
              },
            }))}
            colorDomain={DOMAINS.buildingType}
            monochrome={false}
            horizontal
            height={300}
            valueFormat={(v) => `${fmtOne(v)} Mm³`}
            valueLabel="volume"
          />
          <BarChart
            title="Rooftop solar potential by type"
            subtitle="Mean annual irradiation on the roof plane, after self-shading"
            data={byType.data.map((r) => ({
              category: r.building_type,
              value: r.mean_solar,
              secondary: { label: 'shading', value: `shadow index ${fmtOne(r.mean_shadow * 100)}%` },
            }))}
            valueFormat={(v) => `${fmtInt(v)}`}
            valueLabel="kWh/m²/yr"
            height={240}
          />
        </>
      )}

      {hypso.data && (
        <BarChart
          title="Hypsometry — land area by elevation band"
          subtitle="How much of the study area sits at each height above NAP"
          data={hypso.data.map((b) => ({
            category: b.label,
            value: b.area_km2,
            secondary: { label: 'cumulative', value: `${fmtOne(b.cumulative_pct)}% of area at or below` },
          }))}
          horizontal
          height={280}
          valueFormat={(v) => `${fmtOne(v)} km²`}
          valueLabel="area"
          note="Roughly a quarter of the study area sits below NAP — normal for the Dutch polder landscape, and the reason the drainage network in the agriculture project exists at all."
        />
      )}

      {solar.data && (
        <BarChart
          title="Best rooftop solar candidates"
          subtitle="Ranked by total annual yield: irradiation × roof area"
          data={solar.data.map((r) => ({
            category: r.name ?? `${r.building_type} #${r.id}`,
            value: r.annual_mwh,
            secondary: {
              label: 'roof',
              value: `${fmtInt(r.footprint_m2)} m² · ${fmtInt(r.solar_kwh_m2)} kWh/m² · class ${r.energy_class}`,
            },
          }))}
          horizontal
          height={340}
          valueFormat={(v) => `${fmtInt(v)} MWh`}
          valueLabel="annual yield"
        />
      )}
    </ProjectShell>
  );
}
