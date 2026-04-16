# ProfitLens Stabilization Design

## Goal
Stabilize ProfitLens v3 for safe development and production rollout by fixing blocking build/deploy issues, extension/backend contract mismatches, and high-risk secret/TLS exposures.

## Scope
- Frontend build/lint unblock
- Store detail route refresh correctness
- Extension pricing-config and list-now contract fixes
- Remove plaintext API key exposure to frontend
- Enforce safer production config for secrets/TLS/CORS
- Fix docker production compose validation issues

## Approach
1. Patch frontend toolchain so `npm run build` and `npm run lint` are meaningful and pass.
2. Patch extension and backend together so pricing-config and list-now reflect real behavior.
3. Patch backend security defaults and deployment configs to remove the highest-risk misconfigurations without broad refactors.
4. Verify with targeted local commands: build, lint, compileall, compose config.

## Non-Goals
- Full auth redesign to HttpOnly cookies
- Full migration/bootstrap of every database table
- Replacing all extension auth UX flows
- Broad test framework introduction
