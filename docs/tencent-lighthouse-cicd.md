# Tencent Lighthouse CI/CD

This is the optional deployment path for a Tencent Cloud Lighthouse or
compatible self-managed Linux server. Whether it is the active production
target is controlled by repository variables and environment protection.

## Workflow

The workflow is `.github/workflows/tencent-lighthouse-deploy.yml`.

- `workflow_dispatch`: verify the repository, then deploy to Tencent Lighthouse.
- `push` to `main`: runs only when repository variable `TENCENT_DEPLOY_ON_PUSH`
  is set to `true`.

The default is intentionally manual so a normal push does not accidentally
change a self-managed production server.

## GitHub variables

- `TENCENT_HOST`: server hostname or IP supplied through the repository variable, for example `<SERVER_HOST>`.
- `TENCENT_SSH_PORT`: SSH port, usually `22`.
- `TENCENT_SSH_USER`: SSH user, usually `ubuntu`.
- `DY_WEB_BASE_URL`: public HTTPS dashboard base URL used by CLI browser authorization.
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
2. Fetch and reset to the target Git commit.
3. Validate Docker Compose configuration.
4. Build `api`, `web`, and `browser` images.
5. Start PostgreSQL.
6. Run Alembic migrations.
7. Start `api`, `web`, `browser`, and `proxy`.
8. Keep `worker` stopped unless `TENCENT_START_WORKER=true` is present in the
   workflow/server environment.
9. Smoke test `/`, `/api/v1/auth/me`, and CLI device authorization startup.

Set `TENCENT_START_WORKER=true` only when this deployment is intentionally the
active collector. Leave it unset when another environment owns collection, so
two workers cannot ingest or refresh the same data independently.
