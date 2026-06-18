# GitHub CI/CD

This repository deploys the Railway production services from GitHub Actions.

## Workflow

The workflow is `.github/workflows/ci-cd.yml`.

- Pull requests to `main`: run backend tests, frontend build, and API/Worker/Web Docker builds.
- Pushes to `main`: run the same verification, then deploy Railway `api`, `worker`, and `web`.
- Railway `Postgres` is managed as a Railway database service and is not deployed by GitHub.

## GitHub variables

Repository variables used by the workflow:

- `RAILWAY_PROJECT_ID`
- `RAILWAY_ENVIRONMENT`
- `RAILWAY_API_SERVICE_ID`
- `RAILWAY_WORKER_SERVICE_ID`
- `RAILWAY_BROWSER_SERVICE_ID` (optional)
- `RAILWAY_WEB_SERVICE_ID`
- `RAILWAY_WEB_URL`

## GitHub secrets

Repository secrets used by the workflow:

- `RAILWAY_TOKEN`

Create this token in Railway as a project token with deploy access to project `62f9e7d8-cecf-40ea-87fa-1002c6465b13`, then add it in GitHub repository settings. The workflow passes this GitHub secret to Railway CLI as `RAILWAY_TOKEN`.

If `RAILWAY_TOKEN` is not configured, pushes to `main` still run verification but skip the Railway deploy job with a warning.

## Railway runtime variables

Runtime secrets stay in Railway service variables, not in GitHub Actions logs or repository files.

Required `api` variables:

- `DATABASE_URL`
- `DY_SUPER_ADMIN_USERNAME`
- `DY_SUPER_ADMIN_PASSWORD_HASH`
- `DY_SESSION_SECRET`

Required `web` variables:

- `API_UPSTREAM`

Required `worker` variables:

- `DATABASE_URL`
- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`
- `RAILWAY_DOCKERFILE_PATH=apps/worker/Dockerfile`
- `WORKER_MODE=collect_and_settle`
- `WORKER_INTERVAL_SECONDS=86400`
- `DOUYIN_COLLECT_OVERLAP_DAYS=7`
- `DOUYIN_VERIFY_CHUNK_DAYS=7`

Set `WORKER_SKIP_BROWSER_EXPORT=true` on historical backfill workers. Open API collection still runs with this flag enabled, and browser exports should not run once per backfill chunk.

Optional `browser` variables:

- `DATABASE_URL`
- `RAILWAY_DOCKERFILE_PATH=deploy/browser/Dockerfile`
- `BROWSER_EXPORT_SCHEDULER_ENABLED=true`
- `BROWSER_EXPORT_INTERVAL_SECONDS=86400`
- `BROWSER_EXPORT_START_DELAY_SECONDS=60`
- `BROWSER_EXPORT_DOWNLOAD_DIR=/home/browser/Downloads/job-runs`
- `BROWSER_EXPORT_ARTIFACT_DIR=/home/browser/Downloads/exports`
- `BACKEND_AWEME_EXPORT_URL`

Use the `browser` service for the low-frequency backend aweme/sub-organization export. The browser container runs Chromium/noVNC and the export scheduler in the same container so CDP stays on `127.0.0.1` and is not exposed as a separate Railway service port. Configure `RAILWAY_BROWSER_SERVICE_ID` only after the Railway browser service exists; otherwise the workflow skips this optional deploy.

For one-time historical backfills, temporarily set `WORKER_MODE=backfill`, `WORKER_RUN_ONCE=true`, `DOUYIN_COLLECT_START`, `DOUYIN_COLLECT_END`, and `WORKER_BACKFILL_CHUNK_DAYS`. Backfill mode commits each chunk independently, then the service should be restored to `WORKER_MODE=collect_and_settle` for daily incremental collection.

The existing production web URL is:

```text
https://web-production-2e113.up.railway.app
```
