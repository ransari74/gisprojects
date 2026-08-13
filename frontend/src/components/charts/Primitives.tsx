/**
 * Chart shell pieces: figure frame, legend, tooltip, table view and stat tile.
 *
 * The figure frame is what enforces the accessibility contract -- every chart
 * with two or more series gets a legend, and every chart offers a table view,
 * so nothing is conveyed by colour alone.
 */

import { useId, useMemo, useState, type ReactNode } from 'react';

import { CHROME } from '@/styles/theme';
import { titleCase, useInk, useMode, type TooltipState } from './chartkit';

// ---------------------------------------------------------------------------
// Figure frame
// ---------------------------------------------------------------------------
export interface LegendItem {
  label: string;
  color: string;
}

interface FigureProps {
  title: string;
  subtitle?: string;
  /** Present whenever the chart draws two or more series. */
  legend?: LegendItem[];
  /** Rows backing the "Table" toggle -- the non-visual route to the same data. */
  table?: { columns: string[]; rows: Array<Array<string | number>> };
  note?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
}

export function Figure({ title, subtitle, legend, table, note, actions, children }: FigureProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();

  return (
    <figure className="figure" style={{ background: ink.surface, borderColor: ink.border }}>
      <div className="figure-head">
        <div>
          <figcaption className="figure-title" style={{ color: ink.textPrimary }}>
            {title}
          </figcaption>
          {subtitle && (
            <p className="figure-subtitle" style={{ color: ink.textSecondary }}>
              {subtitle}
            </p>
          )}
        </div>
        <div className="figure-actions">
          {actions}
          {table && (
            <button
              type="button"
              className="ghost-button"
              aria-expanded={showTable}
              aria-controls={tableId}
              onClick={() => setShowTable((v) => !v)}
              style={{ color: ink.textSecondary, borderColor: ink.border }}
            >
              {showTable ? 'Chart' : 'Table'}
            </button>
          )}
        </div>
      </div>

      {legend && legend.length > 1 && (
        <ul className="legend" aria-label="Legend">
          {legend.map((item) => (
            <li key={item.label} style={{ color: ink.textSecondary }}>
              <span className="legend-swatch" style={{ background: item.color }} aria-hidden="true" />
              {titleCase(item.label)}
            </li>
          ))}
        </ul>
      )}

      {showTable && table ? (
        <div className="table-wrap" id={tableId}>
          <table className="data-table">
            <thead>
              <tr>
                {table.columns.map((c) => (
                  <th key={c} style={{ color: ink.textSecondary, borderColor: ink.grid }}>
                    {titleCase(c)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {table.rows.map((row, i) => (
                <tr key={i}>
                  {row.map((cell, j) => (
                    <td
                      key={j}
                      style={{ color: ink.textPrimary, borderColor: ink.grid }}
                      className={typeof cell === 'number' ? 'num' : undefined}
                    >
                      {typeof cell === 'number' ? cell.toLocaleString() : cell}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        children
      )}

      {note && (
        <p className="figure-note" style={{ color: ink.textMuted }}>
          {note}
        </p>
      )}
    </figure>
  );
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------
export function Tooltip({ state }: { state: TooltipState | null }) {
  const mode = useMode();
  const ink = CHROME[mode];
  if (!state) return null;
  return (
    <div
      className="chart-tooltip"
      role="status"
      style={{
        left: state.x,
        top: state.y,
        background: ink.surface,
        color: ink.textPrimary,
        borderColor: ink.border,
      }}
    >
      <div className="tooltip-title">{state.title}</div>
      {state.rows.map((row) => (
        <div className="tooltip-row" key={row.label}>
          {row.color && <span className="tooltip-swatch" style={{ background: row.color }} />}
          <span style={{ color: ink.textSecondary }}>{row.label}</span>
          <span className="num" style={{ color: ink.textPrimary }}>
            {row.value}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat tile -- the right form when the answer is one number, not a chart
// ---------------------------------------------------------------------------
interface StatTileProps {
  label: string;
  value: string | number;
  unit?: string;
  hint?: string;
  accent?: string;
}

export function StatTile({ label, value, unit, hint, accent }: StatTileProps) {
  const mode = useMode();
  const ink = useInk(mode);
  return (
    <div className="stat-tile" style={{ background: ink.surface, borderColor: ink.border }}>
      <div className="stat-label" style={{ color: ink.textSecondary }}>
        {label}
      </div>
      <div className="stat-value" style={{ color: accent ?? ink.textPrimary }}>
        {typeof value === 'number' ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value}
        {unit && <span className="stat-unit" style={{ color: ink.textMuted }}>{unit}</span>}
      </div>
      {hint && (
        <div className="stat-hint" style={{ color: ink.textMuted }}>
          {hint}
        </div>
      )}
    </div>
  );
}

export function StatRow({ children }: { children: ReactNode }) {
  return <div className="stat-row">{children}</div>;
}

// ---------------------------------------------------------------------------
// Sequential legend for choropleth-style encodings
// ---------------------------------------------------------------------------
export function SequentialLegend({
  title,
  range,
  colors,
  format,
}: {
  title: string;
  range: [number, number];
  colors: string[];
  format?: (v: number) => string;
}) {
  const mode = useMode();
  const ink = useInk(mode);
  const gradient = useMemo(() => `linear-gradient(to right, ${colors.join(', ')})`, [colors]);
  const fmt = format ?? ((v: number) => v.toLocaleString(undefined, { maximumFractionDigits: 1 }));
  return (
    <div className="seq-legend">
      <div className="seq-legend-title" style={{ color: ink.textSecondary }}>
        {titleCase(title)}
      </div>
      <div className="seq-legend-bar" style={{ background: gradient, borderColor: ink.border }} />
      <div className="seq-legend-scale" style={{ color: ink.textMuted }}>
        <span>{fmt(range[0])}</span>
        <span>{fmt(range[1])}</span>
      </div>
    </div>
  );
}

export function EmptyState({ message }: { message: string }) {
  const mode = useMode();
  const ink = useInk(mode);
  return (
    <div className="empty-state" style={{ color: ink.textMuted, borderColor: ink.grid }}>
      {message}
    </div>
  );
}
