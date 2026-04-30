# Launch Rehearsal and Ownership Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready launch rehearsal handbook that defines ownership, freeze steps, rehearsal timeline, switch table, smoke acceptance, downgrade matrix, rollback commands, and communication rhythm.

**Architecture:** This plan turns the existing launch runbook into an operational launch-day handbook. It is organized as a release-control loop: people, freeze, rehearsal timeline, switches, smoke checks, downgrade decisions, rollback commands, and post-launch observation. It explicitly freezes the switch-governance rule: switches are preloaded in the `super_admin` backend, but every execution still requires spoken confirmation from the release lead.

**Tech Stack:** Markdown docs, Git, existing launch runbook docs

---

### Task 1: Add launch rehearsal and ownership document

**Files:**
- Create: `/d/小黑erp/14_上线彩排与责任矩阵.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the launch rehearsal breakdown document**

Create `/d/小黑erp/14_上线彩排与责任矩阵.md` with these sections:

```md
# 上线彩排与责任矩阵

## 1. 目标
说明文件把 08_上线_Runbook 继续下沉为当天可执行手册。

## 2. 发布治理总原则
说明发布负责人统一确认、super_admin 后台预置开关、所有动作留痕。

## 3. 角色与责任矩阵
## 4. 发布前冻结清单
## 5. 彩排剧本（按时间线）
## 6. 开关表
## 7. Smoke 验收表
## 8. 降级决策矩阵
## 9. 回滚口令与操作表
## 10. 值守与沟通节奏
## 11. 发布后 24 小时观察表
## 12. 关键冻结点
```

- [ ] **Step 2: Freeze switch-governance rule**

Ensure the document explicitly contains this rule:

```md
- 应急开关预置在 `super_admin` 后台
- 实际执行前，必须由发布负责人明确口头确认
- 执行人、确认人、执行时间必须留痕
```

Expected: switch execution is not distributed without release-lead confirmation.

- [ ] **Step 3: Review consistency with existing runbook**

Manually verify `/d/小黑erp/14_上线彩排与责任矩阵.md` with this checklist:

```text
1. 是否覆盖 08_上线_Runbook 的发布顺序和开关节奏
2. 是否把角色职责下沉到上线前/中/异常/后四个阶段
3. 是否有明确的开关表、降级矩阵、回滚口令表
4. 是否把 smoke 验收项细化到模块级
5. 是否有 24 小时观察与复盘输出要求
```

Expected: all five checks pass without placeholders.

- [ ] **Step 4: Update task board entry**

Append a new row after the current T30 row in `/d/小黑erp/01_任务看板.md`:

```md
| T31 | 拆解上线彩排与责任矩阵 | `done` | 已产出 `14_上线彩排与责任矩阵.md`，明确责任矩阵、彩排剧本、开关表、降级矩阵与回滚口令 | 下一轮继续补齐 P1 接口与表级 DDL 清单 |
```

- [ ] **Step 5: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 5:

```md
5. 基于 `08_上线_Runbook.md` 与 `14_上线彩排与责任矩阵.md` 明确发布责任矩阵、彩排清单与开关表
```

- [ ] **Step 6: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 上线彩排、责任矩阵、开关表、降级矩阵与回滚口令是否已经形成唯一执行口径
```

- [ ] **Step 7: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D026：上线准备按“责任矩阵 → 彩排剧本 → 开关表 → 降级/回滚口令”闭环推进

- 决策：将上线准备继续拆为责任矩阵、彩排剧本、开关表、Smoke 验收表、降级决策矩阵、回滚口令与值守沟通节奏
- 原因：如果只保留 Runbook 主线而不细化责任、口令和开关表，上线当天仍会因为等待确认、动作冲突或信息不对称而返工
- 影响：后续上线演练、正式发布、降级与回滚应以 `14_上线彩排与责任矩阵.md` 为唯一执行主版本
```

Also append:

```md
### D027：上线当天开关控制采用“super_admin 后台预置 + 发布负责人统一口头确认”

- 决策：应急开关预置在 `super_admin` 后台，但实际执行仍必须由发布负责人统一口头确认，各域负责人或操作人不能自行跳过确认
- 原因：完全中心化手工切换会慢，完全分权又容易在高压场景下失控，需要兼顾速度与控制
- 影响：后续开关表、彩排剧本、降级矩阵和回滚流程都必须保留“确认人 / 执行人 / 执行时间”字段
```

- [ ] **Step 8: Commit the launch-planning update**

Run:

```bash
git -C "/d/小黑erp" add "14_上线彩排与责任矩阵.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add launch rehearsal and ownership breakdown

Document the ERP launch-day execution handbook, including ownership,
rehearsal timeline, switches, downgrade matrix, and rollback commands.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T31 is:

```md
下一轮继续补齐 P1 接口与表级 DDL 清单
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after launch-handbook refinement, the next major targets remain `P1` API batches and table-level DDL/index/rollback checklists.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align launch planning handoff

Refine the ERP planning handoff so the next round returns to P1 API
batches and detailed table-level DDL rollout checklists.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
