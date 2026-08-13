-- ---------------------------------------------------------------------------
-- RBAC seed: permission catalogue, built-in roles, role->permission mapping.
--
-- Idempotent: safe to re-run against an existing database.
-- Demo users are created by the API on startup (they need bcrypt hashes),
-- see backend/app/core/bootstrap.py.
-- ---------------------------------------------------------------------------

INSERT INTO auth.permissions (code, resource, action, description) VALUES
    -- per-project read
    ('agriculture:read',   'agriculture',   'read',   'View agriculture layers, tiles and analytics'),
    ('parcel:read',        'parcel',        'read',   'View cadastral parcels and zoning'),
    ('demographics:read',  'demographics',  'read',   'View census tracts and population data'),
    ('transport:read',     'transport',     'read',   'View road network, transit and isochrones'),
    ('terrain:read',       'terrain',       'read',   'View 3D buildings, contours and terrain'),
    -- per-project write
    ('agriculture:write',  'agriculture',   'write',  'Create/update field records'),
    ('parcel:write',       'parcel',        'write',  'Create/update parcel records'),
    ('demographics:write', 'demographics',  'write',  'Create/update census records'),
    ('transport:write',    'transport',     'write',  'Create/update network records'),
    ('terrain:write',      'terrain',       'write',  'Create/update building records'),
    -- cross-cutting
    ('data:export',        'data',          'export', 'Export query results as GeoJSON/CSV'),
    ('analytics:read',     'analytics',     'read',   'Access aggregate analytics endpoints'),
    ('admin:users',        'admin',         'users',  'Create, edit and deactivate users'),
    ('admin:roles',        'admin',         'roles',  'Assign roles and edit role permissions'),
    ('admin:audit',        'admin',         'audit',  'Read the audit log')
ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO auth.roles (name, description, is_system) VALUES
    ('admin',       'Full access to every project plus user and role administration', TRUE),
    ('analyst',     'Read access to all five projects, analytics and data export',    TRUE),
    ('agronomist',  'Agriculture read/write; read-only elsewhere for context',        TRUE),
    ('planner',     'Parcel and transport read/write; reads demographics + terrain',  TRUE),
    ('viewer',      'Read-only access to map layers, no export, no analytics detail', TRUE)
ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;

-- --- admin: everything ------------------------------------------------------
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r CROSS JOIN auth.permissions p
WHERE r.name = 'admin'
ON CONFLICT DO NOTHING;

-- --- analyst: all reads + analytics + export --------------------------------
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r JOIN auth.permissions p ON TRUE
WHERE r.name = 'analyst'
  AND p.code IN ('agriculture:read','parcel:read','demographics:read',
                 'transport:read','terrain:read','analytics:read','data:export')
ON CONFLICT DO NOTHING;

-- --- agronomist: agriculture write, contextual reads ------------------------
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r JOIN auth.permissions p ON TRUE
WHERE r.name = 'agronomist'
  AND p.code IN ('agriculture:read','agriculture:write','terrain:read',
                 'demographics:read','analytics:read','data:export')
ON CONFLICT DO NOTHING;

-- --- planner: parcel + transport write --------------------------------------
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r JOIN auth.permissions p ON TRUE
WHERE r.name = 'planner'
  AND p.code IN ('parcel:read','parcel:write','transport:read','transport:write',
                 'demographics:read','terrain:read','analytics:read','data:export')
ON CONFLICT DO NOTHING;

-- --- viewer: reads only, no export, no analytics ----------------------------
INSERT INTO auth.role_permissions (role_id, permission_id)
SELECT r.id, p.id FROM auth.roles r JOIN auth.permissions p ON TRUE
WHERE r.name = 'viewer'
  AND p.code IN ('agriculture:read','parcel:read','demographics:read',
                 'transport:read','terrain:read')
ON CONFLICT DO NOTHING;
