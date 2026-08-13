import { useState } from 'react';

import type { CorrelationResult } from '@/api/types';
import { BarChart } from '@/components/charts/BarChart';
import { fmtCurrency, fmtInt, fmtOne, fmtTwo } from '@/components/charts/chartkit';
import { PopulationPyramid, type AgeBand } from '@/components/charts/PopulationPyramid';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { ScatterPlot } from '@/components/charts/ScatterPlot';
import { StackedBar } from '@/components/charts/StackedBar';
import { ProjectShell, Selector } from '@/components/ProjectShell';
import { useApiQuery } from '@/hooks/useApi';

interface DemogSummary {
  tract_count: number;
  total_population: number;
  total_households: number;
  total_area_km2: number;
  overall_density: number;
  mean_median_age: number;
  median_income: number;
  mean_unemployment: number;
  mean_pct_65_plus: number;
  mean_deprivation: number;
}

interface RankRow {
  id: number;
  tract_code: string;
  tract_name: string;
  district: string;
  population: number;
  value: number;
}

interface CommuteMatrix {
  topFlows: Array<{ origin_code: string; dest_code: string; mode: string; trips: number; duration_min: number; distance_km: number }>;
  modalSplit: Array<{ mode: string; trips: number; mean_duration_min: number; mean_distance_km: number; share_pct: number }>;
  totalTrips: number;
}

interface AgeComposition {
  tract_code: string;
  tract_name: string;
  population: number;
  under_15: number;
  age_15_29: number;
  age_30_44: number;
  age_45_64: number;
  age_65_plus: number;
}

const METRICS = [
  { value: 'density_km2', label: 'Population density (per km²)' },
  { value: 'median_income', label: 'Median income (€)' },
  { value: 'deprivation_index', label: 'Deprivation index' },
  { value: 'unemployment_rate', label: 'Unemployment rate (%)' },
  { value: 'median_rent', label: 'Median rent (€)' },
  { value: 'pct_65_plus', label: 'Share aged 65+ (%)' },
];

const DRIVERS = [
  { value: 'pct_tertiary_educated', label: 'Tertiary education (%)' },
  { value: 'unemployment_rate', label: 'Unemployment rate (%)' },
  { value: 'pct_owner_occupied', label: 'Owner occupied (%)' },
  { value: 'density_km2', label: 'Population density' },
  { value: 'median_age', label: 'Median age' },
];

export function DemographicsProject() {
  const [metric, setMetric] = useState('density_km2');
  const [driver, setDriver] = useState('pct_tertiary_educated');

  const summary = useApiQuery<DemogSummary>(['demog', 'summary'], '/demographics/summary');
  const pyramid = useApiQuery<AgeBand[]>(['demog', 'pyramid'], '/demographics/population-pyramid');
  const correlation = useApiQuery<CorrelationResult>(
    ['demog', 'corr', driver],
    `/demographics/income-vs-education?x=${driver}`,
  );
  const ranking = useApiQuery<RankRow[]>(
    ['demog', 'rank', metric],
    `/demographics/density-ranking?metric=${metric}&limit=15`,
  );
  const commute = useApiQuery<CommuteMatrix>(['demog', 'commute'], '/demographics/commute-matrix');
  const composition = useApiQuery<AgeComposition[]>(['demog', 'composition'], '/demographics/age-composition?limit=16');

  const s = summary.data;
  const metricLabel = METRICS.find((m) => m.value === metric)?.label ?? metric;
  const isCurrency = metric === 'median_income' || metric === 'median_rent';

  return (
    <ProjectShell
      project="demographics"
      title="Population & Socio-Economic Atlas"
      tagline="Census structure, deprivation and commuting patterns across 60 Utrecht neighbourhoods"
      defaultLayers={['demog_tracts', 'demog_flows']}
      initialView={{ center: [5.1214, 52.0907], zoom: 10.4 }}
      colorOverrides={{ demog_tracts: metric === 'median_rent' ? 'density_km2' : metric }}
      controls={
        <>
          <Selector label="Map & ranking metric" value={metric} onChange={setMetric} options={METRICS} />
          <Selector label="Income driver" value={driver} onChange={setDriver} options={DRIVERS} />
        </>
      }
    >
      {s && (
        <StatRow>
          <StatTile label="Population" value={s.total_population} />
          <StatTile label="Households" value={s.total_households} />
          <StatTile label="Density" value={fmtInt(s.overall_density)} unit=" /km²" />
          <StatTile label="Median income" value={fmtCurrency(s.median_income)} />
          <StatTile label="Aged 65+" value={`${fmtOne(s.mean_pct_65_plus)}%`} hint={`median age ${fmtOne(s.mean_median_age)}`} />
        </StatRow>
      )}

      {pyramid.data && pyramid.data.length > 0 && (
        <PopulationPyramid
          title="Age and sex structure"
          subtitle="All neighbourhoods combined, five-year bands"
          bands={pyramid.data}
          note="The bulge in the 20–34 bands is the student and early-career population that a university city carries."
        />
      )}

      {correlation.data && correlation.data.points.length > 0 && (
        <ScatterPlot
          title="What predicts neighbourhood income"
          subtitle="One point per neighbourhood; point size is population"
          data={correlation.data.points.map((p) => ({
            x: p.x,
            y: p.y,
            label: String(p.tract_name ?? p.tract_code ?? ''),
            size: typeof p.size === 'number' ? p.size : undefined,
          }))}
          xLabel={DRIVERS.find((d) => d.value === driver)?.label ?? driver}
          yLabel="median income (€)"
          yFormat={(v) => fmtCurrency(v)}
          note={
            <>
              Pearson r = <strong>{fmtTwo(correlation.data.pearson_r ?? 0)}</strong>, R² ={' '}
              <strong>{fmtTwo(correlation.data.r_squared ?? 0)}</strong> over{' '}
              {correlation.data.n} neighbourhoods.
            </>
          }
        />
      )}

      {ranking.data && (
        <BarChart
          title={`Neighbourhoods ranked by ${metricLabel.toLowerCase()}`}
          subtitle="Top 15"
          data={ranking.data.map((r) => ({
            category: r.tract_name,
            value: r.value,
            secondary: { label: 'population', value: fmtInt(r.population) },
          }))}
          horizontal
          height={380}
          valueFormat={isCurrency ? (v) => fmtCurrency(v) : (v) => fmtInt(v)}
          valueLabel={metricLabel}
        />
      )}

      {commute.data && (
        <>
          <BarChart
            title="Modal split"
            subtitle={`${fmtInt(commute.data.totalTrips)} modelled daily trips between neighbourhoods`}
            data={commute.data.modalSplit.map((m) => ({
              category: m.mode,
              value: m.share_pct,
              secondary: {
                label: 'mean trip',
                value: `${fmtOne(m.mean_distance_km)} km · ${fmtOne(m.mean_duration_min)} min`,
              },
            }))}
            valueFormat={(v) => `${fmtOne(v)}%`}
            valueLabel="share of trips"
            height={220}
            note="Bike carries a share here that would be extraordinary almost anywhere outside the Netherlands — short trips overwhelmingly go by bike, and car share only takes over past about 8 km."
          />
          <BarChart
            title="Strongest origin–destination pairs"
            subtitle="Highest-volume flows, drawn as desire lines on the map"
            data={commute.data.topFlows.slice(0, 10).map((f) => ({
              category: `${f.origin_code}→${f.dest_code}`,
              value: f.trips,
              secondary: { label: 'mode', value: `${f.mode} · ${fmtOne(f.distance_km)} km` },
            }))}
            horizontal
            height={300}
            valueFormat={fmtInt}
            valueLabel="daily trips"
          />
        </>
      )}

      {composition.data && composition.data.length > 0 && (
        <StackedBar
          title="Age composition of the largest neighbourhoods"
          subtitle="Share of residents in each broad age band"
          data={composition.data.map((c) => ({
            tract: c.tract_name,
            'under 15': c.under_15,
            '15–29': c.age_15_29,
            '30–44': c.age_30_44,
            '45–64': c.age_45_64,
            '65+': c.age_65_plus,
          }))}
          categoryKey="tract"
          keys={['under 15', '15–29', '30–44', '45–64', '65+']}
          percent
          height={340}
        />
      )}
    </ProjectShell>
  );
}
