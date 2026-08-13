-- ---------------------------------------------------------------------------
-- RBAC model
--
--   user ──< user_roles >── role ──< role_permissions >── permission
--
-- Permissions are opaque string codes of the form "<resource>:<action>", e.g.
-- "agriculture:read", "parcel:write", "admin:users". The API never checks a
-- role name directly -- it always checks a permission code, so roles can be
-- reshaped from the admin UI without touching application code.
-- ---------------------------------------------------------------------------

CREATE TABLE auth.users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- emails are normalised to lowercase by the API; the functional unique
    -- index below is the backstop so case-variant duplicates cannot exist
    email           TEXT NOT NULL,
    full_name       TEXT,
    hashed_password TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    is_superuser    BOOLEAN NOT NULL DEFAULT FALSE,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX users_email_lower_idx ON auth.users (lower(email));

CREATE TABLE auth.roles (
    id          SERIAL PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    description TEXT,
    -- built-in roles cannot be deleted from the admin UI
    is_system   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE auth.permissions (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    resource    TEXT NOT NULL,
    action      TEXT NOT NULL,
    description TEXT
);

CREATE TABLE auth.role_permissions (
    role_id       INTEGER NOT NULL REFERENCES auth.roles(id) ON DELETE CASCADE,
    permission_id INTEGER NOT NULL REFERENCES auth.permissions(id) ON DELETE CASCADE,
    PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE auth.user_roles (
    user_id     UUID    NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role_id     INTEGER NOT NULL REFERENCES auth.roles(id) ON DELETE CASCADE,
    granted_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by  UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    PRIMARY KEY (user_id, role_id)
);

-- Refresh tokens are stored hashed so a database leak cannot be replayed.
CREATE TABLE auth.refresh_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    token_hash  TEXT UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    revoked_at  TIMESTAMPTZ,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX refresh_tokens_user_idx ON auth.refresh_tokens (user_id) WHERE revoked_at IS NULL;

CREATE TABLE auth.audit_log (
    id          BIGSERIAL PRIMARY KEY,
    user_id     UUID REFERENCES auth.users(id) ON DELETE SET NULL,
    action      TEXT NOT NULL,
    resource    TEXT,
    detail      JSONB,
    ip_address  INET,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX audit_log_user_time_idx ON auth.audit_log (user_id, created_at DESC);

-- Flattened permission lookup -- one indexed read per request instead of a
-- three-table join in the auth dependency.
CREATE OR REPLACE VIEW auth.user_permissions AS
SELECT DISTINCT
    ur.user_id,
    p.code,
    p.resource,
    p.action
FROM auth.user_roles ur
JOIN auth.role_permissions rp ON rp.role_id = ur.role_id
JOIN auth.permissions      p  ON p.id = rp.permission_id;
