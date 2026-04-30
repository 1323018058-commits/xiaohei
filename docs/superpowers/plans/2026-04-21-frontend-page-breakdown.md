# Frontend Page Breakdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready frontend page breakdown that turns the ERP wireframes into pages, dialogs, drawers, reusable UI units, dependency APIs, and rollout priority.

**Architecture:** This plan does not implement UI code. It refines the existing page-level wireframe document into a delivery-oriented frontend implementation checklist organized by app shell, task flows, and reusable interaction layers. The fulfillment flow is explicitly frozen as a two-tab structure with a centered immersive ticketing dialog.

**Tech Stack:** Markdown docs, Git, existing frontend wireframe docs

---

### Task 1: Add frontend page breakdown document

**Files:**
- Create: `/d/小黑erp/12_前端页面实施清单.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the frontend breakdown document**

Create `/d/小黑erp/12_前端页面实施清单.md` with these sections:

```md
# 前端页面实施清单

## 1. 目标
说明文档继续下沉 06_页面级线框稿。

## 2. 实施总原则
先 P0、后 P1，先任务闭环、后展示细节。

## 3-10.
按这些层次展开：
- 全局框架层
- Dashboard 任务总览流
- Admin 用户与权限流
- Store / Sync 流
- Fulfillment / PO 任务流
- Bidding 流
- Finance 流
- Task / Audit 通用交互层

每一层都写：页面、抽屉、弹层、组件、依赖接口、验收口径。

## 11. 通用交互件清单
## 12. 实施优先级
## 13. 关键冻结点
```

- [ ] **Step 2: Freeze fulfillment interaction in the document**

Ensure the fulfillment section includes this exact structure:

```md
- `订单池 Tab`：专注挑货合单
- `PO 工作台 Tab`：专注沉浸打单
- `PO` 打单使用屏幕中央约 80% 宽度的毛玻璃 `Dialog`
- 打单视线只保留 `48x48` 商品图、粗体 `SKU`、回车自动跳行的单号输入框
- 跨仓合单时按钮置灰，并出现黑白 Toast：`禁止跨仓合单`
```

Expected: fulfillment interaction no longer depends on a right drawer workbench.

- [ ] **Step 3: Review consistency with existing docs**

Manually verify `/d/小黑erp/12_前端页面实施清单.md` with this checklist:

```text
1. 是否沿用 06_页面级线框稿 的页面范围
2. 是否把通用件抽出来，避免按页面重复
3. Fulfillment 是否已按用户确认的双 Tab + 居中 Dialog 冻结
4. 是否列出依赖接口而非只写视觉结构
5. 是否给出实施优先级
```

Expected: all five checks pass without placeholders.

- [ ] **Step 4: Update task board entry**

Append a new row after the current T28 row in `/d/小黑erp/01_任务看板.md`:

```md
| T29 | 拆解前端页面实施清单 | `done` | 已产出 `12_前端页面实施清单.md`，明确页面、抽屉、弹层、组件、依赖接口与实施优先级 | 下一轮继续准备压测脚本与造数方案 |
```

- [ ] **Step 5: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 3:

```md
3. 基于 `06_页面级线框稿.md` 与 `12_前端页面实施清单.md` 拆解首发页面、抽屉、弹层与组件清单
```

- [ ] **Step 6: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 前端页面实施清单是否已经形成唯一页面、弹层、抽屉、组件与交互冻结口径
```

- [ ] **Step 7: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D022：前端页面实施按“页面壳 + 任务流 + 通用交互件”推进

- 决策：将前端实施清单按全局框架、业务任务流和通用交互件拆解，而不是单纯按页面名平铺
- 原因：直接按页面名拆会重复定义抽屉、弹层和通用组件，后续实现容易发散
- 影响：后续前端页面开发、组件拆分和联调依赖应以 `12_前端页面实施清单.md` 为主版本
```

Also append:

```md
### D023：Fulfillment 前端主交互冻结为双 Tab + 沉浸式打单 Dialog

- 决策：`Fulfillment` 页面采用 `订单池 Tab` 与 `PO 工作台 Tab` 双阶段结构，`PO` 打单使用居中 80% 宽度毛玻璃 Dialog，而不是右侧抽屉
- 原因：该域的核心效率目标不是浏览信息，而是“挑货合单”和“沉浸打单”，需要明确切断干扰
- 影响：后续 Fulfillment 前端实现必须按该交互冻结点推进，跨仓合单前端需置灰并提示，后端继续保留强校验
```

- [ ] **Step 8: Commit the frontend planning update**

Run:

```bash
git -C "/d/小黑erp" add "12_前端页面实施清单.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add frontend page implementation breakdown

Document the ERP frontend implementation breakdown by page shell, task flow,
and shared interaction units, including the frozen fulfillment UX.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T29 is:

```md
下一轮继续准备压测脚本与造数方案
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after the frontend breakdown, the next main target is pressure-test scripts, data generation, and environment preparation based on `07_压测计划.md`.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align frontend planning handoff

Refine the ERP planning handoff so the next round continues with pressure-test
scripts, seed data, observability, and environment preparation.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
