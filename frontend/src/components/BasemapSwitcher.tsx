/**
 * Floating control cluster: basemap choice, plus a toggle + opacity slider
 * for each raster overlay the current map offers (e.g. ESA WorldCover on the
 * agriculture project). Self-contained -- MapView owns all of the state this
 * reads and writes, so every project page gets the same control for free.
 */

import type { BasemapSpec, OverlaySpec } from '@/api/types';
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

  return (
    <div className="basemap-panel" style={{ background: ink.surface, borderColor: ink.border }}>
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
    </div>
  );
}
