"use client";

import { useEffect, useMemo, useState } from "react";
import {
  BellRing,
  CheckCircle2,
  Clock3,
  Filter,
  Inbox,
  PackageCheck,
  RefreshCcw,
  Search,
  ShieldAlert,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type TaskListResponse = components["schemas"]["TaskListResponse"];
type TaskRunDetail = components["schemas"]["TaskRunDetail"];
type TaskEventListResponse = components["schemas"]["TaskEventListResponse"];
type TaskSummary = TaskListResponse["tasks"][number];
type TaskEvent = TaskEventListResponse["events"][number];

type EventKindFilter = "all" | "offer" | "sale" | "leadtime" | "dropship" | "other";
type ResultFilter = "all" | "applied" | "pending" | "attention" | "stored";
type EventKind = Exclude<EventKindFilter, "all">;
type ResultKey = Exclude<ResultFilter, "all">;

type WebhookMeta = {
  deliveryId: string | null;
  eventType: string | null;
  applyStatus: string | null;
  storeId: string | null;
  listingSku: string | null;
  listingId: string | null;
  payloadSummary: Record<string, unknown> | null;
};

type PlatformEventRecord = {
  task: TaskSummary;
  meta: WebhookMeta;
  kind: EventKind;
  result: ResultKey;
};

const TAKEALOT_WEBHOOK_TASK_TYPE = "TAKEALOT_WEBHOOK_PROCESS";

const KIND_FILTERS: { value: EventKindFilter; label: string }[] = [
  { value: "all", label: "全部事件" },
  { value: "offer", label: "报价事件" },
  { value: "sale", label: "订单状态" },
  { value: "leadtime", label: "Leadtime" },
  { value: "dropship", label: "Dropship" },
  { value: "other", label: "其他" },
];

const RESULT_FILTERS: { value: ResultFilter; label: string }[] = [
  { value: "all", label: "全部结果" },
  { value: "applied", label: "已写入" },
  { value: "pending", label: "待处理" },
  { value: "attention", label: "需处理" },
  { value: "stored", label: "已留存" },
];

export default function WebhooksPage() {
  const [tasks, setTasks] = useState<TaskSummary[]>([]);
  const [selectedTask, setSelectedTask] = useState<TaskRunDetail | null>(null);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [kindFilter, setKindFilter] = useState<EventKindFilter>("all");
  const [resultFilter, setResultFilter] = useState<ResultFilter>("all");
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDetailLoading, setIsDetailLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  useEffect(() => {
    void loadPlatformEvents();
  }, []);

  async function loadPlatformEvents(targetTaskId?: string | null) {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const data = await apiFetch<TaskListResponse>("/api/tasks");
      const webhookTasks = data.tasks
        .filter((task) => task.task_type === TAKEALOT_WEBHOOK_TASK_TYPE || task.domain === "webhook")
        .sort((left, right) => new Date(right.created_at).getTime() - new Date(left.created_at).getTime());

      setTasks(webhookTasks);

      const nextTaskId =
        targetTaskId && webhookTasks.some((task) => task.task_id === targetTaskId)
          ? targetTaskId
          : selectedTask?.task_id && webhookTasks.some((task) => task.task_id === selectedTask.task_id)
            ? selectedTask.task_id
            : webhookTasks[0]?.task_id ?? null;

      if (nextTaskId) {
        await loadTaskDetail(nextTaskId);
      } else {
        setSelectedTask(null);
        setEvents([]);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载平台事件失败");
      setTasks([]);
      setSelectedTask(null);
      setEvents([]);
    } finally {
      setIsLoading(false);
    }
  }

  async function loadTaskDetail(taskId: string) {
    setIsDetailLoading(true);
    setErrorMessage("");

    try {
      const [detail, eventData] = await Promise.all([
        apiFetch<TaskRunDetail>(`/api/tasks/${encodeURIComponent(taskId)}`),
        apiFetch<TaskEventListResponse>(`/api/tasks/${encodeURIComponent(taskId)}/events`),
      ]);
      setSelectedTask(detail);
      setEvents(eventData.events);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载事件详情失败");
      setSelectedTask(null);
      setEvents([]);
    } finally {
      setIsDetailLoading(false);
    }
  }

  const records = useMemo<PlatformEventRecord[]>(
    () =>
      tasks.map((task) => {
        const meta = getWebhookMeta(task.ui_meta);
        return {
          task,
          meta,
          kind: eventKindFrom(meta.eventType),
          result: resultFromTask(task, meta.applyStatus),
        };
      }),
    [tasks],
  );

  const visibleRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return records.filter((record) => {
      const matchesKind = kindFilter === "all" || record.kind === kindFilter;
      const matchesResult = resultFilter === "all" || record.result === resultFilter;
      const matchesQuery = keyword
        ? [
            record.meta.eventType,
            record.meta.deliveryId,
            record.meta.listingSku,
            record.meta.listingId,
            record.task.task_id,
            record.task.request_id,
            record.task.target_id,
            record.task.error_code,
            payloadSummaryText(record.meta.payloadSummary),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(keyword)
        : true;

      return matchesKind && matchesResult && matchesQuery;
    });
  }, [kindFilter, query, records, resultFilter]);

  const selectedRecord = useMemo(() => {
    if (!selectedTask) return null;
    return records.find((record) => record.task.task_id === selectedTask.task_id) ?? null;
  }, [records, selectedTask]);

  const metricItems = useMemo(
    () => [
      {
        label: "事件总数",
        value: String(records.length),
        icon: Inbox,
        tone: "neutral" as const,
      },
      {
        label: "已写入",
        value: String(records.filter((record) => record.result === "applied").length),
        icon: CheckCircle2,
        tone: "neutral" as const,
      },
      {
        label: "待处理",
        value: String(records.filter((record) => record.result === "pending").length),
        icon: Clock3,
        tone: "neutral" as const,
      },
      {
        label: "需处理",
        value: String(records.filter((record) => record.result === "attention").length),
        icon: TriangleAlert,
        tone: records.some((record) => record.result === "attention")
          ? ("danger" as const)
          : ("neutral" as const),
      },
    ],
    [records],
  );

  return (
    <div className="space-y-4 bg-[#FAFAFA] text-[#000000]">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-medium text-[#595959]">平台事件</div>
          <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
            平台事件收件箱
          </h1>
        </div>

        <button
          type="button"
          onClick={() => void loadPlatformEvents(selectedTask?.task_id)}
          className="inline-flex h-9 items-center justify-center gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm font-medium text-[#000000]"
        >
          <RefreshCcw className={["h-4 w-4 stroke-[1.8]", isLoading ? "animate-spin" : ""].join(" ")} />
          刷新
        </button>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metricItems.map((item) => (
          <MetricCard
            key={item.label}
            label={item.label}
            value={isLoading ? "--" : item.value}
            icon={item.icon}
            tone={item.tone}
          />
        ))}
      </section>

      <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-3">
        <div className="flex flex-col gap-3 2xl:flex-row 2xl:items-center">
          <div className="flex flex-wrap gap-2">
            {KIND_FILTERS.map((filter) => (
              <button
                key={filter.value}
                type="button"
                onClick={() => setKindFilter(filter.value)}
                className={[
                  "inline-flex h-9 items-center justify-center rounded-[6px] border px-3 text-sm font-medium",
                  kindFilter === filter.value
                    ? "border-[#000000] bg-[#FFFFFF] text-[#000000]"
                    : "border-[#EBEBEB] bg-[#FFFFFF] text-[#595959]",
                ].join(" ")}
              >
                {filter.label}
              </button>
            ))}
          </div>

          <div className="flex flex-col gap-3 md:flex-row md:items-center 2xl:ml-auto">
            <label className="relative min-w-0 md:w-[300px]">
              <Filter className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
              <select
                value={resultFilter}
                onChange={(event) => setResultFilter(event.target.value as ResultFilter)}
                className="h-9 w-full appearance-none rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] pl-9 pr-3 text-sm text-[#000000] outline-none"
              >
                {RESULT_FILTERS.map((filter) => (
                  <option key={filter.value} value={filter.value}>
                    {filter.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="relative min-w-0 md:w-[360px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索事件、单号、SKU..."
                className="h-9 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] pl-9 pr-3 text-sm text-[#000000] outline-none placeholder:text-[#595959]"
              />
            </label>
          </div>
        </div>
      </section>

      <section className="grid gap-4 2xl:grid-cols-[minmax(340px,430px)_minmax(0,1fr)]">
        <aside className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
          <div className="flex items-center justify-between border-b border-[#EBEBEB] px-4 py-3">
            <div className="text-sm font-semibold text-[#000000]">事件列表</div>
            <div className="text-xs text-[#595959]">
              {isLoading ? "刷新中" : `${visibleRecords.length} 条`}
            </div>
          </div>

          <div className="max-h-[calc(100vh-330px)] min-h-[360px] overflow-y-auto p-3">
            <div className="grid gap-2">
              {visibleRecords.map((record) => (
                <EventListItem
                  key={record.task.task_id}
                  record={record}
                  active={selectedTask?.task_id === record.task.task_id}
                  onSelect={() => void loadTaskDetail(record.task.task_id)}
                />
              ))}
            </div>

            {!isLoading && visibleRecords.length === 0 ? (
              <div className="rounded-[6px] border border-dashed border-[#EBEBEB] bg-[#FFFFFF] px-4 py-10 text-center text-sm text-[#595959]">
                当前筛选下没有事件。
              </div>
            ) : null}
          </div>
        </aside>

        <main className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          {selectedRecord && selectedTask ? (
            <EventDetailPanel
              record={selectedRecord}
              task={selectedTask}
              events={events}
              isLoading={isDetailLoading}
            />
          ) : (
            <div className="rounded-[6px] border border-dashed border-[#EBEBEB] bg-[#FFFFFF] px-6 py-12 text-center text-sm text-[#595959]">
              选择一条事件查看处理结果。
            </div>
          )}
        </main>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  value,
  icon: Icon,
  tone,
}: {
  label: string;
  value: string;
  icon: LucideIcon;
  tone: "neutral" | "danger";
}) {
  return (
    <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm text-[#595959]">{label}</div>
        <Icon className={["h-4 w-4 stroke-[1.8]", tone === "danger" ? "text-[#D9363E]" : "text-[#595959]"].join(" ")} />
      </div>
      <div
        className={[
          "mt-3 text-2xl font-semibold tracking-[-0.03em]",
          tone === "danger" ? "text-[#D9363E]" : "text-[#000000]",
        ].join(" ")}
      >
        {value}
      </div>
    </article>
  );
}

function EventListItem({
  record,
  active,
  onSelect,
}: {
  record: PlatformEventRecord;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={[
        "grid gap-2 rounded-[6px] border bg-[#FFFFFF] p-3 text-left transition-colors",
        active ? "border-[#000000]" : "border-[#EBEBEB] hover:border-[#D9D9D9]",
      ].join(" ")}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-[#000000]">
            {record.meta.eventType ?? "未知事件"}
          </div>
          <div className="mt-1 truncate text-xs text-[#595959]">
            {businessTarget(record)}
          </div>
        </div>
        <ResultBadge result={record.result} />
      </div>

      <div className="flex flex-wrap gap-2">
        <span className="rounded-[6px] border border-[#EBEBEB] px-2 py-1 text-xs font-medium text-[#595959]">
          {eventKindLabel(record.kind)}
        </span>
        {record.meta.listingSku ? (
          <span className="max-w-full truncate rounded-[6px] border border-[#EBEBEB] px-2 py-1 text-xs font-medium text-[#595959]">
            {record.meta.listingSku}
          </span>
        ) : null}
      </div>

      <div className="flex items-center justify-between gap-3 text-xs text-[#595959]">
        <span className="truncate">{record.meta.deliveryId ?? record.task.request_id}</span>
        <span className="whitespace-nowrap">{formatDateTime(record.task.created_at)}</span>
      </div>
    </button>
  );
}

function EventDetailPanel({
  record,
  task,
  events,
  isLoading,
}: {
  record: PlatformEventRecord;
  task: TaskRunDetail;
  events: TaskEvent[];
  isLoading: boolean;
}) {
  const appliedEvent = events.find((event) =>
    ["webhook.listing_upserted", "webhook.order_upserted"].includes(event.event_type),
  );
  const businessResult = appliedEvent?.message ?? task.error_msg ?? resultCopy(record);
  const payloadSummary = record.meta.payloadSummary;

  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-4 border-b border-[#EBEBEB] pb-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0">
          <div className="text-xs font-medium text-[#595959]">{eventKindLabel(record.kind)}</div>
          <h2 className="mt-1 break-words text-2xl font-semibold tracking-[-0.03em] text-[#000000]">
            {record.meta.eventType ?? "平台事件"}
          </h2>
          <div className="mt-2 text-sm leading-6 text-[#595959]">{businessResult}</div>
        </div>
        <ResultBadge result={record.result} large />
      </div>

      {isLoading ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-4 py-3 text-sm text-[#595959]">
          正在刷新详情...
        </div>
      ) : null}

      <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <DetailMetric label="处理结果" value={resultLabel(record.result)} />
        <DetailMetric label="关联对象" value={businessTarget(record)} />
        <DetailMetric label="接收时间" value={formatDateTime(task.created_at)} />
        <DetailMetric label="完成时间" value={formatDateTime(task.finished_at)} />
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
          <SectionHeader icon={PackageCheck} title="本次带回字段" />
          <div className="grid gap-2 p-4">
            {payloadSummary && Object.keys(payloadSummary).length > 0 ? (
              Object.entries(payloadSummary).map(([key, value]) => (
                <SummaryField key={key} label={formatPayloadKey(key)} value={formatPayloadValue(value)} />
              ))
            ) : (
              <div className="rounded-[6px] border border-dashed border-[#EBEBEB] px-4 py-8 text-center text-sm text-[#595959]">
                暂无摘要字段。
              </div>
            )}
          </div>
        </div>

        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
          <SectionHeader icon={BellRing} title="处理时间线" />
          <div className="divide-y divide-[#EBEBEB] px-4">
            {events.map((event) => (
              <TimelineRow key={event.event_id} event={event} />
            ))}
            {events.length === 0 ? (
              <div className="py-8 text-center text-sm text-[#595959]">暂无处理记录。</div>
            ) : null}
          </div>
        </div>
      </section>

      {record.result === "attention" ? (
        <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4">
          <div className="flex items-start gap-3">
            <ShieldAlert className="mt-0.5 h-4 w-4 text-[#D9363E] stroke-[1.8]" />
            <div className="space-y-1">
              <div className="text-sm font-semibold text-[#D9363E]">需要处理</div>
              <div className="text-sm leading-6 text-[#595959]">
                {attentionCopy(task, record.meta.applyStatus)}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      <details className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
        <summary className="cursor-pointer px-4 py-3 text-sm font-semibold text-[#000000]">
          管理员排障信息
        </summary>
        <div className="grid gap-3 border-t border-[#EBEBEB] p-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <DetailMetric label="事件编号" value={record.meta.deliveryId ?? task.request_id} />
            <DetailMetric label="任务状态" value={`${formatTaskStatus(task.status)} / ${task.stage}`} />
            <DetailMetric label="重试次数" value={`${task.attempt_count}/${task.max_retries}`} />
            <DetailMetric label="错误码" value={task.error_code ?? "--"} />
          </div>
          {task.error_msg ? (
            <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2 text-sm leading-6 text-[#D9363E]">
              {task.error_msg}
            </div>
          ) : null}
          <JsonBlock
            value={{
              task_id: task.task_id,
              request_id: task.request_id,
              target_type: task.target_type,
              target_id: task.target_id,
              ui_meta: task.ui_meta,
            }}
          />
        </div>
      </details>
    </div>
  );
}

function SectionHeader({ icon: Icon, title }: { icon: LucideIcon; title: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-[#EBEBEB] px-4 py-3 text-sm font-semibold text-[#000000]">
      <Icon className="h-4 w-4 text-[#595959] stroke-[1.8]" />
      {title}
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2.5">
      <div className="text-xs text-[#595959]">{label}</div>
      <div className="mt-1 break-words text-sm font-medium text-[#000000]">{value}</div>
    </div>
  );
}

function SummaryField({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[140px_minmax(0,1fr)] gap-3 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2 text-sm">
      <div className="text-[#595959]">{label}</div>
      <div className="break-words font-medium text-[#000000]">{value}</div>
    </div>
  );
}

function TimelineRow({ event }: { event: TaskEvent }) {
  const hasDetails = Boolean(event.details && Object.keys(event.details).length > 0);
  return (
    <div className="py-4">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="text-sm font-medium text-[#000000]">{formatEventTitle(event.event_type)}</div>
          <div className="mt-1 text-sm leading-6 text-[#595959]">{event.message}</div>
        </div>
        <div className="whitespace-nowrap text-xs text-[#595959]">{formatDateTime(event.created_at)}</div>
      </div>
      {event.stage ? (
        <div className="mt-2 inline-flex rounded-[6px] border border-[#EBEBEB] px-2 py-1 text-xs font-medium text-[#595959]">
          {event.stage}
        </div>
      ) : null}
      {hasDetails ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-medium text-[#595959]">查看详情</summary>
          <div className="mt-2">
            <JsonBlock value={event.details} />
          </div>
        </details>
      ) : null}
    </div>
  );
}

function ResultBadge({ result, large = false }: { result: ResultKey; large?: boolean }) {
  return (
    <span
      className={[
        "inline-flex shrink-0 items-center rounded-[6px] border font-semibold",
        large ? "px-3 py-2 text-sm" : "px-2 py-1 text-xs",
        result === "attention"
          ? "border-[#EBEBEB] bg-[#FFFFFF] text-[#D9363E]"
          : "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000]",
      ].join(" ")}
    >
      {resultLabel(result)}
    </span>
  );
}

function JsonBlock({ value }: { value: unknown }) {
  return (
    <pre className="max-h-[360px] overflow-auto rounded-[6px] bg-[#111111] p-3 text-xs leading-6 text-[#F8FAFC]">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function getWebhookMeta(uiMeta: TaskSummary["ui_meta"]): WebhookMeta {
  const meta = uiMeta && typeof uiMeta === "object" ? uiMeta : {};
  return {
    deliveryId: getMetaString(meta, "webhook_delivery_id"),
    eventType: getMetaString(meta, "webhook_event_type"),
    applyStatus: getMetaString(meta, "webhook_apply_status"),
    storeId: getMetaString(meta, "webhook_store_id"),
    listingSku: getMetaString(meta, "webhook_listing_sku"),
    listingId: getMetaString(meta, "webhook_listing_id"),
    payloadSummary: getMetaObject(meta, "webhook_payload_summary"),
  };
}

function getMetaString(meta: Record<string, unknown>, key: string) {
  const value = meta[key];
  if (typeof value === "string" && value.trim()) return value;
  if (typeof value === "number") return String(value);
  return null;
}

function getMetaObject(meta: Record<string, unknown>, key: string) {
  const value = meta[key];
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function resultFromTask(task: TaskSummary, applyStatus: string | null): ResultKey {
  const status = `${task.status} ${task.stage} ${applyStatus ?? ""} ${task.error_code ?? ""}`.toLowerCase();
  if (
    ["failed", "dead_letter", "timed_out", "manual_intervention", "needs_mapping", "missing"].some((token) =>
      status.includes(token),
    )
  ) {
    return "attention";
  }
  if (["queued", "leased", "running", "pending"].some((token) => status.includes(token))) {
    return "pending";
  }
  if (status.includes("applied")) {
    return "applied";
  }
  return "stored";
}

function eventKindFrom(eventType: string | null): EventKind {
  const text = (eventType ?? "").toLowerCase();
  if (text.includes("offer")) return "offer";
  if (text.includes("leadtime")) return "leadtime";
  if (text.includes("drop")) return "dropship";
  if (text.includes("sale") || text.includes("order")) return "sale";
  return "other";
}

function businessTarget(record: PlatformEventRecord) {
  if (record.meta.listingSku) return record.meta.listingSku;
  if (record.task.target_type === "order" && record.task.target_id) return `订单 ${shortId(record.task.target_id)}`;
  if (record.task.target_type === "listing" && record.task.target_id) return `报价 ${shortId(record.task.target_id)}`;
  if (record.meta.storeId) return `店铺 ${shortId(record.meta.storeId)}`;
  return record.meta.deliveryId ? `事件 ${shortId(record.meta.deliveryId)}` : "未关联业务对象";
}

function resultCopy(record: PlatformEventRecord) {
  if (record.result === "applied") return "事件已经写入对应业务对象。";
  if (record.result === "pending") return "事件已接收，正在等待后台处理。";
  if (record.result === "attention") return "事件未完成写入，需要管理员复核。";
  return "事件已留存，可用于后续对账或修复。";
}

function attentionCopy(task: TaskRunDetail, applyStatus: string | null) {
  if ((applyStatus ?? "").includes("store_mapping")) {
    return "当前事件没有匹配到唯一店铺，需要先确认事件应该归属哪一家 Takealot 店铺。";
  }
  if ((applyStatus ?? "").includes("identifier")) {
    return "当前事件缺少可识别的报价或订单编号，需要结合原始事件内容复核。";
  }
  if (task.error_msg) return task.error_msg;
  return "先复核事件类型、关联店铺和最近处理记录，再决定是否重新入队。";
}

function eventKindLabel(kind: EventKind) {
  const labels: Record<EventKind, string> = {
    offer: "报价事件",
    sale: "订单状态",
    leadtime: "Leadtime",
    dropship: "Dropship",
    other: "其他",
  };
  return labels[kind];
}

function resultLabel(result: ResultKey) {
  const labels: Record<ResultKey, string> = {
    applied: "已写入",
    pending: "待处理",
    attention: "需处理",
    stored: "已留存",
  };
  return labels[result];
}

function formatTaskStatus(status: string) {
  const labels: Record<string, string> = {
    queued: "排队中",
    leased: "已领取",
    running: "处理中",
    waiting_retry: "等待重试",
    cancelled: "已取消",
    succeeded: "已完成",
    failed: "失败",
    failed_final: "最终失败",
    dead_letter: "死信",
    manual_intervention: "人工介入",
    timed_out: "超时",
  };
  return labels[status] ?? status;
}

function formatEventTitle(eventType: string) {
  const labels: Record<string, string> = {
    "webhook.received": "事件已接收",
    "task.started": "开始处理",
    "webhook.listing_upserted": "报价已写入",
    "webhook.order_upserted": "订单已写入",
    "task.succeeded": "处理完成",
    "task.failed": "处理失败",
    "task.retry_scheduled": "已安排重试",
    "task.cancelled": "已取消",
  };
  return labels[eventType] ?? eventType;
}

function formatPayloadKey(key: string) {
  const labels: Record<string, string> = {
    offer_id: "Offer ID",
    sku: "SKU",
    title: "标题",
    price: "售价",
    stock: "库存",
    changed_fields: "变更字段",
    keys: "字段列表",
  };
  return labels[key] ?? key;
}

function formatPayloadValue(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item)).join(", ");
  if (value && typeof value === "object") return JSON.stringify(value);
  if (value == null || value === "") return "--";
  return String(value);
}

function payloadSummaryText(summary: Record<string, unknown> | null) {
  if (!summary) return "";
  return Object.entries(summary)
    .map(([key, value]) => `${key}:${formatPayloadValue(value)}`)
    .join(" ");
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function shortId(value: string) {
  return value.length > 10 ? `${value.slice(0, 8)}...` : value;
}
