import { useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch, apiPost, API_BASE } from '@/api/client';
import type { ApiKeyCreated, MetricUsage } from '@/api/types';
import { useAuth } from '@/auth/AuthContext';
import { useInk, useMode } from '@/components/charts/chartkit';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { Icon } from '@/components/Icon';
import { useApiKeys, useSubscription, useUsage } from '@/hooks/useApi';
import { useQueryClient } from '@tanstack/react-query';

const STATUS_COPY: Record<string, string> = {
  trialing: 'Trial',
  active: 'Active',
  past_due: 'Payment failed — keys still work during the grace window',
  canceled: 'Cancelled',
};

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/** A usage bar that stays honest about an unmetered plan rather than drawing 0%. */
function QuotaBar({ label, metric }: { label: string; metric: MetricUsage | undefined }) {
  const mode = useMode();
  const ink = useInk(mode);
  if (!metric) return null;

  if (metric.limit === null) {
    return (
      <div className="quota-row">
        <div className="quota-head" style={{ color: ink.textSecondary }}>
          <span>{label}</span>
          <span className="num">{metric.used.toLocaleString()} · unmetered</span>
        </div>
      </div>
    );
  }

  const pct = Math.min(100, metric.percentUsed ?? 0);
  // Colour is state, not decoration: it only ever means "this is about to stop
  // working", and the number beside it says the same thing without colour.
  const fill = pct >= 90 ? '#d03b3b' : pct >= 75 ? '#fab219' : '#2a78d6';

  return (
    <div className="quota-row">
      <div className="quota-head" style={{ color: ink.textSecondary }}>
        <span>{label}</span>
        <span className="num">
          {metric.used.toLocaleString()} / {metric.limit.toLocaleString()} ({pct.toFixed(1)}%)
        </span>
      </div>
      <div className="quota-track" style={{ background: ink.grid }}>
        <div className="quota-fill" style={{ width: `${Math.max(pct, 0.5)}%`, background: fill }} />
      </div>
    </div>
  );
}

/**
 * The customer-facing half of the commercial layer: which plan, how much of it
 * is left, and the keys that spend it.
 *
 * The one piece of state this screen holds locally is a freshly minted secret.
 * It is in the creation response and nowhere else — the server stores only a
 * SHA-256 digest — so it has to survive on screen until the user copies it, and
 * must not be refetchable afterwards.
 */
export function AccountPage() {
  const mode = useMode();
  const ink = useInk(mode);
  const { user } = useAuth();
  const queryClient = useQueryClient();

  const { data: subscription } = useSubscription();
  const { data: usage } = useUsage();
  const { data: keys } = useApiKeys();

  const [newKeyName, setNewKeyName] = useState('');
  const [freshSecret, setFreshSecret] = useState<ApiKeyCreated | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const liveKeys = (keys ?? []).filter((k) => k.revoked_at === null);
  const atCap = subscription ? liveKeys.length >= subscription.plan.max_api_keys : false;

  async function createKey(event: React.FormEvent) {
    event.preventDefault();
    if (!newKeyName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await apiPost<ApiKeyCreated>('/billing/keys', { name: newKeyName.trim() });
      setFreshSecret(created);
      setCopied(false);
      setNewKeyName('');
      await queryClient.invalidateQueries({ queryKey: ['billing', 'keys'] });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not create the key');
    } finally {
      setBusy(false);
    }
  }

  async function revokeKey(id: string, name: string) {
    if (!window.confirm(`Revoke “${name}”? Anything using it stops working immediately.`)) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await apiFetch(`/billing/keys/${id}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 204) throw new Error(`Revoke failed (${resp.status})`);
      if (freshSecret?.id === id) setFreshSecret(null);
      await queryClient.invalidateQueries({ queryKey: ['billing', 'keys'] });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not revoke the key');
    } finally {
      setBusy(false);
    }
  }

  async function copySecret(secret: string) {
    try {
      await navigator.clipboard.writeText(secret);
      setCopied(true);
    } catch {
      // Clipboard access is refused in some embedded contexts; the value is on
      // screen and selectable either way, so this is not worth an error banner.
      setCopied(false);
    }
  }

  const origin = typeof window === 'undefined' ? '' : window.location.origin;
  const apiRoot = API_BASE.startsWith('http') ? API_BASE : `${origin}${API_BASE}`;

  return (
    <div className="account-page">
      <header className="account-header">
        <h1 style={{ color: ink.textPrimary }}>Account &amp; API access</h1>
        <p style={{ color: ink.textSecondary }}>
          Signed in as <strong>{user?.email}</strong>. Everything below governs{' '}
          <em>programmatic</em> use of this API; what you can see in this app is decided by your
          role, not your plan.
        </p>
      </header>

      {error && (
        <div className="account-error" style={{ borderColor: '#d03b3b', color: '#d03b3b' }}>
          {error}
        </div>
      )}

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>
          <Icon name="tag" size={15} /> Plan
        </h2>
        {subscription ? (
          <>
            <StatRow>
              <StatTile label="Plan" value={subscription.plan.name} />
              <StatTile
                label="Status"
                value={STATUS_COPY[subscription.status] ?? subscription.status}
              />
              <StatTile
                label="Rate limit"
                value={subscription.plan.rate_limit_per_minute}
                unit="req/min"
              />
              <StatTile
                label="Renews"
                value={formatDate(subscription.current_period_end)}
                hint={
                  subscription.cancel_at_period_end
                    ? 'Cancels at period end'
                    : 'Quotas reset on the 1st'
                }
              />
            </StatRow>
            <p className="account-cta" style={{ color: ink.textSecondary }}>
              <Link to="/pricing">See all plans →</Link>
              {!subscription.payments_configured && (
                <span style={{ color: ink.textMuted }}>
                  {' '}
                  · this deployment has no payment provider configured, so paid tiers are invoiced
                </span>
              )}
            </p>
          </>
        ) : (
          <p style={{ color: ink.textMuted }}>Loading plan…</p>
        )}
      </section>

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>Usage this period</h2>
        {usage ? (
          <>
            <p className="account-period" style={{ color: ink.textMuted }}>
              Since {formatDate(usage.periodStart)} · counted per request, flushed continuously
            </p>
            <QuotaBar label="Tile requests" metric={usage.metrics.tile_request} />
            <QuotaBar label="Analytics requests" metric={usage.metrics.analytics_request} />
            <QuotaBar label="Exports" metric={usage.metrics.export_request} />
          </>
        ) : (
          <p style={{ color: ink.textMuted }}>Loading usage…</p>
        )}
      </section>

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>
          <Icon name="key" size={15} /> API keys
        </h2>

        {freshSecret && (
          <div className="key-reveal" style={{ borderColor: '#006300' }}>
            <div style={{ color: ink.textPrimary }}>
              <strong>Copy “{freshSecret.name}” now.</strong> This is the only time it is shown —
              the server keeps a hash, not the key.
            </div>
            <code className="key-secret" style={{ background: ink.page, borderColor: ink.border }}>
              {freshSecret.secret}
            </code>
            <div className="key-reveal-actions">
              <button
                type="button"
                className="ghost-button"
                style={{ color: ink.textSecondary, borderColor: ink.border }}
                onClick={() => void copySecret(freshSecret.secret)}
              >
                {copied ? 'Copied' : 'Copy'}
              </button>
              <button
                type="button"
                className="ghost-button"
                style={{ color: ink.textSecondary, borderColor: ink.border }}
                onClick={() => setFreshSecret(null)}
              >
                Done
              </button>
            </div>
          </div>
        )}

        <form className="key-form" onSubmit={createKey}>
          <input
            value={newKeyName}
            onChange={(e) => setNewKeyName(e.target.value)}
            placeholder="What will use this key? e.g. staging dashboard"
            maxLength={80}
            style={{ background: ink.page, color: ink.textPrimary, borderColor: ink.border }}
          />
          <button type="submit" className="primary-button" disabled={busy || atCap}>
            Create key
          </button>
        </form>
        {atCap && subscription && (
          <p className="account-period" style={{ color: ink.textMuted }}>
            The {subscription.plan.name} plan allows {subscription.plan.max_api_keys} active keys.
            Revoke one, or <Link to="/pricing">move up a tier</Link>.
          </p>
        )}

        {keys && keys.length > 0 ? (
          <table className="key-table">
            <thead>
              <tr style={{ color: ink.textMuted }}>
                <th>Name</th>
                <th>Key</th>
                <th>Created</th>
                <th>Last used</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {keys.map((key) => (
                <tr
                  key={key.id}
                  style={{
                    color: key.revoked_at ? ink.textMuted : ink.textSecondary,
                    borderColor: ink.border,
                  }}
                >
                  <td>{key.name}</td>
                  <td>
                    <code>{key.masked}</code>
                  </td>
                  <td>{formatDate(key.created_at)}</td>
                  <td>{key.last_used_at ? formatDate(key.last_used_at) : 'never'}</td>
                  <td>
                    {key.revoked_at ? (
                      <span>revoked {formatDate(key.revoked_at)}</span>
                    ) : (
                      <button
                        type="button"
                        className="ghost-button"
                        style={{ color: ink.textSecondary, borderColor: ink.border }}
                        disabled={busy}
                        onClick={() => void revokeKey(key.id, key.name)}
                      >
                        Revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p style={{ color: ink.textMuted }}>No keys yet.</p>
        )}
      </section>

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>Using a key</h2>
        <p style={{ color: ink.textSecondary, fontSize: 12.5, margin: '0 0 10px' }}>
          Send it as a header, or — where headers are impossible, such as a native map SDK — as{' '}
          <code>?api_key=</code>. The query form lands in access logs, so prefer the header.
        </p>
        <pre className="key-snippet" style={{ background: ink.page, borderColor: ink.border, color: ink.textSecondary }}>
{`# One vector tile
curl -H "X-API-Key: $GEO_KEY" \\
  "${apiRoot}/tiles/agri_fields/11/1053/675.mvt" -o tile.mvt

# Analytics, as JSON
curl -H "X-API-Key: $GEO_KEY" \\
  "${apiRoot}/agriculture/yield-by-crop"

# What your key is allowed to see
curl -H "X-API-Key: $GEO_KEY" "${apiRoot}/tiles/capabilities"`}
        </pre>
      </section>
    </div>
  );
}
