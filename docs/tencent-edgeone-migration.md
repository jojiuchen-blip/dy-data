# Tencent Cloud EdgeOne Migration Runbook

This runbook describes the planned migration from Railway to Tencent Cloud CVM with EdgeOne in front. It is intentionally operational: use it as the checklist for provisioning, first deployment, validation, cutover, and later CI/CD automation.

## Target Architecture

```text
Users
  -> EdgeOne
  -> Tencent Cloud CVM origin, ports 80/443 only
  -> host Nginx or Caddy
  -> Docker Compose proxy on 127.0.0.1:8080
  -> web, api, worker, Postgres, browser/noVNC
```

The CVM is the origin and owns the runtime. EdgeOne is only the acceleration and security layer. Do not use EdgeOne as a permanent reverse proxy to Railway if the goal is to remove the Railway access dependency.

## Required User-Side Prerequisites

These items must be completed in Tencent Cloud before technical migration can finish:

- Tencent Cloud account real-name verification.
- Domain real-name verification.
- ICP filing for the production domain if EdgeOne acceleration region uses Mainland China or Global.
- CVM instance purchased, preferably Ubuntu 22.04 LTS or 24.04 LTS.
- Security group opened only for:
  - `22/tcp` from trusted admin IPs.
  - `80/tcp` and `443/tcp` for public HTTP(S), later restricted to EdgeOne origin-pull IP ranges if feasible.
- DNS control for the production domain and at least one test subdomain.

Recommended initial CVM size:

- Minimum: 2 vCPU, 4 GB RAM, 80 GB SSD.
- Preferred for this project: 4 vCPU, 8 GB RAM, 100 GB SSD.
- Reason: the browser/noVNC container and Chromium profile are memory-heavy, and Postgres is local in the first migration phase.

## Domain Plan

Use separate hostnames to avoid EdgeOne origin loops:

- `origin.example.com`: direct CVM origin. Used by EdgeOne for origin-pull and by administrators for emergency debugging. Keep it unadvertised.
- `app.example.com`: public dashboard domain served through EdgeOne.
- Optional `edge-test.example.com`: EdgeOne staging domain before production cutover.

DNS sequence:

1. Lower current production TTL to 60-300 seconds before cutover.
2. Point `origin.example.com` to CVM.
3. Add `edge-test.example.com` to EdgeOne and set its origin to `origin.example.com`.
4. Validate EdgeOne behavior on `edge-test.example.com`.
5. Move production domain only after validation passes.

## EdgeOne Settings

### Acceleration Region

- Use Mainland China or Global only after ICP filing is complete.
- If the domain is not filed, EdgeOne must use Global excluding Mainland China, which does not solve the Mainland China access problem.

### Origin

- Origin type: domain origin, preferably `origin.example.com`.
- Origin protocol: HTTPS after the origin certificate is ready.
- Origin Host/SNI/certificate validation must be configured consistently. If strict origin certificate validation is enabled, the origin certificate name must match the origin-pull SNI/Host configuration.

### Cache Rules

Cache static assets only:

- `/assets/*`
- `*.js`
- `*.css`
- `*.svg`
- `*.png`
- `*.jpg`
- `*.jpeg`
- `*.webp`
- `*.ico`

Do not cache dynamic or authenticated routes:

- `/api/*`
- `/auth/*`
- `/admin/*`
- `/browser/*`
- `/websockify`
- Any request with `Cookie` or `Authorization`.

Suggested initial policy:

- Static hashed assets: 7-30 days.
- HTML: no cache or very short TTL during launch.
- API/browser/admin: bypass cache.

### WebSocket And Long Connections

Enable and test WebSocket support for:

- `/browser/*`
- `/websockify`

Set long read/send timeouts for noVNC. Browser access is an administrative path and should be tested separately from the normal dashboard.

### WAF And Bot Protection

Launch in observe/log mode first. Do not enable hard blocking on day one.

After 24-48 hours of logs:

- Allow known admin paths and legitimate API traffic.
- Add rate limits for obvious abuse.
- Enable blocking only after confirming no login, export, browser, or API false positives.

## CVM Deployment Layout

Recommended directories:

```text
/opt/dy-dashboard/
  repo/
  env/
  backups/
  logs/
```

Secret files must stay outside git:

```text
/opt/dy-dashboard/env/production.env
```

Start from `deploy/.env.example` and fill real values on the server. Do not commit production `.env` files.

For first deployment, keep the existing Compose proxy bound to localhost:

```env
HTTP_BIND=127.0.0.1
HTTP_PORT=8080
```

Then terminate public HTTP(S) at host Nginx or Caddy and proxy to `127.0.0.1:8080`.

## Runtime Variables To Collect

Required for API:

- `DATABASE_URL`
- `DY_SUPER_ADMIN_USERNAME`
- `DY_SUPER_ADMIN_PASSWORD_HASH`
- `DY_SESSION_SECRET`

Required for worker:

- `DATABASE_URL`
- `DOUYIN_APP_ID`
- `DOUYIN_APP_SECRET`
- `DOUYIN_ACCOUNT_ID`
- `WORKER_MODE`
- `DOUYIN_COLLECT_START`
- `DOUYIN_COLLECT_OVERLAP_DAYS`
- `DOUYIN_VERIFY_CHUNK_DAYS`

Required for browser/noVNC:

- `BROWSER_VNC_PASSWORD`
- `CHROMIUM_START_URL`
- `BROWSER_CDP_URL`
- `BROWSER_EXPORT_DOWNLOAD_DIR`
- `BROWSER_EXPORT_ARTIFACT_DIR`
- `BACKEND_AWEME_EXPORT_URL`

## Data Migration Plan

### Initial Dry Run

1. Keep Railway production running.
2. Create a Postgres dump from Railway production.
3. Restore the dump to CVM Postgres.
4. Start CVM services on the test origin.
5. Validate dashboard data and API responses.

### Final Cutover

1. Announce maintenance window.
2. Pause Railway worker or ensure no scheduled writes during final dump.
3. Create final Postgres dump.
4. Restore final dump to CVM.
5. Start CVM `api`, `web`, `worker`, `browser`, and `proxy`.
6. Validate direct origin.
7. Validate EdgeOne staging domain.
8. Switch production DNS.
9. Keep Railway online but read-only/idle for rollback.

Browser profile migration is not guaranteed. If Railway browser volume cannot be exported cleanly, plan for a fresh Douyin backend login through the protected `/browser/` path after cutover.

## Validation Checklist

Direct origin:

- `GET /` returns `200`.
- `GET /api/v1/auth/me` returns `401` before login.
- Admin login works.
- Dashboard pages load data.
- CSV/export paths work if enabled.
- Worker writes a new `job_runs` row.
- `/browser/` opens only for authorized admin.
- `/websockify` works through EdgeOne when browser access is needed.

EdgeOne:

- Public domain TLS certificate is valid.
- Static assets show cache hits after warm-up.
- `/api/*` is never cached.
- Auth cookies are not cached or shared.
- WebSocket/noVNC path works.
- WAF logs do not show false positives for normal admin operations.

## Rollback Plan

Keep Railway unchanged until CVM has been stable for at least 48 hours.

Rollback options:

1. DNS rollback: point production domain back to Railway or previous endpoint.
2. EdgeOne rollback: disable production domain acceleration or switch origin back.
3. Runtime rollback: stop CVM worker first to prevent split-brain writes.

If a rollback occurs after CVM has accepted writes, preserve the CVM database dump before changing traffic back. Do not overwrite Railway data without a deliberate reconciliation step.

## CI/CD Phasing

### Phase 1: Manual Verified Deployment

Use manual SSH deployment first:

```bash
git pull --ff-only
docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml up -d --build
docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml ps
```

This avoids coupling first migration risk to CI/CD setup.

### Phase 2: CI/CD To CVM

After the manual deployment is stable:

1. Keep GitHub Actions `verify` job.
2. Add a Tencent deployment job or configure Tencent CODING/CloudBase pipeline.
3. Build images in CI.
4. Push images to Tencent Container Registry or build on the CVM.
5. SSH to CVM and run:

```bash
docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml pull
docker compose --env-file /opt/dy-dashboard/env/production.env -f deploy/compose.yaml up -d
```

Do not put production secrets in repository files or CI logs.

## Immediate Next Step

Before any server work, collect these values:

- Tencent Cloud region and CVM public IP.
- Domain to use for `origin`.
- Domain to use for EdgeOne staging.
- Domain to use for production.
- ICP filing status.
- SSH username and authentication method.
- Whether Postgres remains local on CVM for phase 1 or moves to TencentDB for PostgreSQL.

## Reference Documents

- Tencent Cloud EdgeOne quick access guide: https://cloud.tencent.com/document/product/1552/87601
- Tencent Cloud EdgeOne ICP filing FAQ: https://cloud.tencent.com/document/product/1552/110835
- Tencent Cloud EdgeOne WebSocket: https://www.tencentcloud.com/document/product/1145/46971
- Tencent Cloud EdgeOne origin protection: https://www.tencentcloud.com/document/product/1145/48535
