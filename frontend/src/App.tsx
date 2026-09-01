import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom';

import type { ProjectKey } from '@/api/types';
import { AuthProvider, useAuth } from '@/auth/AuthContext';
import { useInk, useMode } from '@/components/charts/chartkit';
import { Icon, type IconName } from '@/components/Icon';
import { AdminPage } from '@/pages/Admin';
import { LandingPage } from '@/pages/Landing';
import { LoginPage } from '@/pages/Login';
import { AgricultureProject } from '@/projects/Agriculture';
import { DemographicsProject } from '@/projects/Demographics';
import { ParcelProject } from '@/projects/Parcel';
import { RemoteSensingProject } from '@/projects/RemoteSensing';
import { Terrain3DProject } from '@/projects/Terrain3D';
import { TransportProject } from '@/projects/Transport';
import '@/styles/app.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
      staleTime: 60_000,
    },
  },
});

// Icon names mirror the `icon` field the backend assigns per project in
// PROJECTS (app/services/layers.py) -- kept as a local literal rather than
// read off /tiles/capabilities so the nav can render on the very first paint,
// before that request resolves.
const NAV: Array<{ to: string; label: string; project: ProjectKey; icon: IconName }> = [
  { to: '/agriculture', label: 'Agriculture', project: 'agriculture', icon: 'sprout' },
  { to: '/parcel', label: 'Cadastre', project: 'parcel', icon: 'map' },
  { to: '/demographics', label: 'Demographics', project: 'demographics', icon: 'users' },
  { to: '/transport', label: 'Transport', project: 'transport', icon: 'route' },
  { to: '/terrain', label: '3D Terrain', project: 'terrain', icon: 'mountain' },
  { to: '/remote-sensing', label: 'Remote Sensing', project: 'remote_sensing', icon: 'satellite' },
];

function Shell() {
  const { user, signOut, canOpen, can, loading } = useAuth();
  const mode = useMode();
  const ink = useInk(mode);
  const location = useLocation();

  if (loading) {
    return (
      <div className="boot-screen" style={{ background: ink.page, color: ink.textMuted }}>
        Restoring session…
      </div>
    );
  }

  if (!user) return <LoginPage />;

  return (
    <div className="app-shell" style={{ background: ink.page }}>
      <nav className="app-nav" style={{ background: ink.surface, borderColor: ink.border }}>
        <NavLink to="/" className="brand" style={{ color: ink.textPrimary }}>
          Geo<span style={{ color: ink.textMuted }}>Portfolio</span>
        </NavLink>

        <div className="nav-links">
          {NAV.filter((item) => canOpen(item.project)).map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              style={{ color: ink.textSecondary }}
            >
              <Icon name={item.icon} size={15} />
              {item.label}
            </NavLink>
          ))}
          {can('admin:users') && (
            <NavLink
              to="/admin"
              className={({ isActive }) => `nav-link${isActive ? ' active' : ''}`}
              style={{ color: ink.textSecondary }}
            >
              <Icon name="shield" size={15} />
              Admin
            </NavLink>
          )}
        </div>

        <div className="nav-user">
          <span style={{ color: ink.textSecondary }}>
            {user.full_name ?? user.email}
            <span className="role-chip" style={{ borderColor: ink.border, color: ink.textMuted }}>
              {user.roles.join(', ') || 'no role'}
            </span>
          </span>
          <button
            type="button"
            className="ghost-button"
            onClick={() => void signOut()}
            style={{ color: ink.textSecondary, borderColor: ink.border }}
          >
            Sign out
          </button>
        </div>
      </nav>

      <main className="app-main">
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route
            path="/agriculture"
            element={canOpen('agriculture') ? <AgricultureProject /> : <Denied />}
          />
          <Route path="/parcel" element={canOpen('parcel') ? <ParcelProject /> : <Denied />} />
          <Route
            path="/demographics"
            element={canOpen('demographics') ? <DemographicsProject /> : <Denied />}
          />
          <Route path="/transport" element={canOpen('transport') ? <TransportProject /> : <Denied />} />
          <Route path="/terrain" element={canOpen('terrain') ? <Terrain3DProject /> : <Denied />} />
          <Route
            path="/remote-sensing"
            element={canOpen('remote_sensing') ? <RemoteSensingProject /> : <Denied />}
          />
          <Route path="/admin" element={can('admin:users') ? <AdminPage /> : <Denied />} />
          <Route path="*" element={<Navigate to="/" replace state={{ from: location }} />} />
        </Routes>
      </main>
    </div>
  );
}

function Denied() {
  const mode = useMode();
  const ink = useInk(mode);
  const { user } = useAuth();
  return (
    <div className="denied" style={{ color: ink.textSecondary }}>
      <h2 style={{ color: ink.textPrimary }}>Not available for your role</h2>
      <p>
        You are signed in as <strong>{user?.email}</strong> with the role{' '}
        <strong>{user?.roles.join(', ') || 'none'}</strong>, which does not include access to this
        project. The navigation only lists projects your role can open — this page is what a direct
        link to a restricted project looks like.
      </p>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Shell />
      </AuthProvider>
    </QueryClientProvider>
  );
}
