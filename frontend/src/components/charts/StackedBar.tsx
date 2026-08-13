import * as d3 from 'd3';
import { useMemo, useState, type ReactNode } from 'react';

import { CATEGORICAL } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisLeft,
  drawGrid,
  fmtOne,
  titleCase,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip, type LegendItem } from './Primitives';

interface StackedBarProps {
  title: string;
  subtitle?: string;
  /** One row per bar; keys listed in `keys` become the stacked segments. */
  data: Array<Record<string, number | string>>;
  categoryKey: string;
  keys: string[];
  /** Normalise each bar to 100%. */
  percent?: boolean;
  valueFormat?: (v: number) => string;
  height?: number;
  note?: ReactNode;
}

/**
 * Composition within each category.
 *
 * A 2px surface gap separates adjacent segments -- without it two similar
 * steps merge into one block and the boundary is lost.
 */
export function StackedBar({
  title,
  subtitle,
  data,
  categoryKey,
  keys,
  percent = false,
  valueFormat = fmtOne,
  height = 300,
  note,
}: StackedBarProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = { ...DEFAULT_MARGIN, bottom: 72 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const stacked = useMemo(() => {
    const series = d3
      .stack<Record<string, number | string>>()
      .keys(keys)
      .value((row, key) => Number(row[key] ?? 0))
      .offset(percent ? d3.stackOffsetExpand : d3.stackOffsetNone)(data);
    return series;
  }, [data, keys, percent]);

  const xScale = useMemo(
    () =>
      d3
        .scaleBand<string>()
        .domain(data.map((d) => String(d[categoryKey])))
        .range([0, innerW])
        .padding(0.24),
    [data, categoryKey, innerW],
  );

  const yMax = d3.max(stacked, (layer) => d3.max(layer, (d) => d[1])) ?? 1;
  const yScale = useMemo(
    () => d3.scaleLinear().domain([0, percent ? 1 : yMax]).range([innerH, 0]).nice(),
    [innerH, percent, yMax],
  );

  const legend: LegendItem[] = keys.map((k, i) => ({
    label: k,
    color: CATEGORICAL[mode][i] ?? ink.textMuted,
  }));

  const table = {
    columns: [categoryKey, ...keys],
    rows: data.map((row) => [String(row[categoryKey]), ...keys.map((k) => Number(row[k] ?? 0))]),
  };

  const GAP = 2;

  return (
    <Figure title={title} subtitle={subtitle} legend={legend} table={table} note={note}>
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

              {stacked.map((layer, li) => (
                <g key={layer.key}>
                  {layer.map((segment, si) => {
                    const category = String(data[si][categoryKey]);
                    const y0 = yScale(segment[0]);
                    const y1 = yScale(segment[1]);
                    const h = Math.max(0, y0 - y1 - GAP);
                    if (h <= 0) return null;
                    const color = CATEGORICAL[mode][li] ?? ink.textMuted;
                    return (
                      <rect
                        key={`${layer.key}-${si}`}
                        x={xScale(category) ?? 0}
                        y={y1}
                        width={xScale.bandwidth()}
                        height={h}
                        fill={color}
                        onMouseEnter={(e) =>
                          setTip({
                            x: e.clientX,
                            y: e.clientY,
                            title: titleCase(category),
                            rows: keys.map((k, ki) => ({
                              label: titleCase(k),
                              value: valueFormat(Number(data[si][k] ?? 0)),
                              color: CATEGORICAL[mode][ki] ?? ink.textMuted,
                            })),
                          })
                        }
                        onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                        onMouseLeave={() => setTip(null)}
                      />
                    );
                  })}
                </g>
              ))}

              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  g.call(d3.axisBottom(xScale).tickSize(0).tickPadding(8) as never);
                  g.select('.domain').attr('stroke', ink.axis);
                  g.selectAll('text')
                    .attr('fill', ink.textMuted)
                    .attr('font-size', 10)
                    .attr('transform', 'rotate(-40)')
                    .attr('text-anchor', 'end');
                }}
              />
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisLeft(
                    g as never,
                    yScale,
                    ink,
                    percent ? (v) => `${Math.round(Number(v) * 100)}%` : (v) => valueFormat(Number(v)),
                  );
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
