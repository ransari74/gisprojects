import { useState } from 'react';

import { useAuth } from '@/auth/AuthContext';
import { useInk, useMode } from '@/components/charts/chartkit';

/** The five seeded demo accounts, so the RBAC model is explorable immediately. */
const DEMO_ACCOUNTS = [
  { email: 'admin@geo.dev', role: 'admin', blurb: 'Every project, plus user and role administration' },
  { email: 'analyst@geo.dev', role: 'analyst', blurb: 'Reads all five projects, analytics and export' },
  { email: 'agronomist@geo.dev', role: 'agronomist', blurb: 'Agriculture read/write — cadastre is hidden' },
  { email: 'planner@geo.dev', role: 'planner', blurb: 'Cadastre and transport — agriculture is hidden' },
  { email: 'viewer@geo.dev', role: 'viewer', blurb: 'Map layers only: no analytics detail, no export' },
];

const DEMO_PASSWORD = 'demo1234';

// VITE_API_BASE is only set for the deployed build (Cloudflare); local dev
// and docker-compose both leave it unset and use the same-origin /api proxy
// instead -- so its presence is a reliable "is this the free-tier deploy?"
// signal, no separate env flag needed.
const IS_DEPLOYED = Boolean(import.meta.env.VITE_API_BASE);

export function LoginPage() {
  const { signIn, error } = useAuth();
  const mode = useMode();
  const ink = useInk(mode);
  const [email, setEmail] = useState('admin@geo.dev');
  const [password, setPassword] = useState(DEMO_PASSWORD);
  const [busy, setBusy] = useState(false);
  const [showDeployNotice, setShowDeployNotice] = useState(IS_DEPLOYED);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await signIn(email, password);
    } catch {
      /* error surfaces through the auth context */
    } finally {
      setBusy(false);
    }
  }

  async function quickSignIn(demoEmail: string) {
    setEmail(demoEmail);
    setPassword(DEMO_PASSWORD);
    setBusy(true);
    try {
      await signIn(demoEmail, DEMO_PASSWORD);
    } catch {
      /* handled above */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page" style={{ background: ink.page }}>
      <div className="login-card" style={{ background: ink.surface, borderColor: ink.border }}>
        <h1 style={{ color: ink.textPrimary }}>Geospatial Portfolio</h1>
        <p style={{ color: ink.textSecondary }}>
          Five analytics projects over Utrecht, Netherlands — agriculture, cadastre, demographics,
          transport and 3D terrain. Vector tiles are served from PostGIS and gated per role.
        </p>

        {showDeployNotice && (
          <div className="deploy-notice" role="status">
            <button
              type="button"
              className="deploy-notice-close"
              onClick={() => setShowDeployNotice(false)}
              aria-label="Dismiss"
            >
              ×
            </button>
            This deployment runs on free-tier hosting — an AWS Lambda API (cold starts) in front of
            a free-tier Postgres instance, both of which add real latency the first time each layer
            or chart loads. For a faster, always-warm experience, clone the repo and run it locally
            with Docker Compose instead.
          </div>
        )}

        <form onSubmit={submit} className="login-form">
          <label style={{ color: ink.textSecondary }}>
            Email
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
              style={{ background: ink.page, color: ink.textPrimary, borderColor: ink.border }}
            />
          </label>
          <label style={{ color: ink.textSecondary }}>
            Password
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
              style={{ background: ink.page, color: ink.textPrimary, borderColor: ink.border }}
            />
          </label>
          {error && (
            <div className="login-error" role="alert">
              {error}
            </div>
          )}
          <button type="submit" className="primary-button" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="demo-accounts">
          <div className="demo-title" style={{ color: ink.textSecondary }}>
            Demo accounts — each sees a different slice
          </div>
          <ul>
            {DEMO_ACCOUNTS.map((account) => (
              <li key={account.email}>
                <button
                  type="button"
                  onClick={() => void quickSignIn(account.email)}
                  disabled={busy}
                  style={{ borderColor: ink.border }}
                >
                  <span className="demo-role" style={{ color: ink.textPrimary }}>{account.role}</span>
                  <span className="demo-blurb" style={{ color: ink.textMuted }}>{account.blurb}</span>
                </button>
              </li>
            ))}
          </ul>
          <p className="figure-note" style={{ color: ink.textMuted }}>
            All demo accounts use the password <code>{DEMO_PASSWORD}</code>. Sign in as the
            agronomist and the cadastre disappears from the navigation — and a direct request for
            its tiles returns 403 from the API, not just a hidden link.
          </p>
        </div>
      </div>
    </div>
  );
}
