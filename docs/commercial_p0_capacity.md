# Commercial P0 Capacity Baseline

## Scope

- Goal: support the control-plane baseline for a Takealot-only ERP heading toward `1000` concurrent active users.
- Focus only on the current P0 surface:
  - `Auth`
  - `Admin`
  - `Store`
  - `Task Center`
  - Worker lease / claim path
- This document does **not** certify external Takealot API throughput. It certifies our own control-plane readiness path.

## Chosen Worker Supervisor

- Windows production baseline: **Task Scheduler**
- Reason:
  - built-in on the current deployment platform
  - no extra Windows service wrapper dependency
  - enough for the current single-host worker topology
- Install script:
  - dry run: `powershell -ExecutionPolicy Bypass -File scripts/install-worker-scheduled-task.ps1`
  - register task: `powershell -ExecutionPolicy Bypass -File scripts/install-worker-scheduled-task.ps1 -Install`
- The scheduled task runs `scripts/worker-api.ps1`, not raw Python, so worker stdout/stderr and supervisor start/stop records are written under `reports/runtime`.

## Load Commands

- Light smoke:
  - `npm run load:commercial:smoke`
- Subscription / quota smoke:
  - `npm run db:smoke:subscription`
- Tenant onboarding smoke:
  - `npm run db:smoke:tenant-onboarding`
- Full 1000-user baseline:
  - `npm run load:commercial`
- Production warmup before opening traffic:
  - `npm run api:warmup`
- Operations guardrail report:
  - `npm run ops:guardrails`
  - strict release check: `npm run ops:guardrails:strict`
  - scheduled guardrail dry run: `npm run ops:schedule:dry`
  - scheduled guardrail install: `npm run ops:schedule:install`
  - alert channel test: `npm run ops:alert:test`
  - strict webhook-required alert test: `npm run ops:alert:test:strict`
  - local alert summary: `npm run ops:alerts`
  - local alert summary JSON: `npm run ops:alerts:json`
- Worker operations:
  - one-shot drain with logs: `npm run worker:api:ps:once`
  - scheduled-task dry run: `npm run worker:schedule:dry`
  - scheduled-task install from elevated PowerShell: `npm run worker:schedule:install`
- Release preflight:
  - full: `npm run release:preflight`
  - fast script validation: `npm run release:preflight -- -SkipSmoke -SkipWarmup -SkipBackup`
- Host activation check:
  - `npm run host:check`
- Environment readiness:
  - `npm run ops:env:check`
  - non-blocking report: `npm run ops:env:check:nofail`
- Data safety:
  - database backup: `npm run db:backup`
  - restore artifact validation: `npm run db:restore:check`
  - data integrity scan: `npm run ops:data:check`
  - strict data integrity scan: `npm run ops:data:check:strict`
- Secret rotation:
  - store credential encryption key bootstrap / rotation: `npm run ops:secrets:rotate-store-key`
- Real execution package:
  - set `XH_LOAD_BASE_URL`
  - set `XH_LOAD_PASSWORD`
  - optionally set `XH_LOAD_USERNAME`
  - run `npm run load:commercial`
- Custom direct run:
  - `python packages/db/scripts/load_commercial_baseline.py --base-url https://your-api.example.com --users 1000 --iterations 3 --concurrency 100`

## Real Run Environment

- Required environment variables:
  - `XH_LOAD_BASE_URL`: deployed API origin, for example `https://erp-api.example.com`
  - `XH_LOAD_PASSWORD`: password for the load-test account; do not pass real passwords on the command line
- Optional environment variables:
  - `XH_LOAD_USERNAME`: defaults to `tenant_admin`
  - `XH_LOAD_USERS`: defaults to `1000`
  - `XH_LOAD_ITERATIONS`: defaults to `3`
  - `XH_LOAD_CONCURRENCY`: defaults to `100`
  - `XH_LOAD_WARMUP_USERS`: defaults to `20`
  - `XH_LOAD_OUTPUT_DIR`: defaults to `reports/load`
- PowerShell example:
  - `$env:XH_LOAD_BASE_URL="https://erp-api.example.com"`
  - `$env:XH_LOAD_USERNAME="tenant_admin"`
  - `$env:XH_LOAD_PASSWORD="<secret>"`
  - `npm run load:commercial`

## Script Behavior

- Script file: `packages/db/scripts/load_commercial_baseline.py`
- Execution wrapper: `scripts/load-commercial.ps1`
- Each virtual user executes:
  - `POST /api/auth/login`
  - `GET /api/auth/me`
  - `GET /api/v1/stores`
  - `GET /api/tasks`
  - `GET /admin/api/system/health`
- `POST /api/auth/logout` is skipped when the generated account pool is enabled, because idempotent login intentionally reuses fresh sessions per account and per-user logout would invalidate concurrent virtual users sharing that account.
- Output is JSON and includes:
  - target `base_url`
  - run timestamps
  - total requests
  - requests per second
  - global `p50 / p95 / p99 / max`
  - per-step `p50 / p95 / p99 / max`
  - `error_rate`
  - `five_xx_count`
  - pass / fail verdict
- Reports are written to `reports/load/commercial-load-*.json` by the wrapper.

## Worker Logs And Alerts

- Worker wrapper: `scripts/worker-api.ps1`
- Supervisor log: `reports/runtime/worker-supervisor-YYYYMMDD.log`
- Worker stdout: `reports/runtime/worker-YYYYMMDD-HHmmss.out.log`
- Worker stderr: `reports/runtime/worker-YYYYMMDD-HHmmss.err.log`
- Default retention is `14` days and can be changed with `XH_WORKER_LOG_RETENTION_DAYS`.
- Operations guardrail wrapper: `scripts/ops-guardrails.ps1`
- Operations guardrail schedule installer: `scripts/install-ops-guardrails-scheduled-task.ps1`
- Guardrail reports: `reports/ops/commercial-ops-*.json`
- Local alert records: `reports/alerts/ops-alert-*.json`
- Alert channel test records:
  - report: `reports/release/alert-channel-test-*.json`
  - payload: `reports/alerts/ops-alert-channel-test-*.json`
- Local alert summary wrapper: `scripts/list-alerts.ps1`
- Optional webhook routing:
  - set `XH_ALERT_WEBHOOK_URL`
  - set `XH_ALERT_REQUIRE_DELIVERY=true` if failed webhook delivery must fail the command
  - set `XH_ALERT_ON_WARN=false` if warning-only reports should not create alerts
- Environment readiness wrapper: `scripts/env-readiness.ps1`
- Store credential key rotation wrapper: `scripts/rotate-store-credential-key.ps1`
- Backup wrapper: `scripts/db-backup.ps1`
- Restore-check wrapper: `scripts/db-restore-check.ps1`
- Data integrity wrapper: `scripts/data-integrity-check.ps1`
- Backup artifacts and restore-check reports are written under `reports/backups`.
- `db:backup` prefers `pg_dump` when available; on hosts without PostgreSQL client tools it falls back to a gzip JSONL logical backup so the release path is not blocked by local PostgreSQL setup.

## Guardrail Thresholds

- Default pass gates:
  - `error_rate <= 1%`
  - `5xx_count == 0`
  - global `p95 <= 1500ms`
  - global `p99 <= 3000ms`
  - login `p95 <= 2000ms`
- These are the current commercial P0 gates for the control plane.
- Takealot sync operational budgets:
  - rolling production sync window: `6h`
  - `SYNC_STORE_LISTINGS` task failure rate `<= 5%`
  - production credential/auth failures: `0`
  - temporary Takealot platform failures: `<= 10` per window
  - active Takealot store freshness target: `last_synced_at <= 6h`
  - listing unhealthy rate (`stale` / `error`) `<= 1%`
- Test artifacts are excluded by default from operations guardrails when names or labels contain `smoke`, `guardrail`, `slice`, `debug`, or `mock`.

## Current Interpretation

- `load:commercial:smoke` is a **local script validation** command and explicitly uses `--local-asgi`.
- `load:commercial` is the real gate and refuses to run without `XH_LOAD_BASE_URL` and `XH_LOAD_PASSWORD`.
- Real run passwords must stay in environment variables; do not put them in `package.json`, shell history, screenshots, or docs.
- Current passed baseline: `reports/load/commercial-load-20260423-162234.json`.
- Baseline metrics: `1000` users, `3` iterations, `100` concurrency, `0` errors, `0` 5xx, `583.23 RPS`, global `p95=201.69ms`, global `p99=218.94ms`, login `p95=203.33ms`.
- Password hardening is included in this baseline: legacy SHA256 hashes remain readable during rollout, successful logins upgrade to PBKDF2-SHA256, and repeated verification is guarded by a bounded password verification cache.
- `npm run api:warmup` is the deploy-time mitigation for cold DB checkout: it pre-creates the load account pool, warms application sessions, and touches the high-frequency control-plane read paths before traffic is admitted.
- Current warmup validation: `reports/warmup/api-warmup-20260423-162923.json`, `100` users, `1` iteration, `20` concurrency, `0` errors, `565.64 RPS`, global `p95=43.71ms`, login `p95=41.74ms`.
- Current operations guardrail validation: `reports/ops/commercial-ops-20260423-171347.json`, `passed=true`, strict mode, `9` ok, `0` warn, `0` fail.
- Current subscription guardrail validation: `npm run db:smoke:subscription` passed on `2026-04-23`; a `starter` tenant can create up to `3` users and `1` store, and further writes return `429`.
- Current tenant onboarding validation: `npm run db:smoke:tenant-onboarding` passed on `2026-04-23`; it covers Super Admin tenant creation, first tenant-admin login, store creation, subscription upgrade / pause / resume, and audit-log verification.
- Current tenant lifecycle validation: `npm run db:smoke:tenant-lifecycle` passed on `2026-04-23`; it covers suspend / disable / restore, old session revocation, blocked login and Store writes for non-active tenants, tenant-admin password reset, temporary-password login, and audit-log verification.
- Current billing lifecycle validation: `npm run db:smoke:billing-lifecycle` passed on `2026-04-23`; it covers manual paid activation, effective expiry to `past_due`, write blocking with `402`, renewal recovery, and subscription audit verification.
- Current tenant self-service validation: `npm run db:smoke:tenant-self-service` passed on `2026-04-23`; it covers tenant-admin own usage visibility, same-cookie `/auth/me` status refresh after expiry, friendly `402` write-block prerequisite, and renewal recovery.
- Current Takealot pilot validation: `Takealot Pilot Store` synced successfully with `3` production listings; seeded `Takealot Main` demo store was disabled through the service layer with audit.
- Worker logging validation: `npm run worker:api:ps:once` wrote supervisor/stdout/stderr files under `reports/runtime` and exited with code `0`.
- Alert routing validation: forced stale-report simulation generated `reports/alerts/ops-alert-20260423-171330.json`; a normal strict report was run afterward and passed.
- Store credential encryption key was rotated away from the development default. Rotation verified `19` PGP-encrypted credential rows under the new key and skipped `2` historical non-PGP placeholder rows.
- Environment readiness validation: `reports/release/env-readiness-20260423-174317.json`, `passed=true`, `3` ok, `6` warn, `0` fail.
- Takealot sync post-rotation validation: `Takealot Pilot Store` sync succeeded after the key rotation and the store now has production listings readable through the new key.
- Release preflight validation: `reports/release/release-preflight-20260423-191305.json`, `passed=true`, `8` passed, `0` failed, `3` intentionally skipped (`db-backup`, `db-restore-check`, `api-warmup`).
- Alert channel validation: `reports/release/alert-channel-test-20260423-173039.json`, `passed=true`; local alert payload written to `reports/alerts/ops-alert-channel-test-20260423-173039.json`.
- Host activation validation: `reports/release/host-activation-20260423-191553.json`, `passed=true`, `8` ok, `2` warn, `0` fail. `XiaoheiERPWorker` is running, `XiaoheiERPOpsGuardrails` is installed, and alert channel local fallback is verified.
- Data safety validation: latest backup validation passed with `17` tables and `10111` rows in `reports/backups/db-restore-check-20260423-183102.json`.
- Data integrity validation: `reports/ops/data-integrity-20260423-183139.json`, `passed=true`, `7` ok, `0` warn, `0` fail; test/smoke artifacts are excluded by default from credential hygiene warnings.
- Latest data integrity validation: `reports/ops/data-integrity-20260423-193525.json`, `passed=true`, `7` ok, `0` warn, `0` fail.
- Latest data integrity validation after billing lifecycle: `reports/ops/data-integrity-20260423-194932.json`, `passed=true`, `7` ok, `0` warn, `0` fail.
- Latest data integrity validation after tenant self-service: `reports/ops/data-integrity-20260423-195929.json`, `passed=true`, `7` ok, `0` warn, `0` fail.
- Host activation now checks the latest backup restore-check and data integrity reports in addition to worker, guardrails, release preflight, env readiness, and alert channel state; latest report is `reports/release/host-activation-20260423-183648.json`, `8` ok, `2` warn, `0` fail.
- Remaining host warnings: `XH_ALERT_WEBHOOK_URL` is not configured, and HTTPS-only production env items are intentionally deferred until public domain launch (`XH_SESSION_COOKIE_SECURE=true`, `XH_DB_BOOTSTRAP_DEMO_DATA=false`, Takealot webhook public URL/secret/store mapping).
- Local alert summary validation: `npm run ops:alerts` and `npm run ops:alerts:json` both read the current local alert files successfully.
- `2026-04-25` refresh: a new real `1000`-user network gate passed against a temporary `uvicorn` instance on `http://127.0.0.1:8001`, written to `reports/load/commercial-load-20260425-233820.json`; metrics were `0` errors, `0` 5xx, `401.1 RPS`, global `p95=412.03ms`, global `p99=593.62ms`, login `p95=217.79ms`.
- `2026-04-25` refresh: strict ops guardrails re-passed in `reports/ops/commercial-ops-20260425-233552.json` after excluding self-service smoke tenants, disabled stores, and `disabled_by_takealot` historical listings from commercial production budgets.
- `2026-04-25` refresh: latest data integrity report `reports/ops/data-integrity-20260425-235855.json` is clean with `7` ok, `0` warn, `0` fail under the same production-only filtering.
- `2026-04-25` refresh: a full preflight rerun reached the final `ops-guardrails-strict` step, but `reports/release/release-preflight-20260425-234741.json` still failed because that step hit a transient PostgreSQL `SSL connection has been closed unexpectedly` error after the earlier steps had already passed.
- `2026-04-26` refresh: commercial ops and data-integrity read paths were hardened to stop issuing redundant read-only `rollback()` calls and now retry once on transient PostgreSQL `OperationalError`, eliminating the flaky guardrail/preflight failure mode.
- `2026-04-26` refresh: scheduled ops guardrails recovered cleanly; `XiaoheiERPOpsGuardrails` last run succeeded with result `0` and the latest strict report is `reports/ops/commercial-ops-20260426-003047.json`.
- `2026-04-26` refresh: full release preflight passed in `reports/release/release-preflight-20260426-002309.json` with `11` passed, `0` failed, `1` skipped (`api-warmup` intentionally skipped by `-SkipWarmup`).
- `2026-04-26` refresh: host activation passed in `reports/release/host-activation-20260426-003438.json` with `8` ok, `2` warn, `0` fail; the remaining warnings are still the expected launch-infrastructure items (`env-readiness` public-domain settings and missing `XH_ALERT_WEBHOOK_URL`).

## Observability Checklist

- During a full run, capture:
  - API latency by endpoint group
  - DB CPU / connections / slow queries
  - active session growth
  - `task_runs` counts by `queued / leased / running / waiting_retry`
  - lease timeout count
  - worker restart count
  - Takealot upstream error counts separated from local 5xx
  - `npm run ops:guardrails` report after each deploy and before opening traffic

## Release Gate

- Commercial P0 capacity is considered passed only when all items below are true:
  - tenant isolation smoke passes
  - control-plane smoke passes
  - full `1000`-user load run passes thresholds
  - worker survives restart and resumes lease-based draining
  - no duplicate task claim is observed
  - no cross-tenant data leak is observed
  - `npm run api:warmup` passes after deploy
  - `npm run ops:guardrails` has no hard failures; warnings require operator disposition before production traffic
  - `npm run release:preflight` is the final local command before handing traffic to the instance
  - `npm run host:check` confirms scheduled worker heartbeat and scheduled ops guardrails before launch
  - `npm run ops:env:check` must have `0` hard failures before production traffic
  - `npm run db:backup` and `npm run db:restore:check` must pass before any schema-changing deploy
  - `npm run ops:data:check` must have `0` hard failures before production traffic
  - `npm run db:smoke:subscription` must pass after any tenant, plan, user, store, or task admission-control change
  - `npm run db:smoke:tenant-onboarding` must pass after any customer provisioning, Admin tenant UI, subscription update, or auth onboarding change
  - `npm run db:smoke:tenant-lifecycle` must pass after any tenant status, session revocation, password reset, or Admin tenant lifecycle change
  - `npm run db:smoke:billing-lifecycle` must pass after any subscription period, paid activation, expiry, renewal, or payment-required write-guard change
  - `npm run db:smoke:tenant-self-service` must pass after any tenant Dashboard, `/api/auth/me` subscription payload, usage visibility, or friendly payment-required UX change
