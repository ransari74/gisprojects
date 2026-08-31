import { useState } from 'react';

import { apiFetch } from '@/api/client';
import { useInk, useMode } from '@/components/charts/chartkit';
import { StatRow, StatTile } from '@/components/charts/Primitives';
import { useApiQuery } from '@/hooks/useApi';
import { useQueryClient } from '@tanstack/react-query';

interface AdminUser {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_login_at: string | null;
  roles: Array<{ id: number; name: string; description: string | null }>;
}

interface Role {
  id: number;
  name: string;
  description: string | null;
  is_system: boolean;
  permissions: Array<{ id: number; code: string; resource: string; action: string }>;
}

interface AdminStats {
  total_users: number;
  active_users: number;
  users_by_role: Record<string, number>;
  active_sessions: number;
}

/**
 * The RBAC model made visible: which roles exist, what each one may do, and
 * which users hold them. Reassigning a role here immediately changes what that
 * user's next token carries.
 */
export function AdminPage() {
  const mode = useMode();
  const ink = useInk(mode);
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState<string | null>(null);

  const users = useApiQuery<AdminUser[]>(['admin', 'users'], '/admin/users?limit=100');
  const roles = useApiQuery<Role[]>(['admin', 'roles'], '/admin/roles');
  const stats = useApiQuery<AdminStats>(['admin', 'stats'], '/admin/stats');

  async function assignRole(userId: string, roleName: string) {
    setBusy(userId);
    try {
      await apiFetch(`/admin/users/${userId}/roles`, {
        method: 'PUT',
        body: JSON.stringify({ role_names: roleName ? [roleName] : [] }),
      });
      await queryClient.invalidateQueries({ queryKey: ['admin'] });
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="admin-page">
      <header className="project-header">
        <div>
          <h1 style={{ color: ink.textPrimary }}>Users & roles</h1>
          <p style={{ color: ink.textSecondary }}>
            Permissions are checked by code, never by role name, so a role can be reshaped here
            without touching application code.
          </p>
        </div>
      </header>

      {Boolean(import.meta.env.VITE_API_BASE) && (
        <div className="deploy-notice" role="status">
          This is a public demo deployment — creating, deleting or reassigning users/roles is
          disabled here (the API rejects it too, not just this notice). Clone the repo and run it
          locally to try full admin read/write access.
        </div>
      )}

      {stats.data && (
        <StatRow>
          <StatTile label="Users" value={stats.data.total_users} hint={`${stats.data.active_users} active`} />
          <StatTile label="Roles" value={roles.data?.length ?? 0} />
          <StatTile label="Live sessions" value={stats.data.active_sessions} hint="unrevoked refresh tokens" />
        </StatRow>
      )}

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>Role permissions</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {['Role', 'Description', 'Permissions'].map((h) => (
                  <th key={h} style={{ color: ink.textSecondary, borderColor: ink.grid }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(roles.data ?? []).map((role) => (
                <tr key={role.id}>
                  <td style={{ color: ink.textPrimary, borderColor: ink.grid }}>
                    <strong>{role.name}</strong>
                    {role.is_system && (
                      <span className="role-chip" style={{ borderColor: ink.border, color: ink.textMuted }}>
                        system
                      </span>
                    )}
                  </td>
                  <td style={{ color: ink.textSecondary, borderColor: ink.grid }}>{role.description}</td>
                  <td style={{ color: ink.textMuted, borderColor: ink.grid }}>
                    <div className="perm-list">
                      {role.permissions.map((p) => (
                        <code key={p.id} style={{ borderColor: ink.border }}>{p.code}</code>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="admin-section" style={{ background: ink.surface, borderColor: ink.border }}>
        <h2 style={{ color: ink.textPrimary }}>Users</h2>
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                {['Email', 'Name', 'Role', 'Status', 'Last login'].map((h) => (
                  <th key={h} style={{ color: ink.textSecondary, borderColor: ink.grid }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(users.data ?? []).map((user) => (
                <tr key={user.id}>
                  <td style={{ color: ink.textPrimary, borderColor: ink.grid }}>{user.email}</td>
                  <td style={{ color: ink.textSecondary, borderColor: ink.grid }}>{user.full_name ?? '—'}</td>
                  <td style={{ borderColor: ink.grid }}>
                    <select
                      value={user.roles[0]?.name ?? ''}
                      disabled={busy === user.id}
                      onChange={(e) => void assignRole(user.id, e.target.value)}
                      style={{ background: ink.page, color: ink.textPrimary, borderColor: ink.border }}
                    >
                      <option value="">no role</option>
                      {(roles.data ?? []).map((role) => (
                        <option key={role.id} value={role.name}>{role.name}</option>
                      ))}
                    </select>
                  </td>
                  <td style={{ color: ink.textSecondary, borderColor: ink.grid }}>
                    {user.is_active ? 'active' : 'disabled'}
                    {user.is_superuser && ' · superuser'}
                  </td>
                  <td style={{ color: ink.textMuted, borderColor: ink.grid }}>
                    {user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'never'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="figure-note" style={{ color: ink.textMuted }}>
          A role change takes effect on that user's next token. Access tokens are short-lived by
          design precisely so a revocation cannot sit unenforced for long.
        </p>
      </section>
    </div>
  );
}
