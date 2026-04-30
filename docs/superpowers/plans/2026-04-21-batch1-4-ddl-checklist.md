# Batch 1-4 Table-Level DDL Checklist Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a table-level DDL checklist for schema migration Batches 1-4 with enough field-level detail that engineers can write SQL migrations with minimal reinterpretation.

**Architecture:** This plan refines the existing migration-batch document into a field-level DDL execution checklist. It does not generate SQL files yet; instead it defines table-by-table fields, constraints, immediate indexes, deferred indexes, rollback notes, and acceptance checks for launch-critical schema batches.

**Tech Stack:** Markdown docs, Git, PostgreSQL schema planning docs

---

### Task 1: Add table-level DDL rollout checklist

**Files:**
- Create: `/d/小黑erp/15_Batch1-4表级DDL落地清单.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the table-level DDL checklist**

Create `/d/小黑erp/15_Batch1-4表级DDL落地清单.md` with this structure:

```md
# Batch 1~4 表级 DDL 落地清单

## 1. 目标
说明本文件把 11_数据库迁移批次拆解继续下沉到字段级。

## 2. Batch 1
按表写：
- tenants
- users
- user_passwords
- auth_sessions
- user_feature_flags
- audit_logs
- task_definitions
- task_runs
- task_events

## 3. Batch 2
按表写：
- stores
- store_credentials
- connector_inbox

## 4. Batch 3
按表写：
- fulfillment_orders
- fulfillment_order_items
- fulfillment_pos
- fulfillment_purchase_shipments

## 5. Batch 4
按表写：
- bid_products
- sku_floor_prices
- bid_log
- autobid_store_policy

每张表都写：
- 建表核心字段
- 建表即落约束
- 建表即落索引
- 可延后索引
- 回滚注意点
- 验收点

## 6. 批次级统一规则
## 7. 验收总口径
```

- [ ] **Step 2: Keep field detail close to SQL**

Ensure the document uses field lines like these examples:

```md
- `id uuid primary key`
- `tenant_id uuid not null`
- `created_at timestamptz not null default now()`
- `unique (tenant_id, name)`
- `index on (tenant_id, status)`
```

Expected: detail level is high enough to write SQL without re-deciding core schema facts.

- [ ] **Step 3: Review consistency with existing schema docs**

Manually verify `/d/小黑erp/15_Batch1-4表级DDL落地清单.md` with this checklist:

```text
1. Batch 1 是否覆盖控制面与任务骨架核心表
2. Batch 2 是否覆盖店铺、凭证、连接器入口核心表
3. Batch 3 是否覆盖履约主链核心表
4. Batch 4 是否覆盖竞价主链核心表
5. 是否区分“建表即落索引”和“可延后索引”
```

Expected: all checks pass without placeholders.

- [ ] **Step 4: Update task board entry**

Append a new row after the current T31 row in `/d/小黑erp/01_任务看板.md`:

```md
| T32 | 细化 Batch 1~4 表级 DDL 清单 | `done` | 已产出 `15_Batch1-4表级DDL落地清单.md`，明确字段、约束、索引、回滚与验收点 | 下一轮继续补齐 P1 接口实现批次 |
```

- [ ] **Step 5: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 2:

```md
2. 基于 `05_Schema_Blueprint.md`、`11_数据库迁移批次拆解.md` 与 `15_Batch1-4表级DDL落地清单.md` 细化 Batch 1~4 表级 DDL、索引与回滚清单
```

- [ ] **Step 6: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- Batch 1~4 是否已经形成接近 SQL 粒度的字段、约束、索引与回滚口径
```

- [ ] **Step 7: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D029：Batch 1~4 数据库迁移继续下沉到表级 DDL 清单

- 决策：将 Batch 1~4 继续细化为字段级、接近 SQL 粒度的表级 DDL 落地清单
- 原因：如果只停留在“批次 + 表名”层级，开发在真正写 migration 时仍会重复讨论字段、约束、索引时机和回滚边界
- 影响：后续 SQL 迁移脚本、DDL review 和上线前数据库验收应以 `15_Batch1-4表级DDL落地清单.md` 为执行基准
```

- [ ] **Step 8: Commit the DDL checklist update**

Run:

```bash
git -C "/d/小黑erp" add "15_Batch1-4表级DDL落地清单.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add table-level DDL rollout checklist

Document Batch 1-4 schema rollout at near-SQL field granularity,
including constraints, index timing, rollback notes, and acceptance checks.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T32 is:

```md
下一轮继续补齐 P1 接口实现批次
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after the table-level DDL checklist, the next highest-value gap is still the `P1` API implementation batch breakdown.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align DDL planning handoff

Refine the ERP planning handoff so the next round focuses on the remaining
P1 API implementation batch breakdown.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
