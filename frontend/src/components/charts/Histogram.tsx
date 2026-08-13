import * as d3 from 'd3';
import { useState, type ReactNode } from 'react';

import { CATEGORICAL } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisBottom,
  drawAxisLeft,
  drawGrid,
  fmtInt,
  fmtTwo,
  titleCase,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip } from './Primitives';

export interface HistBin {
  x0: number;
  x1: number;
  count: number;
}

interface HistogramProps {
  title: string;
  subtitle?: string;
  bins: HistBin[];
  xLabel: string;
  /** Draws a dashed rule and label at these positions (mean, median). */
  markers?: Array<{ value: number; label: string }>;
  xFormat?: (v: number) => string;
  height?: number;
  note?: ReactNode;
}

/** Distribution of one continuous measure. Single hue -- there is one series. */
export function Histogram({
  title,
  subtitle,
  bins,
  xLabel,
  markers = [],
  xFormat = fmtTwo,
  height = 250,
  note,
}: HistogramProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = { ...DEFAULT_MARGIN, bottom: 42 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const xMin = d3.min(bins, (b) => b.x0) ?? 0;
  const xMax = d3.max(bins, (b) => b.x1) ?? 1;
  const xScale = d3.scaleLinear().domain([xMin, xMax]).range([0, innerW]);
  const yScale = d3
    .scaleLinear()
    .domain([0, d3.max(bins, (b) => b.count) ?? 1])
    .range([innerH, 0])
    .nice();

  const table = {
    columns: ['from', 'to', 'count'],
    rows: bins.map((b) => [Number(b.x0.toFixed(3)), Number(b.x1.toFixed(3)), b.count]),
  };

  const GAP = 2;

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

              {bins.map((b, i) => {
                const x = xScale(b.x0);
                const w = Math.max(0, xScale(b.x1) - x - GAP);
                const y = yScale(b.count);
                const h = Math.max(0, innerH - y);
                if (h <= 0 || w <= 0) return null;
                const r = Math.min(4, w / 2, h);
                return (
                  <path
                    key={i}
                    d={`M${x},${y + h} L${x},${y + r} Q${x},${y} ${x + r},${y} L${x + w - r},${y} Q${x + w},${y} ${x + w},${y + r} L${x + w},${y + h} Z`}
                    fill={CATEGORICAL[mode][0]}
                    onMouseEnter={(e) =>
                      setTip({
                        x: e.clientX,
                        y: e.clientY,
                        title: `${xFormat(b.x0)} – ${xFormat(b.x1)}`,
                        rows: [{ label: 'count', value: fmtInt(b.count), color: CATEGORICAL[mode][0] }],
                      })
                    }
                    onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                    onMouseLeave={() => setTip(null)}
                  />
                );
              })}

              {markers.map((m) => (
                <g key={m.label}>
                  <line
                    x1={xScale(m.value)}
                    x2={xScale(m.value)}
                    y1={0}
                    y2={innerH}
                    stroke={ink.textPrimary}
                    strokeWidth={1.5}
                    strokeDasharray="4 3"
                    opacity={0.7}
                  />
                  <text
                    x={xScale(m.value) + 4}
                    y={10}
                    fontSize={10}
                    fill={ink.textSecondary}
                  >
                    {m.label}
                  </text>
                </g>
              ))}

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
                  drawAxisLeft(g as never, yScale, ink, (v) => fmtInt(Number(v)));
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
            </g>
          </svg>
        )}
        <Tooltip state={tip} />
      </div>
    </Figure>
  );
}
