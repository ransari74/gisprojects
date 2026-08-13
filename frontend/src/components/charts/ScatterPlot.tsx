import * as d3 from 'd3';
import { useMemo, useState, type ReactNode } from 'react';

import { ALL_PAIRS_SERIES_CAP, CATEGORICAL } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisBottom,
  drawAxisLeft,
  drawGrid,
  fmtTwo,
  linearFit,
  titleCase,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip, type LegendItem } from './Primitives';

export interface ScatterDatum {
  x: number;
  y: number;
  label?: string;
  group?: string;
  size?: number;
}

interface ScatterPlotProps {
  title: string;
  subtitle?: string;
  data: ScatterDatum[];
  xLabel: string;
  yLabel: string;
  xFormat?: (v: number) => string;
  yFormat?: (v: number) => string;
  /** Draws a least-squares line through the points. */
  showFit?: boolean;
  /** Reference line at y = this value (e.g. 1.0 for an index). */
  yReference?: number;
  height?: number;
  note?: ReactNode;
}

/**
 * Relationship between two continuous measures.
 *
 * Scatter is an ALL-PAIRS form: any point can land beside any other, so the
 * categorical palette's three-slot all-pairs cap applies. Groups beyond the
 * third are folded into "Other" rather than given a generated hue -- see the
 * validator notes in styles/theme.ts.
 */
export function ScatterPlot({
  title,
  subtitle,
  data,
  xLabel,
  yLabel,
  xFormat = fmtTwo,
  yFormat = fmtTwo,
  showFit = true,
  yReference,
  height = 300,
  note,
}: ScatterPlotProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = { ...DEFAULT_MARGIN, bottom: 44, left: 58 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  // Fold the tail of the group list into "Other" so no pair exceeds the cap.
  const { groups, groupOf } = useMemo(() => {
    const counts = d3.rollup(
      data.filter((d) => d.group),
      (v) => v.length,
      (d) => d.group as string,
    );
    const ranked = [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([g]) => g);
    const kept = ranked.slice(0, ALL_PAIRS_SERIES_CAP);
    const hasOther = ranked.length > kept.length;
    return {
      groups: hasOther ? [...kept, 'Other'] : kept,
      groupOf: (d: ScatterDatum) =>
        d.group ? (kept.includes(d.group) ? d.group : 'Other') : undefined,
    };
  }, [data]);

  const xScale = useMemo(() => {
    const extent = d3.extent(data, (d) => d.x) as [number, number];
    const pad = ((extent[1] ?? 1) - (extent[0] ?? 0)) * 0.05 || 1;
    return d3.scaleLinear().domain([(extent[0] ?? 0) - pad, (extent[1] ?? 1) + pad]).range([0, innerW]).nice();
  }, [data, innerW]);

  const yScale = useMemo(() => {
    const extent = d3.extent(data, (d) => d.y) as [number, number];
    const pad = ((extent[1] ?? 1) - (extent[0] ?? 0)) * 0.06 || 1;
    return d3.scaleLinear().domain([(extent[0] ?? 0) - pad, (extent[1] ?? 1) + pad]).range([innerH, 0]).nice();
  }, [data, innerH]);

  const rScale = useMemo(() => {
    const extent = d3.extent(data, (d) => d.size ?? 1) as [number, number];
    return d3.scaleSqrt().domain([extent[0] ?? 0, extent[1] ?? 1]).range([3, 9]);
  }, [data]);

  const fit = showFit ? linearFit(data) : null;

  const colorFor = (d: ScatterDatum) => {
    const g = groupOf(d);
    if (!g) return CATEGORICAL[mode][0];
    const idx = groups.indexOf(g);
    return idx >= 0 && idx < CATEGORICAL[mode].length ? CATEGORICAL[mode][idx] : ink.textMuted;
  };

  const legend: LegendItem[] | undefined = groups.length
    ? groups.map((g, i) => ({ label: g, color: CATEGORICAL[mode][i] ?? ink.textMuted }))
    : undefined;

  // Down-sample the table view; the chart can hold thousands of dots, a table cannot.
  const table = {
    columns: [xLabel, yLabel, ...(groups.length ? ['group'] : [])],
    rows: data.slice(0, 200).map((d) => {
      const row: Array<string | number> = [d.x, d.y];
      if (groups.length) row.push(groupOf(d) ?? '');
      return row;
    }),
  };

  // Marks are ≥8px in diameter and carry a 2px surface ring so overlaps separate.
  const opacity = data.length > 900 ? 0.42 : data.length > 300 ? 0.6 : 0.82;

  return (
    <Figure
      title={title}
      subtitle={subtitle}
      legend={legend}
      table={table}
      note={
        note ??
        (data.length > table.rows.length
          ? `Table view shows the first ${table.rows.length} of ${data.length.toLocaleString()} points.`
          : undefined)
      }
    >
      <div ref={ref} className="chart-host" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={title}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawGrid(g as never, yScale, innerW, ink);
                }}
              />

              {yReference !== undefined && (
                <>
                  <line
                    x1={0}
                    x2={innerW}
                    y1={yScale(yReference)}
                    y2={yScale(yReference)}
                    stroke={ink.axis}
                    strokeWidth={1.5}
                    strokeDasharray="4 4"
                  />
                  <text
                    x={innerW - 2}
                    y={yScale(yReference) - 5}
                    textAnchor="end"
                    fontSize={10}
                    fill={ink.textMuted}
                  >
                    crop average
                  </text>
                </>
              )}

              {data.map((d, i) => (
                <circle
                  key={i}
                  cx={xScale(d.x)}
                  cy={yScale(d.y)}
                  r={d.size !== undefined ? rScale(d.size) : 4}
                  fill={colorFor(d)}
                  fillOpacity={opacity}
                  stroke={ink.surface}
                  strokeWidth={1}
                  onMouseEnter={(e) =>
                    setTip({
                      x: e.clientX,
                      y: e.clientY,
                      title: d.label ?? titleCase(groupOf(d) ?? 'Point'),
                      rows: [
                        { label: xLabel, value: xFormat(d.x), color: colorFor(d) },
                        { label: yLabel, value: yFormat(d.y) },
                        ...(d.group ? [{ label: 'group', value: titleCase(d.group) }] : []),
                      ],
                    })
                  }
                  onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                  onMouseLeave={() => setTip(null)}
                />
              ))}

              {fit && (
                <line
                  x1={xScale(xScale.domain()[0])}
                  y1={yScale(fit.intercept + fit.slope * xScale.domain()[0])}
                  x2={xScale(xScale.domain()[1])}
                  y2={yScale(fit.intercept + fit.slope * xScale.domain()[1])}
                  stroke={ink.textPrimary}
                  strokeWidth={2}
                  strokeOpacity={0.65}
                />
              )}

              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisBottom(g as never, xScale, ink, undefined, 6);
                }}
              />
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisLeft(g as never, yScale, ink, (v) => yFormat(Number(v)));
                }}
              />

              <text
                x={innerW / 2}
                y={innerH + 36}
                textAnchor="middle"
                fontSize={11}
                fill={ink.textSecondary}
              >
                {titleCase(xLabel)}
              </text>
              <text
                transform={`translate(${-margin.left + 14},${innerH / 2}) rotate(-90)`}
                textAnchor="middle"
                fontSize={11}
                fill={ink.textSecondary}
              >
                {titleCase(yLabel)}
              </text>
            </g>
          </svg>
        )}
        <Tooltip state={tip} />
      </div>
    </Figure>
  );
}
