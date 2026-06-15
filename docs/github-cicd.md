# GitHub CI/CD

This repository deploys the Railway production services from GitHub Actions.

## Workflow

The workflow is `.github/workflows/ci-cd.yml`.

- Pull requests to `main`: run backend tests, frontend build, and API/Web Docker builds.
- Pushes to `main`: run the same verification, then deploy Railway `api` and `web`.
- Railway `Postgres` is managed as a Railway database service and is not deployed by GitHub.

## GitHub variables

Repository variables used by the workflow:

- `RAILWAY_PROJECT_ID`
- `RAILWAY_ENVIRONMENT`
- `RAILWAY_API_SERVICE_ID`
- `RAILWAY_WEB_SERVICE_ID`
- `RAILWAY_WEB_URL`

## GitHub secrets

Repository secrets used by the workflow:

- `RAILWAY_TOKEN`

Create this token in Railway as a project or account token with deploy access to project `62f9e7d8-cecf-40ea-87fa-1002c6465b13`, then add it in GitHub repository settings.

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

The existing production web URL is:

```text
https://web-production-2e113.up.railway.app
```
