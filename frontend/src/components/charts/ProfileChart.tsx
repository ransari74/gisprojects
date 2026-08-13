import * as d3 from 'd3';
import { useRef, useState, type ReactNode } from 'react';

import { CATEGORICAL } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisBottom,
  drawAxisLeft,
  drawGrid,
  fmtOne,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip } from './Primitives';

export interface ProfilePoint {
  distance_m: number;
  terrain_m: number;
  surface_m: number;
}

interface ProfileChartProps {
  title: string;
  subtitle?: string;
  points: ProfilePoint[];
  height?: number;
  note?: ReactNode;
}

/**
 * Cross-section: terrain as a filled ground profile with the built skyline
 * layered above it.
 *
 * Both series are metres above NAP on one shared axis -- the built surface is
 * literally the terrain plus building height, so stacking them on one scale is
 * the physically correct reading, not a dual-axis shortcut.
 */
export function ProfileChart({ title, subtitle, points, height = 260, note }: ProfileChartProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);
  const [hoverX, setHoverX] = useState<number | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);

  const margin = { ...DEFAULT_MARGIN, bottom: 42 };
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const xScale = d3
    .scaleLinear()
    .domain(d3.extent(points, (p) => p.distance_m) as [number, number])
    .range([0, innerW]);

  const yMin = Math.min(0, d3.min(points, (p) => p.terrain_m) ?? 0);
  const yMax = d3.max(points, (p) => p.surface_m) ?? 1;
  const yScale = d3.scaleLinear().domain([yMin - 2, yMax * 1.06]).range([innerH, 0]).nice();

  const terrainColor = CATEGORICAL[mode][2];
  const surfaceColor = CATEGORICAL[mode][0];

  const terrainArea = d3
    .area<ProfilePoint>()
    .x((p) => xScale(p.distance_m))
    .y0(innerH)
    .y1((p) => yScale(p.terrain_m))
    .curve(d3.curveLinear);

  const surfaceLine = d3
    .line<ProfilePoint>()
    .x((p) => xScale(p.distance_m))
    .y((p) => yScale(p.surface_m))
    .curve(d3.curveStepAfter);

  const table = {
    columns: ['distance (m)', 'terrain (m)', 'surface (m)'],
    rows: points
      .filter((_, i) => i % 8 === 0)
      .map((p) => [Math.round(p.distance_m), p.terrain_m, p.surface_m]),
  };

  function handleMove(event: React.MouseEvent<SVGRectElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const localX = event.clientX - rect.left - margin.left;
    setHoverX(localX);
    const distance = xScale.invert(localX);
    const nearest = d3.least(points, (p) => Math.abs(p.distance_m - distance));
    if (!nearest) return;
    setTip({
      x: event.clientX,
      y: event.clientY,
      title: `${(nearest.distance_m / 1000).toFixed(2)} km along transect`,
      rows: [
        { label: 'Terrain', value: `${fmtOne(nearest.terrain_m)} m`, color: terrainColor },
        { label: 'Built surface', value: `${fmtOne(nearest.surface_m)} m`, color: surfaceColor },
        { label: 'Massing above ground', value: `${fmtOne(nearest.surface_m - nearest.terrain_m)} m` },
      ],
    });
  }

  return (
    <Figure
      title={title}
      subtitle={subtitle}
      legend={[
        { label: 'Terrain (Copernicus DEM)', color: terrainColor },
        { label: 'Built surface', color: surfaceColor },
      ]}
      table={table}
      note={note}
    >
      <div ref={ref} className="chart-host" style={{ height }}>
        {width > 0 && points.length > 1 && (
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

              <path d={surfaceLine(points) ?? ''} fill="none" stroke={surfaceColor} strokeWidth={1.5} opacity={0.9} />
              <path d={terrainArea(points) ?? ''} fill={terrainColor} fillOpacity={0.45} />
              <path
                d={d3.line<ProfilePoint>().x((p) => xScale(p.distance_m)).y((p) => yScale(p.terrain_m))(points) ?? ''}
                fill="none"
                stroke={terrainColor}
                strokeWidth={2}
              />

              {/* Sea level matters here: much of the western polder sits below it */}
              {yMin < 0 && (
                <>
                  <line x1={0} x2={innerW} y1={yScale(0)} y2={yScale(0)} stroke={ink.textPrimary} strokeWidth={1} strokeDasharray="5 3" opacity={0.5} />
                  <text x={2} y={yScale(0) - 4} fontSize={10} fill={ink.textMuted}>NAP (0 m)</text>
                </>
              )}

              {hoverX !== null && hoverX >= 0 && hoverX <= innerW && (
                <line x1={hoverX} x2={hoverX} y1={0} y2={innerH} stroke={ink.axis} strokeWidth={1} strokeDasharray="3 3" />
              )}

              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisBottom(g as never, xScale, ink, ((v: number) => `${(v / 1000).toFixed(0)} km`) as never, 6);
                }}
              />
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  drawAxisLeft(g as never, yScale, ink, (v) => `${Math.round(Number(v))} m`);
                }}
              />

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
