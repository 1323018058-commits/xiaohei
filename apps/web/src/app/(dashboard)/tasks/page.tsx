"use client";

import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type TaskListResponse = components["schemas"]["TaskListResponse"];
type TaskSummary = TaskListResponse["tasks"][number];
type TaskRunDetail = components["schemas"]["TaskRunDetail"];
type TaskEventListResponse = components["schemas"]["TaskEventListResponse"];
type TaskEvent = TaskEventListResponse["events"][number];
type TaskStatusFilter =
  | "all"
  | "queued"
  | "running"
  | "waiting_retry"
  | "manual_intervention"
  | "failed_group"
  | "cancelled"
  | "succeeded";

type WebhookTaskMeta = {
  eventType: string | null;
  deliveryId: string | null;
  applyStatus: string | null;
  storeId: string | null;
  listingSku: string | null;
  listingId: string | null;
  payloadSummary: Record<string, unknown> | null;
};

type TaskHintTone = "neutral" | "info" | "warning" | "danger";

type TaskActionHint = {
  title: string;
  body: string;
  tone: TaskHintTone;
};

const TASK_STATUS_FILTERS: { label: string; value: TaskStatusFilter }[] = [
  { label: "全部", value: "all" },
  { label: "排队中", value: "queued" },
  { label: "执行中", value: "running" },
  { label: "等待重试", value: "waiting_retry" },
  { label: "人工介入", value: "manual_intervention" },
  { label: "失败组", value: "failed_group" },
  { label: "已取消", value: "cancelled" },
  { label: "已完成", value: "succeeded" },
];

const RETRYABLE_STATUSES = new Set([
  "waiting_retry",
  "failed",
  "failed_retryable",
  "failed_final",
  "partial",
  "dead_letter",
  "timed_out",
  "manual_intervention",
  "cancelled",
]);

const CANCELLABLE_STATUSES = new Set([
  "created",
  "queued",
  "leased",
  "running",
  "waiting_dependency",
  "waiting_retry",
  "failed_retryable",
  "manual_intervention",
]);

export default function TasksPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskRunDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [errorMessage, setErrorMessage] = useState("");
  const [successMessage, setSuccessMessage] = useState("");
  const [statusFilter, setStatusFilter] = useState<TaskStatusFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [mutatingTaskId, setMutatingTaskId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    void loadTasks();
  }, []);

  async function loadTasks(targetTaskId?: string, nextStatusFilter = statusFilter) {
    setErrorMessage("");
    setIsLoading(true);
    try {
      const params = new URLSearchParams();
      if (nextStatusFilter !== "all" && nextStatusFilter !== "failed_group") {
        params.set("status", nextStatusFilter);
      }
      const suffix = params.size > 0 ? `?${params.toString()}` : "";
      const taskData = await apiFetch<TaskListResponse>(`/api/tasks${suffix}`);
      const nextTasks =
        nextStatusFilter === "failed_group"
          ? taskData.tasks.filter((task) => isFailedTaskStatus(task.status))
          : taskData.tasks;
      setTasks(nextTasks);

      const nextTaskId = targetTaskId ?? selectedTask?.task_id ?? nextTasks[0]?.task_id;
      if (nextTaskId && nextTasks.some((task) => task.task_id === nextTaskId)) {
        await loadTaskDetail(nextTaskId);
      } else {
        setSelectedTask(null);
        setEvents([]);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载任务失败");
    } finally {
      setIsLoading(false);
    }
  }

  async function loadTaskDetail(taskId: string) {
    setErrorMessage("");
    try {
      const [detail, eventData] = await Promise.all([
        apiFetch<TaskRunDetail>(`/api/tasks/${taskId}`),
        apiFetch<TaskEventListResponse>(`/api/tasks/${taskId}/events`),
      ]);
      setSelectedTask(detail);
      setEvents(eventData.events);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载任务详情失败");
    }
  }

  async function retryTaskNow(taskId: string) {
    setErrorMessage("");
    setSuccessMessage("");
    setMutatingTaskId(taskId);
    try {
      const detail = await apiFetch<TaskRunDetail>(`/api/tasks/${taskId}/retry-now`, {
        method: "POST",
        body: JSON.stringify({ reason: "任务中心手动重试" }),
      });
      setSelectedTask(detail);
      setSuccessMessage("任务已重新入队。");
      await loadTasks(taskId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "手动重试失败");
    } finally {
      setMutatingTaskId(null);
    }
  }

  async function cancelTask(taskId: string) {
    setErrorMessage("");
    setSuccessMessage("");
    setMutatingTaskId(taskId);
    try {
      const detail = await apiFetch<TaskRunDetail>(`/api/tasks/${taskId}/cancel`, {
        method: "POST",
        body: JSON.stringify({ reason: "任务中心手动取消" }),
      });
      setSelectedTask(detail);
      setSuccessMessage("任务已取消。");
      await loadTasks(taskId);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "取消任务失败");
    } finally {
      setMutatingTaskId(null);
    }
  }

  async function copyTaskError(task: TaskRunDetail) {
    const payload = {
      task_id: task.task_id,
      task_type: task.task_type,
      status: task.status,
      stage: task.stage,
      error_code: task.error_code,
      error_msg: task.error_msg,
      error_details: task.error_details,
      request_id: task.request_id,
    };
    try {
      await navigator.clipboard.writeText(JSON.stringify(payload, null, 2));
      setSuccessMessage("错误详情已复制。");
    } catch {
      setErrorMessage("当前浏览器无法写入剪贴板。");
    }
  }

  function changeStatusFilter(nextStatusFilter: TaskStatusFilter) {
    setStatusFilter(nextStatusFilter);
    void loadTasks(undefined, nextStatusFilter);
  }

  const visibleTasks = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();
    if (!keyword) return tasks;
    return tasks.filter((task) => {
      const text = [
        task.task_id,
        task.task_type,
        task.domain,
        task.status,
        task.stage,
        task.error_code,
        task.error_msg,
        getTaskMetaValue(task.ui_meta, "label"),
        getTaskMetaValue(task.ui_meta, "next_action"),
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return text.includes(keyword);
    });
  }, [searchText, tasks]);

  const activeCount = useMemo(
    () => tasks.filter((task) => ["queued", "leased", "running", "waiting_retry"].includes(task.status)).length,
    [tasks],
  );
  const failedCount = useMemo(() => tasks.filter((task) => isFailedTaskStatus(task.status)).length, [tasks]);
  const retryCount = useMemo(() => tasks.filter((task) => task.status === "waiting_retry").length, [tasks]);
  const manualCount = useMemo(
    () => tasks.filter((task) => task.status === "manual_intervention").length,
    [tasks],
  );

  return (
    <div style={pageStyle}>
      <section style={heroStyle}>
        <div style={{ display: "grid", gap: 10 }}>
          <div style={eyebrowStyle}>任务中心 / 值班台</div>
          <h1 style={heroTitleStyle}>任务中心</h1>
          <p style={heroCopyStyle}>
            统一查看同步、校验、上架、重试和人工介入任务。页内口径已对齐异常手册：先看状态，再看错误码，最后才决定重试或取消。
          </p>
        </div>

        <div style={heroMetricsStyle}>
          <MetricCard label="任务总数" value={String(tasks.length)} />
          <MetricCard label="活动中" value={String(activeCount)} tone={activeCount ? "info" : "neutral"} />
          <MetricCard label="等待重试" value={String(retryCount)} tone={retryCount ? "warning" : "neutral"} />
          <MetricCard label="人工介入" value={String(manualCount)} tone={manualCount ? "warning" : "neutral"} />
          <MetricCard label="失败组" value={String(failedCount)} tone={failedCount ? "danger" : "neutral"} />
        </div>
      </section>

      {errorMessage ? <div style={errorBannerStyle}>{errorMessage}</div> : null}
      {successMessage ? <div style={successBannerStyle}>{successMessage}</div> : null}

      <section style={workspaceStyle}>
        <aside style={listPanelStyle}>
          <div style={sectionHeaderStyle}>
            <div>
              <div style={sectionTitleStyle}>任务列表</div>
              <div style={mutedTextStyle}>{isLoading ? "正在刷新..." : `共 ${visibleTasks.length} 条结果`}</div>
            </div>
            <button
              type="button"
              style={primaryButtonStyle}
              onClick={() => void loadTasks(selectedTask?.task_id)}
            >
              刷新
            </button>
          </div>

          <div style={controlBarStyle}>
            <input
              value={searchText}
              onChange={(event) => setSearchText(event.target.value)}
              placeholder="搜索任务类型 / 错误码 / 标签"
              style={searchInputStyle}
            />
            <div style={filterRowStyle}>
              {TASK_STATUS_FILTERS.map((filter) => (
                <button
                  key={filter.value}
                  type="button"
                  style={filterButtonStyle(statusFilter === filter.value)}
                  onClick={() => changeStatusFilter(filter.value)}
                >
                  {filter.label}
                </button>
              ))}
            </div>
          </div>

          <div style={briefPanelStyle}>
            <BriefHint
              title="值班顺序"
              body="先看 waiting_retry / manual_intervention，再看 failed_group；只有 tenant_admin 与 super_admin 才能执行任务重试或取消。"
            />
          </div>

          <div style={listBodyStyle}>
            {visibleTasks.map((task) => (
              <button
                key={task.task_id}
                type="button"
                style={taskCardStyle(selectedTask?.task_id === task.task_id)}
                onClick={() => void loadTaskDetail(task.task_id)}
              >
                <div style={taskCardHeaderStyle}>
                  <strong style={taskTitleStyle}>{getTaskMetaValue(task.ui_meta, "label") ?? task.task_type}</strong>
                  <span style={statusPillStyle(task.status)}>{formatTaskStatus(task.status)}</span>
                </div>
                <div style={taskMetaStyle}>
                  <span>{formatTaskStage(task.stage)}</span>
                  <span>·</span>
                  <span>{formatDomain(task.domain)}</span>
                </div>
                <div style={chipRowStyle}>
                  <span style={softChipStyle}>{task.task_type}</span>
                  {task.error_code ? <span style={warningChipStyle}>{task.error_code}</span> : null}
                  {task.retryable ? <span style={infoChipStyle}>可重试</span> : null}
                </div>
                <RetryTaskBrief task={task} />
                <WebhookTaskBrief uiMeta={task.ui_meta} />
                <ProgressBar value={task.progress_percent ?? 0} />
              </button>
            ))}
            {!isLoading && visibleTasks.length === 0 ? <div style={emptyStateStyle}>当前筛选下没有任务。</div> : null}
          </div>
        </aside>

        <main style={detailPanelStyle}>
          {selectedTask ? (
            <TaskDetailPanel
              task={selectedTask}
              events={events}
              isMutating={mutatingTaskId === selectedTask.task_id}
              onRetryNow={retryTaskNow}
              onCancelTask={cancelTask}
              onCopyError={copyTaskError}
            />
          ) : (
            <div style={emptyStateStyle}>选择一条任务查看状态、错误码、事件和恢复建议。</div>
          )}
        </main>
      </section>
    </div>
  );
}

function TaskDetailPanel({
  task,
  events,
  isMutating,
  onRetryNow,
  onCancelTask,
  onCopyError,
}: {
  task: TaskRunDetail;
  events: TaskEvent[];
  isMutating: boolean;
  onRetryNow: (taskId: string) => void | Promise<void>;
  onCancelTask: (taskId: string) => void | Promise<void>;
  onCopyError: (task: TaskRunDetail) => void | Promise<void>;
}) {
  const webhookMeta = getWebhookMeta(task.ui_meta);
  const actionHint = getTaskActionHint(task);
  const retryDisabled = isMutating || !canRetryTask(task.status);
  const cancelDisabled = isMutating || !canCancelTask(task.status);
  const copyDisabled = isMutating || !hasTaskError(task);

  return (
    <div style={{ display: "grid", gap: 18 }}>
      <div style={sectionHeaderStyle}>
        <div style={{ display: "grid", gap: 8 }}>
          <div style={eyebrowStyle}>{task.task_type}</div>
          <div style={detailTitleStyle}>{getTaskMetaValue(task.ui_meta, "label") ?? task.task_type}</div>
          <div style={mutedTextStyle}>
            {formatTaskStatus(task.status)} · {formatTaskStage(task.stage)} · queue={task.queue_name}
          </div>
        </div>
        <span style={statusPillStyle(task.status)}>{formatTaskStatus(task.status)}</span>
      </div>

      <div style={actionRowStyle}>
        <button
          type="button"
          style={secondaryButtonStyle(retryDisabled)}
          disabled={retryDisabled}
          onClick={() => void onRetryNow(task.task_id)}
        >
          {isMutating ? "处理中..." : "立即重试"}
        </button>
        <button
          type="button"
          style={dangerButtonStyle(cancelDisabled)}
          disabled={cancelDisabled}
          onClick={() => void onCancelTask(task.task_id)}
        >
          取消任务
        </button>
        <button
          type="button"
          style={ghostButtonStyle(copyDisabled)}
          disabled={copyDisabled}
          onClick={() => void onCopyError(task)}
        >
          复制错误
        </button>
      </div>

      <HintPanel hint={actionHint} />

      <div style={metricsGridStyle}>
        <Property label="进度" value={`${Math.round(task.progress_percent ?? 0)}%`} />
        <Property label="尝试次数" value={`${task.attempt_count}/${task.max_retries}`} />
        <Property label="下一次重试" value={formatDateTime(task.next_retry_at)} />
        <Property label="可重试" value={task.retryable ? "是" : "否"} />
        <Property label="租户 / 店铺" value={[task.tenant_id ?? "--", task.store_id ?? "--"].join(" / ")} />
        <Property label="请求链路" value={task.request_id} />
      </div>

      {task.status === "waiting_retry" || task.next_retry_at ? <RetrySignalPanel task={task} /> : null}
      {webhookMeta ? <WebhookSignalPanel meta={webhookMeta} task={task} /> : null}

      <div style={panelStyle}>
        <div style={sectionHeaderStyle}>
          <div>
            <div style={subSectionTitleStyle}>下一步动作</div>
            <div style={mutedTextStyle}>从 `ui_meta.next_action` 和当前状态综合判断。</div>
          </div>
        </div>
        <div style={panelCopyStyle}>{getTaskMetaValue(task.ui_meta, "next_action") ?? "当前没有附加建议。"}</div>
        <ProgressBar value={task.progress_percent ?? 0} />
      </div>

      {task.error_code || task.error_msg || task.error_details ? (
        <div style={errorPanelStyle}>
          <div style={subSectionTitleStyle}>错误与排障</div>
          <div style={metricsGridStyle}>
            <Property label="错误码" value={task.error_code ?? "--"} />
            <Property label="错误摘要" value={task.error_msg ?? "--"} />
          </div>
          {task.error_details ? <JsonBlock value={task.error_details} /> : null}
        </div>
      ) : null}

      <div style={panelStyle}>
        <div style={sectionHeaderStyle}>
          <div>
            <div style={subSectionTitleStyle}>最近事件</div>
            <div style={mutedTextStyle}>按时间倒序展示 worker、API 和调度器留下的轨迹。</div>
          </div>
          <span style={mutedTextStyle}>{events.length} 条</span>
        </div>
        <div style={eventListStyle}>
          {events.map((event) => (
            <EventRow key={event.event_id} event={event} />
          ))}
          {events.length === 0 ? <div style={emptyStateStyle}>当前任务还没有事件记录。</div> : null}
        </div>
      </div>
    </div>
  );
}

function BriefHint({ title, body }: { title: string; body: string }) {
  return (
    <div style={smallHintCardStyle}>
      <div style={smallHintTitleStyle}>{title}</div>
      <div style={smallHintBodyStyle}>{body}</div>
    </div>
  );
}

function HintPanel({ hint }: { hint: TaskActionHint }) {
  return (
    <div style={hintPanelStyle(hint.tone)}>
      <div style={subSectionTitleStyle}>{hint.title}</div>
      <div style={panelCopyStyle}>{hint.body}</div>
    </div>
  );
}

function RetryTaskBrief({ task }: { task: TaskSummary }) {
  if (task.status !== "waiting_retry" && !task.next_retry_at) return null;
  return (
    <div style={retryBriefStyle}>
      <span>
        第 {task.attempt_count}/{task.max_retries} 次
      </span>
      <span>{formatRetryCountdown(task.next_retry_at)}</span>
    </div>
  );
}

function RetrySignalPanel({ task }: { task: TaskRunDetail }) {
  return (
    <div style={retryPanelStyle}>
      <div style={sectionHeaderStyle}>
        <div>
          <div style={subSectionTitleStyle}>自动重试窗口</div>
          <div style={mutedTextStyle}>先观察自动恢复，再决定是否手动重试。</div>
        </div>
        <span style={retryBadgeStyle}>{formatRetryCountdown(task.next_retry_at)}</span>
      </div>
      <div style={metricsGridStyle}>
        <Property label="下一次尝试" value={formatDateTime(task.next_retry_at)} />
        <Property label="当前预算" value={`${task.attempt_count}/${task.max_retries}`} />
        <Property label="错误码" value={task.error_code ?? "--"} />
        <Property label="租约持有者" value={task.lease_owner ?? "已释放"} />
      </div>
    </div>
  );
}

function WebhookTaskBrief({ uiMeta }: { uiMeta: TaskSummary["ui_meta"] }) {
  const webhookMeta = getWebhookMeta(uiMeta);
  if (!webhookMeta) return null;
  return (
    <div style={chipRowStyle}>
      {webhookMeta.eventType ? <span style={softChipStyle}>{webhookMeta.eventType}</span> : null}
      {webhookMeta.deliveryId ? <span style={softChipStyle}>delivery {webhookMeta.deliveryId}</span> : null}
      {webhookMeta.applyStatus ? (
        <span style={applyStatusChipStyle(webhookMeta.applyStatus)}>{webhookMeta.applyStatus}</span>
      ) : null}
    </div>
  );
}

function WebhookSignalPanel({ meta, task }: { meta: WebhookTaskMeta; task: TaskRunDetail }) {
  return (
    <div style={panelStyle}>
      <div style={sectionHeaderStyle}>
        <div>
          <div style={subSectionTitleStyle}>Takealot Webhook</div>
          <div style={mutedTextStyle}>用于核对 delivery id、映射店铺和应用结果。</div>
        </div>
        <span style={applyStatusChipStyle(meta.applyStatus ?? task.stage)}>{meta.applyStatus ?? task.stage}</span>
      </div>
      <div style={metricsGridStyle}>
        <Property label="事件类型" value={meta.eventType ?? "--"} />
        <Property label="Delivery ID" value={meta.deliveryId ?? task.request_id} />
        <Property label="映射店铺" value={meta.storeId ?? task.store_id ?? "--"} />
        <Property label="Listing" value={meta.listingSku ?? meta.listingId ?? "--"} />
      </div>
      <div style={panelCopyStyle}>{formatPayloadSummary(meta.payloadSummary)}</div>
    </div>
  );
}

function EventRow({ event }: { event: TaskEvent }) {
  return (
    <div style={eventRowStyle}>
      <div style={taskCardHeaderStyle}>
        <strong style={taskTitleStyle}>{formatEventType(event.event_type)}</strong>
        <span style={mutedTextStyle}>{formatDateTime(event.created_at)}</span>
      </div>
      <div style={panelCopyStyle}>{event.message || "无附加说明"}</div>
      <div style={chipRowStyle}>
        <span style={softChipStyle}>{event.stage ?? "未标记阶段"}</span>
        <span style={softChipStyle}>
          {event.source}
          {event.source_id ? ` · ${event.source_id}` : ""}
        </span>
      </div>
      {event.details ? <JsonBlock value={event.details} /> : null}
    </div>
  );
}

function MetricCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: TaskHintTone;
}) {
  return (
    <div style={metricCardStyle(tone)}>
      <span style={metricLabelStyle}>{label}</span>
      <strong style={metricValueStyle}>{value}</strong>
    </div>
  );
}

function Property({ label, value }: { label: string; value: string }) {
  return (
    <div style={propertyCardStyle}>
      <span style={metricLabelStyle}>{label}</span>
      <span style={propertyValueStyle}>{value}</span>
    </div>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return <pre style={jsonBlockStyle}>{JSON.stringify(value, null, 2)}</pre>;
}

function ProgressBar({ value }: { value: number }) {
  const normalizedValue = Math.max(0, Math.min(100, value));
  return (
    <div style={progressTrackStyle}>
      <div style={{ ...progressFillStyle, width: `${normalizedValue}%` }} />
    </div>
  );
}

function getTaskActionHint(task: TaskRunDetail): TaskActionHint {
  const code = task.error_code ?? "";
  if (code === "STORE_AUTH_FAILED") {
    return {
      title: "先修凭证，不先硬重试",
      body: "这类任务通常不是平台临时波动，而是店铺凭证不可用。先到店铺管理更新 Key / Secret，再做一次受控重试。",
      tone: "warning",
    };
  }
  if (code === "LISTING_BARCODE_MISSING") {
    return {
      title: "先补条码 / GTIN",
      body: "上架 worker 无法在缺少 barcode 的情况下继续走官方创建报价路径。先补齐条码，再手动重试。",
      tone: "warning",
    };
  }
  if (code === "LISTING_SELLING_PRICE_MISSING") {
    return {
      title: "先补售价",
      body: "当前任务缺少售价，重复重试不会自愈。先确认利润预览和 list-now 输入，再重新入队。",
      tone: "warning",
    };
  }
  if (code === "FINANCE_SNAPSHOT_STALE") {
    return {
      title: "走受控重算",
      body: "财务快照过期不应手工改表，需由 super_admin 触发任务化重算，并保留审计链路。",
      tone: "danger",
    };
  }
  if (task.status === "manual_intervention") {
    return {
      title: "先看错误码和最近事件",
      body: "人工介入态不是立刻点击重试，而是先判断是缺输入、平台抖动还是对象关系问题，再决定是否恢复。",
      tone: "warning",
    };
  }
  if (task.status === "waiting_retry") {
    return {
      title: "优先等待自动重试",
      body: "系统已经安排下一次尝试。若没有新的业务输入变化，先观察 `next_retry_at`，避免人工连续重试打爆平台。",
      tone: "info",
    };
  }
  if (task.status === "queued") {
    return {
      title: "排队中，先不要重复提交",
      body: "排队中表示任务已经创建，但还没被 Worker 领取。本地无数据库模式由 API 内置 Worker 自动消费；正式或数据库部署才需要独立运行 `npm run worker:api`。不要重复点击同步商品。",
      tone: "info",
    };
  }
  if (task.status === "dead_letter") {
    return {
      title: "死信需升级",
      body: "死信说明自动恢复预算已耗尽。优先升级给 tenant_admin / super_admin 复核，不建议一线直接处理。",
      tone: "danger",
    };
  }
  return {
    title: "按标准顺序处理",
    body: "先看 status/stage，再看 error_code，再看 recent events；只有确定条件满足后，才执行重试或取消。",
    tone: "neutral",
  };
}

function getTaskMetaValue(uiMeta: unknown, key: string): string | null {
  if (!uiMeta || typeof uiMeta !== "object") return null;
  const value = (uiMeta as Record<string, unknown>)[key];
  if (typeof value === "string" && value.trim()) return value;
  return null;
}

function getWebhookMeta(uiMeta: unknown): WebhookTaskMeta | null {
  if (!uiMeta || typeof uiMeta !== "object") return null;
  const meta = uiMeta as Record<string, unknown>;
  const eventType = getStringMeta(meta, "webhook_event_type");
  const deliveryId = getStringMeta(meta, "webhook_delivery_id");
  const applyStatus = getStringMeta(meta, "webhook_apply_status");
  const payloadSummary = getObjectMeta(meta, "webhook_payload_summary");
  if (!eventType && !deliveryId && !applyStatus && !payloadSummary) return null;
  return {
    eventType,
    deliveryId,
    applyStatus,
    storeId: getStringMeta(meta, "webhook_store_id"),
    listingSku: getStringMeta(meta, "webhook_listing_sku"),
    listingId: getStringMeta(meta, "webhook_listing_id"),
    payloadSummary,
  };
}

function getStringMeta(meta: Record<string, unknown>, key: string): string | null {
  const value = meta[key];
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return null;
}

function getObjectMeta(meta: Record<string, unknown>, key: string): Record<string, unknown> | null {
  const value = meta[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function formatPayloadSummary(summary: Record<string, unknown> | null) {
  if (!summary) return "暂无 payload 摘要。";
  const entries = Object.entries(summary);
  if (!entries.length) return "payload 摘要为空。";
  return entries
    .map(([key, value]) => `${key}: ${Array.isArray(value) ? value.join(", ") : String(value)}`)
    .join(" · ");
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}

function formatRetryCountdown(value: string | null | undefined) {
  if (!value) return "等待中";
  const retryAt = new Date(value);
  if (Number.isNaN(retryAt.getTime())) return value;
  const seconds = Math.ceil((retryAt.getTime() - Date.now()) / 1000);
  if (seconds <= 0) return "现在可重试";
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  return `${Math.ceil(minutes / 60)}h`;
}

function isFailedTaskStatus(status: string) {
  return ["failed", "failed_final", "dead_letter", "timed_out"].includes(status);
}

function canRetryTask(status: string) {
  return RETRYABLE_STATUSES.has(status);
}

function canCancelTask(status: string) {
  return CANCELLABLE_STATUSES.has(status);
}

function hasTaskError(task: TaskRunDetail) {
  return Boolean(task.error_code || task.error_msg || task.error_details);
}

function formatTaskStatus(status: string) {
  const labels: Record<string, string> = {
    created: "已创建",
    queued: "排队中",
    leased: "已领取",
    running: "执行中",
    waiting_dependency: "等待依赖",
    waiting_retry: "等待重试",
    cancel_requested: "取消中",
    cancelled: "已取消",
    succeeded: "已完成",
    failed: "失败",
    failed_retryable: "可重试失败",
    failed_final: "最终失败",
    dead_letter: "死信",
    manual_intervention: "人工介入",
    timed_out: "超时",
    quarantined: "已隔离",
    partial: "部分成功",
  };
  return labels[status] ?? status;
}

function formatTaskStage(stage: string | null | undefined) {
  if (!stage) return "未标记阶段";
  const labels: Record<string, string> = {
    queued: "排队",
    running: "执行",
    waiting_retry: "等待重试",
    failed: "失败",
    completed: "完成",
    cancelled: "取消",
    manual_intervention: "人工介入",
    waiting_listing_worker: "等待上架 worker",
    prepared: "已准备提交",
  };
  return labels[stage] ?? stage;
}

function formatDomain(domain: string) {
  const labels: Record<string, string> = {
    store: "店铺",
    listing: "上架",
    bidding: "竞价",
    auth: "鉴权",
    order: "订单",
    webhook: "Webhook",
    finance: "财务",
  };
  return labels[domain] ?? domain;
}

function formatEventType(eventType: string) {
  const labels: Record<string, string> = {
    "task.created": "任务创建",
    "task.queued": "已入队",
    "task.leased": "worker 领取",
    "task.started": "开始执行",
    "task.progress": "进度更新",
    "task.stage.changed": "阶段变化",
    "task.retry_scheduled": "已安排重试",
    "task.retry_requested": "人工请求重试",
    "task.cancelled": "任务已取消",
    "task.manual_intervention": "转人工介入",
    "task.succeeded": "任务成功",
    "task.failed.final": "最终失败",
    "task.quarantined": "任务隔离",
    "webhook.received": "Webhook 已接收",
  };
  return labels[eventType] ?? eventType;
}

function statusPillStyle(status: string): CSSProperties {
  const isDanger = isFailedTaskStatus(status) || status === "quarantined";
  return {
    border: "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "6px 10px",
    fontSize: 12,
    fontWeight: 800,
    background: "#FFFFFF",
    color: isDanger ? "#D9363E" : "#000000",
  };
}

function taskCardStyle(active: boolean): CSSProperties {
  return {
    border: active ? "1px solid #000000" : "1px solid #EBEBEB",
    borderRadius: 6,
    padding: 14,
    background: "#ffffff",
    display: "grid",
    gap: 8,
    textAlign: "left",
    cursor: "pointer",
    boxShadow: "none",
    transition: "border-color 160ms ease, box-shadow 160ms ease",
  };
}

function metricCardStyle(tone: TaskHintTone): CSSProperties {
  return {
    borderRadius: 6,
    padding: 14,
    background: "#FFFFFF",
    border: "1px solid #EBEBEB",
    color: tone === "danger" ? "#D9363E" : "#000000",
    display: "grid",
    gap: 4,
  };
}

function applyStatusChipStyle(status: string): CSSProperties {
  return {
    ...softChipStyle,
    background: "#FFFFFF",
    color: ["needs_mapping", "store_mapping_missing"].includes(status) ? "#D9363E" : "#000000",
  };
}

function hintPanelStyle(tone: TaskHintTone): CSSProperties {
  return {
    borderRadius: 6,
    padding: 16,
    display: "grid",
    gap: 8,
    background: "#FFFFFF",
    border: "1px solid #EBEBEB",
    color: tone === "danger" ? "#D9363E" : "#000000",
  };
}

const pageStyle: CSSProperties = {
  minHeight: "calc(100vh - 136px)",
  display: "grid",
  gap: 18,
  color: "#1d1d1f",
  fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "Segoe UI", sans-serif',
};

const heroStyle: CSSProperties = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 20,
  background: "#FFFFFF",
  boxShadow: "none",
  display: "grid",
  gap: 18,
};

const heroTitleStyle: CSSProperties = {
  margin: 0,
  fontSize: 42,
  lineHeight: 1.05,
  letterSpacing: "-0.04em",
};

const heroCopyStyle: CSSProperties = {
  margin: 0,
  maxWidth: 760,
  color: "#6e6e73",
  fontSize: 16,
  lineHeight: 1.7,
};

const heroMetricsStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(5, minmax(0, 1fr))",
  gap: 10,
};

const workspaceStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "360px minmax(0, 1fr)",
  gap: 18,
  alignItems: "start",
};

const listPanelStyle: CSSProperties = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: 20,
  background: "#FFFFFF",
  boxShadow: "none",
  display: "grid",
  gap: 16,
};

const detailPanelStyle: CSSProperties = {
  ...listPanelStyle,
  padding: 24,
};

const sectionHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "flex-start",
  gap: 14,
};

const sectionTitleStyle: CSSProperties = {
  fontSize: 22,
  fontWeight: 900,
  letterSpacing: "-0.03em",
};

const detailTitleStyle: CSSProperties = {
  fontSize: 28,
  fontWeight: 900,
  letterSpacing: "-0.04em",
};

const subSectionTitleStyle: CSSProperties = {
  fontSize: 15,
  fontWeight: 800,
};

const eyebrowStyle: CSSProperties = {
  color: "#595959",
  fontSize: 12,
  fontWeight: 800,
  letterSpacing: "0.1em",
  textTransform: "uppercase",
};

const mutedTextStyle: CSSProperties = {
  color: "#6e6e73",
  fontSize: 13,
};

const controlBarStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};

const searchInputStyle: CSSProperties = {
  width: "100%",
  height: 38,
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#ffffff",
  padding: "0 14px",
  fontSize: 13,
  outline: "none",
};

const filterRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 8,
};

function filterButtonStyle(active: boolean): CSSProperties {
  return {
    border: active ? "1px solid #000000" : "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "8px 11px",
    background: active ? "#000000" : "#ffffff",
    color: active ? "#FFFFFF" : "#595959",
    cursor: "pointer",
    fontSize: 12,
    fontWeight: 850,
  };
}

const briefPanelStyle: CSSProperties = {
  display: "grid",
  gap: 8,
};

const smallHintCardStyle: CSSProperties = {
  borderRadius: 6,
  padding: 14,
  background: "#FAFAFA",
  border: "1px solid #EBEBEB",
  display: "grid",
  gap: 6,
};

const smallHintTitleStyle: CSSProperties = {
  fontSize: 13,
  fontWeight: 800,
};

const smallHintBodyStyle: CSSProperties = {
  color: "#475569",
  fontSize: 12,
  lineHeight: 1.6,
};

const listBodyStyle: CSSProperties = {
  display: "grid",
  gap: 10,
  maxHeight: "calc(100vh - 360px)",
  overflow: "auto",
  paddingRight: 4,
};

const taskCardHeaderStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 12,
  alignItems: "center",
};

const taskTitleStyle: CSSProperties = {
  fontSize: 14,
  lineHeight: 1.45,
};

const taskMetaStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
  color: "#6e6e73",
  fontSize: 12,
};

const chipRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 6,
};

const softChipStyle: CSSProperties = {
  border: "1px solid #EBEBEB",
  borderRadius: 6,
  padding: "5px 8px",
  background: "#FFFFFF",
  color: "#595959",
  fontSize: 11,
  fontWeight: 800,
  maxWidth: "100%",
};

const warningChipStyle: CSSProperties = {
  ...softChipStyle,
  background: "#FFFFFF",
  color: "#D9363E",
};

const infoChipStyle: CSSProperties = {
  ...softChipStyle,
  background: "#FFFFFF",
  color: "#000000",
};

const actionRowStyle: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 10,
  alignItems: "center",
  padding: 12,
  borderRadius: 6,
  background: "#FAFAFA",
  border: "1px solid #EBEBEB",
};

const metricsGridStyle: CSSProperties = {
  display: "grid",
  gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
  gap: 12,
};

const propertyCardStyle: CSSProperties = {
  borderRadius: 6,
  padding: 13,
  display: "grid",
  gap: 5,
  background: "#ffffff",
  border: "1px solid #EBEBEB",
};

const metricLabelStyle: CSSProperties = {
  color: "#86868b",
  fontSize: 12,
  fontWeight: 700,
};

const metricValueStyle: CSSProperties = {
  fontSize: 24,
  letterSpacing: "-0.03em",
};

const propertyValueStyle: CSSProperties = {
  color: "#1d1d1f",
  fontSize: 13,
  fontWeight: 700,
  wordBreak: "break-word",
};

const panelStyle: CSSProperties = {
  borderRadius: 6,
  padding: 16,
  display: "grid",
  gap: 14,
  background: "#FAFAFA",
  border: "1px solid #EBEBEB",
};

const retryPanelStyle: CSSProperties = {
  ...panelStyle,
  background: "#FFFFFF",
  border: "1px solid #EBEBEB",
};

const retryBriefStyle: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  gap: 8,
  borderRadius: 6,
  padding: "8px 10px",
  background: "#FFFFFF",
  border: "1px solid #EBEBEB",
  color: "#595959",
  fontSize: 12,
  fontWeight: 800,
};

const retryBadgeStyle: CSSProperties = {
  borderRadius: 6,
  padding: "6px 10px",
  background: "#FFFFFF",
  border: "1px solid #EBEBEB",
  color: "#000000",
  fontSize: 12,
  fontWeight: 900,
};

const panelCopyStyle: CSSProperties = {
  color: "#475569",
  fontSize: 13,
  lineHeight: 1.65,
};

const errorPanelStyle: CSSProperties = {
  ...panelStyle,
  background: "#FFFFFF",
  border: "1px solid #EBEBEB",
  color: "#D9363E",
};

const eventListStyle: CSSProperties = {
  display: "grid",
  gap: 10,
};

const eventRowStyle: CSSProperties = {
  borderRadius: 6,
  padding: 13,
  display: "grid",
  gap: 8,
  background: "#ffffff",
  border: "1px solid #EBEBEB",
};

const jsonBlockStyle: CSSProperties = {
  margin: 0,
  borderRadius: 6,
  padding: 12,
  background: "#111111",
  color: "#f8fafc",
  overflowX: "auto",
  fontSize: 12,
  lineHeight: 1.55,
};

const progressTrackStyle: CSSProperties = {
  height: 8,
  borderRadius: 6,
  background: "#EBEBEB",
  overflow: "hidden",
};

const progressFillStyle: CSSProperties = {
  height: "100%",
  borderRadius: 6,
  background: "#000000",
};

const emptyStateStyle: CSSProperties = {
  border: "1px dashed #EBEBEB",
  borderRadius: 6,
  padding: 20,
  color: "#6e6e73",
  background: "#FFFFFF",
  textAlign: "center",
};

const errorBannerStyle: CSSProperties = {
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#FFFFFF",
  color: "#D9363E",
  padding: "13px 16px",
  fontSize: 14,
  fontWeight: 700,
};

const successBannerStyle: CSSProperties = {
  borderRadius: 6,
  border: "1px solid #EBEBEB",
  background: "#FFFFFF",
  color: "#000000",
  padding: "13px 16px",
  fontSize: 14,
  fontWeight: 800,
};

const primaryButtonStyle: CSSProperties = {
  border: "1px solid #000000",
  borderRadius: 6,
  padding: "10px 14px",
  background: "#000000",
  color: "#ffffff",
  cursor: "pointer",
  fontSize: 13,
  fontWeight: 800,
  boxShadow: "none",
};

function secondaryButtonStyle(disabled = false): CSSProperties {
  return {
    border: "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "10px 14px",
    background: disabled ? "#FAFAFA" : "#ffffff",
    color: disabled ? "#B3B3B3" : "#000000",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 13,
    fontWeight: 850,
  };
}

function dangerButtonStyle(disabled = false): CSSProperties {
  return {
    border: "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "10px 14px",
    background: disabled ? "#FAFAFA" : "#ffffff",
    color: disabled ? "#B3B3B3" : "#D9363E",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 13,
    fontWeight: 850,
  };
}

function ghostButtonStyle(disabled = false): CSSProperties {
  return {
    border: "1px solid #EBEBEB",
    borderRadius: 6,
    padding: "10px 14px",
    background: disabled ? "#FAFAFA" : "#FFFFFF",
    color: disabled ? "#B3B3B3" : "#595959",
    cursor: disabled ? "not-allowed" : "pointer",
    fontSize: 13,
    fontWeight: 850,
  };
}
