/**
 * Floating control cluster: basemap choice, plus a toggle + opacity slider
 * for each raster overlay the current map offers (e.g. ESA WorldCover on the
 * agriculture project). Self-contained -- MapView owns all of the state this
 * reads and writes, so every project page gets the same control for free.
 *
 * Collapsed by default behind a header button -- with several projects now
 * offering multiple overlays, the panel's content can get tall enough to
 * cover a meaningful chunk of the map otherwise.
 */

import { useState } from 'react';
import type { BasemapSpec, OverlaySpec } from '@/api/types';
import { Icon } from './Icon';
import { useInk, useMode } from './charts/chartkit';

interface OverlayUiState {
  visible: boolean;
  opacity: number;
}

interface BasemapSwitcherProps {
  basemaps: BasemapSpec[];
  activeId: string;
  onChange: (id: string) => void;
  overlays: OverlaySpec[];
  overlayState: Record<string, OverlayUiState>;
  onOverlayChange: (id: string, patch: Partial<OverlayUiState>) => void;
}

export function BasemapSwitcher({
  basemaps,
  activeId,
  onChange,
  overlays,
  overlayState,
  onOverlayChange,
}: BasemapSwitcherProps) {
  const mode = useMode();
  const ink = useInk(mode);
  const [open, setOpen] = useState(false);
  const activeBasemap = basemaps.find((b) => b.id === activeId);
  const activeOverlayCount = overlays.filter((o) => overlayState[o.id]?.visible).length;

  return (
    <div
      className={`basemap-panel${open ? '' : ' collapsed'}`}
      style={{ background: ink.surface, borderColor: ink.border }}
    >
      <button
        type="button"
        className="basemap-panel-toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        style={{ color: ink.textPrimary }}
      >
        <span>
          {activeBasemap?.name ?? 'Basemap'}
          {activeOverlayCount > 0 ? ` + ${activeOverlayCount} overlay${activeOverlayCount > 1 ? 's' : ''}` : ''}
        </span>
        <span style={{ color: ink.textSecondary, display: 'flex' }}>
          <Icon name={open ? 'close' : 'layers'} size={15} />
        </span>
      </button>

      {open && (
        <>
      <div className="basemap-panel-title" style={{ color: ink.textSecondary }}>
        Basemap
      </div>
      <div className="basemap-options" role="radiogroup" aria-label="Basemap">
        {basemaps.map((b) => (
          <button
            key={b.id}
            type="button"
            role="radio"
            aria-checked={b.id === activeId}
            title={b.description}
            className={`basemap-option${b.id === activeId ? ' active' : ''}`}
            onClick={() => onChange(b.id)}
            style={
              b.id === activeId
                ? { background: ink.textPrimary, color: ink.surface, borderColor: ink.textPrimary }
                : { color: ink.textSecondary, borderColor: ink.border }
            }
          >
            {/* "roads" vs "imagery" is the one distinction that actually
                separates a set of basemaps that are otherwise just names --
                the glyph says at a glance what family an option belongs to. */}
            <Icon name={b.kind === 'roads' ? 'road' : 'image'} size={13} />
            {b.name}
          </button>
        ))}
      </div>

      {overlays.length > 0 && (
        <div className="basemap-overlays">
          <div className="basemap-panel-title" style={{ color: ink.textSecondary }}>
            Overlays
          </div>
          {overlays.map((overlay) => {
            const state = overlayState[overlay.id] ?? { visible: false, opacity: overlay.defaultOpacity };
            return (
              <div key={overlay.id} className="overlay-control">
                <label className="overlay-toggle-row">
                  <input
                    type="checkbox"
                    checked={state.visible}
                    onChange={(e) => onOverlayChange(overlay.id, { visible: e.target.checked })}
                  />
                  <span style={{ color: ink.textPrimary }}>{overlay.name}</span>
                </label>
                {state.visible && (
                  <>
                    <input
                      type="range"
                      min={0.1}
                      max={1}
                      step={0.05}
                      value={state.opacity}
                      aria-label={`${overlay.name} opacity`}
                      onChange={(e) => onOverlayChange(overlay.id, { opacity: Number(e.target.value) })}
                      className="overlay-opacity"
                    />
                    {overlay.legend.length > 0 ? (
                      <ul className="legend compact overlay-legend">
                        {overlay.legend.map((c) => (
                          <li key={c.code} style={{ color: ink.textSecondary }}>
                            <span
                              className="legend-swatch"
                              style={{ background: c.colorHex }}
                              aria-hidden="true"
                            />
                            {c.label}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      // A continuous property (SoilGrids) or a pre-styled
                      // cartographic layer (the water reference overlay) has
                      // no fixed class list -- explain what the colours mean
                      // in prose instead of inventing fake swatches.
                      <p className="figure-note overlay-legend-note" style={{ color: ink.textSecondary }}>
                        {overlay.legendNote}
                      </p>
                    )}
                    <p className="figure-note overlay-attribution" style={{ color: ink.textMuted }}>
                      {overlay.description} · {overlay.attribution}
                    </p>
                  </>
                )}
              </div>
            );
          })}
        </div>
      )}
        </>
      )}
    </div>
  );
}
