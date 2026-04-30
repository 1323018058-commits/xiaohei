# Frontend Order and Interaction Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready frontend freeze document that locks page rollout waves, shared component dependency order, high-risk interaction rules, and long-task UX requirements.

**Architecture:** This plan refines the existing frontend implementation checklist into a freeze-oriented execution guide. It focuses on preventing rework: wave order, reusable UI layers, consistent confirmation patterns, and frozen interaction boundaries for critical domains such as Fulfillment and Admin.

**Tech Stack:** Markdown docs, Git, existing frontend implementation docs

---

### Task 1: Add frontend order and interaction freeze document

**Files:**
- Create: `/d/小黑erp/17_页面开发顺序与交互冻结点.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the frontend freeze document**

Create `/d/小黑erp/17_页面开发顺序与交互冻结点.md` with this structure:

```md
# 页面开发顺序与交互冻结点

## 1. 目标
说明本文件继续下沉 12_前端页面实施清单。

## 2. 页面开发总原则
## 3. 页面开发波次
Wave 1: 全局框架与控制面
Wave 2: Fulfillment 主链
Wave 3: Store / Sync 与 Bidding
Wave 4: Finance / Warehouse / Selection / Extension

## 4. 通用组件依赖顺序
## 5. 高危交互冻结表
## 6. 长任务反馈冻结表
## 7. 页面级冻结点
## 8. 页面验收门槛
## 9. 关键冻结点总结
```

- [ ] **Step 2: Freeze Admin confirmation pattern**

Ensure the document explicitly contains this rule:

```md
- 所有高危动作采用统一确认骨架
- 但不同动作必须显示不同风险说明
- 不允许页面各自发明确认文案结构
```

Expected: Admin high-risk actions share one structural pattern but have differentiated risk copy.

- [ ] **Step 3: Keep Fulfillment freeze intact**

Ensure the document still contains these constraints:

```md
- `Fulfillment` 双 Tab 结构冻结
- `PO` 打单必须用居中 `Dialog`
- 禁止跨仓合单必须按钮置灰 + 黑白 Toast
```

Expected: the previously approved fulfillment UX remains unchanged.

- [ ] **Step 4: Review consistency with existing frontend docs**

Manually verify `/d/小黑erp/17_页面开发顺序与交互冻结点.md` with this checklist:

```text
1. 是否沿用 12_前端页面实施清单 的页面边界
2. 是否给出清晰的 Wave 1~4 顺序
3. 是否把通用组件依赖顺序写清
4. 是否冻结高危交互与长任务反馈规则
5. 是否把 Fulfillment 和 Admin 的关键交互定死
```

Expected: all five checks pass without placeholders.

- [ ] **Step 5: Update task board entry**

Append a new row after the current T33 row in `/d/小黑erp/01_任务看板.md`:

```md
| T34 | 冻结页面开发顺序与交互确认点 | `done` | 已产出 `17_页面开发顺序与交互冻结点.md`，明确 Wave 顺序、组件依赖、高危交互与长任务反馈规则 | 下一轮继续冻结压测执行口径 |
```

- [ ] **Step 6: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 3:

```md
3. 基于 `12_前端页面实施清单.md` 与 `17_页面开发顺序与交互冻结点.md` 冻结页面开发顺序、组件依赖与高危交互确认点
```

- [ ] **Step 7: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 页面开发顺序、组件依赖和高危交互确认点是否已经形成唯一冻结口径
```

- [ ] **Step 8: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D032：前端页面开发顺序按 Wave 1~4 冻结

- 决策：将前端页面开发顺序冻结为 Wave 1 全局框架与控制面、Wave 2 Fulfillment 主链、Wave 3 Store/Sync 与 Bidding、Wave 4 Finance/Warehouse/Selection/Extension
- 原因：如果不固定开发波次，前端很容易在通用件未稳定时并行开发多个业务页面，导致返工
- 影响：后续页面开发排期、联调顺序与组件复用应按该 Wave 顺序推进
```

Also append:

```md
### D033：Admin 高危交互采用“统一骨架 + 动作差异化风险说明”

- 决策：Admin 域高危动作统一使用确认骨架，但根据动作类型展示不同风险说明与按钮文案
- 原因：完全分散会导致交互风格漂移，完全统一文案又会让风险语义失真，需要兼顾一致性与可理解性
- 影响：后续 Admin 前端实现、设计稿和验收都必须按该规则执行，不得私自新增非标准确认框
```

- [ ] **Step 9: Commit the frontend freeze update**

Run:

```bash
git -C "/d/小黑erp" add "17_页面开发顺序与交互冻结点.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add frontend rollout and interaction freeze

Document frontend rollout waves, shared component dependency order,
and frozen high-risk interaction rules for the ERP UI.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T34 is:

```md
下一轮继续冻结压测执行口径
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after frontend freeze, the next major target is freezing load-test execution rules, directory structure, seed-data responsibility, and revalidation practice.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align frontend freeze handoff

Refine the ERP planning handoff so the next round focuses on freezing
load-test execution rules and operational pressure-test practice.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
