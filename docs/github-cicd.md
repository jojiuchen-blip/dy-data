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
- `DY_ADMIN_USERNAME`
- `DY_ADMIN_PASSWORD_HASH`
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

Set `WORKER_SKIP_BROWSER_EXPORT=true` until the browser-backed backend export service is available in Railway. Open API collection still runs with this flag enabled.

The existing production web URL is:

```text
https://web-production-2e113.up.railway.app
```
