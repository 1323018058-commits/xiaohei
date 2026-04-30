"use client";

import { useMemo, useState } from "react";
import {
  ArrowRight,
  BadgeAlert,
  Boxes,
  ClipboardList,
  Gauge,
  PackageSearch,
  ShoppingCart,
  Store,
  Truck,
} from "lucide-react";
import {
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ChartPoint = {
  date: string;
  sales: number;
  volume: number;
};

const sidebarItems = [
  { label: "工作台", icon: Gauge, active: true },
  { label: "店铺管理", icon: Store, active: false },
  { label: "商品管理", icon: Boxes, active: false },
  { label: "自动竞价", icon: BadgeAlert, active: false },
  { label: "上架记录", icon: PackageSearch, active: false },
  { label: "订单中心", icon: ShoppingCart, active: false },
  { label: "履约中心", icon: Truck, active: false },
] as const;

const kpis = [
  { label: "今日订单", value: "128", accent: "default" as const },
  { label: "今日销售额", value: "R 12,450", accent: "default" as const },
  { label: "今日已上架", value: "45", accent: "default" as const },
  { label: "今日上架异常", value: "3", accent: "danger" as const },
] as const;

const chart7d: ChartPoint[] = [
  { date: "04-19", sales: 9200, volume: 72 },
  { date: "04-20", sales: 10100, volume: 84 },
  { date: "04-21", sales: 11250, volume: 91 },
  { date: "04-22", sales: 10850, volume: 88 },
  { date: "04-23", sales: 12030, volume: 101 },
  { date: "04-24", sales: 11840, volume: 97 },
  { date: "04-25", sales: 12450, volume: 128 },
];

const chart30d: ChartPoint[] = [
  { date: "03-27", sales: 6500, volume: 51 },
  { date: "03-30", sales: 7100, volume: 58 },
  { date: "04-02", sales: 7700, volume: 63 },
  { date: "04-05", sales: 8200, volume: 67 },
  { date: "04-08", sales: 8600, volume: 72 },
  { date: "04-11", sales: 9300, volume: 78 },
  { date: "04-14", sales: 9950, volume: 82 },
  { date: "04-17", sales: 10700, volume: 89 },
  { date: "04-20", sales: 11400, volume: 95 },
  { date: "04-23", sales: 11900, volume: 106 },
  { date: "04-25", sales: 12450, volume: 128 },
];

const storeHealthRows = [
  {
    name: "King Store",
    platform: "Takealot",
    statusLabel: "正常",
    statusTone: "default" as const,
    syncedAgo: "10分钟前",
    action: null,
  },
  {
    name: "Alpha Shop",
    platform: "Takealot",
    statusLabel: "授权失效",
    statusTone: "danger" as const,
    syncedAgo: "2天前",
    action: "去处理",
  },
] as const;

const pendingActions = [
  "你有 12 个订单待生成 PO 单",
  "昨日有 3 个商品上架失败 (条码冲突)",
] as const;

export function B2BSaaSErpDashboard() {
  const [range, setRange] = useState<"7d" | "30d">("7d");
  const chartData = useMemo(() => (range === "7d" ? chart7d : chart30d), [range]);

  return (
    <div className="min-h-screen bg-[#FAFAFA] text-[#000000]">
      <div className="flex min-h-screen flex-col lg:flex-row">
        <aside className="w-full border-b border-[#EBEBEB] bg-[#FAFAFA] lg:w-64 lg:border-b-0 lg:border-r">
          <div className="flex h-full flex-col gap-8 px-4 py-6">
            <div className="space-y-1">
              <div className="text-[11px] font-medium uppercase tracking-[0.18em] text-[#595959]">
                ERP Console
              </div>
              <div className="text-lg font-semibold tracking-[-0.02em] text-[#000000]">
                XiaoHei OS
              </div>
            </div>

            <nav className="flex gap-2 overflow-x-auto pb-1 lg:grid lg:gap-1 lg:overflow-visible">
              {sidebarItems.map((item) => {
                const Icon = item.icon;
                return (
                  <button
                    key={item.label}
                    type="button"
                    className={[
                      "inline-flex min-w-fit items-center gap-3 rounded-[6px] border px-3 py-2 text-sm transition-colors lg:w-full",
                      item.active
                        ? "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000]"
                        : "border-transparent bg-transparent text-[#595959] hover:border-[#EBEBEB] hover:bg-[#FFFFFF]",
                    ].join(" ")}
                  >
                    <Icon className="h-4 w-4 stroke-[1.75]" />
                    <span className="whitespace-nowrap">{item.label}</span>
                  </button>
                );
              })}
            </nav>
          </div>
        </aside>

        <main className="min-w-0 flex-1 p-6">
          <header className="mb-6 flex items-center justify-between">
            <div className="space-y-1">
              <div className="text-xs font-medium text-[#595959]">工作台</div>
              <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
                B2B SaaS ERP Dashboard
              </h1>
            </div>
          </header>

          <div className="grid gap-6">
            <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
              {kpis.map((item) => (
                <article
                  key={item.label}
                  className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5"
                >
                  <div className="mb-4 flex items-center gap-2 text-sm text-[#595959]">
                    {item.accent === "danger" ? (
                      <span className="inline-flex h-2 w-2 rounded-full bg-[#D9363E]" />
                    ) : null}
                    <span>{item.label}</span>
                  </div>
                  <div
                    className={[
                      "text-3xl font-bold tracking-[-0.04em]",
                      item.accent === "danger" ? "text-[#D9363E]" : "text-[#000000]",
                    ].join(" ")}
                  >
                    {item.value}
                  </div>
                </article>
              ))}
            </section>

            <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5">
              <div className="mb-6 flex flex-col gap-4 border-b border-[#EBEBEB] pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-base font-semibold text-[#000000]">
                  销售与单量趋势
                </div>
                <div className="flex items-center gap-2 text-sm text-[#595959]">
                  <button
                    type="button"
                    onClick={() => setRange("7d")}
                    className={range === "7d" ? "text-[#000000]" : "text-[#595959]"}
                  >
                    最近 7 天
                  </button>
                  <span>/</span>
                  <button
                    type="button"
                    onClick={() => setRange("30d")}
                    className={range === "30d" ? "text-[#000000]" : "text-[#595959]"}
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

              <div className="h-[280px] w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={chartData} margin={{ top: 8, right: 4, left: 4, bottom: 0 }}>
                    <XAxis
                      dataKey="date"
                      axisLine={false}
                      tickLine={false}
                      tick={{ fill: "#595959", fontSize: 12 }}
                    />
                    <YAxis hide />
                    <Tooltip
                      cursor={false}
                      content={<DashboardTooltip />}
                    />
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
                      stroke="#B3B3B3"
                      strokeWidth={2}
                      strokeDasharray="6 6"
                      dot={false}
                      activeDot={{ r: 3, fill: "#B3B3B3", stroke: "#B3B3B3" }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section className="grid gap-6 xl:grid-cols-10">
              <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5 xl:col-span-6">
                <div className="mb-4 flex items-center justify-between">
                  <div className="text-base font-semibold text-[#000000]">店铺健康</div>
                  <div className="text-xs text-[#595959]">同步与授权状态</div>
                </div>

                <div className="overflow-x-auto">
                  <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b border-[#EBEBEB] text-[#595959]">
                        <th className="pb-3 font-medium">店铺名称</th>
                        <th className="pb-3 font-medium">平台</th>
                        <th className="pb-3 font-medium">凭证状态</th>
                        <th className="pb-3 font-medium">距上次同步</th>
                      </tr>
                    </thead>
                    <tbody>
                      {storeHealthRows.map((row) => (
                        <tr key={row.name} className="border-b border-[#EBEBEB] last:border-b-0">
                          <td className="py-4 pr-4 font-medium text-[#000000]">{row.name}</td>
                          <td className="py-4 pr-4 text-[#595959]">{row.platform}</td>
                          <td className="py-4 pr-4">
                            <div
                              className={[
                                "inline-flex items-center gap-2 text-sm",
                                row.statusTone === "danger" ? "text-[#D9363E]" : "text-[#000000]",
                              ].join(" ")}
                            >
                              <span
                                className={[
                                  "h-2 w-2 rounded-full",
                                  row.statusTone === "danger" ? "bg-[#D9363E]" : "bg-[#000000]",
                                ].join(" ")}
                              />
                              <span>{row.statusLabel}</span>
                            </div>
                          </td>
                          <td className="py-4 text-[#595959]">
                            <div className="flex items-center justify-between gap-4">
                              <span>{row.syncedAgo}</span>
                              {row.action ? (
                                <button
                                  type="button"
                                  className="inline-flex items-center gap-1 text-sm text-[#000000] underline decoration-[#000000]/20 underline-offset-4"
                                >
                                  {row.action}
                                  <ArrowRight className="h-3.5 w-3.5" />
                                </button>
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
                <div className="mb-4 text-base font-semibold text-[#000000]">待处理事项</div>
                <div className="divide-y divide-[#EBEBEB]">
                  {pendingActions.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className="flex w-full items-center justify-between gap-4 py-4 text-left first:pt-0 last:pb-0"
                    >
                      <span className="text-sm leading-6 text-[#000000]">
                        {item}
                        <span className="ml-1 text-[#595959]">👉 去处理</span>
                      </span>
                      <ArrowRight className="h-4 w-4 flex-none text-[#595959]" />
                    </button>
                  ))}
                </div>
              </article>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

type DashboardTooltipProps = {
  active?: boolean;
  payload?: Array<{ value: number; dataKey: string }>;
  label?: string;
};

function DashboardTooltip({ active, payload, label }: DashboardTooltipProps) {
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

export default B2BSaaSErpDashboard;
