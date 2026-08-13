import { useMemo, useState } from 'react';

import { BarChart } from '@/components/charts/BarChart';
import { BoxPlot } from '@/components/charts/BoxPlot';
import { fmtCurrency, fmtInt, fmtOne } from '@/components/charts/chartkit';
import { LineChart } from '@/components/charts/LineChart';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { StackedBar } from '@/components/charts/StackedBar';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery } from '@/hooks/useApi';
import { DOMAINS } from '@/styles/theme';

interface ParcelSummary {
  parcel_count: number;
  total_area_km2: number;
  mean_lot_m2: number;
  total_value_m: number;
  mean_value_per_m2: number;
  median_value_per_m2: number;
  mean_far: number;
  total_units: number;
  tax_exempt_count: number;
  vacant_count: number;
}

interface LandUseRow {
  land_use: string;
  parcels: number;
  area_ha: number;
  value_m: number;
  mean_value_per_m2: number;
  mean_far: number;
  units: number;
}

interface ValueDistRow {
  category: string;
  n: number;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
}

interface PriceTrendRow {
  month: string;
  sales: number;
  median_price_m2: number;
  mean_price_m2: number;
  volume_m: number;
}

interface AgeRow {
  decade: number;
  land_use: string;
  parcels: number;
}

interface ZoningCompliance {
  byCategory: Array<{
    zone_category: string;
    parcels: number;
    over_far: number;
    mean_far: number;
    mean_max_far: number;
    mean_unused_far: number;
  }>;
  totalParcels: number;
  totalOverFar: number;
}

// Hoisted: parcels only tile from z13, so this project needs a fixed close-in
// view rather than the study-area fit. A literal here would otherwise create
// a fresh object every render and needlessly invalidate the map's layer sync.
const INITIAL_VIEW = { center: [5.1214, 52.0907] as [number, number], zoom: 14.2 };

export function ParcelProject() {
  const [groupBy, setGroupBy] = useState('land_use');
  const [colorBy, setColorBy] = useState('value_per_m2');

  const summary = useApiQuery<ParcelSummary>(['parcel', 'summary'], '/parcel/summary');
  const landUse = useApiQuery<LandUseRow[]>(['parcel', 'land-use'], '/parcel/land-use-breakdown');
  const valueDist = useApiQuery<ValueDistRow[]>(
    ['parcel', 'value-dist', groupBy],
    `/parcel/value-distribution?by=${groupBy}`,
  );
  const trend = useApiQuery<PriceTrendRow[]>(['parcel', 'price-trend'], '/parcel/price-trend');
  const ages = useApiQuery<AgeRow[]>(['parcel', 'age'], '/parcel/building-age-profile');
  const compliance = useApiQuery<ZoningCompliance>(['parcel', 'compliance'], '/parcel/zoning-compliance');

  // Pivot decade x land-use into one row per decade for the stacked bars.
  const ageStack = useMemo(() => {
    const rows = ages.data ?? [];
    const uses = [...new Set(rows.map((r) => r.land_use))];
    const byDecade = new Map<number, Record<string, number | string>>();
    for (const row of rows) {
      if (!byDecade.has(row.decade)) {
        byDecade.set(row.decade, { decade: `${row.decade}s` });
      }
      byDecade.get(row.decade)![row.land_use] = row.parcels;
    }
    const data = [...byDecade.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([, row]) => row);
    // Keep the eight largest uses; the palette has eight slots and we never
    // invent a ninth hue.
    const totals = uses.map((u) => ({
      use: u,
      total: rows.filter((r) => r.land_use === u).reduce((a, r) => a + r.parcels, 0),
    }));
    const keys = totals.sort((a, b) => b.total - a.total).slice(0, 8).map((t) => t.use);
    return { data, keys };
  }, [ages.data]);

  const trendSeries = useMemo(
    () => [
      {
        name: 'median price per m²',
        points: (trend.data ?? []).map((r) => ({
          x: new Date(`${r.month}-01`),
          y: r.median_price_m2,
        })),
      },
    ],
    [trend.data],
  );

  const s = summary.data;
  const colorOverrides = useMemo(() => ({ parcel_parcels: colorBy }), [colorBy]);

  return (
    <ProjectShell
      project="parcel"
      title="Cadastral Parcel & Land Value Explorer"
      tagline="Zoning envelope, land use and assessed value across the Utrecht cadastre"
      defaultLayers={['parcel_zoning', 'parcel_parcels']}
      // Parcels only tile from z13; opening fitted to the whole province
      // would show zoning polygons over an empty cadastre.
      initialView={INITIAL_VIEW}
      colorOverrides={colorOverrides}
      controls={
        <>
          <Selector
            label="Colour parcels by"
            value={colorBy}
            onChange={setColorBy}
            options={[
              { value: 'value_per_m2', label: 'Value per m²' },
              { value: 'land_use', label: 'Land use' },
              { value: 'year_built', label: 'Year built' },
              { value: 'lot_area_m2', label: 'Lot area' },
            ]}
          />
          <Selector
            label="Compare value by"
            value={groupBy}
            onChange={setGroupBy}
            options={[
              { value: 'land_use', label: 'Land use' },
              { value: 'owner_type', label: 'Owner type' },
              { value: 'district', label: 'District' },
              { value: 'zone_code', label: 'Zone code' },
            ]}
          />
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile label="Parcels" value={s.parcel_count} />
          <StatTile label="Median value" value={fmtCurrency(s.median_value_per_m2)} unit=" /m²" />
          <StatTile label="Total assessed" value={`€${fmtOne(s.total_value_m)}M`} />
          <StatTile label="Dwelling units" value={s.total_units} />
          <StatTile label="Vacant lots" value={s.vacant_count} hint={`${s.tax_exempt_count} tax-exempt`} />
        </StatRow>
      )}

      {landUse.data && (
        <BarChart
          title="Land area by use class"
          subtitle="Where the cadastre's surface actually goes"
          data={landUse.data.map((r) => ({
            category: r.land_use,
            value: r.area_ha,
            secondary: {
              label: 'value',
              value: `€${fmtOne(r.value_m)}M across ${fmtInt(r.parcels)} parcels`,
            },
          }))}
          colorDomain={DOMAINS.landUse}
          monochrome={false}
          horizontal
          valueFormat={(v) => `${fmtInt(v)} ha`}
          valueLabel="area"
        />
      )}

      {valueDist.data && valueDist.data.length > 0 && (
        <BoxPlot
          title={`Value per m² by ${groupBy.replace(/_/g, ' ')}`}
          subtitle="Median, interquartile range and full spread — categories with the same mean can have very different spread"
          data={valueDist.data}
          valueLabel="€ per m²"
          valueFormat={(v) => fmtCurrency(v)}
        />
      )}

      {trendSeries[0].points.length > 0 && (
        <LineChart
          title="Median transaction price"
          subtitle="Monthly median sale price per m², all recorded transactions"
          series={trendSeries}
          isTime
          area
          yFormat={(v) => fmtCurrency(v)}
          note="The 2021–22 run-up and the 2023 correction are both visible — the shape of the Dutch market over the period."
        />
      )}

      {ageStack.data.length > 0 && (
        <StackedBar
          title="Building stock by construction decade"
          subtitle="Parcel count per decade, split by land use"
          data={ageStack.data}
          categoryKey="decade"
          keys={ageStack.keys}
          valueFormat={fmtInt}
          height={320}
        />
      )}

      {compliance.data && (
        <>
          <StatRow>
            <StatTile
              label="Parcels above their FAR cap"
              value={compliance.data.totalOverFar}
              hint={`of ${compliance.data.totalParcels.toLocaleString()} with a zoning match`}
            />
            <StatTile
              label="Share over cap"
              value={`${((100 * compliance.data.totalOverFar) / Math.max(compliance.data.totalParcels, 1)).toFixed(1)}%`}
            />
          </StatRow>
          <BarChart
            title="Unused development capacity"
            subtitle="Mean unbuilt floor area ratio remaining under the zoning cap, by district category"
            data={compliance.data.byCategory.map((r) => ({
              category: r.zone_category,
              value: r.mean_unused_far,
              secondary: {
                label: 'realised / cap',
                value: `${fmtOne(r.mean_far)} of ${fmtOne(r.mean_max_far)} · ${r.over_far} over`,
              },
            }))}
            valueFormat={(v) => v.toFixed(2)}
            valueLabel="unused FAR"
            note="Headroom under the adopted cap — the first screen a planner runs when looking for densification sites."
          />
        </>
      )}
    </ProjectShell>
  );
}
