import * as d3 from 'd3';
import { useState, type ReactNode } from 'react';

import { CATEGORICAL } from '@/styles/theme';
import { fmtInt, useChartSize, useInk, useMode, type TooltipState } from './chartkit';
import { Figure, Tooltip } from './Primitives';

export interface AgeBand {
  age_band: string;
  band_order: number;
  male: number;
  female: number;
}

interface PyramidProps {
  title: string;
  subtitle?: string;
  bands: AgeBand[];
  height?: number;
  note?: ReactNode;
}

/**
 * Back-to-back bars: two opposed magnitude scales sharing one category axis.
 *
 * This is not a dual-axis chart -- both arms use the same units and the same
 * scale, mirrored. The two arms are a genuine two-series chart, so they carry
 * a legend as well as the left/right position cue.
 */
export function PopulationPyramid({ title, subtitle, bands, height = 340, note }: PyramidProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = { top: 14, right: 16, bottom: 32, left: 16 };
  const centreGap = 46;
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);
  const armW = Math.max(0, (innerW - centreGap) / 2);

  const sorted = [...bands].sort((a, b) => a.band_order - b.band_order);
  const maxValue = d3.max(sorted, (b) => Math.max(b.male, b.female)) ?? 1;

  const yScale = d3
    .scaleBand<string>()
    .domain(sorted.map((b) => b.age_band))
    .range([innerH, 0])
    .padding(0.22);
  const xScale = d3.scaleLinear().domain([0, maxValue]).range([0, armW]);

  const maleColor = CATEGORICAL[mode][0];
  const femaleColor = CATEGORICAL[mode][1];

  const table = {
    columns: ['age band', 'male', 'female', 'total'],
    rows: sorted.map((b) => [b.age_band, b.male, b.female, b.male + b.female]),
  };

  const show = (e: React.MouseEvent, band: AgeBand) =>
    setTip({
      x: e.clientX,
      y: e.clientY,
      title: `Age ${band.age_band}`,
      rows: [
        { label: 'Male', value: fmtInt(band.male), color: maleColor },
        { label: 'Female', value: fmtInt(band.female), color: femaleColor },
        { label: 'Total', value: fmtInt(band.male + band.female) },
      ],
    });

  return (
    <Figure
      title={title}
      subtitle={subtitle}
      legend={[
        { label: 'Male', color: maleColor },
        { label: 'Female', color: femaleColor },
      ]}
      table={table}
      note={note}
    >
      <div ref={ref} className="chart-host" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={title}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              {sorted.map((band) => {
                const y = yScale(band.age_band) ?? 0;
                const h = yScale.bandwidth();
                const mw = xScale(band.male);
                const fw = xScale(band.female);
                const r = 4;
                return (
                  <g key={band.age_band}>
                    {/* Left arm: male, growing leftward from the centre gap */}
                    <path
                      d={leftBar(armW - mw, y, mw, h, r)}
                      fill={maleColor}
                      onMouseEnter={(e) => show(e, band)}
                      onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                      onMouseLeave={() => setTip(null)}
                    />
                    {/* Centre label doubles as the category axis */}
                    <text
                      x={armW + centreGap / 2}
                      y={y + h / 2}
                      dy="0.34em"
                      textAnchor="middle"
                      fontSize={10}
                      fill={ink.textMuted}
                      className="num"
                    >
                      {band.age_band}
                    </text>
                    <path
                      d={rightBar(armW + centreGap, y, fw, h, r)}
                      fill={femaleColor}
                      onMouseEnter={(e) => show(e, band)}
                      onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                      onMouseLeave={() => setTip(null)}
                    />
                  </g>
                );
              })}

              {/* Mirrored value axes, both reading outward from zero */}
              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  const mirrored = d3.scaleLinear().domain([maxValue, 0]).range([0, armW]);
                  g.call(
                    d3.axisBottom(mirrored).ticks(3).tickSize(0).tickPadding(6)
                      .tickFormat((v) => d3.format('.2~s')(Number(v))) as never,
                  );
                  g.select('.domain').attr('stroke', ink.axis);
                  g.selectAll('text').attr('fill', ink.textMuted).attr('font-size', 10);
                }}
              />
              <g
                transform={`translate(${armW + centreGap},${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  g.call(
                    d3.axisBottom(xScale).ticks(3).tickSize(0).tickPadding(6)
                      .tickFormat((v) => d3.format('.2~s')(Number(v))) as never,
                  );
                  g.select('.domain').attr('stroke', ink.axis);
                  g.selectAll('text').attr('fill', ink.textMuted).attr('font-size', 10);
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

function leftBar(x: number, y: number, w: number, h: number, r: number): string {
  if (w <= 0) return '';
  const radius = Math.min(r, w, h / 2);
  return `M${x + w},${y} L${x + radius},${y} Q${x},${y} ${x},${y + radius} L${x},${y + h - radius} Q${x},${y + h} ${x + radius},${y + h} L${x + w},${y + h} Z`;
}

function rightBar(x: number, y: number, w: number, h: number, r: number): string {
  if (w <= 0) return '';
  const radius = Math.min(r, w, h / 2);
  return `M${x},${y} L${x + w - radius},${y} Q${x + w},${y} ${x + w},${y + radius} L${x + w},${y + h - radius} Q${x + w},${y + h} ${x + w - radius},${y + h} L${x},${y + h} Z`;
}
