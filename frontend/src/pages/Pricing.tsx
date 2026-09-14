import { useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { apiPost } from '@/api/client';
import type { CheckoutResponse, Plan } from '@/api/types';
import { useInk, useMode } from '@/components/charts/chartkit';
import { Icon } from '@/components/Icon';
import { usePlans, useSubscription } from '@/hooks/useApi';
import { useQueryClient } from '@tanstack/react-query';

/** Prices are stored in cents so the ladder never drifts through float maths. */
function formatPrice(plan: Plan): { amount: string; suffix: string } {
  if (plan.price_cents === null) return { amount: 'Let’s talk', suffix: '' };
  if (plan.price_cents === 0) return { amount: 'Free', suffix: 'forever' };
  const major = plan.price_cents / 100;
  const symbol = plan.currency === 'EUR' ? '€' : `${plan.currency} `;
  return {
    amount: `${symbol}${major.toLocaleString(undefined, { maximumFractionDigits: 0 })}`,
    suffix: `per ${plan.billing_interval}`,
  };
}

function formatQuota(value: number | null): string {
  if (value === null) return 'Unmetered';
  return value.toLocaleString();
}

/**
 * The price list.
 *
 * Deliberately readable signed-out — /billing/plans takes no auth — because a
 * pricing page that needs an account is a pricing page nobody reads. The tier
 * the caller is already on is flagged from the same response rather than
 * computed here, so "current" cannot disagree with what the API will enforce.
 */
export function PricingPage() {
  const mode = useMode();
  const ink = useInk(mode);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: plans, isLoading } = usePlans();
  const { data: subscription } = useSubscription();

  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);

  async function choose(plan: Plan) {
    setBusy(plan.code);
    setNotice(null);
    try {
      const result = await apiPost<CheckoutResponse>('/billing/checkout', {
        plan_code: plan.code,
      });
      // A hosted checkout hands back a URL; a free plan is applied on the spot.
      if (result.checkout_url) {
        window.location.href = result.checkout_url;
        return;
      }
      await queryClient.invalidateQueries({ queryKey: ['billing'] });
      setNotice({ kind: 'ok', text: result.message });
      navigate('/account');
    } catch (err) {
      setNotice({
        kind: 'error',
        text: err instanceof Error ? err.message : 'Could not change plan',
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="pricing-page">
      <header className="pricing-header">
        <h1 style={{ color: ink.textPrimary }}>Pricing</h1>
        <p style={{ color: ink.textSecondary }}>
          The same vector tiles and analytics this app runs on, available to your own code. Mint an
          API key, send it as <code>X-API-Key</code>, and every endpoint in these six projects
          answers. Each tier is a permission set, a monthly allowance and a rate limit — nothing is
          gated behind a sales call except the tier that says so.
        </p>
      </header>

      {notice && (
        <div
          className="pricing-notice"
          style={{
            borderColor: ink.border,
            background: ink.surface,
            color: notice.kind === 'error' ? '#d03b3b' : ink.textSecondary,
          }}
        >
          {notice.text}
        </div>
      )}

      {isLoading && <p style={{ color: ink.textMuted }}>Loading plans…</p>}

      <div className="plan-grid">
        {(plans ?? []).map((plan) => {
          const price = formatPrice(plan);
          const isCurrent = plan.current || subscription?.plan.code === plan.code;
          return (
            <section
              key={plan.code}
              className={`plan-card${isCurrent ? ' current' : ''}`}
              style={{ background: ink.surface, borderColor: isCurrent ? '#2a78d6' : ink.border }}
            >
              {isCurrent && (
                <div className="plan-badge" style={{ background: '#2a78d6' }}>
                  Your plan
                </div>
              )}
              <h2 style={{ color: ink.textPrimary }}>{plan.name}</h2>
              <div className="plan-price" style={{ color: ink.textPrimary }}>
                {price.amount}
                {price.suffix && (
                  <span className="plan-price-suffix" style={{ color: ink.textMuted }}>
                    {price.suffix}
                  </span>
                )}
              </div>
              <p className="plan-blurb" style={{ color: ink.textSecondary }}>
                {plan.blurb}
              </p>

              <ul className="plan-features" style={{ color: ink.textSecondary }}>
                {plan.features.map((feature) => (
                  <li key={feature}>
                    <span className="plan-tick" style={{ color: '#006300' }}>
                      ✓
                    </span>
                    {feature}
                  </li>
                ))}
              </ul>

              <dl className="plan-limits" style={{ color: ink.textMuted }}>
                <div>
                  <dt>Tiles</dt>
                  <dd className="num">{formatQuota(plan.tile_quota)}</dd>
                </div>
                <div>
                  <dt>Analytics</dt>
                  <dd className="num">{formatQuota(plan.analytics_quota)}</dd>
                </div>
                <div>
                  <dt>Rate</dt>
                  <dd className="num">{plan.rate_limit_per_minute.toLocaleString()}/min</dd>
                </div>
              </dl>

              {plan.self_serve ? (
                <button
                  type="button"
                  className="primary-button plan-cta"
                  disabled={isCurrent || busy !== null}
                  onClick={() => void choose(plan)}
                >
                  {isCurrent ? 'Current plan' : busy === plan.code ? 'Working…' : `Choose ${plan.name}`}
                </button>
              ) : (
                <a
                  className="primary-button plan-cta"
                  href={`mailto:${plan.sales_email ?? ''}?subject=${encodeURIComponent(
                    `${plan.name} plan enquiry`,
                  )}`}
                >
                  Talk to us
                </a>
              )}
            </section>
          );
        })}
      </div>

      <section className="pricing-notes" style={{ background: ink.surface, borderColor: ink.border }}>
        <h3 style={{ color: ink.textPrimary }}>
          <Icon name="key" size={15} /> How metering works
        </h3>
        <dl style={{ color: ink.textSecondary }}>
          <div>
            <dt>What counts</dt>
            <dd>
              One tile request is one tile; one analytics or feature call is one analytics request.
              Traffic from this web app, signed in as you, is <strong>not</strong> metered — you pay
              for programmatic access, not for reading your own dashboard.
            </dd>
          </div>
          <div>
            <dt>What a key can do</dt>
            <dd>
              A key carries its <em>plan’s</em> permissions, never its owner’s. An administrator who
              pastes a key into a client-side app exposes the tier they bought, not their account.
            </dd>
          </div>
          <div>
            <dt>When the meter resets</dt>
            <dd>
              On the first of the calendar month. Going over returns <code>402</code> with the used
              and allowed counts in the response headers; going too fast returns <code>429</code>{' '}
              with <code>Retry-After</code>. Neither drops a plan or charges an overage.
            </dd>
          </div>
          <div>
            <dt>If a payment fails</dt>
            <dd>
              Keys keep working through a grace window rather than cutting off the moment a card
              expires. Cancelling drops you to Free at the end of the period, and your keys keep
              working at Free’s limits.
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}
