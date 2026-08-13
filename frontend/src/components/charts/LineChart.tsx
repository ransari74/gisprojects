import * as d3 from 'd3';
import { useMemo, useRef, useState, type ReactNode } from 'react';

import { CATEGORICAL } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisBottom,
  drawAxisLeft,
  drawGrid,
  fmtTwo,
  titleCase,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip, type LegendItem } from './Primitives';

export interface SeriesPoint {
  x: number | Date;
  y: number;
  /** Optional confidence band. */
  lower?: number;
  upper?: number;
}

export interface Series {
  name: string;
  points: SeriesPoint[];
}

interface LineChartProps {
  title: string;
  subtitle?: string;
  series: Series[];
  xLabel?: string;
  yLabel?: string;
  xFormat?: (v: number | Date) => string;
  yFormat?: (v: number) => string;
  height?: number;
  /** Renders the area under a single series -- use for volume, not for ratios. */
  area?: boolean;
  note?: ReactNode;
  isTime?: boolean;
}

/**
 * Change over time, one line per series, with a shared crosshair.
 *
 * The crosshair reads every series at the hovered x, which is why this form
 * never needs a second y-axis: series that do not share a scale belong in a
 * separate chart, not on a right-hand axis.
 */
export function LineChart({
  title,
  subtitle,
  series,
  xFormat,
  yFormat = fmtTwo,
  height = 280,
  area = false,
  note,
  isTime = false,
}: LineChartProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const margin = { ...DEFAULT_MARGIN, right: 24 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const all = useMemo(() => series.flatMap((s) => s.points), [series]);

  const xScale = useMemo(() => {
    const values = all.map((p) => (p.x instanceof Date ? p.x.getTime() : p.x));
    const extent = d3.extent(values) as [number, number];
    const domain: [number, number] = [extent[0] ?? 0, extent[1] ?? 1];
    return isTime
      ? d3.scaleTime().domain([new Date(domain[0]), new Date(domain[1])]).range([0, innerW])
      : d3.scaleLinear().domain(domain).range([0, innerW]);
  }, [all, innerW, isTime]);

  const yScale = useMemo(() => {
    const lo = d3.min(all, (p) => Math.min(p.y, p.lower ?? p.y)) ?? 0;
    const hi = d3.max(all, (p) => Math.max(p.y, p.upper ?? p.y)) ?? 1;
    const pad = (hi - lo) * 0.08 || 0.5;
    return d3.scaleLinear().domain([lo - pad, hi + pad]).range([innerH, 0]).nice();
  }, [all, innerH]);

  const px = (p: SeriesPoint) => xScale(p.x instanceof Date ? p.x : (p.x as never)) as number;

  const lineGen = d3
    .line<SeriesPoint>()
    .defined((p) => Number.isFinite(p.y))
    .x(px)
    .y((p) => yScale(p.y))
    .curve(d3.curveMonotoneX);

  const areaGen = d3
    .area<SeriesPoint>()
    .defined((p) => Number.isFinite(p.y))
    .x(px)
    .y0(innerH)
    .y1((p) => yScale(p.y))
    .curve(d3.curveMonotoneX);

  const bandGen = d3
    .area<SeriesPoint>()
    .defined((p) => p.lower !== undefined && p.upper !== undefined)
    .x(px)
    .y0((p) => yScale(p.lower ?? p.y))
    .y1((p) => yScale(p.upper ?? p.y))
    .curve(d3.curveMonotoneX);

  const legend: LegendItem[] = series.map((s, i) => ({
    label: s.name,
    color: CATEGORICAL[mode][i] ?? ink.textMuted,
  }));

  function handleMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const localX = event.clientX - rect.left - margin.left;
    setHoverX(localX);

    const xValue = xScale.invert(localX) as number | Date;
    const target = xValue instanceof Date ? xValue.getTime() : xValue;

    const rows = series
      .map((s, i) => {
        const nearest = d3.least(s.points, (p) =>
          Math.abs((p.x instanceof Date ? p.x.getTime() : p.x) - target),
        );
        if (!nearest) return null;
        return {
          label: titleCase(s.name),
          value: yFormat(nearest.y),
          color: CATEGORICAL[mode][i] ?? ink.textMuted,
        };
      })
      .filter((r): r is NonNullable<typeof r> => r !== null);

    const label = xFormat
      ? xFormat(xValue)
      : xValue instanceof Date
        ? d3.timeFormat('%b %Y')(xValue)
        : d3.format('.4~g')(xValue as number);

    setTip({ x: event.clientX, y: event.clientY, title: label, rows });
  }

  const table = {
    columns: ['x', ...series.map((s) => s.name)],
    rows: (series[0]?.points ?? []).map((p, idx) => {
      const label = p.x instanceof Date ? d3.timeFormat('%Y-%m-%d')(p.x) : String(p.x);
      return [label, ...series.map((s) => s.points[idx]?.y ?? '')] as Array<string | number>;
    }),
  };

  return (
    <Figure title={title} subtitle={subtitle} legend={legend} table={table} note={note}>
      <div ref={ref} className="chart-host" style={{ height }}>
        {width > 0 && (
          <svg ref={svgRef} width={width} height={height} role="img" aria-label={title}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawGrid(g as never, yScale, innerW, ink);
                }}
              />

              {/* Confidence bands sit under the lines at low opacity */}
              {series.map((s, i) =>
                s.points.some((p) => p.lower !== undefined) ? (
                  <path
                    key={`band-${s.name}`}
                    d={bandGen(s.points) ?? ''}
                    fill={CATEGORICAL[mode][i] ?? ink.textMuted}
                    opacity={0.14}
                  />
                ) : null,
              )}

              {area && series.length === 1 && (
                <path d={areaGen(series[0].points) ?? ''} fill={CATEGORICAL[mode][0]} opacity={0.18} />
              )}

              {series.map((s, i) => (
                <path
                  key={s.name}
                  d={lineGen(s.points) ?? ''}
                  fill="none"
                  stroke={CATEGORICAL[mode][i] ?? ink.textMuted}
                  strokeWidth={2}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}

              {/* Direct labels at the line end, for up to four series */}
              {series.length <= 4 &&
                series.map((s) => {
                  const last = s.points.at(-1);
                  if (!last) return null;
                  return (
                    <text
                      key={`label-${s.name}`}
                      x={px(last) + 4}
                      y={yScale(last.y)}
                      dy="0.32em"
                      fontSize={11}
                      fill={ink.textSecondary}
                    >
                      {titleCase(s.name)}
                    </text>
                  );
                })}

              {hoverX !== null && hoverX >= 0 && hoverX <= innerW && (
                <line
                  x1={hoverX}
                  x2={hoverX}
                  y1={0}
                  y2={innerH}
                  stroke={ink.axis}
                  strokeWidth={1}
                  strokeDasharray="3 3"
                />
              )}

              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisBottom(g as never, xScale as never, ink, undefined, 6);
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

              {/* Hit area larger than the marks, per the interaction rules */}
              <rect
                width={innerW}
                height={innerH}
                fill="transparent"
                onMouseMove={handleMove}
                onMouseLeave={() => {
                  setTip(null);
                  setHoverX(null);
                }}
              />
            </g>
          </svg>
        )}
        <Tooltip state={tip} />
      </div>
    </Figure>
  );
}
