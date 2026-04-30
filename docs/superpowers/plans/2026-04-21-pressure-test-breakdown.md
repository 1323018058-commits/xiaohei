# Pressure Test Scripts and Seed Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready pressure-testing preparation document that defines the Locust-based script structure, seed-data responsibilities, observability checklist, failure template, and execution batches.

**Architecture:** This plan refines the existing load-test strategy into a delivery-oriented operational document. It uses a closed-loop structure: environment, seed data, Locust scenarios, observability, failure logging, execution batches, and pre-launch revalidation. It does not implement scripts yet.

**Tech Stack:** Markdown docs, Git, Locust, PostgreSQL, Redis/queue, existing ERP load-test docs

---

### Task 1: Add pressure-test scripts and seed-data document

**Files:**
- Create: `/d/小黑erp/13_压测脚本与造数方案.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the pressure-test breakdown document**

Create `/d/小黑erp/13_压测脚本与造数方案.md` with these sections:

```md
# 压测脚本与造数方案

## 1. 目标
说明把 07_压测计划继续拆成可执行方案。

## 2. 为什么选择 Locust
说明选择 Python/Locust 的原因。

## 3. 压测闭环结构
环境 → 造数 → 场景脚本 → 观测 → 失败模板 → 执行批次 → 上线复验

## 4. 环境准备清单
## 5. 造数方案
## 6. Locust 场景脚本清单
## 7. 观测项与看板
## 8. 失败记录模板
## 9. 执行批次
## 10. 上线前复验清单
## 11. 关键冻结点
```

- [ ] **Step 2: Freeze Locust as the primary tool**

Ensure the document explicitly contains these constraints:

```md
- 压测工具首选 `Locust`
- 脚本结构按“公共能力 + 场景文件”组织
- 首轮先覆盖 `P0` 场景 A~D
- 外部失败模拟属于必测项，不是可选项
```

Expected: the plan is no longer tool-neutral.

- [ ] **Step 3: Review consistency with existing load-test plan**

Manually verify `/d/小黑erp/13_压测脚本与造数方案.md` with this checklist:

```text
1. 是否覆盖 07_压测计划 的 A~E 场景
2. 是否给出明确造数职责，而不只是数据规模
3. 是否给出 Locust 场景脚本结构
4. 是否给出观测项和失败记录模板
5. 是否给出执行批次和上线前复验
```

Expected: all five checks pass without placeholders.

- [ ] **Step 4: Update task board entry**

Append a new row after the current T29 row in `/d/小黑erp/01_任务看板.md`:

```md
| T30 | 拆解压测脚本与造数方案 | `done` | 已产出 `13_压测脚本与造数方案.md`，明确环境、造数、Locust 场景、观测、失败模板与执行批次 | 下一轮继续准备上线彩排与责任矩阵 |
```

- [ ] **Step 5: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 4:

```md
4. 基于 `07_压测计划.md` 与 `13_压测脚本与造数方案.md` 明确压测脚本、造数、观测指标与环境准备方案
```

- [ ] **Step 6: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 压测方案是否已经形成唯一工具、场景脚本、造数、观测与失败记录口径
```

- [ ] **Step 7: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D024：压测准备按“环境 → 造数 → Locust 场景 → 观测 → 复验”闭环推进

- 决策：将压测准备拆为环境、造数、Locust 场景脚本、观测项、失败记录模板、执行批次与上线前复验清单
- 原因：如果只保留场景描述而没有脚本结构、造数职责和观测规则，压测工作无法真正开工
- 影响：后续压测实施、环境准备、失败复盘和上线前复验应以 `13_压测脚本与造数方案.md` 为唯一主版本
```

Also append:

```md
### D025：压测工具首选 Locust

- 决策：首轮压测默认以 `Locust` 作为主工具，而不是维持工具无关状态
- 原因：ERP 压测需要登录、长任务轮询、高危写冲突和外部异常模拟，使用 Python 更利于表达复杂业务流程
- 影响：后续压测脚本目录、用户类型、场景编排和造数辅助脚本默认围绕 `Locust` 组织
```

- [ ] **Step 8: Commit the load-test planning update**

Run:

```bash
git -C "/d/小黑erp" add "13_压测脚本与造数方案.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add pressure test script and seed plan

Document the ERP pressure-test preparation workflow, including Locust
scenarios, seed data responsibilities, observability, and execution batches.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T30 is:

```md
下一轮继续准备上线彩排与责任矩阵
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after pressure-test preparation, the next major target is launch rehearsal, owner matrix, and switch table preparation based on `08_上线_Runbook.md`.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align load-test planning handoff

Refine the ERP planning handoff so the next round continues with launch
rehearsal, owner matrix, and switch-table preparation.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
