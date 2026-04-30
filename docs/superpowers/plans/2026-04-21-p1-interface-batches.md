# P1 Interface Batches Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready P1 API batch plan that defines limited-availability rollout order, integration sequence, and acceptance gates for Selection, Extension, Warehouse, and Finance.

**Architecture:** This plan extends the existing P0 interface batch structure into P1. It uses a limited-availability dependency chain rather than a launch-blocking main-chain model. The plan explicitly freezes Finance as read-first with whitelist-only recalculation and non-default adjustment exposure.

**Tech Stack:** Markdown docs, Git, existing ERP API and rollout docs

---

### Task 1: Add P1 interface batch breakdown document

**Files:**
- Create: `/d/小黑erp/16_P1接口实现批次拆解.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the P1 batch breakdown document**

Create `/d/小黑erp/16_P1接口实现批次拆解.md` with this structure:

```md
# P1 接口实现批次拆解

## 1. 目标
说明把 04_API契约逐接口展开.md 的 P1 接口按受限可用依赖链拆批次。

## 2. 为什么采用方案 B
解释为什么按“Selection/Extension → Warehouse → Finance”推进。

## 3. 批次总览
Batch 5: Selection / Extension
Batch 6: Warehouse
Batch 7: Finance

## 4-6.
每个批次都写：范围、前置依赖、开发顺序、联调顺序、验收口径、风险点。

## 7. 批次间关系
## 8. 与前面文档的边界关系
## 9. 验收总口径
```

- [ ] **Step 2: Freeze Finance rollout rule**

Ensure the Finance section explicitly contains these constraints:

```md
- 读侧优先
- `recalculate` 只对白名单或受限范围开放
- `adjustments` 不做默认全面开放
- `freeze` 仅 `super_admin` 可用
```

Expected: Finance is constrained enough to stay in P1 without destabilizing the system.

- [ ] **Step 3: Review consistency with existing API docs**

Manually verify `/d/小黑erp/16_P1接口实现批次拆解.md` with this checklist:

```text
1. 是否只覆盖 P1，而未把 P2 混入
2. 是否把 Warehouse 放在 Finance 之前
3. 是否把 Selection / Extension 定位为轻量受限能力
4. 是否明确 Finance 的白名单重算策略
5. 是否给出“读侧 / 受限写侧 / 暂不开放”的边界
```

Expected: all checks pass without placeholders.

- [ ] **Step 4: Update task board entry**

Append a new row after the current T32 row in `/d/小黑erp/01_任务看板.md`:

```md
| T33 | 补齐 P1 接口实现批次 | `done` | 已产出 `16_P1接口实现批次拆解.md`，明确 Batch 5~7 的开发、联调与受限上线边界 | 下一轮继续冻结页面与压测执行口径 |
```

- [ ] **Step 5: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 1:

```md
1. 基于 `04_API契约逐接口展开.md`、`10_P0接口实现批次拆解.md` 与 `16_P1接口实现批次拆解.md` 补齐 `P1` 接口实现批次与联调顺序
```

- [ ] **Step 6: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- `P1` 是否已经形成唯一批次顺序、联调顺序与受限上线边界
```

- [ ] **Step 7: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D030：P1 接口实现按“Selection/Extension → Warehouse → Finance”批次推进

- 决策：将 `P1` 接口拆分为 Batch 5~7，按“Selection / Extension → Warehouse → Finance”的顺序推进
- 原因：`P1` 的重点是受限可用而不是阻断主链，如果按模块平铺推进，容易把风险最高的 Finance 提前做重
- 影响：后续 `P1` 接口开发、联调和灰度上线应按该顺序推进，不与 `P0` 主链抢节奏
```

Also append:

```md
### D031：Finance 在 P1 阶段采用“读侧优先 + 白名单重算 + 非默认全面 adjustment”

- 决策：`Finance` 在 `P1` 阶段优先开放读侧，`recalculate` 只对白名单或受限范围开放，`adjustments` 不做默认全面开放
- 原因：财务域风险最高，若过早全面开放写能力，会直接增加数据失控与审计风险
- 影响：后续前端、后端、压测和上线验收都必须按该受限边界设计，不得把 `Finance` 当作完整开放域
```

- [ ] **Step 8: Commit the P1 interface planning update**

Run:

```bash
git -C "/d/小黑erp" add "16_P1接口实现批次拆解.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add P1 API batch breakdown

Document the ERP P1 API rollout batches, including limited-availability
boundaries for Selection, Warehouse, and Finance.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T33 is:

```md
下一轮继续冻结页面与压测执行口径
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after P1 interface batches are filled in, the next highest-value work is freezing page-development order and load-test execution rules.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align P1 planning handoff

Refine the ERP planning handoff so the next round focuses on page-order
freezing and load-test execution rules.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
