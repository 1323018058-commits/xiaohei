# Exception Handling Manual Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce an execution-ready exception-handling and manual-intervention handbook focused on ERP operational control, with primary weight on Fulfillment/PO/tracking/binding incidents, secondary weight on store sync/external platform/dirty data issues, and stricter limited treatment for Finance incidents.

**Architecture:** This plan does not implement runtime code. It adds an operations-grade control document that defines exception classes, intervention levels, ownership, allowed actions, forbidden actions, audit requirements, recovery actions, and fast-reference incident cards. The manual is structured as a runbook for operators, tenant admins, super admins, and launch-day technical owners.

**Tech Stack:** Markdown docs, Git, existing ERP API/schema/task/audit/runbook docs

---

### Task 1: Add exception-handling and manual-intervention handbook

**Files:**
- Create: `/d/小黑erp/21_异常处理与人工介入手册.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the handbook skeleton**

Create `/d/小黑erp/21_异常处理与人工介入手册.md` with this structure:

```md
# 异常处理与人工介入手册

## 1. 目标与适用范围
## 2. 异常分级标准
## 3. 人工介入权限矩阵
## 4. 异常分类总表
## 5. A 类主手册：Fulfillment / PO / 补号 / 错绑
## 6. B 类辅助手册：Store Sync / 外部平台 / 脏数据
## 7. C 类严格手册：Finance
## 8. Task / ErrorCode / Audit 映射
## 9. 上线期特殊处理规则
## 10. TOP 10 高频异常速查表
## 11. 关键冻结点
```

- [ ] **Step 2: Freeze intervention levels**

Ensure the handbook explicitly defines these levels:

```md
- `L1`：操作员可直接处理
- `L2`：`tenant_admin` 可处理
- `L3`：必须 `super_admin`
- `L4`：必须技术负责人 / 发布负责人联合处理
```

Expected: intervention authority is fixed before incident cards are written.

- [ ] **Step 3: Freeze weighting strategy**

Ensure the handbook explicitly states:

```md
- A 类为主火力：`Fulfillment / PO / 补号 / 错绑`
- B 类为辅助：`Store Sync / 外部平台 / 脏数据`
- C 类严格受控：`Finance / 重算 / adjustment / 入账`
```

Expected: the manual no longer treats all incident domains equally.

- [ ] **Step 4: Add incident-card template**

Each incident card in the handbook must include these fields:

```md
- 触发条件
- 用户可见症状
- 系统自动处理
- 人工处理动作
- 处理权限级别
- 确认人
- 审计要求
- 后置验证
- 禁止动作
- 是否阻断上线
```

Expected: the manual is usable by real operators during incidents.

- [ ] **Step 5: Review handbook consistency with existing docs**

Manually verify `/d/小黑erp/21_异常处理与人工介入手册.md` with this checklist:

```text
1. 是否以 Fulfillment 为主火力，而不是平均分配篇幅
2. 是否有 L1~L4 介入等级
3. 是否把 Task / ErrorCode / Audit 映射补齐
4. 是否区分可执行动作与禁止动作
5. 是否适用于上线当天值班而不只是日常说明
```

Expected: all five checks pass without placeholders.

- [ ] **Step 6: Update task board entry**

Append a new row after the current T39 row in `/d/小黑erp/01_任务看板.md`:

```md
| T40 | 补齐异常处理与人工介入手册 | `done` | 已产出 `21_异常处理与人工介入手册.md`，明确异常等级、人工介入权限、异常卡模板与高频异常速查表 | 下一轮进入程序实现准备 |
```

- [ ] **Step 7: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, append a new current-priority line after the existing items:

```md
6. 基于 `21_异常处理与人工介入手册.md` 明确异常等级、人工介入路径与值班处理规则，为程序实现准备扫清运行控制歧义
```

- [ ] **Step 8: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- 高频异常是否已经有统一分级、统一处理权限、统一审计要求和统一恢复动作
```

- [ ] **Step 9: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D039：异常处理与人工介入手册采用“A 主、B 辅、C 严控”结构

- 决策：异常处理与人工介入手册采用 A 类主手册（Fulfillment / PO / 补号 / 错绑）、B 类辅助手册（Store Sync / 外部平台 / 脏数据）、C 类严格手册（Finance）的结构，而不平均分配篇幅
- 原因：真正高频、强体感、最影响日常运营的是履约主链异常；财务异常虽然重要，但频率更低、权限更高、动作更严，不应抢走第一版手册的主火力
- 影响：后续值班手册、人工介入设计、任务中心恢复动作与异常培训应优先围绕 A 类异常建设
```

Also append:

```md
### D040：人工介入权限冻结为 L1~L4 四级

- 决策：人工介入权限固定为 L1 操作员、L2 tenant_admin、L3 super_admin、L4 技术负责人/发布负责人联合处理
- 原因：如果不先冻结介入等级，异常手册最终会退化成“谁都能看、谁都不敢动”的说明文档
- 影响：后续异常处理卡、恢复动作、后台权限、审计要求与上线应急处理都必须显式绑定 L1~L4 级别
```

- [ ] **Step 10: Commit the handbook planning update**

Run:

```bash
git -C "/d/小黑erp" add "21_异常处理与人工介入手册.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add exception handling and manual intervention handbook

Document the ERP exception-handling handbook with intervention levels,
operational ownership, and incident cards weighted toward fulfillment incidents.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare implementation handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T40 is:

```md
下一轮开始程序实现准备
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after this handbook, the document-governance phase is effectively sufficient to enter implementation preparation.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align handbook-to-implementation handoff

Refine the ERP planning handoff so the next round moves from document
governance into implementation preparation.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
