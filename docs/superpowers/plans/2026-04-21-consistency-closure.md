# Consistency Review and Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a cross-document consistency review master checklist that aligns the ERP API, schema, frontend, load-test, and launch-execution documents under one closure baseline.

**Architecture:** This plan does not add new business scope. It creates a cross-document control layer: version mapping, boundary checks, interface-schema mappings, interface-frontend mappings, task/error/audit consistency checks, pressure-test ↔ launch decision mapping, drift-risk tracking, and closure rules. The result is a hybrid audit checklist + mapping matrix document.

**Tech Stack:** Markdown docs, Git, existing ERP execution docs

---

### Task 1: Add consistency review and closure document

**Files:**
- Create: `/d/小黑erp/19_一致性复查与收口清单.md`
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`
- Modify: `/d/小黑erp/02_决策日志.md`

- [ ] **Step 1: Write the consistency-review document**

Create `/d/小黑erp/19_一致性复查与收口清单.md` with this structure:

```md
# 一致性复查与收口清单

## 1. 目标
## 2. 复查范围
## 3. 主版本映射表
## 4. P0/P1/P2 边界对照表
## 5. 接口 ↔ Schema 映射矩阵
## 6. 接口 ↔ 页面交互映射矩阵
## 7. 任务 / 错误码 / 审计一致性核对表
## 8. 压测 ↔ 上线门槛映射表
## 9. 已冻结关键点清单
## 10. 漂移风险清单
## 11. 收口动作规则
## 12. 结论口径
```

- [ ] **Step 2: Use hybrid style (checklist + matrix)**

Ensure the document contains both:

```md
- 对照矩阵（mapping tables）
- 勾选式核对项（checklist items）
```

Expected: the document supports both audit-style checking and architecture-style mapping.

- [ ] **Step 3: Keep key frozen boundaries visible**

Ensure the document explicitly rechecks these frozen points:

```md
- `Fulfillment` 双 Tab + 沉浸式打单 Dialog
- `Finance` 读侧优先 + 白名单重算 + 非默认全面 adjustment
- `Locust` 为唯一主压测工具
- 开关控制采用 `super_admin` 后台预置 + 发布负责人统一口头确认
```

Expected: the consistency-review doc becomes the place where frozen points are re-validated across documents.

- [ ] **Step 4: Review consistency-document quality**

Manually verify `/d/小黑erp/19_一致性复查与收口清单.md` with this checklist:

```text
1. 是否覆盖 API / Schema / 前端 / 压测 / 上线五条主线
2. 是否给出唯一主版本映射
3. 是否给出边界对照和映射矩阵
4. 是否列出具体漂移风险
5. 是否定义收口完成条件
```

Expected: all five checks pass without placeholders.

- [ ] **Step 5: Update task board entry**

Append a new row after the current T35 row in `/d/小黑erp/01_任务看板.md`:

```md
| T36 | 完成一致性复查与收口清单 | `done` | 已产出 `19_一致性复查与收口清单.md`，建立 API/Schema/页面/压测/上线的一致性总控基准 | 下一轮按清单逐项消除剩余漂移 |
```

- [ ] **Step 6: Update project context priority**

In `/d/小黑erp/00_项目上下文.md`, replace the current broad next-step emphasis with a closure-oriented note:

```md
1. 基于 `19_一致性复查与收口清单.md` 对 API、Schema、页面、压测、上线文档做整体一致性复查与收口
```

- [ ] **Step 7: Update project checkpoints**

Ensure `/d/小黑erp/00_项目上下文.md` includes this checkpoint concern:

```md
- API / Schema / 页面 / 压测 / 上线五条主线是否已经完成统一收口，并不存在明确冲突
```

- [ ] **Step 8: Update decision log**

Append a new decision entry to `/d/小黑erp/02_决策日志.md`:

```md
### D036：进入“整体一致性复查与收口”阶段

- 决策：在完成接口、DDL、页面、压测与上线细化文档后，下一阶段以一致性复查与收口为主，而不是继续横向扩展新文档
- 原因：当前风险已从“缺文档”转为“文档之间潜在漂移”，如果不先收口，后续实现阶段会在细节冲突处返工
- 影响：后续工作应优先依据 `19_一致性复查与收口清单.md` 逐项检查并收敛口径，再进入正式实现准备
```

- [ ] **Step 9: Commit the consistency-review update**

Run:

```bash
git -C "/d/小黑erp" add "19_一致性复查与收口清单.md" "00_项目上下文.md" "01_任务看板.md" "02_决策日志.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: add consistency review and closure checklist

Document the ERP cross-document consistency baseline so API, schema,
frontend, load-test, and launch docs can be reviewed and closed systematically.
EOF
)"
```

Expected: commit succeeds and creates a new documentation commit.

### Task 2: Prepare next planning handoff

**Files:**
- Modify: `/d/小黑erp/01_任务看板.md`
- Modify: `/d/小黑erp/00_项目上下文.md`

- [ ] **Step 1: Align next-step wording**

Update `/d/小黑erp/01_任务看板.md` next-step wording so the focus after T36 is:

```md
下一轮按清单逐项消除剩余漂移
```

- [ ] **Step 2: Align project context handoff**

Ensure `/d/小黑erp/00_项目上下文.md` highlights that after this document, the next valuable work is not adding scope but eliminating remaining inconsistencies.

- [ ] **Step 3: Commit the handoff refinement**

Run:

```bash
git -C "/d/小黑erp" add "00_项目上下文.md" "01_任务看板.md"
git -C "/d/小黑erp" commit -m "$(cat <<'EOF'
docs: align consistency-review handoff

Refine the ERP planning handoff so the next round focuses on closing
remaining cross-document drift rather than expanding scope.
EOF
)"
```

Expected: commit succeeds only if Task 2 introduced new diffs. If there are no diffs, skip this commit.
