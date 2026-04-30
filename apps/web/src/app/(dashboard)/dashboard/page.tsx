"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowUpRight,
  BadgeDollarSign,
  type LucideIcon,
  PackageCheck,
  ShieldAlert,
  ShoppingCart,
  Store,
  TriangleAlert,
} from "lucide-react";
import {
  Line,
  LineChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type SessionInfoResponse = components["schemas"]["SessionInfoResponse"];
type TenantUsageResponse = components["schemas"]["TenantUsageResponse"];
type DashboardSummaryResponse = components["schemas"]["DashboardSummaryResponse"];
type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type OrderListResponse = components["schemas"]["OrderListResponse"];
type OrderSummary = components["schemas"]["OrderSummary"];
type ListingJobListResponse = components["schemas"]["ListingJobListResponse"];
type ListingJob = components["schemas"]["ListingJobResponse"];
type BiddingRuleListResponse = components["schemas"]["BiddingRuleListResponse"];

type ChartPoint = {
  date: string;
  sales: number;
  volume: number;
};

type KpiCard = {
  title: string;
  value: string;
  icon: LucideIcon;
  caption?: string;
  danger?: boolean;
};

type PendingAction = {
  text: string;
  action: string;
  href: string;
};

type RecentRecord = {
  id: string;
  title: string;
  detail: string;
  status: string;
  href: string;
};

const sellerBlessings = [
  "愿今天少一点返工，多一点出单。",
  "愿今天广告少烧一点，订单多来一点。",
  "愿今天库存刚刚好，BuyBox 稳稳拿。",
  "愿今天差评少一点，好评自然来。",
  "愿今天上架一次过，爆款自己跑。",
  "愿今天客服少催单，仓库准时发。",
  "愿今天价格稳得住，利润留得下。",
];

export default function DashboardPage() {
  const [session, setSession] = useState<SessionInfoResponse | null>(null);
  const [usage, setUsage] = useState<TenantUsageResponse | null>(null);
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [jobs, setJobs] = useState<ListingJob[]>([]);
  const [biddingSkuCount, setBiddingSkuCount] = useState<number | null>(null);
  const [range, setRange] = useState<"7d" | "30d">("7d");
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [chartWidth, setChartWidth] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [sellerBlessing, setSellerBlessing] = useState(() => blessingForDate(new Date()));

  useEffect(() => {
    void loadDashboard();
  }, []);

  useEffect(() => {
    const updateBlessing = () => setSellerBlessing(blessingForDate(new Date()));
    const timer = window.setInterval(updateBlessing, 60 * 60 * 1000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    if (stores.length === 0) {
      setBiddingSkuCount(0);
      return;
    }

    let isCancelled = false;

    async function loadBiddingUsage() {
      try {
        const ruleGroups = await Promise.all(
          stores.map((store) =>
            apiFetch<BiddingRuleListResponse>(
              `/api/v1/bidding/rules?store_id=${encodeURIComponent(store.store_id)}`,
            ).catch(() => ({ rules: [] })),
          ),
        );
        if (isCancelled) return;
        const activeSkuSet = new Set<string>();
        for (const group of ruleGroups) {
          for (const rule of group.rules) {
            if (rule.is_active) {
              activeSkuSet.add(`${rule.store_id}:${rule.sku}`);
            }
          }
        }
        setBiddingSkuCount(activeSkuSet.size);
      } catch {
        if (!isCancelled) {
          setBiddingSkuCount(null);
        }
      }
    }

    void loadBiddingUsage();

    return () => {
      isCancelled = true;
    };
  }, [stores]);

  useEffect(() => {
    const node = chartContainerRef.current;
    if (!node) return;

    const updateChartWidth = () => {
      setChartWidth(Math.max(0, Math.floor(node.getBoundingClientRect().width)));
    };

    updateChartWidth();
    const observer = new ResizeObserver(updateChartWidth);
    observer.observe(node);

    return () => observer.disconnect();
  }, []);

  async function loadDashboard() {
    setErrorMessage("");

    try {
      const sessionData = await apiFetch<SessionInfoResponse>("/api/auth/me");
      const canReadUsage = ["super_admin", "tenant_admin"].includes(sessionData.user.role);

      const [summaryResult, storesResult, ordersResult, jobsResult, usageResult] = await Promise.allSettled([
        apiFetch<DashboardSummaryResponse>("/api/v1/dashboard/summary"),
        apiFetch<StoreListResponse>("/api/v1/stores"),
        apiFetch<OrderListResponse>("/api/v1/orders"),
        apiFetch<ListingJobListResponse>("/api/listing/jobs"),
        canReadUsage
          ? apiFetch<TenantUsageResponse>("/admin/api/tenant/usage")
          : Promise.resolve(null),
      ]);

      setSession(sessionData);
      setSummary(readSettled<DashboardSummaryResponse | null>(summaryResult, null));
      setStores(readSettled(storesResult, { stores: [] }).stores);
      setOrders(readSettled(ordersResult, { orders: [] }).orders);
      setJobs(readSettled(jobsResult, { jobs: [] }).jobs);
      setUsage(readSettled<TenantUsageResponse | null>(usageResult, null));

      if ([summaryResult, storesResult, ordersResult, jobsResult].some((item) => item.status === "rejected")) {
        setErrorMessage("部分数据暂时不可用，已优先展示可读取内容。");
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载首页看板失败");
    } finally {
      setIsLoading(false);
    }
  }

  const todaySalesQuantity = summary?.today_sales_quantity ?? 0;
  const todaySalesTotal = summary?.today_sales_total ?? 0;
  const successfulJobs = summary?.today_listing_success_count ?? 0;
  const failedJobs = summary?.today_listing_failed_count ?? 0;
  const businessDayCaption = summary ? `南非 ${summary.business_date}` : "南非业务日";

  const kpis: KpiCard[] = [
    {
      title: "今日销量",
      value: String(todaySalesQuantity),
      icon: ShoppingCart,
      caption: businessDayCaption,
    },
    {
      title: "今日销售额",
      value: formatMoney(todaySalesTotal),
      icon: BadgeDollarSign,
      caption: businessDayCaption,
    },
    {
      title: "今日已上架",
      value: String(successfulJobs),
      icon: PackageCheck,
    },
    {
      title: "今日上架异常",
      value: String(failedJobs),
      icon: TriangleAlert,
      danger: failedJobs > 0,
    },
  ];

  const chart7d = useMemo(
    () => summary?.chart_7d ?? buildChartData(orders, 7),
    [orders, summary],
  );
  const chart30d = useMemo(
    () => summary?.chart_30d ?? buildChartData(orders, 30),
    [orders, summary],
  );
  const chartData = range === "7d" ? chart7d : chart30d;

  const storeRows = useMemo(
    () =>
      stores.slice(0, 6).map((store) => {
        const needsAttention = !isCredentialHealthy(store.credential_status);
        return {
          name: store.name,
          status: needsAttention ? "授权失效" : "正常",
          advice: needsAttention ? "需要处理" : "无需操作",
          danger: needsAttention,
          action: needsAttention ? "去处理" : null,
          href: "/stores",
        };
      }),
    [stores],
  );

  const pendingActions = useMemo<PendingAction[]>(() => {
    const failedListings = jobs.filter((job) => isFailedJob(job)).length;
    const pendingOrders = orders.filter((order) =>
      ["pending", "processing", "awaiting_fulfillment"].includes(
        (order.fulfillment_status ?? order.status).toLowerCase(),
      ),
    ).length;
    const credentialIssues = stores.filter(
      (store) => !isCredentialHealthy(store.credential_status),
    ).length;
    const lowListingQuota =
      usage && usage.limits.max_listings > 0
        ? usage.remaining.listings / usage.limits.max_listings <= 0.1
        : false;

    const next: PendingAction[] = [];

    if (stores.length === 0) {
      next.push({
        text: "还没有接入店铺，先完成第一家店铺授权",
        action: "去接入",
        href: "/stores",
      });
    }

    if (credentialIssues > 0) {
      next.push({
        text: `${credentialIssues} 家店铺凭证需要处理`,
        action: "查看店铺",
        href: "/stores",
      });
    }

    if (pendingOrders > 0) {
      next.push({
        text: `你有 ${pendingOrders} 个订单待生成 PO 单`,
        action: "去处理",
        href: "/orders",
      });
    }

    if (failedListings > 0) {
      next.push({
        text: `${failedListings} 个商品上架失败需要复核`,
        action: "查看记录",
        href: "/listing",
      });
    }

    if (usage && lowListingQuota) {
      next.push({
        text: `AI 上品额度剩余 ${usage.remaining.listings} 个`,
        action: "查看额度",
        href: "/dashboard",
      });
    }

    if (usage && !usage.limits.autobid_enabled) {
      next.push({
        text: "当前套餐未开启自动竞价额度",
        action: "查看套餐",
        href: "/dashboard",
      });
    }

    if (summary?.order_data_status.is_stale) {
      next.push({
        text: "订单数据正在后台更新",
        action: "查看订单",
        href: "/orders",
      });
    }

    if (!summary?.order_data_status.is_stale && todaySalesQuantity === 0 && stores.length > 0) {
      next.push({
        text: "今日暂无新销量，可以复查订单明细",
        action: "查看订单",
        href: "/orders",
      });
    }

    if (!next.length) {
      return [
        { text: "当前没有阻塞项", action: "查看店铺健康", href: "/stores" },
        { text: "可以复查最新上架结果", action: "查看记录", href: "/listing" },
        { text: "可以查看今日订单明细", action: "查看订单", href: "/orders" },
        { text: "可以确认商品列表字段是否够用", action: "配置字段", href: "/products" },
      ];
    }

    const supplementalActions: PendingAction[] = [
      { text: "查看店铺健康状态", action: "查看店铺", href: "/stores" },
      { text: "复查最新上架记录", action: "查看记录", href: "/listing" },
      { text: "查看今日订单明细", action: "查看订单", href: "/orders" },
      { text: "确认商品列表字段是否够用", action: "配置字段", href: "/products" },
    ];

    for (const item of supplementalActions) {
      if (next.length >= 4) break;
      if (!next.some((existing) => existing.text === item.text)) {
        next.push(item);
      }
    }

    return next.slice(0, 6);
  }, [jobs, orders, stores, summary, todaySalesQuantity, usage]);

  const recentRecords = useMemo(() => buildRecentRecords(orders, jobs, stores), [jobs, orders, stores]);

  return (
    <div className="space-y-6 bg-[#FAFAFA] text-[#000000]">
      <header className="flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="space-y-1">
          <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
            首页看板
          </h1>
          <p className="text-sm leading-6 text-[#595959]">
            {sellerBlessing}
          </p>
        </div>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      <section className="grid gap-6 sm:grid-cols-2 xl:grid-cols-4">
        {kpis.map((item) => {
          const Icon = item.icon;
          return (
            <article
              key={item.title}
              className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5"
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-[#595959]">
                  {item.danger ? <span className="h-2 w-2 rounded-full bg-[#D9363E]" /> : null}
                  <span>{item.title}</span>
                </div>
                <Icon className="h-4 w-4 text-[#595959] stroke-[1.8]" />
              </div>
              <div
                className={[
                  "text-3xl font-bold tracking-[-0.04em]",
                  item.danger ? "text-[#D9363E]" : "text-[#000000]",
                ].join(" ")}
              >
                {isLoading ? "--" : item.value}
              </div>
              {item.caption ? (
                <div className="mt-3 text-xs text-[#595959]">{item.caption}</div>
              ) : null}
            </article>
          );
        })}
      </section>

      <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
        <div className="mb-6 flex flex-col gap-4 border-b border-[#EBEBEB] pb-4 md:flex-row md:items-center md:justify-between">
          <div className="text-base font-semibold text-[#000000]">销售与单量趋势</div>
          <div className="inline-flex items-center gap-2 text-sm text-[#595959]">
            <button
              type="button"
              className={range === "7d" ? "font-medium text-[#000000]" : "text-[#595959]"}
              onClick={() => setRange("7d")}
            >
              最近 7 天
            </button>
            <span>/</span>
            <button
              type="button"
              className={range === "30d" ? "font-medium text-[#000000]" : "text-[#595959]"}
              onClick={() => setRange("30d")}
            >
              最近 30 天
            </button>
          </div>
        </div>

        <div className="mb-4 flex items-center gap-5 text-xs text-[#595959]">
          <div className="flex items-center gap-2">
            <span className="inline-block h-[2px] w-6 bg-[#000000]" />
            <span>销售额</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="inline-block h-[2px] w-6 border-t border-dashed border-[#B3B3B3]" />
            <span>单量</span>
          </div>
        </div>

        <div ref={chartContainerRef} className="h-[280px] w-full min-w-0">
          {chartWidth > 0 ? (
            <LineChart
              width={chartWidth}
              height={280}
              data={chartData}
              margin={{ top: 10, right: 4, left: 4, bottom: 0 }}
            >
              <XAxis
                dataKey="date"
                axisLine={false}
                tickLine={false}
                tick={{ fill: "#595959", fontSize: 12 }}
              />
              <YAxis hide />
              <Tooltip cursor={false} content={<DashboardTooltip />} />
              <Line
                type="monotone"
                dataKey="sales"
                stroke="#000000"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 3, fill: "#000000", stroke: "#000000" }}
              />
              <Line
                type="monotone"
                dataKey="volume"
                stroke="#A3A3A3"
                strokeWidth={2}
                strokeDasharray="6 6"
                dot={false}
                activeDot={{ r: 3, fill: "#A3A3A3", stroke: "#A3A3A3" }}
              />
            </LineChart>
          ) : null}
        </div>
      </section>

      <section className="grid gap-6 xl:grid-cols-10">
        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5 xl:col-span-6">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Store className="h-4 w-4 text-[#595959] stroke-[1.8]" />
              <div className="text-base font-semibold text-[#000000]">店铺健康</div>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="min-w-full border-collapse text-left text-sm">
              <thead>
                <tr className="border-b border-[#EBEBEB] text-[#595959]">
                  <th className="pb-3 font-medium">店铺名称</th>
                  <th className="pb-3 font-medium">凭证状态</th>
                  <th className="pb-3 font-medium">处理建议</th>
                </tr>
              </thead>
              <tbody>
                {storeRows.map((row) => (
                  <tr key={row.name} className="border-b border-[#EBEBEB] last:border-b-0">
                    <td className="py-4 pr-4 font-medium text-[#000000]">{row.name}</td>
                    <td className="py-4 pr-4">
                      <div
                        className={[
                          "inline-flex items-center gap-2 text-sm",
                          row.danger ? "text-[#D9363E]" : "text-[#000000]",
                        ].join(" ")}
                      >
                        <span
                          className={[
                            "h-2 w-2 rounded-full",
                            row.danger ? "bg-[#D9363E]" : "bg-[#000000]",
                          ].join(" ")}
                        />
                        <span>{row.status}</span>
                      </div>
                    </td>
                    <td className="py-4 text-[#595959]">
                      <div className="flex items-center justify-between gap-4">
                        <span>{row.advice}</span>
                        {row.action ? (
                          <Link
                            href={row.href}
                            className="inline-flex items-center gap-1 text-sm text-[#000000] underline decoration-[#000000]/20 underline-offset-4"
                          >
                            {row.action}
                            <ArrowUpRight className="h-3.5 w-3.5" />
                          </Link>
                        ) : null}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>

        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5 xl:col-span-4">
          <div className="mb-4 flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-[#595959] stroke-[1.8]" />
            <div className="text-base font-semibold text-[#000000]">待处理事项</div>
          </div>

          <div className="divide-y divide-[#EBEBEB]">
            {pendingActions.map((item) => (
              <Link
                key={`${item.text}-${item.href}`}
                href={item.href}
                className="flex items-center justify-between gap-4 py-4 text-left first:pt-0 last:pb-0"
              >
                <span className="text-sm leading-6 text-[#000000]">
                  {item.text}
                  <span className="ml-1 text-[#595959]">→ {item.action}</span>
                </span>
                <ArrowUpRight className="h-4 w-4 flex-none text-[#595959]" />
              </Link>
            ))}
          </div>
        </article>
      </section>

      <section className="grid gap-6 xl:grid-cols-[minmax(0,1.3fr)_minmax(0,0.7fr)]">
        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-base font-semibold text-[#000000]">最近结果</div>
            <div className="text-xs text-[#595959]">订单与上架混合视图</div>
          </div>
          <div className="divide-y divide-[#EBEBEB]">
            {recentRecords.map((record) => (
              <Link
                key={record.id}
                href={record.href}
                className="flex items-start justify-between gap-4 py-4 first:pt-0 last:pb-0"
              >
                <div className="space-y-1">
                  <div className="text-sm font-medium text-[#000000]">{record.title}</div>
                  <div className="text-xs leading-5 text-[#595959]">{record.detail}</div>
                </div>
                <div className="whitespace-nowrap text-xs text-[#595959]">{record.status}</div>
              </Link>
            ))}
            {!recentRecords.length ? (
              <div className="py-6 text-sm text-[#595959]">暂无最近结果。</div>
            ) : null}
          </div>
        </article>

        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          <div className="mb-1 text-base font-semibold text-[#000000]">套餐权益</div>
          <div className="mb-4 text-xs text-[#595959]">
            {usage?.plan_name ?? "当前套餐"} · {session ? formatSubscription(session.subscription_status) : "--"}
          </div>
          <div className="space-y-4">
            <QuotaLine
              label="竞价 SKU 额度"
              value={formatBiddingQuota(usage, biddingSkuCount)}
            />
            <QuotaLine
              label="店铺数"
              value={formatQuota(usage?.usage.active_stores, usage?.limits.max_stores)}
            />
            <QuotaLine
              label="AI 上品额度"
              value={formatQuota(usage?.usage.listings, usage?.limits.max_listings)}
            />
            <QuotaLine
              label="剩余额度"
              value={formatRemainingListings(usage)}
            />
          </div>
        </article>
      </section>
    </div>
  );
}

function buildChartData(orders: OrderSummary[], days: number): ChartPoint[] {
  const today = new Date();
  const buckets = new Map<string, { sales: number; volume: number }>();

  for (let offset = days - 1; offset >= 0; offset -= 1) {
    const current = new Date(today);
    current.setHours(0, 0, 0, 0);
    current.setDate(today.getDate() - offset);
    const key = dateKey(current);
    buckets.set(key, { sales: 0, volume: 0 });
  }

  for (const order of orders) {
    const source = order.placed_at ?? order.created_at;
    if (!source) continue;
    const date = new Date(source);
    if (Number.isNaN(date.getTime())) continue;
    const key = dateKey(date);
    const bucket = buckets.get(key);
    if (!bucket) continue;
    bucket.sales += order.total_amount ?? 0;
    bucket.volume += 1;
  }

  return Array.from(buckets.entries()).map(([key, bucket]) => ({
    date: key,
    sales: Number(bucket.sales.toFixed(2)),
    volume: bucket.volume,
  }));
}

function buildRecentRecords(
  orders: OrderSummary[],
  jobs: ListingJob[],
  stores: StoreSummary[],
): RecentRecord[] {
  const storeNameMap = new Map(stores.map((store) => [store.store_id, store.name]));

  const orderRecords: RecentRecord[] = orders.slice(0, 4).map((order) => ({
    id: order.order_id,
    title: order.order_number ?? order.external_order_id,
    detail: `${storeNameMap.get(order.store_id) ?? "未知店铺"} · ${formatMoney(
      order.total_amount ?? 0,
      order.currency,
    )} · ${order.item_count} 件商品`,
    status: formatOrderStatus(order.status, order.fulfillment_status),
    href: "/orders",
  }));

  const jobRecords: RecentRecord[] = jobs.slice(0, 4).map((job) => ({
    id: job.job_id,
    title: job.title,
    detail: `${storeNameMap.get(job.store_id) ?? "未知店铺"} · ${formatListingStatus(job.status, job.stage)}`,
    status: formatDateTime(job.updated_at),
    href: "/listing",
  }));

  return [...orderRecords, ...jobRecords].slice(0, 6);
}

function readSettled<T>(result: PromiseSettledResult<T>, fallback: T): T {
  return result.status === "fulfilled" ? result.value : fallback;
}

function isCredentialHealthy(status: string | null) {
  return ["active", "valid", "verified", "ok", "configured", "validating"].includes(
    (status ?? "").toLowerCase(),
  );
}

function blessingForDate(date: Date) {
  const yearStart = new Date(date.getFullYear(), 0, 0);
  const dayOfYear = Math.floor((date.getTime() - yearStart.getTime()) / 86_400_000);
  return sellerBlessings[Math.abs(dayOfYear) % sellerBlessings.length];
}

function isStaleSync(value: string | null | undefined) {
  if (!value) return true;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return true;
  return Date.now() - date.getTime() > 24 * 60 * 60 * 1000;
}

function isSuccessfulJob(job: ListingJob) {
  const text = `${job.status} ${job.stage}`.toLowerCase();
  return ["success", "completed", "ready_to_submit", "buyable"].some((token) =>
    text.includes(token),
  );
}

function isFailedJob(job: ListingJob) {
  const text = `${job.status} ${job.stage}`.toLowerCase();
  return ["failed", "error", "manual_intervention", "rejected"].some((token) =>
    text.includes(token),
  );
}

function formatListingStatus(status: string, stage: string) {
  const text = `${status} ${stage}`.toLowerCase();
  if (["success", "completed", "ready_to_submit", "buyable"].some((token) => text.includes(token))) {
    return "已上架";
  }
  if (["failed", "error", "manual_intervention", "rejected"].some((token) => text.includes(token))) {
    return "失败";
  }
  return "处理中";
}

function formatOrderStatus(status: string, fulfillmentStatus: string | null) {
  if (fulfillmentStatus) {
    const text = fulfillmentStatus.toLowerCase();
    if (text.includes("delivered")) return "已完成";
    if (text.includes("pending")) return "待处理";
  }
  if (status === "delivered") return "已完成";
  if (status === "cancelled") return "已取消";
  return "处理中";
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatRelativeTime(value: string | null | undefined) {
  if (!value) return "未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未同步";
  const diffMinutes = Math.round((Date.now() - date.getTime()) / (1000 * 60));
  if (diffMinutes < 1) return "刚刚";
  if (diffMinutes < 60) return `${diffMinutes}分钟前`;
  const diffHours = Math.round(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}小时前`;
  const diffDays = Math.round(diffHours / 24);
  return `${diffDays}天前`;
}

function formatMoney(value: number | null | undefined, currency = "ZAR") {
  if (value == null) return "R 0";
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatQuota(used: number | null | undefined, limit: number | null | undefined) {
  if (used == null || limit == null) return "--";
  return `${used}/${limit}`;
}

function formatBiddingQuota(usage: TenantUsageResponse | null, activeSkuCount: number | null) {
  if (!usage) return "--";
  if (!usage.limits.autobid_enabled) return "未开通";
  return `${activeSkuCount ?? "--"}/${usage.limits.max_listings}`;
}

function formatRemainingListings(usage: TenantUsageResponse | null) {
  if (!usage) return "--";
  return `${usage.remaining.listings} 个可用`;
}

function formatSubscription(status: string) {
  if (status === "active") return "订阅正常";
  if (status === "trialing") return "试用中";
  if (status === "past_due") return "待续费";
  if (status === "paused") return "已暂停";
  return status;
}

function dateKey(date: Date) {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${month}-${day}`;
}

function DashboardTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; dataKey: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;

  const sales = payload.find((item) => item.dataKey === "sales")?.value ?? 0;
  const volume = payload.find((item) => item.dataKey === "volume")?.value ?? 0;

  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2 text-xs text-[#000000]">
      <div className="mb-1 font-medium">{label}</div>
      <div className="text-[#595959]">销售额: R {sales.toLocaleString()}</div>
      <div className="text-[#595959]">单量: {volume}</div>
    </div>
  );
}

function QuotaLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between border-b border-[#EBEBEB] pb-3 last:border-b-0 last:pb-0">
      <span className="text-sm text-[#595959]">{label}</span>
      <span className="text-sm font-medium text-[#000000]">{value}</span>
    </div>
  );
}
