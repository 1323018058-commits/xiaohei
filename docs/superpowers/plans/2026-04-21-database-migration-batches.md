# Database Migration Batches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready database migration batch plan that aligns schema rollout order with the ERP API implementation batches and launch-critical dependencies.

**Architecture:** This plan converts the existing schema blueprint into dependency-driven migration batches. It focuses on tables, constraints, indexes, rollout order, and rollback strategy rather than code migrations. The output becomes the canonical migration sequencing reference for subsequent DDL planning.

**Tech Stack:** Markdown docs, Git, PostgreSQL schema planning docs

---

### Task 1: Add database migration batch breakdown document

**Files:**
- Create: `/d/小黑erp/11_数据库迁移批次拆解.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the migration batch document**

Create `/d/小黑erp/11_数据库迁移批次拆解.md` with these sections:

```md
# 数据库迁移批次拆解

## 1. 目标
说明本文件把 `05_Schema_Blueprint.md` 拆成迁移批次、DDL 顺序、索引顺序与回滚策略。

## 2. 为什么采用方案 B
解释为什么采用“基础设施 → 主链 → 扩展”。

## 3. 迁移批次总览
Batch 1: 身份、权限、审计、任务骨架
Batch 2: 店铺、凭证、连接器入口
Batch 3: 履约主链
Batch 4: 竞价主链
Batch 5: 财务与重算
Batch 6: P1/P2 扩展域

## 4-9.
每个批次都包含：建表范围、DDL 顺序、约束/唯一键、索引顺序、回滚策略、验收口径。

## 10. 批次间依赖
Batch 1 → 2 → 3 → 4 → 5 → 6

## 11. 与接口批次的对应关系
把 10_P0接口实现批次拆解.md 映射过来。

## 12. 验收总口径
列出全局验收标准。
```

- [ ] **Step 2: Review document consistency**

Manually verify `/d/小黑erp/11_数据库迁移批次拆解.md` with this checklist:

```text
1. Batch 1 是否覆盖 users / audit / task 骨架
2. Batch 2 是否覆盖 stores / credentials / connector 入口
3. Batch 3 是否把 fulfillment 放在 autobid 前
4. Batch 5 是否把 finance 作为 append-only / versioned 独立批次
5. Batch 6 是否明确不阻断 P0 首发
```

Expected: all checks pass without placeholders.

- [ ] **Step 3: Update task board entry**

Append a new row after the current T27 row in `/d/小黑erp/01_任务看板.md`:

```md
| T28 | 拆解数据库迁移批次 | `done` | 已产出 `11_数据库迁移批次拆解.md`，明确 Batch 1~6 的建表、索引、回滚与验收顺序 | 下一轮继续拆解前端页面实施清单 |
```

- [ ] **Step 4: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 2:

```md
2. 基于 `05_Schema_Blueprint.md` 与 `11_数据库迁移批次拆解.md` 拆解迁移批次、表级 DDL 与索引落地顺序
```

- [ ] **Step 5: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 数据库迁移批次是否已经形成唯一建表、索引、回滚顺序
```

- [ ] **Step 6: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D020：数据库迁移按“基础设施 → 主链 → 扩展”批次推进

- 决策：将数据库迁移拆分为 Batch 1~6，按“身份权限与任务骨架 → 店铺与连接器 → 履约 → 竞价 → 财务 → P1/P2 扩展”的顺序推进
- 原因：如果仅按业务域平铺迁移，接口开发顺序、联调顺序和上线顺序会错位，回滚边界也不清晰
- 影响：后续 DDL、索引、分区和迁移脚本应以该批次顺序落地，并与 `10_P0接口实现批次拆解.md` 保持一致
```

- [ ] **Step 7: Commit the migration planning update**

Run:

```bash
git -C "/d/小黑erp" add "11_数据库迁移批次拆解.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add database migration batch breakdown

Document dependency-driven database migration batches and align the
project context, task board, and decision log with the migration order.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T28 is:

```md
下一轮继续拆解前端页面实施清单
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after schema batches, the next major planning target is page/component breakdown based on `06_页面级线框稿.md`.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align schema planning handoff

Refine the ERP planning handoff so the next round continues with the
frontend page and component implementation breakdown.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
