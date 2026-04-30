"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  BadgeDollarSign,
  Flame,
  ImageIcon,
  type LucideIcon,
  PackageCheck,
  ShoppingCart,
  Target,
  X,
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

type DashboardSummaryResponse = components["schemas"]["DashboardSummaryResponse"];
type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type StoreListingListResponse = components["schemas"]["StoreListingListResponse"];
type OrderListResponse = components["schemas"]["OrderListResponse"];
type OrderSummary = components["schemas"]["OrderSummary"];
type OrderDetail = components["schemas"]["OrderDetail"];
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
  pixel?: boolean;
  valueInvert?: boolean;
};

type ListingHealth = {
  all: number;
  buyable: number;
  notBuyable: number;
  platformDisabled: number;
  sellerDisabled: number;
};

type BiddingHealth = {
  active: number;
  blocked: number;
  floorMissing: number;
};

type RecentRecord = {
  id: string;
  title: string;
  detail: string;
  status: string;
  href: string;
};

type HotProduct = {
  sku: string;
  title: string;
  quantity: number;
  sales: number;
  lastSoldAt: string | null;
  imageUrl: string | null;
};

type ImagePreview = {
  title: string;
  imageUrl: string;
};

const emptyListingHealth: ListingHealth = {
  all: 0,
  buyable: 0,
  notBuyable: 0,
  platformDisabled: 0,
  sellerDisabled: 0,
};

const emptyBiddingHealth: BiddingHealth = {
  active: 0,
  blocked: 0,
  floorMissing: 0,
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
  const [summary, setSummary] = useState<DashboardSummaryResponse | null>(null);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [jobs, setJobs] = useState<ListingJob[]>([]);
  const [hotProducts, setHotProducts] = useState<HotProduct[]>([]);
  const [listingHealth, setListingHealth] = useState<ListingHealth>(emptyListingHealth);
  const [biddingHealth, setBiddingHealth] = useState<BiddingHealth>(emptyBiddingHealth);
  const [range, setRange] = useState<"7d" | "30d">("7d");
  const [imagePreview, setImagePreview] = useState<ImagePreview | null>(null);
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
      setBiddingHealth(emptyBiddingHealth);
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
        let blocked = 0;
        let floorMissing = 0;
        for (const group of ruleGroups) {
          for (const rule of group.rules) {
            if (rule.is_active) {
              activeSkuSet.add(`${rule.store_id}:${rule.sku}`);
              if (rule.buybox_status === "blocked" || rule.repricing_blocked_reason) {
                blocked += 1;
              }
              if (rule.floor_price == null) {
                floorMissing += 1;
              }
            }
          }
        }
        setBiddingHealth({ active: activeSkuSet.size, blocked, floorMissing });
      } catch {
        if (!isCancelled) {
          setBiddingHealth(emptyBiddingHealth);
        }
      }
    }

    void loadBiddingUsage();

    return () => {
      isCancelled = true;
    };
  }, [stores]);

  useEffect(() => {
    if (stores.length === 0) {
      setListingHealth(emptyListingHealth);
      return;
    }

    let isCancelled = false;

    async function loadListingHealth() {
      try {
        const listingGroups = await Promise.all(
          stores.map((store) =>
            apiFetch<StoreListingListResponse>(
              `/api/v1/stores/${encodeURIComponent(store.store_id)}/listings?limit=1`,
            ).catch(() => ({ listings: [], total: 0, limit: 1, offset: 0, status_counts: {} })),
          ),
        );
        if (isCancelled) return;
        const next = { ...emptyListingHealth };
        for (const group of listingGroups) {
          const counts = (group.status_counts ?? {}) as Record<string, unknown>;
          next.all += numberFromUnknown(counts.all) || group.total || 0;
          next.buyable += numberFromUnknown(counts.buyable);
          next.notBuyable += numberFromUnknown(counts.not_buyable);
          next.platformDisabled += numberFromUnknown(counts.platform_disabled);
          next.sellerDisabled += numberFromUnknown(counts.seller_disabled);
        }
        setListingHealth(next);
      } catch {
        if (!isCancelled) {
          setListingHealth(emptyListingHealth);
        }
      }
    }

    void loadListingHealth();

    return () => {
      isCancelled = true;
    };
  }, [stores]);

  useEffect(() => {
    if (orders.length === 0) {
      setHotProducts([]);
      return;
    }

    let isCancelled = false;

    async function loadHotProducts() {
      const recentOrders = orders.slice(0, 24);
      const details = await Promise.all(
        recentOrders.map((order) =>
          apiFetch<OrderDetail>(`/api/v1/orders/${encodeURIComponent(order.order_id)}`).catch(() => null),
        ),
      );
      if (isCancelled) return;
      const products = buildHotProducts(details.filter(Boolean) as OrderDetail[]);
      const enrichedProducts = await enrichHotProductTitles(products, stores);
      if (!isCancelled) {
        setHotProducts(enrichedProducts);
      }
    }

    void loadHotProducts();

    return () => {
      isCancelled = true;
    };
  }, [orders, stores]);

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
      const [summaryResult, storesResult, ordersResult, jobsResult] = await Promise.allSettled([
        apiFetch<DashboardSummaryResponse>("/api/v1/dashboard/summary"),
        apiFetch<StoreListResponse>("/api/v1/stores"),
        apiFetch<OrderListResponse>("/api/v1/orders"),
        apiFetch<ListingJobListResponse>("/api/listing/jobs"),
      ]);

      setSummary(readSettled<DashboardSummaryResponse | null>(summaryResult, null));
      setStores(readSettled(storesResult, { stores: [] }).stores);
      setOrders(readSettled(ordersResult, { orders: [] }).orders);
      setJobs(readSettled(jobsResult, { jobs: [] }).jobs);

      if ([summaryResult, storesResult, ordersResult, jobsResult].some((item) => item.status === "rejected")) {
        setErrorMessage("部分数据暂时不可用，已优先展示可读取内容。");
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载首页看板失败");
    } finally {
      setIsLoading(false);
    }
  }

  const businessTimezone = summary?.business_timezone ?? "Africa/Johannesburg";
  const viewerTimezone =
    summary?.viewer_timezone ?? Intl.DateTimeFormat().resolvedOptions().timeZone ?? "Asia/Shanghai";
  const businessDate = summary?.business_date ?? businessDateForNow(businessTimezone);
  const viewerDate = businessDateForNow(viewerTimezone);
  const businessTodayFromOrders = useMemo(
    () => buildTodayBusinessFromOrders(orders, businessDate, businessTimezone),
    [businessDate, businessTimezone, orders],
  );
  const viewerTodayFromOrders = useMemo(
    () => buildTodayBusinessFromOrders(orders, viewerDate, viewerTimezone),
    [orders, viewerDate, viewerTimezone],
  );
  const localTodayBusiness =
    businessTodayFromOrders.orderCount > 0 ? businessTodayFromOrders : viewerTodayFromOrders;
  const summaryTodayOrderCount = summary?.today_order_count ?? 0;
  const summaryTodaySalesQuantity = summary?.today_sales_quantity ?? 0;
  const summaryTodaySalesTotal = summary?.today_sales_total ?? 0;
  const shouldUseOrderFallback = localTodayBusiness.orderCount > 0 && summaryTodayOrderCount === 0;
  const todaySalesQuantity = shouldUseOrderFallback
    ? localTodayBusiness.salesQuantity
    : summaryTodaySalesQuantity;
  const todayOrderCount = shouldUseOrderFallback
    ? localTodayBusiness.orderCount
    : summaryTodayOrderCount;
  const todaySalesTotal = shouldUseOrderFallback
    ? localTodayBusiness.salesTotal
    : summaryTodaySalesTotal;
  const usedViewerFallback =
    shouldUseOrderFallback &&
    businessTodayFromOrders.orderCount === 0 &&
    viewerTodayFromOrders.orderCount > 0;
  const businessDayCaption = usedViewerFallback
    ? `订单中心 ${viewerDate}`
    : businessDate
      ? `南非 ${businessDate}`
      : "南非业务日";
  const listingRiskCount =
    listingHealth.notBuyable + listingHealth.platformDisabled + listingHealth.sellerDisabled;
  const completedChart30d = useMemo(
    () => withoutCurrentBusinessDay(summary?.chart_30d ?? buildChartData(orders, 30), summary?.business_date),
    [orders, summary],
  );
  const completedChart7d = useMemo(() => completedChart30d.slice(-7), [completedChart30d]);
  const latestCompletedPoint = completedChart30d.at(-1) ?? null;

  const kpis: KpiCard[] = [
    {
      title: "今日生意",
      value: `${todayOrderCount} 单`,
      icon: ShoppingCart,
      caption: `${formatMoney(todaySalesTotal)} · ${todaySalesQuantity} 件 · ${businessDayCaption}`,
    },
    {
      title: "商品可售",
      value: `${listingHealth.buyable}/${listingHealth.all}`,
      icon: PackageCheck,
      valueInvert: true,
      caption:
        listingRiskCount > 0
          ? `不可售 ${listingHealth.notBuyable} · 禁用 ${
              listingHealth.platformDisabled + listingHealth.sellerDisabled
            }`
          : "当前商品状态正常",
    },
    {
      title: "自动竞价",
      value: `${biddingHealth.active} 个`,
      icon: Target,
      caption: `阻断 ${biddingHealth.blocked} · 未设底价 ${biddingHealth.floorMissing}`,
      danger: biddingHealth.blocked > 0,
      pixel: true,
    },
  ];

  const chartData = range === "7d" ? completedChart7d : completedChart30d;

  const recentRecords = useMemo(() => buildRecentRecords(orders, jobs, stores), [jobs, orders, stores]);
  const storeStatusText = stores.length ? stores.map((store) => store.name).join("、") : "未接入店铺";
  const orderSyncText = summary?.order_data_status.is_stale ? "订单同步更新中" : "订单同步正常";
  const autobidStatusText =
    biddingHealth.active > 0 ? `自动竞价监控 ${biddingHealth.active} 个` : "自动竞价未开启";

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
          <div className="flex flex-wrap gap-2 pt-2 text-xs text-[#595959]">
            <span className="rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-2.5 py-1">
              {storeStatusText}
            </span>
            <span className="rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-2.5 py-1">
              {orderSyncText}
            </span>
            <span className="rounded-[4px] border border-[#EBEBEB] bg-[#FFFFFF] px-2.5 py-1">
              {autobidStatusText}
            </span>
          </div>
        </div>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      <section className="grid gap-4 md:grid-cols-3">
        {kpis.map((item) => {
          const Icon = item.icon;
          return (
            <article
              key={item.title}
              className={
                item.pixel
                  ? "rounded-[4px] border-2 border-[#111111] bg-[#FFFFFF] p-5 shadow-[4px_4px_0_#111111]"
                  : "rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5"
              }
            >
              <div className="mb-4 flex items-center justify-between">
                <div className="flex items-center gap-2 text-sm text-[#595959]">
                  {item.danger ? <span className="h-2 w-2 rounded-full bg-[#D9363E]" /> : null}
                  {item.pixel && !item.danger ? (
                    <span className="h-2.5 w-2.5 border border-[#111111] bg-[#22C55E]" />
                  ) : null}
                  <span>{item.title}</span>
                </div>
                <div
                  className={
                    item.pixel
                      ? "flex h-7 w-7 items-center justify-center border border-[#111111] bg-[#FFDF57]"
                      : ""
                  }
                >
                  <Icon className="h-4 w-4 text-[#595959] stroke-[1.8]" />
                </div>
              </div>
              <div
                className={[
                  "text-3xl font-bold tracking-[-0.04em]",
                  item.danger ? "text-[#D9363E]" : item.valueInvert ? "text-[#FFFFFF]" : "text-[#000000]",
                ].join(" ")}
              >
                <span
                  className={
                    item.valueInvert
                      ? "inline-flex border-2 border-[#111111] bg-[#111111] px-2 py-1 leading-none shadow-[3px_3px_0_#D4D4D4]"
                      : ""
                  }
                >
                  {isLoading ? "--" : item.value}
                </span>
              </div>
              {item.caption ? (
                <div className="mt-3 text-xs text-[#595959]">{item.caption}</div>
              ) : null}
            </article>
          );
        })}
      </section>

      <section className="grid items-start gap-4">
        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Flame className="h-4 w-4 text-[#595959] stroke-[1.8]" />
              <div className="text-base font-semibold text-[#000000]">最近热销商品</div>
            </div>
            <div className="text-xs text-[#595959]">按最近订单聚合</div>
          </div>
          {hotProducts.length ? (
            <div className="divide-y divide-[#EBEBEB]">
              {hotProducts.slice(0, 5).map((product, index) => (
                <div
                  key={product.sku}
                  className="grid gap-3 py-3 first:pt-0 last:pb-0 sm:grid-cols-[32px_48px_minmax(0,1fr)_120px]"
                >
                  <div className="flex h-7 w-7 items-center justify-center rounded-[4px] border border-[#EBEBEB] text-xs font-semibold text-[#595959]">
                    {index + 1}
                  </div>
                  {product.imageUrl ? (
                    <button
                      type="button"
                      onClick={() =>
                        setImagePreview({
                          title: product.title,
                          imageUrl: product.imageUrl ?? "",
                        })
                      }
                      className="h-11 w-11 overflow-hidden rounded-[4px] border border-[#EBEBEB] bg-[#FAFAFA]"
                      aria-label="放大商品图片"
                    >
                      <img
                        src={product.imageUrl}
                        alt={product.title}
                        className="h-full w-full object-cover"
                      />
                    </button>
                  ) : (
                    <div className="flex h-11 w-11 items-center justify-center rounded-[4px] border border-[#EBEBEB] bg-[#FAFAFA] text-[#595959]">
                      <ImageIcon className="h-4 w-4 stroke-[1.8]" />
                    </div>
                  )}
                  <div className="min-w-0">
                    <Link
                      href={`/products?q=${encodeURIComponent(product.sku)}`}
                      className="block truncate text-sm font-medium text-[#000000] hover:text-[#2F6F63]"
                    >
                      {product.title}
                    </Link>
                    <div className="mt-1 text-xs text-[#595959]">
                      SKU {product.sku} · 最近 {formatBusinessDateTime(product.lastSoldAt)}
                    </div>
                  </div>
                  <div className="text-left sm:text-right">
                    <div className="text-sm font-semibold text-[#000000]">{product.quantity} 件</div>
                    <div className="mt-1 text-xs text-[#595959]">{formatMoney(product.sales)}</div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="rounded-[4px] border border-[#EBEBEB] bg-[#FAFAFA] px-4 py-8 text-sm text-[#595959]">
              暂无可聚合的订单商品。
            </div>
          )}
        </article>
      </section>

      <section className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          <div className="mb-5 flex flex-col gap-3 border-b border-[#EBEBEB] pb-4 md:flex-row md:items-center md:justify-between">
            <div>
              <div className="flex items-center gap-2 text-base font-semibold text-[#000000]">
                <BadgeDollarSign className="h-4 w-4 text-[#595959] stroke-[1.8]" />
                最近完整日销售
              </div>
              <div className="mt-1 text-xs text-[#595959]">
                {latestCompletedPoint
                  ? `${latestCompletedPoint.date} ${formatMoney(latestCompletedPoint.sales)} · ${
                      latestCompletedPoint.volume
                    } 件`
                  : "等待订单同步"}
              </div>
            </div>
            <div className="inline-flex items-center border-2 border-[#111111] bg-[#FFFFFF] p-1 text-sm text-[#595959] shadow-[3px_3px_0_#111111]">
              <button
                type="button"
                className={[
                  "h-8 border border-transparent px-3 text-xs font-black transition",
                  range === "7d"
                    ? "border-[#111111] bg-[#111111] text-[#FFFFFF]"
                    : "bg-[#FFF7CC] text-[#111111] hover:bg-[#FFDF57]",
                ].join(" ")}
                onClick={() => setRange("7d")}
              >
                7 日
              </button>
              <button
                type="button"
                className={[
                  "h-8 border border-transparent px-3 text-xs font-black transition",
                  range === "30d"
                    ? "border-[#111111] bg-[#111111] text-[#FFFFFF]"
                    : "bg-[#FFF7CC] text-[#111111] hover:bg-[#FFDF57]",
                ].join(" ")}
                onClick={() => setRange("30d")}
              >
                30 日
              </button>
            </div>
          </div>

          <div ref={chartContainerRef} className="h-[190px] w-full min-w-0">
            {chartWidth > 0 ? (
              <LineChart
                width={chartWidth}
                height={190}
                data={chartData}
                margin={{ top: 8, right: 4, left: 4, bottom: 0 }}
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
        </article>

        <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
          <div className="mb-4 flex items-center justify-between">
            <div className="text-base font-semibold text-[#000000]">最近订单</div>
            <Link
              href="/orders"
              className="inline-flex h-7 items-center border-2 border-[#111111] bg-[#FFF7CC] px-2.5 text-xs font-black text-[#111111] shadow-[2px_2px_0_#111111] hover:bg-[#FFDF57]"
            >
              查看全部
            </Link>
          </div>
          <div className="divide-y divide-[#EBEBEB]">
            {recentRecords.slice(0, 4).map((record) => (
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
              <div className="py-6 text-sm text-[#595959]">暂无最近订单。</div>
            ) : null}
          </div>
        </article>
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

function buildTodayBusinessFromOrders(
  orders: OrderSummary[],
  businessDate: string,
  businessTimezone = "Africa/Johannesburg",
) {
  const todayOrders = orders.filter((order) => {
    const source = order.placed_at ?? order.created_at;
    return source ? dateKeyInTimezone(source, businessTimezone) === businessDate : false;
  });

  return {
    orderCount: todayOrders.length,
    salesQuantity: todayOrders.reduce((sum, order) => sum + (order.item_count ?? 0), 0),
    salesTotal: todayOrders.reduce((sum, order) => sum + (order.total_amount ?? 0), 0),
  };
}

function businessDateForNow(businessTimezone = "Africa/Johannesburg") {
  return dateKeyInTimezone(new Date().toISOString(), businessTimezone);
}

function dateKeyInTimezone(value: string, timeZone: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  try {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(date);
    const partMap = new Map(parts.map((part) => [part.type, part.value]));
    return `${partMap.get("year")}-${partMap.get("month")}-${partMap.get("day")}`;
  } catch (_) {
    return "";
  }
}

function withoutCurrentBusinessDay(points: ChartPoint[], businessDate: string | undefined) {
  if (!businessDate) return points;
  const currentKey = businessDateKey(businessDate);
  return points.filter((point) => point.date !== currentKey);
}

function businessDateKey(value: string) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  return match ? `${match[2]}-${match[3]}` : value;
}

function numberFromUnknown(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }
  return 0;
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
    )} · ${order.item_count} 件商品 · 南非 ${formatBusinessDateTime(
      order.placed_at ?? order.created_at,
    )}`,
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

function buildHotProducts(orderDetails: OrderDetail[]): HotProduct[] {
  const bySku = new Map<string, HotProduct>();

  for (const order of orderDetails) {
    const soldAt = order.placed_at ?? order.created_at ?? null;
    for (const item of order.items ?? []) {
      const sku = String(item.sku || item.external_order_item_id || "").trim();
      if (!sku) continue;
      const payload = (item.raw_payload ?? {}) as Record<string, unknown>;
      const quantity = Math.max(0, Number(item.quantity || 0));
      const unitPrice =
        item.unit_price ??
        numberFromUnknown(payload.selling_price) ??
        numberFromUnknown(payload.price) ??
        0;
      const imageUrl = extractImageUrl(payload);
      const current = bySku.get(sku) ?? {
        sku,
        title: item.title || sku,
        quantity: 0,
        sales: 0,
        lastSoldAt: null,
        imageUrl,
      };
      current.quantity += quantity;
      current.sales += quantity * unitPrice;
      if (!current.lastSoldAt || (soldAt && new Date(soldAt) > new Date(current.lastSoldAt))) {
        current.lastSoldAt = soldAt;
      }
      if ((!current.title || current.title === sku) && item.title) {
        current.title = item.title;
      }
      if (!current.imageUrl && imageUrl) {
        current.imageUrl = imageUrl;
      }
      bySku.set(sku, current);
    }
  }

  return Array.from(bySku.values()).sort((left, right) => {
    if (right.quantity !== left.quantity) return right.quantity - left.quantity;
    if (right.sales !== left.sales) return right.sales - left.sales;
    return String(right.lastSoldAt ?? "").localeCompare(String(left.lastSoldAt ?? ""));
  });
}

async function enrichHotProductTitles(products: HotProduct[], stores: StoreSummary[]) {
  if (!products.length || !stores.length) return products;

  const enriched = new Map<string, HotProduct>();
  await Promise.all(
    products.slice(0, 5).map(async (product) => {
      for (const store of stores) {
        try {
          const response = await apiFetch<StoreListingListResponse>(
            `/api/v1/stores/${encodeURIComponent(store.store_id)}/listings?q=${encodeURIComponent(
              product.sku,
            )}&limit=1`,
          );
          const listing =
            response.listings.find((item) => item.sku === product.sku) ?? response.listings[0];
          if (listing) {
            const imageUrl = extractImageUrl(listing.raw_payload);
            enriched.set(product.sku, {
              ...product,
              title: product.title && product.title !== product.sku ? product.title : listing.title,
              imageUrl: product.imageUrl || imageUrl,
            });
            return;
          }
        } catch {
          // Title enrichment is best effort; the SKU still makes the row usable.
        }
      }
    }),
  );

  return products.map((product) => enriched.get(product.sku) ?? product);
}

function extractImageUrl(payload: { [key: string]: unknown } | null | undefined) {
  return (
    payloadValue(payload, "image_url") ??
    payloadValue(payload, "imageUrl") ??
    payloadValue(payload, "thumbnail_url") ??
    payloadValue(payload, "thumbnailUrl") ??
    findFirstImageUrl(payload)
  );
}

function payloadValue(payload: { [key: string]: unknown } | null | undefined, key: string) {
  const value = payload?.[key];
  if (typeof value === "string" && value.trim()) return value.trim();
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

function formatBusinessDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Africa/Johannesburg",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

function formatMoney(value: number | null | undefined, currency = "ZAR") {
  if (value == null) return "R 0";
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
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
