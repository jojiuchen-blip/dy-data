# Tencent Lighthouse CI/CD

This is the optional deployment path for a Tencent Cloud Lighthouse or
compatible self-managed Linux server. Whether it is the active production
target is controlled by repository variables and environment protection.

## Workflow

The workflow is `.github/workflows/tencent-lighthouse-deploy.yml`.

- `workflow_dispatch`: verify the repository, then deploy to Tencent Lighthouse.
- `push` to `main`: runs only when repository variable `TENCENT_DEPLOY_ON_PUSH`
  is set to `true`.
- The verification job normalizes GitHub Runner's Ubuntu package mirror and
  limits Playwright dependency installation to ten minutes.

The default is intentionally manual so a normal push does not accidentally
change a self-managed production server.

## GitHub variables

- `TENCENT_HOST`: server hostname or IP supplied through the repository variable, for example `<SERVER_HOST>`.
- `TENCENT_SSH_PORT`: SSH port, usually `22`.
- `TENCENT_SSH_USER`: SSH user, usually `ubuntu`.
- `DY_WEB_BASE_URL`: public HTTPS dashboard base URL used by CLI browser authorization.
- `TENCENT_START_WORKER`: must be `true` for this production workflow. The
  workflow fails before SSH when it is absent or false, because persisted
  finance detection jobs require a running worker for restart recovery.
- `TENCENT_DEPLOY_ON_PUSH`: set to `true` only after automatic deploys on every
  `main` push are desired.

## GitHub secrets

- `TENCENT_SSH_KEY`: private SSH key allowed to log in to the server.
- `TENCENT_KNOWN_HOSTS`: pinned server SSH host key entries.

Do not store application runtime secrets in GitHub. They remain in
`/opt/dy-dashboard/env/production.env` on the server.

## Server layout

- Repo: `/opt/dy-dashboard/repo`
- Runtime env: `/opt/dy-dashboard/env/production.env`
- Backups: `/opt/dy-dashboard/backups`
- Logs: `/opt/dy-dashboard/logs`

## Deployment behavior

The server script is `deploy/tencent/deploy.sh`.

It performs:

1. Save any server-side dirty diff to `/opt/dy-dashboard/logs`.
2. Require `TENCENT_START_WORKER=true` in the server script itself; a direct or
   non-GitHub invocation fails before build, backup, or migration when it is
   absent or false.
3. Fetch and reset to the target Git commit.
4. Back up the production environment file and validate Docker Compose
   configuration.
5. Build `api`, `web`, `browser`, and `worker` images.
6. Start PostgreSQL.
7. Read the production `alembic_version` and verify that the target API image
   can resolve it. If the revision is missing, print matching migration source
   from the currently running API container between `migration-source-begin`
   and `migration-source-end`, then stop before `alembic upgrade`.
8. Back up PostgreSQL, then run Alembic migrations and reject unresolved
   statement-snapshot migration exceptions.
9. Start `api`, `web`, `browser`, and `proxy`.
10. Start the required `worker`, verify the scheduler is PID 1, and verify that
    the queue handler imports and can query the production database. Failures
    include worker logs in the deployment diagnostic output.
11. Smoke test `/`, `/api/v1/auth/me`, and CLI device authorization startup.

The lineage preflight is read-only. It never changes `alembic_version` and does
not use `alembic stamp`; a missing production revision always blocks deployment
until its migration source and parent chain are restored in the repository.

Set `TENCENT_START_WORKER=true` only when this deployment is intentionally the
active collector and finance-detection worker. If another environment owns
collection, do not run this production workflow: it now fails closed rather
than deploying an API that cannot recover persisted detection jobs.
