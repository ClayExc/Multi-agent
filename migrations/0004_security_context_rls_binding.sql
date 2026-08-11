BEGIN;

DO $predecessor$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0003_api_task_initialization'
    ) THEN
        RAISE EXCEPTION
            '0004_security_context_rls_binding requires 0003_api_task_initialization'
            USING ERRCODE = '55000';
    END IF;
END
$predecessor$;

INSERT INTO flowpilot.schema_migrations (migration_id, content_digest)
VALUES (
    '0004_security_context_rls_binding',
    'sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2'
)
ON CONFLICT (migration_id) DO UPDATE
SET content_digest = EXCLUDED.content_digest
WHERE flowpilot.schema_migrations.content_digest = EXCLUDED.content_digest;

DO $migration_digest$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM flowpilot.schema_migrations
        WHERE migration_id = '0004_security_context_rls_binding'
          AND content_digest =
            'sha256:1cad07bdc78c9cd0dfd8591c03fdb29c5e3039c15f88f7b624211abf2b5b42a2'
    ) THEN
        RAISE EXCEPTION 'migration id is bound to another content digest'
            USING ERRCODE = '23514';
    END IF;
END
$migration_digest$;

ALTER ROLE flowpilot_api NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS;
ALTER ROLE flowpilot_worker NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS;
ALTER ROLE flowpilot_gateway NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS;
ALTER ROLE flowpilot_publisher NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOINHERIT NOBYPASSRLS;

DO $safe_roles$
DECLARE
    unsafe_count integer;
BEGIN
    SELECT count(*)
    INTO unsafe_count
    FROM unnest(ARRAY[
        'flowpilot_api',
        'flowpilot_worker',
        'flowpilot_gateway',
        'flowpilot_publisher'
    ]) AS required(role_name)
    LEFT JOIN pg_roles ON pg_roles.rolname = required.role_name
    WHERE pg_roles.rolname IS NULL
       OR pg_roles.rolsuper
       OR pg_roles.rolbypassrls
       OR pg_roles.rolcanlogin
       OR pg_roles.rolinherit;

    IF unsafe_count <> 0 THEN
        RAISE EXCEPTION 'tenant runtime database roles are unsafe'
            USING ERRCODE = '42501';
    END IF;
END
$safe_roles$;

CREATE OR REPLACE FUNCTION flowpilot.session_tenant_id()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('flowpilot.tenant_id', true), '')
$function$;

CREATE OR REPLACE FUNCTION flowpilot.session_context_ref()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('flowpilot.context_ref', true), '')
$function$;

CREATE OR REPLACE FUNCTION flowpilot.session_context_hash()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('flowpilot.context_hash', true), '')
$function$;

CREATE OR REPLACE FUNCTION flowpilot.session_subject_id()
RETURNS text
LANGUAGE sql
STABLE
PARALLEL SAFE
AS $function$
    SELECT NULLIF(current_setting('flowpilot.subject_id', true), '')
$function$;

CREATE TABLE IF NOT EXISTS flowpilot.security_contexts (
    context_ref text PRIMARY KEY,
    context_id text NOT NULL UNIQUE,
    tenant_id text NOT NULL,
    context_hash text NOT NULL,
    subject_id text NOT NULL,
    subject_type text NOT NULL,
    purpose text NOT NULL,
    issued_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    context_snapshot jsonb NOT NULL,
    roles jsonb NOT NULL,
    scopes jsonb NOT NULL,
    issuer text NOT NULL,
    authorized_party text NOT NULL,
    identity_token_hash text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    revoked_at timestamptz,
    revocation_reason text,
    CHECK (expires_at > issued_at),
    CHECK (jsonb_typeof(roles) = 'array'),
    CHECK (jsonb_typeof(scopes) = 'array'),
    CHECK (context_snapshot ->> 'context_id' = context_id),
    CHECK (context_snapshot ->> 'context_ref' = context_ref),
    CHECK (context_snapshot ->> 'context_hash' = context_hash),
    CHECK (context_snapshot ->> 'tenant_id' = tenant_id),
    CHECK (context_snapshot ->> 'subject_id' = subject_id),
    CHECK (context_snapshot ->> 'subject_type' = subject_type),
    CHECK (context_snapshot ->> 'purpose' = purpose),
    CHECK ((context_snapshot ->> 'issued_at')::timestamptz = issued_at),
    CHECK ((context_snapshot ->> 'expires_at')::timestamptz = expires_at),
    CHECK (
        (active AND revoked_at IS NULL AND revocation_reason IS NULL)
        OR
        (NOT active AND revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)
    ),
    CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
);

CREATE INDEX IF NOT EXISTS security_contexts_active_lookup_idx
    ON flowpilot.security_contexts (context_ref, tenant_id, subject_id)
    WHERE active;

ALTER TABLE flowpilot.security_contexts ENABLE ROW LEVEL SECURITY;
ALTER TABLE flowpilot.security_contexts FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS security_context_binding ON flowpilot.security_contexts;
CREATE POLICY security_context_binding ON flowpilot.security_contexts
USING (context_ref = flowpilot.session_context_ref())
WITH CHECK (
    context_ref = flowpilot.session_context_ref()
    AND tenant_id = flowpilot.session_tenant_id()
    AND context_hash = flowpilot.session_context_hash()
    AND subject_id = flowpilot.session_subject_id()
);

CREATE OR REPLACE FUNCTION flowpilot.prevent_security_context_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $function$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'security contexts cannot be deleted'
            USING ERRCODE = '55000';
    END IF;
    IF NOT OLD.active
       OR NEW.active
       OR NEW.revoked_at IS NULL
       OR NEW.revocation_reason IS NULL
       OR OLD.context_ref IS DISTINCT FROM NEW.context_ref
       OR OLD.context_id IS DISTINCT FROM NEW.context_id
       OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR OLD.context_hash IS DISTINCT FROM NEW.context_hash
       OR OLD.subject_id IS DISTINCT FROM NEW.subject_id
       OR OLD.subject_type IS DISTINCT FROM NEW.subject_type
       OR OLD.purpose IS DISTINCT FROM NEW.purpose
       OR OLD.issued_at IS DISTINCT FROM NEW.issued_at
       OR OLD.expires_at IS DISTINCT FROM NEW.expires_at
       OR OLD.context_snapshot IS DISTINCT FROM NEW.context_snapshot
       OR OLD.roles IS DISTINCT FROM NEW.roles
       OR OLD.scopes IS DISTINCT FROM NEW.scopes
       OR OLD.issuer IS DISTINCT FROM NEW.issuer
       OR OLD.authorized_party IS DISTINCT FROM NEW.authorized_party
       OR OLD.identity_token_hash IS DISTINCT FROM NEW.identity_token_hash
    THEN
        RAISE EXCEPTION 'security context snapshots are immutable'
            USING ERRCODE = '55000';
    END IF;
    RETURN NEW;
END
$function$;

DROP TRIGGER IF EXISTS security_context_immutable_update
    ON flowpilot.security_contexts;
CREATE TRIGGER security_context_immutable_update
BEFORE UPDATE ON flowpilot.security_contexts
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_security_context_mutation();

DROP TRIGGER IF EXISTS security_context_no_delete
    ON flowpilot.security_contexts;
CREATE TRIGGER security_context_no_delete
BEFORE DELETE ON flowpilot.security_contexts
FOR EACH ROW EXECUTE FUNCTION flowpilot.prevent_security_context_mutation();

CREATE OR REPLACE FUNCTION flowpilot.validate_security_context()
RETURNS TABLE (
    tenant_id text,
    context_ref text,
    context_hash text,
    subject_id text
)
LANGUAGE sql
STABLE
AS $function$
    SELECT sc.tenant_id, sc.context_ref, sc.context_hash, sc.subject_id
    FROM flowpilot.security_contexts AS sc
    WHERE sc.context_ref = flowpilot.session_context_ref()
      AND sc.tenant_id = flowpilot.session_tenant_id()
      AND sc.context_hash = flowpilot.session_context_hash()
      AND sc.subject_id = flowpilot.session_subject_id()
      AND sc.active
      AND sc.revoked_at IS NULL
      AND sc.issued_at <= transaction_timestamp()
      AND sc.expires_at > transaction_timestamp()
$function$;

REVOKE ALL ON flowpilot.security_contexts FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.session_tenant_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.session_context_ref() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.session_context_hash() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.session_subject_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.validate_security_context() FROM PUBLIC;
REVOKE ALL ON FUNCTION flowpilot.prevent_security_context_mutation() FROM PUBLIC;

GRANT SELECT, INSERT, UPDATE ON flowpilot.security_contexts TO flowpilot_api;
GRANT SELECT ON flowpilot.security_contexts
    TO flowpilot_worker, flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.session_tenant_id()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.session_context_ref()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.session_context_hash()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.session_subject_id()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway;
GRANT EXECUTE ON FUNCTION flowpilot.validate_security_context()
    TO flowpilot_api, flowpilot_worker, flowpilot_gateway;

COMMIT;
