import { Link } from 'react-router-dom';

import { useAuth } from '@/auth/AuthContext';
import { useInk, useMode } from '@/components/charts/chartkit';
import { useCapabilities, useProjectCatalogue, useStudyArea } from '@/hooks/useApi';

const ROUTE_FOR: Record<string, string> = {
  agriculture: '/agriculture',
  parcel: '/parcel',
  demographics: '/demographics',
  transport: '/transport',
  terrain: '/terrain',
  remote_sensing: '/remote-sensing',
};

export function LandingPage() {
  const mode = useMode();
  const ink = useInk(mode);
  const { user } = useAuth();
  const { data: projects } = useProjectCatalogue();
  const { data: capabilities } = useCapabilities();
  const { data: studyArea } = useStudyArea();

  const layerCount = (key: string) =>
    capabilities?.projects.find((p) => p.key === key)?.layers.length ?? 0;

  return (
    <div className="landing">
      <header className="landing-header">
        <h1 style={{ color: ink.textPrimary }}>Six geospatial projects, one study area</h1>
        <p style={{ color: ink.textSecondary }}>
          Everything below covers {studyArea?.name ?? 'the study area'} — the same footprint, so the
          layers overlay exactly. Vector tiles come from PostGIS via <code>ST_AsMVT</code>, rendered
          with MapLibre; the analytics panels are D3 over aggregate endpoints. Access is decided by
          your role, both in this navigation and at the API.
        </p>
        {user && (
          <p className="landing-role" style={{ color: ink.textMuted }}>
            Signed in as <strong style={{ color: ink.textSecondary }}>{user.email}</strong> ·
            role <strong style={{ color: ink.textSecondary }}>{user.roles.join(', ') || 'none'}</strong> ·
            {user.permissions.length} permissions
          </p>
        )}
      </header>

      <div className="project-grid">
        {(projects ?? []).map((project) => {
          const layers = layerCount(project.key);
          const body = (
            <>
              <div className="project-card-accent" style={{ background: project.accent }} />
              <h2 style={{ color: ink.textPrimary }}>{project.title}</h2>
              <p style={{ color: ink.textSecondary }}>{project.tagline}</p>
              <div className="project-card-foot" style={{ color: ink.textMuted }}>
                {project.accessible ? (
                  <>
                    {layers} layer{layers === 1 ? '' : 's'} · open project →
                  </>
                ) : (
                  <>Locked — your role has no {project.key} access</>
                )}
              </div>
            </>
          );

          return project.accessible ? (
            <Link
              key={project.key}
              to={ROUTE_FOR[project.key]}
              className="project-card"
              style={{ background: ink.surface, borderColor: ink.border }}
            >
              {body}
            </Link>
          ) : (
            <div
              key={project.key}
              className="project-card locked"
              style={{ background: ink.surface, borderColor: ink.border }}
              aria-disabled="true"
            >
              {body}
            </div>
          );
        })}
      </div>

      <section className="landing-notes" style={{ background: ink.surface, borderColor: ink.border }}>
        <h3 style={{ color: ink.textPrimary }}>How it fits together</h3>
        <dl style={{ color: ink.textSecondary }}>
          <div>
            <dt>Tiles</dt>
            <dd>
              PostGIS builds each tile with <code>ST_AsMVT</code>. The tile envelope is transformed
              into the storage SRID and compared against the untransformed geometry column, so the
              GiST index is usable — transforming the column instead would force a sequential scan
              on every tile.
            </dd>
          </div>
          <div>
            <dt>Access control</dt>
            <dd>
              Permissions travel inside the access token, so a tile request authorises without a
              database round-trip. The layer catalogue is filtered server-side: a role without{' '}
              <code>parcel:read</code> is never told the parcel layers exist.
            </dd>
          </div>
          <div>
            <dt>Geometry</dt>
            <dd>
              Every project carries both polygon and linestring layers — fields and canals, parcels
              and boundaries, tracts and commute flows, isochrones and roads, buildings and contours —
              and the remote-sensing project adds a point layer of InSAR scatterers.
            </dd>
          </div>
          <div>
            <dt>Data</dt>
            <dd>
              The schema mirrors real open datasets — BRP crop parcels, Kadaster BRK, CBS
              neighbourhood statistics, OSM via Geofabrik, 3DBAG, Copernicus DEM, Sentinel-1/2,
              Landsat and the Copernicus Ground Motion Service. The running
              instance is loaded with a synthetic stand-in that reproduces their distributions, so
              the stack works with no downloads; each project's "data sources" panel lists the real
              URLs and licences.
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
