import * as d3 from 'd3';
import { useState, type ReactNode } from 'react';

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
import { Figure, Tooltip } from './Primitives';

export interface BoxDatum {
  category: string;
  min: number;
  q1: number;
  median: number;
  q3: number;
  max: number;
  n?: number;
}

interface BoxPlotProps {
  title: string;
  subtitle?: string;
  data: BoxDatum[];
  valueLabel: string;
  valueFormat?: (v: number) => string;
  height?: number;
  note?: ReactNode;
}

/**
 * Spread comparison across categories.
 *
 * A bar chart of means would hide that two categories with the same average
 * can have completely different spreads, which is exactly the question this
 * panel answers -- so the form is a box plot, not a bar.
 */
export function BoxPlot({
  title,
  subtitle,
  data,
  valueLabel,
  valueFormat = fmtOne,
  height = 300,
  note,
}: BoxPlotProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = { ...DEFAULT_MARGIN, bottom: 66, left: 64 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const xScale = d3
    .scaleBand<string>()
    .domain(data.map((d) => d.category))
    .range([0, innerW])
    .padding(0.4);

  const lo = d3.min(data, (d) => d.min) ?? 0;
  const hi = d3.max(data, (d) => d.max) ?? 1;
  const pad = (hi - lo) * 0.06 || 1;
  const yScale = d3.scaleLinear().domain([lo - pad, hi + pad]).range([innerH, 0]).nice();

  const color = CATEGORICAL[mode][0];

  const table = {
    columns: ['category', 'min', 'q1', 'median', 'q3', 'max', 'n'],
    rows: data.map((d) => [
      titleCase(d.category), d.min, d.q1, d.median, d.q3, d.max, d.n ?? '',
    ] as Array<string | number>),
  };

  return (
    <Figure title={title} subtitle={subtitle} table={table} note={note}>
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

              {data.map((d) => {
                const x = xScale(d.category) ?? 0;
                const w = xScale.bandwidth();
                const cx = x + w / 2;
                const boxTop = yScale(d.q3);
                const boxH = Math.max(1, yScale(d.q1) - yScale(d.q3));
                return (
                  <g
                    key={d.category}
                    onMouseEnter={(e) =>
                      setTip({
                        x: e.clientX,
                        y: e.clientY,
                        title: titleCase(d.category),
                        rows: [
                          { label: 'Median', value: valueFormat(d.median), color },
                          { label: 'Q1 – Q3', value: `${valueFormat(d.q1)} – ${valueFormat(d.q3)}` },
                          { label: 'Range', value: `${valueFormat(d.min)} – ${valueFormat(d.max)}` },
                          ...(d.n ? [{ label: 'n', value: d.n.toLocaleString() }] : []),
                        ],
                      })
                    }
                    onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                    onMouseLeave={() => setTip(null)}
                  >
                    {/* Whiskers */}
                    <line x1={cx} x2={cx} y1={yScale(d.max)} y2={yScale(d.q3)} stroke={color} strokeWidth={1.5} />
                    <line x1={cx} x2={cx} y1={yScale(d.q1)} y2={yScale(d.min)} stroke={color} strokeWidth={1.5} />
                    <line x1={cx - w / 4} x2={cx + w / 4} y1={yScale(d.max)} y2={yScale(d.max)} stroke={color} strokeWidth={1.5} />
                    <line x1={cx - w / 4} x2={cx + w / 4} y1={yScale(d.min)} y2={yScale(d.min)} stroke={color} strokeWidth={1.5} />
                    {/* Interquartile box */}
                    <rect x={x} y={boxTop} width={w} height={boxH} rx={3} fill={color} fillOpacity={0.35} stroke={color} strokeWidth={1.5} />
                    {/* Median: the reading the eye should land on first */}
                    <line x1={x} x2={x + w} y1={yScale(d.median)} y2={yScale(d.median)} stroke={ink.surface} strokeWidth={3} />
                    <line x1={x} x2={x + w} y1={yScale(d.median)} y2={yScale(d.median)} stroke={color} strokeWidth={2} />
                    {/* Transparent hit area, larger than the marks */}
                    <rect x={x - w * 0.2} y={yScale(d.max) - 6} width={w * 1.4} height={yScale(d.min) - yScale(d.max) + 12} fill="transparent" />
                  </g>
                );
              })}

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
                    .text((t) => titleCase(String(t)))
                    .attr('transform', data.length > 5 ? 'rotate(-35)' : null)
                    .attr('text-anchor', data.length > 5 ? 'end' : 'middle');
                }}
              />
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisLeft(g as never, yScale, ink, (v) => valueFormat(Number(v)));
                }}
              />
              <text
                transform={`translate(${-margin.left + 14},${innerH / 2}) rotate(-90)`}
                textAnchor="middle"
                fontSize={11}
                fill={ink.textSecondary}
              >
                {titleCase(valueLabel)}
              </text>
            </g>
          </svg>
        )}
        <Tooltip state={tip} />
      </div>
    </Figure>
  );
}
