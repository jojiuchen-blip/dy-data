\set ON_ERROR_STOP on

-- Run as a PostgreSQL role administrator after the control-plane migration.
-- Credentials are intentionally configured separately with psql's \password.
BEGIN;

DO $bootstrap$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dy_ops_agent') THEN
        CREATE ROLE dy_ops_agent;
    END IF;
END
$bootstrap$;

ALTER ROLE dy_ops_agent
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

-- Remove inherited escape hatches if this script is rerun for an existing role.
SELECT format('REVOKE %I FROM dy_ops_agent', parent.rolname)
FROM pg_auth_members AS membership
JOIN pg_roles AS member ON member.oid = membership.member
JOIN pg_roles AS parent ON parent.oid = membership.roleid
WHERE member.rolname = 'dy_ops_agent'
\gexec

REVOKE ALL PRIVILEGES ON DATABASE :"DBNAME" FROM dy_ops_agent;
GRANT CONNECT ON DATABASE :"DBNAME" TO dy_ops_agent;

SELECT format('REVOKE ALL PRIVILEGES ON SCHEMA %I FROM dy_ops_agent', namespace.nspname)
FROM pg_namespace AS namespace
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname NOT LIKE 'pg\_%' ESCAPE '\'
\gexec

-- Effective privilege checks include grants inherited from default/public ACLs
-- and implicit owner privileges. The administrator must narrow those ACLs first.
DO $preflight$
BEGIN
    IF has_database_privilege('dy_ops_agent', current_database(), 'CREATE')
       OR has_database_privilege('dy_ops_agent', current_database(), 'TEMP') THEN
        RAISE EXCEPTION
            'dy_ops_agent must not have effective database CREATE or TEMP privileges';
    END IF;

    IF has_schema_privilege('dy_ops_agent', 'public', 'CREATE') THEN
        RAISE EXCEPTION
            'dy_ops_agent must not have effective CREATE on schema public';
    END IF;
END
$preflight$;

SELECT format(
    'REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA %I FROM dy_ops_agent',
    namespace.nspname
)
FROM pg_namespace AS namespace
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname NOT LIKE 'pg\_%' ESCAPE '\'
\gexec

SELECT format(
    'REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA %I FROM dy_ops_agent',
    namespace.nspname
)
FROM pg_namespace AS namespace
WHERE namespace.nspname <> 'information_schema'
  AND namespace.nspname NOT LIKE 'pg\_%' ESCAPE '\'
\gexec

GRANT USAGE ON SCHEMA public TO dy_ops_agent;
GRANT SELECT, UPDATE ON TABLE public.ops_commands TO dy_ops_agent;
GRANT SELECT, INSERT, UPDATE ON TABLE public.component_heartbeats TO dy_ops_agent;
GRANT SELECT ON TABLE public.job_runs TO dy_ops_agent;

DO $verify$
DECLARE
    actual_privileges text[];
    expected_privileges constant text[] := ARRAY[
        'public.component_heartbeats:INSERT',
        'public.component_heartbeats:SELECT',
        'public.component_heartbeats:UPDATE',
        'public.job_runs:SELECT',
        'public.ops_commands:SELECT',
        'public.ops_commands:UPDATE'
    ];
BEGIN
    IF has_database_privilege('dy_ops_agent', current_database(), 'CREATE')
       OR has_database_privilege('dy_ops_agent', current_database(), 'TEMP') THEN
        RAISE EXCEPTION 'dy_ops_agent has an effective database CREATE or TEMP privilege';
    END IF;

    IF has_schema_privilege('dy_ops_agent', 'public', 'CREATE') THEN
        RAISE EXCEPTION 'dy_ops_agent has effective CREATE on schema public';
    END IF;

    SELECT array_agg(
        format('%s.%s:%s', table_schema, table_name, privilege_type)
        ORDER BY table_schema, table_name, privilege_type
    )
    INTO actual_privileges
    FROM information_schema.role_table_grants
    WHERE grantee = 'dy_ops_agent'
      AND table_schema <> 'information_schema'
      AND table_schema NOT LIKE 'pg\_%' ESCAPE '\';

    IF actual_privileges IS DISTINCT FROM expected_privileges THEN
        RAISE EXCEPTION 'dy_ops_agent direct table privileges are not the fixed allowlist';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE relation.relkind IN ('r', 'p', 'v', 'm', 'f')
          AND namespace.nspname <> 'information_schema'
          AND namespace.nspname NOT LIKE 'pg\_%' ESCAPE '\'
          AND (namespace.nspname, relation.relname) NOT IN (
              ('public', 'ops_commands'),
              ('public', 'component_heartbeats'),
              ('public', 'job_runs')
          )
          AND (
              has_table_privilege('dy_ops_agent', relation.oid, 'SELECT')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'INSERT')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'UPDATE')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'DELETE')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'TRUNCATE')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'REFERENCES')
              OR has_table_privilege('dy_ops_agent', relation.oid, 'TRIGGER')
          )
    ) THEN
        RAISE EXCEPTION 'dy_ops_agent has effective privileges on a non-allowlisted table';
    END IF;

    IF has_table_privilege('dy_ops_agent', 'public.ops_commands', 'INSERT')
       OR has_table_privilege('dy_ops_agent', 'public.ops_commands', 'DELETE')
       OR has_table_privilege('dy_ops_agent', 'public.ops_commands', 'TRUNCATE')
       OR has_table_privilege('dy_ops_agent', 'public.ops_commands', 'REFERENCES')
       OR has_table_privilege('dy_ops_agent', 'public.ops_commands', 'TRIGGER')
       OR has_table_privilege('dy_ops_agent', 'public.component_heartbeats', 'DELETE')
       OR has_table_privilege('dy_ops_agent', 'public.component_heartbeats', 'TRUNCATE')
       OR has_table_privilege('dy_ops_agent', 'public.component_heartbeats', 'REFERENCES')
       OR has_table_privilege('dy_ops_agent', 'public.component_heartbeats', 'TRIGGER')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'INSERT')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'UPDATE')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'DELETE')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'TRUNCATE')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'REFERENCES')
       OR has_table_privilege('dy_ops_agent', 'public.job_runs', 'TRIGGER') THEN
        RAISE EXCEPTION 'dy_ops_agent has an extra effective allowlisted-table privilege';
    END IF;
END
$verify$;

COMMIT;
