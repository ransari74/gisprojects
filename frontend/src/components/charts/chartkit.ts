/**
 * Shared plumbing for the D3 charts: sizing, ink tokens, tooltip and axis
 * rendering. Every chart in this app is built on these, so the axes, grid
 * weight and hover behaviour are identical across all five projects.
 */

import * as d3 from 'd3';
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

import { CHROME, currentMode, type Mode } from '@/styles/theme';

export interface Margin {
  top: number;
  right: number;
  bottom: number;
  left: number;
}

export const DEFAULT_MARGIN: Margin = { top: 16, right: 20, bottom: 34, left: 52 };

/** Observes the container so charts resize with the layout, not the window. */
export function useChartSize(height: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);

  useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width ?? 0;
      setWidth(Math.max(0, Math.floor(w)));
    });
    observer.observe(node);
    setWidth(node.clientWidth);
    return () => observer.disconnect();
  }, []);

  return { ref, width, height };
}

/** Re-renders on theme change so charts restep for the dark surface. */
export function useMode(): Mode {
  const [mode, setMode] = useState<Mode>(currentMode);
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const update = () => setMode(currentMode());
    mq.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => {
      mq.removeEventListener('change', update);
      observer.disconnect();
    };
  }, []);
  return mode;
}

export function useInk(mode: Mode) {
  return useMemo(() => CHROME[mode], [mode]);
}

export interface TooltipState {
  x: number;
  y: number;
  title: string;
  rows: Array<{ label: string; value: string; color?: string }>;
}

/** Recessive gridlines: hairline weight, never competing with the data. */
export function drawGrid(
  g: d3.Selection<SVGGElement, unknown, null, undefined>,
  scale: d3.ScaleLinear<number, number>,
  width: number,
  ink: Record<string, string>,
  ticks = 5,
) {
  g.selectAll('line.grid')
    .data(scale.ticks(ticks))
    .join('line')
    .attr('class', 'grid')
    .attr('x1', 0)
    .attr('x2', width)
    .attr('y1', (d) => scale(d))
    .attr('y2', (d) => scale(d))
    .attr('stroke', ink.grid)
    .attr('stroke-width', 1)
    .attr('shape-rendering', 'crispEdges');
}

export function drawAxisLeft(
  g: d3.Selection<SVGGElement, unknown, null, undefined>,
  scale: d3.ScaleLinear<number, number>,
  ink: Record<string, string>,
  format?: (v: d3.NumberValue) => string,
  ticks = 5,
) {
  const axis = d3.axisLeft(scale).ticks(ticks).tickSize(0).tickPadding(8);
  if (format) axis.tickFormat(format);
  g.call(axis);
  g.select('.domain').remove();
  g.selectAll('text').attr('fill', ink.textMuted).attr('font-size', 11);
}

export function drawAxisBottom(
  g: d3.Selection<SVGGElement, unknown, null, undefined>,
  scale: d3.ScaleLinear<number, number> | d3.ScaleBand<string> | d3.ScaleTime<number, number>,
  ink: Record<string, string>,
  format?: (v: never) => string,
  ticks = 6,
) {
  const axis = d3.axisBottom(scale as never).tickSize(0).tickPadding(8);
  if ('ticks' in scale && typeof (scale as d3.ScaleLinear<number, number>).ticks === 'function') {
    (axis as d3.Axis<d3.NumberValue>).ticks(ticks);
  }
  if (format) (axis as unknown as d3.Axis<never>).tickFormat(format);
  g.call(axis as never);
  g.select('.domain').attr('stroke', ink.axis).attr('stroke-width', 1);
  g.selectAll('text').attr('fill', ink.textMuted).attr('font-size', 11);
}

// --- formatters -------------------------------------------------------------
export const fmtInt = d3.format(',.0f');
export const fmtOne = d3.format(',.1f');
export const fmtTwo = d3.format(',.2f');
export const fmtPct = d3.format('.1f');
export const fmtCompact = d3.format('.3~s');

export function fmtCurrency(value: number): string {
  if (Math.abs(value) >= 1e6) return `€${d3.format('.2~f')(value / 1e6)}M`;
  if (Math.abs(value) >= 1e3) return `€${d3.format(',.0f')(value)}`;
  return `€${d3.format('.0f')(value)}`;
}

export function titleCase(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Least-squares fit, for the regression overlay on scatter panels. */
export function linearFit(points: Array<{ x: number; y: number }>): { slope: number; intercept: number } | null {
  const valid = points.filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (valid.length < 3) return null;
  const meanX = d3.mean(valid, (p) => p.x) ?? 0;
  const meanY = d3.mean(valid, (p) => p.y) ?? 0;
  let num = 0;
  let den = 0;
  for (const p of valid) {
    num += (p.x - meanX) * (p.y - meanY);
    den += (p.x - meanX) ** 2;
  }
  if (den === 0) return null;
  const slope = num / den;
  return { slope, intercept: meanY - slope * meanX };
}
