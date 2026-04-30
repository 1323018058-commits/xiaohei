# Load Test Execution Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-freeze document for ERP load testing that locks directory structure, Locust user types, seed-data ownership, execution batches, graded pass criteria, failure logging, and pre-launch revalidation.

**Architecture:** This plan refines the existing load-test preparation docs into a rulebook that prevents thrash during execution. It fixes the operational pressure-test shape before script implementation: where files live, who owns seed data, which batches run in what order, and how results are graded as launchable, ideal, or blocking.

**Tech Stack:** Markdown docs, Git, Locust, PostgreSQL, Redis/queue, ERP load-test docs

---

### Task 1: Add load-test execution freeze document

**Files:**
- Create: `/d/小黑erp/18_压测执行口径冻结.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the execution-freeze document**

Create `/d/小黑erp/18_压测执行口径冻结.md` with this structure:

```md
# 压测执行口径冻结

## 1. 目标
说明本文件把 13_压测脚本与造数方案推进到执行冻结。

## 2. 总原则
## 3. 目录结构冻结
## 4. Locust 用户类型冻结
## 5. 造数职责冻结
## 6. 执行批次冻结
## 7. 分级通过标准冻结
## 8. 失败记录与报告输出冻结
## 9. 上线前复验口径冻结
## 10. 关键冻结点
```

- [ ] **Step 2: Freeze graded pass criteria**

Ensure the document explicitly contains these result grades:

```md
- `可上线`
- `理想通过`
- `阻断上线`
```

And that each grade has concrete conditions.

Expected: pressure-test results are no longer a binary pass/fail judgment.

- [ ] **Step 3: Keep Locust and Finance boundaries intact**

Ensure the document still contains these constraints:

```md
- `Locust` 为唯一主工具
- `Finance` 复验仍遵守白名单重算边界
```

Expected: the previously frozen tool and Finance boundary remain unchanged.

- [ ] **Step 4: Review consistency with existing load-test docs**

Manually verify `/d/小黑erp/18_压测执行口径冻结.md` with this checklist:

```text
1. 是否延续 13_压测脚本与造数方案 的目录和职责结构
2. 是否明确 A~E 批次执行顺序
3. 是否给出三档通过标准
4. 是否冻结失败记录和报告输出要求
5. 是否把上线前复验口径写死
```

Expected: all five checks pass without placeholders.

- [ ] **Step 5: Update task board entry**

Append a new row after the current T34 row in `/d/小黑erp/01_任务看板.md`:

```md
| T35 | 冻结压测执行口径 | `done` | 已产出 `18_压测执行口径冻结.md`，明确目录、职责、批次、三档通过标准与复验口径 | 下一轮回到上线手册收口或复查整体一致性 |
```

- [ ] **Step 6: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, refine priority item 4:

```md
4. 基于 `13_压测脚本与造数方案.md` 与 `18_压测执行口径冻结.md` 冻结脚本目录、造数职责、执行批次与复验口径
```

- [ ] **Step 7: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 压测执行口径、批次顺序和三档通过标准是否已经形成唯一冻结版本
```

- [ ] **Step 8: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D034：压测执行采用“目录/职责/批次/三档结果”统一冻结口径

- 决策：将压测执行继续冻结为目录结构、Locust 用户类型、造数职责、执行批次、三档通过标准、失败模板与上线前复验口径
- 原因：如果压测只停留在准备方案层，真正执行时仍会在目录、职责、报告口径与是否通过上反复争论
- 影响：后续压测脚本编写、执行、复盘和上线前复验应以 `18_压测执行口径冻结.md` 为唯一执行主版本
```

Also append:

```md
### D035：压测结果采用“可上线 / 理想通过 / 阻断上线”三档判定

- 决策：压测结果不采用简单二元通过，而采用“可上线 / 理想通过 / 阻断上线”三档判定
- 原因：ERP 首发阶段需要在时间压力下做受控决策，既不能因为不完美就无限延期，也不能因为勉强通过就掩盖重大风险
- 影响：后续压测报告、上线评审和发布窗口决策必须按三档表达，不能只写 pass/fail
```

- [ ] **Step 9: Commit the load-test freeze update**

Run:

```bash
git -C "/d/小黑erp" add "18_压测执行口径冻结.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add load-test execution freeze

Document the ERP load-test execution rules, including directory layout,
ownership, execution batches, graded outcomes, and revalidation policy.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T35 is:

```md
下一轮开始整体一致性复查与收口
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after freezing load-test execution, the next valuable step is a consistency review across API, schema, frontend, load-test, and launch docs.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align load-test freeze handoff

Refine the ERP planning handoff so the next round focuses on end-to-end
consistency review and closing remaining cross-document gaps.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
