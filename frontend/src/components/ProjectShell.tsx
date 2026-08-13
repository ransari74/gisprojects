/**
 * The layout every project page shares: map on the left, analytics rail on
 * the right, a layer panel over the map and a filter row above the charts.
 *
 * Centralising it means the five projects differ only in their layers and
 * their charts, which is the point -- the map plumbing is written once.
 */

import { useMemo, useState, type ReactNode } from 'react';

import type { LayerInfo, ProjectKey, StudyArea, TerrainTileConfig } from '@/api/types';
import { useCapabilities, useDatasetSources, useStudyArea } from '@/hooks/useApi';
import { CHROME, MAP_SEQUENTIAL_RAMP } from '@/styles/theme';
import { useInk, useMode } from './charts/chartkit';
import { EmptyState } from './charts/Primitives';
import { buildLegend } from './layerStyles';
import { MapView, type ActiveLayer } from './MapView';

interface ProjectShellProps {
  project: ProjectKey;
  title: string;
  tagline: string;
  /** Layers on by default; the rest are listed but unchecked. */
  defaultLayers: string[];
  /** Tile-level filters, forwarded to the MVT endpoint. */
  tileFilters?: Record<string, Record<string, string>>;
  colorOverrides?: Record<string, string>;
  terrain?: TerrainTileConfig | null;
  terrainExaggeration?: number;
  pitch?: number;
  /** Opens the camera here instead of fitting the study area. */
  initialView?: { center?: [number, number]; zoom: number } | null;
  /** Controls rendered above the chart rail. */
  controls?: ReactNode;
  children: ReactNode;
}

export function ProjectShell({
  project,
  title,
  tagline,
  defaultLayers,
  tileFilters,
  colorOverrides,
  terrain = null,
  terrainExaggeration = 1.5,
  pitch = 0,
  initialView = null,
  controls,
  children,
}: ProjectShellProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { data: capabilities, isLoading } = useCapabilities();
  const { data: studyArea } = useStudyArea();
  const { data: sources } = useDatasetSources(project);

  const projectLayers: LayerInfo[] = useMemo(
    () => capabilities?.projects.find((p) => p.key === project)?.layers ?? [],
    [capabilities, project],
  );

  const [enabled, setEnabled] = useState<Set<string>>(new Set(defaultLayers));
  const [showSources, setShowSources] = useState(false);

  const active: ActiveLayer[] = useMemo(
    () =>
      projectLayers.map((info) => ({
        info,
        visible: enabled.has(info.name),
        filters: tileFilters?.[info.name],
        colorBy: colorOverrides?.[info.name],
      })),
    [projectLayers, enabled, tileFilters, colorOverrides],
  );

  const legends = useMemo(
    () =>
      active
        .filter((l) => l.visible)
        .map((l) => ({ layer: l.info, legend: buildLegend(l.info, mode, l.colorBy) }))
        .filter((l) => l.legend !== null),
    [active, mode],
  );

  function toggle(name: string) {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  if (isLoading) {
    return <div className="project-loading" style={{ color: ink.textMuted }}>Loading layers…</div>;
  }

  if (!projectLayers.length) {
    return (
      <div className="project-page">
        <EmptyState message="You do not have permission to view this project's layers." />
      </div>
    );
  }

  return (
    <div className="project-page">
      <header className="project-header">
        <div>
          <h1 style={{ color: ink.textPrimary }}>{title}</h1>
          <p style={{ color: ink.textSecondary }}>{tagline}</p>
        </div>
        <button
          type="button"
          className="ghost-button"
          onClick={() => setShowSources((v) => !v)}
          style={{ color: ink.textSecondary, borderColor: ink.border }}
        >
          {showSources ? 'Hide' : 'Show'} data sources
        </button>
      </header>

      {showSources && sources && (
        <div className="sources-panel" style={{ background: ink.surface, borderColor: ink.border }}>
          <table className="data-table">
            <thead>
              <tr>
                {['Dataset', 'Provider', 'Licence', 'Features'].map((h) => (
                  <th key={h} style={{ color: ink.textSecondary, borderColor: ink.grid }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <tr key={`${s.layer}-${s.dataset_name}`}>
                  <td style={{ color: ink.textPrimary, borderColor: ink.grid }}>
                    {s.source_url ? (
                      <a href={s.source_url} target="_blank" rel="noreferrer noopener">{s.dataset_name}</a>
                    ) : (
                      s.dataset_name
                    )}
                  </td>
                  <td style={{ color: ink.textSecondary, borderColor: ink.grid }}>{s.provider ?? '—'}</td>
                  <td style={{ color: ink.textSecondary, borderColor: ink.grid }}>{s.license ?? '—'}</td>
                  <td className="num" style={{ color: ink.textSecondary, borderColor: ink.grid }}>
                    {s.feature_count?.toLocaleString() ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="figure-note" style={{ color: ink.textMuted }}>
            The running instance is loaded with a synthetic stand-in that mirrors these datasets'
            schema and distributions. Point <code>etl/download.py</code> at the URLs above to load
            the real extracts.
          </p>
        </div>
      )}

      <div className="project-body">
        <section className="map-pane">
          <MapView
            layers={active}
            studyArea={studyArea as StudyArea | null}
            terrain={terrain}
            terrainExaggeration={terrainExaggeration}
            pitch={pitch}
            initialView={initialView}
          />

          <div className="layer-panel" style={{ background: ink.surface, borderColor: ink.border }}>
            <div className="layer-panel-title" style={{ color: ink.textSecondary }}>Layers</div>
            {projectLayers.map((info) => (
              <label key={info.name} className="layer-row" title={info.description}>
                <input
                  type="checkbox"
                  checked={enabled.has(info.name)}
                  onChange={() => toggle(info.name)}
                />
                <span style={{ color: ink.textPrimary }}>{info.title}</span>
                <span className={`geom-chip geom-${info.geomKind}`} style={{ borderColor: ink.border, color: ink.textMuted }}>
                  {info.geomKind}
                </span>
              </label>
            ))}
          </div>

          {legends.length > 0 && (
            <div className="map-legend" style={{ background: ink.surface, borderColor: ink.border }}>
              {legends.map(({ layer, legend }) => (
                <div key={layer.name} className="map-legend-block">
                  <div className="map-legend-title" style={{ color: ink.textSecondary }}>
                    {layer.title} · {legend!.title}
                  </div>
                  {legend!.kind === 'categorical' ? (
                    <ul className="legend compact">
                      {legend!.entries.map((e) => (
                        <li key={e.label} style={{ color: ink.textSecondary }}>
                          <span className="legend-swatch" style={{ background: e.color }} aria-hidden="true" />
                          {e.label}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <div className="seq-legend inline">
                      <div
                        className="seq-legend-bar"
                        style={{
                          background: `linear-gradient(to right, ${MAP_SEQUENTIAL_RAMP.join(', ')})`,
                          borderColor: ink.border,
                        }}
                      />
                      <div className="seq-legend-scale" style={{ color: ink.textMuted }}>
                        <span>{legend!.range?.[0].toLocaleString()}</span>
                        <span>{legend!.range?.[1].toLocaleString()}</span>
                      </div>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="analytics-pane" style={{ background: CHROME[mode].page }}>
          {controls && <div className="control-row">{controls}</div>}
          {children}
        </section>
      </div>
    </div>
  );
}

/** A labelled select for the control row. */
export function Selector({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
}) {
  const mode = useMode();
  const ink = useInk(mode);
  return (
    <label className="selector" style={{ color: ink.textSecondary }}>
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ background: ink.surface, color: ink.textPrimary, borderColor: ink.border }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </label>
  );
}
