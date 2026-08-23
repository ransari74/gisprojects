import * as d3 from 'd3';
import { useMemo, useState, type ReactNode } from 'react';

import { CATEGORICAL, categoricalFor } from '@/styles/theme';
import {
  DEFAULT_MARGIN,
  drawAxisBottom,
  drawGrid,
  fmtInt,
  titleCase,
  useChartSize,
  useInk,
  useMode,
  type TooltipState,
} from './chartkit';
import { Figure, Tooltip, type LegendItem } from './Primitives';

/** Bars at least this long carry their value label inside rather than past
 * the end -- roughly the width of a formatted number plus its unit. */
const LABEL_INSIDE_PX = 62;

/**
 * Text colour for a label drawn on top of a bar.
 *
 * The categorical palette spans a wide luminance range -- white reads well on
 * the blue and the purple and badly on the yellow and the pink, where it falls
 * under 3:1. Picking per fill rather than fixing on white is what keeps an
 * inside label legible on every category.
 */
function labelOn(fill: string): string {
  const hex = fill.replace('#', '');
  const full = hex.length === 3 ? hex.split('').map((c) => c + c).join('') : hex;
  const channel = (i: number) => {
    const v = parseInt(full.slice(i * 2, i * 2 + 2), 16) / 255;
    return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  };
  // WCAG relative luminance.
  const L = 0.2126 * channel(0) + 0.7152 * channel(1) + 0.0722 * channel(2);
  // Contrast against white is (1.05)/(L+0.05); 0.18 is where that drops below
  // about 4.5:1, so anything lighter takes dark text instead.
  return L > 0.18 ? '#101010' : '#ffffff';
}

export interface BarDatum {
  category: string;
  value: number;
  /** Optional secondary value shown in the tooltip only. */
  secondary?: { label: string; value: string };
}

interface BarChartProps {
  title: string;
  subtitle?: string;
  data: BarDatum[];
  /** Fixed domain so colour follows the entity, not its rank after sorting. */
  colorDomain?: readonly string[];
  /** Single-hue mode: one colour for every bar (the usual choice for magnitude). */
  monochrome?: boolean;
  horizontal?: boolean;
  valueFormat?: (v: number) => string;
  valueLabel?: string;
  height?: number;
  note?: ReactNode;
}

/**
 * Magnitude comparison across categories.
 *
 * Bars are the default form for magnitude, and by default they are one hue:
 * the category is already named on the axis, so a second colour channel would
 * encode nothing. Pass colorDomain only when the same categories are coloured
 * consistently elsewhere on the page (e.g. matching the map legend).
 */
export function BarChart({
  title,
  subtitle,
  data,
  colorDomain,
  monochrome = true,
  horizontal = false,
  valueFormat = fmtInt,
  valueLabel = 'value',
  height = 260,
  note,
}: BarChartProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const { ref, width } = useChartSize(height);
  const [tip, setTip] = useState<TooltipState | null>(null);

  const margin = horizontal
    ? { ...DEFAULT_MARGIN, left: Math.min(150, Math.max(90, width * 0.28)) }
    : DEFAULT_MARGIN;
  const innerW = Math.max(0, width - margin.left - margin.right);
  const innerH = Math.max(0, height - margin.top - margin.bottom);

  const maxValue = d3.max(data, (d) => d.value) ?? 0;
  const minValue = d3.min(data, (d) => d.value) ?? 0;
  // A signed measure -- a temperature anomaly, a subsidence rate -- needs the
  // baseline inside the domain rather than pinned at the bottom. Anchoring at
  // zero regardless would clip every negative bar to nothing, and for an
  // all-negative series it inverts the axis outright.
  const signed = minValue < 0;

  const scales = useMemo(() => {
    const categories = data.map((d) => d.category);
    const lo = signed ? minValue * 1.05 : 0;
    const hi = maxValue > 0 ? maxValue * 1.05 : 0;
    const domain: [number, number] = lo === hi ? [lo, lo + 1] : [lo, hi];
    if (horizontal) {
      return {
        band: d3.scaleBand<string>().domain(categories).range([0, innerH]).padding(0.28),
        linear: d3.scaleLinear().domain(domain).range([0, innerW]).nice(),
      };
    }
    return {
      band: d3.scaleBand<string>().domain(categories).range([0, innerW]).padding(0.28),
      linear: d3.scaleLinear().domain(domain).range([innerH, 0]).nice(),
    };
  }, [data, horizontal, innerH, innerW, maxValue, minValue, signed]);

  //: Where zero sits on the value axis -- the baseline bars grow away from.
  const zero = scales.linear(0);

  const barColor = (category: string) =>
    monochrome || !colorDomain ? CATEGORICAL[mode][0] : categoricalFor(colorDomain, category, mode);

  const legend: LegendItem[] | undefined =
    !monochrome && colorDomain
      ? [...new Map(data.map((d) => [d.category, barColor(d.category)])).entries()].map(
          ([label, color]) => ({ label, color }),
        )
      : undefined;

  const table = {
    columns: ['category', valueLabel],
    rows: data.map((d) => [titleCase(d.category), d.value] as Array<string | number>),
  };

  return (
    <Figure title={title} subtitle={subtitle} legend={legend} table={table} note={note}>
      <div ref={ref} className="chart-host" style={{ height }}>
        {width > 0 && (
          <svg width={width} height={height} role="img" aria-label={title}>
            <g transform={`translate(${margin.left},${margin.top})`}>
              {/* Gridlines run along the value axis only */}
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  if (horizontal) {
                    g.selectAll('line')
                      .data(scales.linear.ticks(5))
                      .join('line')
                      .attr('y1', 0)
                      .attr('y2', innerH)
                      .attr('x1', (d) => scales.linear(d))
                      .attr('x2', (d) => scales.linear(d))
                      .attr('stroke', ink.grid)
                      .attr('shape-rendering', 'crispEdges');
                  } else {
                    drawGrid(g as never, scales.linear, innerW, ink);
                  }
                }}
              />

              {/* Zero has to be drawn when the domain crosses it: on a signed
                  chart the baseline is the reference the bars are read against,
                  and a gridline of the same weight does not read as one. */}
              {signed &&
                (horizontal ? (
                  <line x1={zero} x2={zero} y1={0} y2={innerH} stroke={ink.textMuted} strokeWidth={1} />
                ) : (
                  <line x1={0} x2={innerW} y1={zero} y2={zero} stroke={ink.textMuted} strokeWidth={1} />
                ))}

              {data.map((d, i) => {
                const color = barColor(d.category);
                const bandPos = scales.band(d.category) ?? 0;
                const bandWidth = scales.band.bandwidth();
                // 4px rounded data-end, square against the baseline.
                const radius = 4;
                if (horizontal) {
                  // Bars run from the zero line, in whichever direction the
                  // value takes them.
                  const v = scales.linear(d.value);
                  const x0 = Math.min(zero, v);
                  const w = Math.abs(v - zero);
                  return (
                    <path
                      key={`${d.category}-${i}`}
                      d={
                        d.value < 0
                          ? roundedLeftBar(x0, bandPos, w, bandWidth, radius)
                          : roundedRightBar(x0, bandPos, w, bandWidth, radius)
                      }
                      fill={color}
                      onMouseEnter={(e) =>
                        setTip({
                          x: e.clientX,
                          y: e.clientY,
                          title: titleCase(d.category),
                          rows: [
                            { label: valueLabel, value: valueFormat(d.value), color },
                            ...(d.secondary ? [{ label: d.secondary.label, value: d.secondary.value }] : []),
                          ],
                        })
                      }
                      onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                      onMouseLeave={() => setTip(null)}
                    />
                  );
                }
                const v = scales.linear(d.value);
                const y = Math.min(zero, v);
                const h = Math.abs(v - zero);
                return (
                  <path
                    key={`${d.category}-${i}`}
                    d={
                      d.value < 0
                        ? roundedBottomBar(bandPos, y, bandWidth, h, radius)
                        : roundedTopBar(bandPos, y, bandWidth, h, radius)
                    }
                    fill={color}
                    onMouseEnter={(e) =>
                      setTip({
                        x: e.clientX,
                        y: e.clientY,
                        title: titleCase(d.category),
                        rows: [
                          { label: valueLabel, value: valueFormat(d.value), color },
                          ...(d.secondary ? [{ label: d.secondary.label, value: d.secondary.value }] : []),
                        ],
                      })
                    }
                    onMouseMove={(e) => setTip((t) => (t ? { ...t, x: e.clientX, y: e.clientY } : t))}
                    onMouseLeave={() => setTip(null)}
                  />
                );
              })}

              {/* Direct value labels: only when there are few enough to read */}
              {data.length <= 12 &&
                data.map((d, i) => {
                  const bandPos = (scales.band(d.category) ?? 0) + scales.band.bandwidth() / 2;
                  const color = barColor(d.category);
                  // The label sits past the data end of the bar -- which for a
                  // negative value is on the other side of the baseline. When
                  // the bar is long enough to hold the label it goes inside
                  // instead: a full-width bar leaves no room outside, and the
                  // label would land on top of the category axis.
                  const end = scales.linear(d.value);
                  const negative = d.value < 0;
                  const barPx = Math.abs(end - zero);
                  const inside = barPx > LABEL_INSIDE_PX;
                  const away = negative ? -1 : 1; // direction pointing away from zero

                  return horizontal ? (
                    <text
                      key={`${d.category}-${i}`}
                      x={end + (inside ? -away * 6 : away * 6)}
                      y={bandPos}
                      dy="0.35em"
                      textAnchor={negative === inside ? 'start' : 'end'}
                      fontSize={11}
                      fill={inside ? labelOn(color) : ink.textSecondary}
                      className="num"
                    >
                      {valueFormat(d.value)}
                    </text>
                  ) : (
                    <text
                      key={`${d.category}-${i}`}
                      x={bandPos}
                      // y grows downward, so "away from zero" flips sign here.
                      y={end + (inside ? away * 14 : -away * 6)}
                      textAnchor="middle"
                      fontSize={11}
                      fill={inside ? labelOn(color) : ink.textSecondary}
                      className="num"
                    >
                      {valueFormat(d.value)}
                    </text>
                  );
                })}

              {/* Axes */}
              <g
                transform={`translate(0,${innerH})`}
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  if (horizontal) {
                    drawAxisBottom(g as never, scales.linear, ink, undefined, 5);
                  } else {
                    g.call(d3.axisBottom(scales.band).tickSize(0).tickPadding(8) as never);
                    g.select('.domain').attr('stroke', ink.axis);
                    g.selectAll('text')
                      .attr('fill', ink.textMuted)
                      .attr('font-size', 11)
                      .text((t) => titleCase(String(t)))
                      .attr('transform', data.length > 6 ? 'rotate(-25)' : null)
                      .attr('text-anchor', data.length > 6 ? 'end' : 'middle');
                  }
                }}
              />
              <g
                ref={(node) => {
                  if (!node) return;
                  const g = d3.select(node);
                  g.selectAll('*').remove();
                  if (horizontal) {
                    g.call(d3.axisLeft(scales.band).tickSize(0).tickPadding(8) as never);
                    g.select('.domain').remove();
                    g.selectAll('text')
                      .attr('fill', ink.textMuted)
                      .attr('font-size', 11)
                      .text((t) => titleCase(String(t)));
                  } else {
                    g.call(
                      d3.axisLeft(scales.linear).ticks(5).tickSize(0).tickPadding(8)
                        .tickFormat((v) => valueFormat(Number(v))) as never,
                    );
                    g.select('.domain').remove();
                    g.selectAll('text').attr('fill', ink.textMuted).attr('font-size', 11);
                  }
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

/** Bar with the two data-end corners rounded, baseline corners square. */
function roundedTopBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, h, w / 2);
  if (h <= 0) return '';
  return `M${x},${y + h} L${x},${y + radius} Q${x},${y} ${x + radius},${y} L${x + w - radius},${y} Q${x + w},${y} ${x + w},${y + radius} L${x + w},${y + h} Z`;
}

function roundedRightBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, w, h / 2);
  if (w <= 0) return '';
  return `M${x},${y} L${x + w - radius},${y} Q${x + w},${y} ${x + w},${y + radius} L${x + w},${y + h - radius} Q${x + w},${y + h} ${x + w - radius},${y + h} L${x},${y + h} Z`;
}

/** Mirrors of the two above, for bars that grow the other way from zero. */
function roundedBottomBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, h, w / 2);
  if (h <= 0) return '';
  return `M${x},${y} L${x},${y + h - radius} Q${x},${y + h} ${x + radius},${y + h} L${x + w - radius},${y + h} Q${x + w},${y + h} ${x + w},${y + h - radius} L${x + w},${y} Z`;
}

function roundedLeftBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, w, h / 2);
  if (w <= 0) return '';
  return `M${x + w},${y} L${x + radius},${y} Q${x},${y} ${x},${y + radius} L${x},${y + h - radius} Q${x},${y + h} ${x + radius},${y + h} L${x + w},${y + h} Z`;
}
