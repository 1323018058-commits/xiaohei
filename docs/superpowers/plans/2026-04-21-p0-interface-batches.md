# P0 Interface Batch Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready batch plan for `P0` API implementation and integration order, based on the agreed dependency-chain approach.

**Architecture:** This plan does not implement product code. It refines existing ERP implementation docs into batch-based execution guidance that aligns API contracts, integration sequence, and acceptance gates. The approach uses four dependency-driven batches: control plane, task/store sync, fulfillment main chain, and autobid.

**Tech Stack:** Markdown docs, Git, existing ERP PRD/control docs

---

### Task 1: Add P0 batch breakdown document

**Files:**
- Create: `/d/小黑erp/10_P0接口实现批次拆解.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the batch breakdown document**

Create `/d/小黑erp/10_P0接口实现批次拆解.md` with these sections:

```md
# P0 接口实现批次拆解

## 1. 目标
说明本文件把 `04_API契约逐接口展开.md` 的 P0 接口按依赖链拆成 4 个批次。

## 2. 为什么采用方案 B
解释为什么按依赖链优于按模块平铺。

## 3. 批次总览
Batch 1: 身份与控制面
Batch 2: 任务骨架与店铺同步
Batch 3: 履约主链
Batch 4: 竞价主链

## 4-7.
每个批次都包含：范围、前置依赖、开发顺序、联调顺序、验收口径、风险点。

## 8. 批次间硬依赖
Batch 1 → Batch 2 → Batch 3 → Batch 4

## 9. 建议联调节奏
按四轮推进。

## 10. 验收总口径
列出全局验收标准。
```

- [ ] **Step 2: Review the created doc for consistency**

Run this checklist manually against `/d/小黑erp/10_P0接口实现批次拆解.md`:

```text
1. Batch 1 是否只包含身份/控制面和 Admin 读写
2. Batch 2 是否先打通 Task 再打通 Store/Sync
3. Batch 3 是否把 Fulfillment 放在 AutoBid 前
4. Batch 4 是否依赖前三批的身份/任务/审计骨架
5. 验收口径是否和 04/08 两份文档一致
```

Expected: all five checks pass without needing placeholder text.

- [ ] **Step 3: Update task board entry**

Append a new row after the current T26 row in `/d/小黑erp/01_任务看板.md`:

```md
| T27 | 拆解 P0 接口实现批次 | `done` | 已产出 `10_P0接口实现批次拆解.md`，按依赖链形成 Batch 1~4 的开发与联调顺序 | 下一轮继续拆解 P1 与数据库迁移批次 |
```

- [ ] **Step 4: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, keep the current stage unchanged and refine priority item 1 so it explicitly points to the new batch doc:

```md
1. 基于 `04_API契约逐接口展开.md` 与 `10_P0接口实现批次拆解.md` 推进 `P0 / P1` 接口实现批次与联调顺序
```

- [ ] **Step 5: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D019：P0 接口实现按依赖链批次推进

- 决策：将 `P0` 接口实现拆分为 Batch 1~4，按“身份与控制面 → 任务骨架与店铺同步 → 履约主链 → 竞价主链”的顺序推进
- 原因：按模块平铺会掩盖真实依赖关系，导致联调顺序和上线顺序错位
- 影响：后续接口开发、联调、验收和排期应以批次顺序为准，而不是按模块各自并行冲刺
```

- [ ] **Step 6: Commit the doc-planning update**

Run:

```bash
git -C "/d/小黑erp" add "10_P0接口实现批次拆解.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add P0 API batch breakdown

Document dependency-driven P0 API implementation batches and sync the
project context, task board, and decision log to use the new execution order.
EOF
)"
```

Expected: commit succeeds and produces a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Confirm next actionable planning targets**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T27 is:

```md
下一轮继续拆解 P1 与数据库迁移批次
```

- [ ] **Step 2: Align project context checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes these two checkpoint concerns in section 7:

```md
- `P0` 四个实现批次是否已经形成唯一开发顺序和联调顺序
- `P1` 接口与数据库迁移批次是否准备进入下一轮拆解
```

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align next planning checkpoints

Refine the ERP planning handoff so the next round continues with P1 API
batches and database migration batch breakdown.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
