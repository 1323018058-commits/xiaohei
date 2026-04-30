"use client";

import { useEffect, useMemo, useState } from "react";
import { ImageIcon, RefreshCcw, Search, X } from "lucide-react";
import { Toaster, toast } from "sonner";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type ListingJobListResponse = components["schemas"]["ListingJobListResponse"];
type ListingJob = components["schemas"]["ListingJobResponse"];
type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];

type StatusFilter = "all" | "success" | "failed" | "processing";
type ListingStatus = "success" | "failed" | "processing";

type DisplayRecord = {
  job: ListingJob;
  submittedAt: string;
  title: string;
  barcode: string | null;
  plid: string;
  store: string;
  source: string;
  status: ListingStatus;
  failureReason: string | null;
  imageUrl: string | null;
  productUrl: string | null;
};

type ImagePreview = {
  title: string;
  imageUrl: string;
};

export default function ListingPage() {
  const [jobs, setJobs] = useState<ListingJob[]>([]);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [query, setQuery] = useState("");
  const [imagePreview, setImagePreview] = useState<ImagePreview | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");

  const storeNameMap = useMemo(
    () => new Map(stores.map((store) => [store.store_id, store.name])),
    [stores],
  );

  const records = useMemo<DisplayRecord[]>(
    () =>
      jobs.map((job) => ({
        job,
        submittedAt: formatDateTime(job.created_at),
        title: displayTitle(job),
        barcode: extractBarcode(job),
        plid: extractPlid(job),
        store: storeNameMap.get(job.store_id) ?? shortId(job.store_id),
        source: formatSource(job.source),
        status: statusKey(job),
        failureReason: extractFailureReason(job),
        imageUrl: extractImageUrl(job.raw_payload),
        productUrl: productLink(job),
      })),
    [jobs, storeNameMap],
  );

  const visibleRecords = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return records.filter((record) => {
      const matchesStatus = statusFilter === "all" || record.status === statusFilter;
      const matchesQuery = keyword
        ? [
            record.title,
            record.barcode,
            record.plid,
            record.store,
            record.source,
            record.job.job_id,
            record.job.source_ref,
            record.job.stage,
            record.job.status,
            extractPlid(record.job),
          ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(keyword)
        : true;

      return matchesStatus && matchesQuery;
    });
  }, [query, records, statusFilter]);

  useEffect(() => {
    void loadRecords();
  }, []);

  async function loadRecords() {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const [jobData, storeData] = await Promise.all([
        apiFetch<ListingJobListResponse>("/api/listing/jobs"),
        apiFetch<StoreListResponse>("/api/v1/stores").catch(() => ({ stores: [] })),
      ]);
      setJobs(jobData.jobs);
      setStores(storeData.stores);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载上架记录失败");
      setJobs([]);
    } finally {
      setIsLoading(false);
    }
  }

  async function refreshRecords() {
    setIsRefreshing(true);
    setErrorMessage("");

    try {
      await loadRecords();
      toast.success("上架记录已刷新");
    } catch (error) {
      toast.error("刷新记录失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
    } finally {
      setIsRefreshing(false);
    }
  }

  return (
    <div className="relative space-y-4 text-[#000000]">
      <Toaster
        richColors={false}
        position="top-right"
        toastOptions={{
          style: {
            background: "#FFFFFF",
            color: "#000000",
            border: "1px solid #EBEBEB",
            borderRadius: "6px",
            boxShadow: "none",
          },
        }}
      />

      <header className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
        <div className="space-y-1">
          <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
            上架记录
          </h1>
        </div>

        <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-center">
          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}
            className="h-9 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none"
          >
            <option value="all">全部状态</option>
            <option value="success">成功</option>
            <option value="failed">失败</option>
            <option value="processing">处理中</option>
          </select>

          <label className="relative block min-w-[260px]">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索 标题 / Barcode / PLID..."
              className="h-9 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] pl-9 pr-3 text-sm text-[#000000] outline-none placeholder:text-[#595959]"
            />
          </label>

          <button
            type="button"
            onClick={() => void refreshRecords()}
            className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm font-medium text-[#595959]"
          >
            <RefreshCcw
              className={["h-4 w-4 stroke-[1.8]", isRefreshing ? "animate-spin" : ""].join(" ")}
            />
            <span>刷新记录</span>
          </button>
        </div>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      <section className="overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-[#EBEBEB] text-xs text-[#595959]">
                <th className="h-11 whitespace-nowrap px-4 font-medium">提交时间</th>
                <th className="h-11 min-w-[420px] px-4 font-medium">商品信息</th>
                <th className="h-11 whitespace-nowrap px-4 font-medium">目标店铺</th>
                <th className="h-11 whitespace-nowrap px-4 font-medium">上架来源</th>
                <th className="h-11 whitespace-nowrap px-4 font-medium">状态</th>
              </tr>
            </thead>
            <tbody>
              {visibleRecords.map((record) => (
                <tr
                  key={record.job.job_id}
                  className="border-b border-[#EBEBEB] text-sm last:border-b-0 hover:bg-[#FAFAFA]"
                >
                  <td className="whitespace-nowrap px-4 py-3 align-top text-sm text-[#595959]">
                    {record.submittedAt}
                  </td>
                  <td className="px-4 py-3 align-top">
                    <div className="flex items-start gap-3">
                      {record.imageUrl ? (
                        <button
                          type="button"
                          onClick={() =>
                            setImagePreview({
                              title: record.title,
                              imageUrl: record.imageUrl ?? "",
                            })
                          }
                          className="h-11 w-11 flex-none overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA]"
                          aria-label="放大商品图片"
                        >
                          <img
                            src={record.imageUrl}
                            alt={record.title}
                            className="h-full w-full object-cover"
                          />
                        </button>
                      ) : (
                        <div className="flex h-11 w-11 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] text-[#595959]">
                          <ImageIcon className="h-4 w-4 stroke-[1.8]" />
                        </div>
                      )}
                      <div className="min-w-0 space-y-1">
                        {record.productUrl ? (
                          <a
                            href={record.productUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="line-clamp-2 font-medium leading-5 text-[#000000] underline decoration-[#B8B8B8] decoration-dotted underline-offset-4 hover:text-[#2F6F63]"
                          >
                            {record.title}
                          </a>
                        ) : (
                          <div className="line-clamp-2 font-medium leading-5 text-[#000000]">
                            {record.title}
                          </div>
                        )}
                        <div className="text-xs text-[#595959]">
                          {record.barcode ? `Barcode: ${record.barcode}` : `PLID: ${record.plid || "--"}`}
                        </div>
                        {record.status === "failed" && record.failureReason ? (
                          <div className="line-clamp-1 text-xs text-[#D9363E]">
                            {record.failureReason}
                          </div>
                        ) : null}
                      </div>
                    </div>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 align-top text-sm text-[#000000]">
                    {record.store}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 align-top">
                    <span className="inline-flex rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-2.5 py-1 text-xs text-[#595959]">
                      {record.source}
                    </span>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 align-top">
                    <StatusView status={record.status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {visibleRecords.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-[#595959]">
            {isLoading ? "正在加载上架记录..." : "暂无上架记录。"}
          </div>
        ) : null}
      </section>

      {imagePreview ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
          onClick={() => setImagePreview(null)}
        >
          <div
            className="relative max-h-full max-w-[920px]"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setImagePreview(null)}
              className="absolute right-3 top-3 inline-flex h-9 w-9 items-center justify-center rounded-[6px] border border-white/20 bg-black/60 text-white"
              aria-label="关闭图片预览"
            >
              <X className="h-4 w-4 stroke-[1.8]" />
            </button>
            <img
              src={imagePreview.imageUrl}
              alt={imagePreview.title}
              className="max-h-[82vh] max-w-full rounded-[6px] bg-white object-contain"
            />
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StatusView({ status }: { status: ListingStatus }) {
  if (status === "failed") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-[#D9363E]">
        <span className="h-2 w-2 rounded-full bg-[#D9363E]" />
        <span>上架失败</span>
      </span>
    );
  }

  if (status === "success") {
    return (
      <span className="inline-flex items-center gap-2 text-sm text-[#000000]">
        <span className="h-2 w-2 rounded-full bg-[#22C55E]" />
        <span>上架成功</span>
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-2 text-sm text-[#595959]">
      <span className="h-2 w-2 animate-pulse rounded-full bg-[#D9A441]" />
      <span>处理中...</span>
    </span>
  );
}

function statusKey(job: ListingJob): ListingStatus {
  const text = `${job.status} ${job.stage}`.toLowerCase();
  if (["success", "completed", "ready_to_submit", "buyable", "listed"].some((token) => text.includes(token))) {
    return "success";
  }
  if (["failed", "error", "manual_intervention", "rejected", "dead_letter"].some((token) => text.includes(token))) {
    return "failed";
  }
  return "processing";
}

function formatSource(source: string) {
  const normalized = source.toLowerCase();
  if (normalized.includes("ai")) return "AI 智能上架";
  if (normalized.includes("excel") || normalized.includes("import")) return "Excel 导入";
  if (normalized.includes("extension") || normalized.includes("plugin")) return "插件跟卖";
  return source || "插件跟卖";
}

function displayTitle(job: ListingJob) {
  const payload = job.raw_payload;
  return (
    payloadValue(nestedPayload(payload, "offer_payload"), "title") ??
    payloadValue(nestedPayload(payload, "batch_status_payload"), "title") ??
    job.title
  );
}

function extractBarcode(job: ListingJob) {
  const payload = job.raw_payload;
  const candidates = [
    payloadValue(payload, "barcode"),
    payloadValue(nestedPayload(payload, "offer_payload"), "barcode"),
    payloadValue(nestedPayload(payload, "batch_status_payload"), "barcode"),
    payloadValue(payload, "Barcode"),
    payloadValue(payload, "bar_code"),
  ];
  return candidates.find(Boolean) ?? null;
}

function extractFailureReason(job: ListingJob) {
  const payload = job.raw_payload;
  const diagnosis = nestedPayload(payload, "offer_diagnosis");
  return (
    payloadValue(payload, "error") ??
    payloadValue(payload, "error_msg") ??
    payloadValue(payload, "failure_reason") ??
    payloadValue(diagnosis, "summary") ??
    job.note
  );
}

function productLink(job: ListingJob) {
  const plid = extractPlid(job);
  if (!plid) return null;
  return `https://www.takealot.com/${takealotSlug(displayTitle(job))}/${plid}`;
}

function extractPlid(job: ListingJob) {
  const payload = job.raw_payload;
  const candidate =
    payloadValue(payload, "plid") ??
    payloadValue(nestedPayload(payload, "offer_payload"), "productline_id") ??
    payloadValue(nestedPayload(payload, "batch_status_payload"), "productline_id") ??
    job.source_ref;
  return normalizePlatformProductId(candidate);
}

function extractImageUrl(payload: { [key: string]: unknown } | null) {
  return (
    payloadValue(payload, "image_url") ??
    payloadValue(nestedPayload(payload, "offer_payload"), "image_url") ??
    payloadValue(nestedPayload(payload, "batch_status_payload"), "image_url") ??
    findFirstImageUrl(payload)
  );
}

function nestedPayload(payload: { [key: string]: unknown } | null, key: string) {
  const value = payload?.[key];
  return isRecord(value) ? value : null;
}

function payloadValue(payload: { [key: string]: unknown } | null, key: string) {
  const value = payload?.[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number" && Number.isFinite(value)) return String(value);
  return null;
}

function findFirstImageUrl(value: unknown, depth = 0): string | null {
  if (depth > 4 || value == null) return null;
  if (typeof value === "string") {
    const trimmed = value.trim();
    return isImageLikeUrl(trimmed) ? trimmed : null;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstImageUrl(item, depth + 1);
      if (found) return found;
    }
    return null;
  }
  if (!isRecord(value)) return null;

  for (const [key, item] of Object.entries(value)) {
    if (/image|thumbnail|cover|picture|photo|url/i.test(key)) {
      const found = findFirstImageUrl(item, depth + 1);
      if (found) return found;
    }
  }
  return null;
}

function isRecord(value: unknown): value is { [key: string]: unknown } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isImageLikeUrl(value: string) {
  return /^https?:\/\//i.test(value) && (
    /\.(png|jpe?g|webp|gif)(\?|$)/i.test(value) ||
    /takealot|covers_images|image|thumbnail|photo|picture/i.test(value)
  );
}

function normalizePlatformProductId(value: string | null | undefined) {
  const compact = (value ?? "").trim().replace(/\s+/g, "");
  const numeric = compact.replace(/^(PLID)+/i, "");
  return numeric ? `PLID${numeric}` : "";
}

function takealotSlug(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "product";
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
  return value.slice(0, 8);
}
