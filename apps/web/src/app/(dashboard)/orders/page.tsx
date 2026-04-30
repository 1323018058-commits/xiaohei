"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Package,
  Search,
  ShoppingBag,
  type LucideIcon,
  X,
} from "lucide-react";
import type { ReactNode } from "react";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type OrderListResponse = components["schemas"]["OrderListResponse"];
type OrderSummary = components["schemas"]["OrderSummary"];
type OrderDetail = components["schemas"]["OrderDetail"];
type OrderItem = components["schemas"]["OrderItemResponse"];
type OrderEvent = components["schemas"]["OrderEventResponse"];

const STATUS_OPTIONS = [
  { value: "all", label: "全部状态" },
  { value: "new", label: "新订单" },
  { value: "processing", label: "处理中" },
  { value: "delivered", label: "已完成" },
  { value: "cancelled", label: "已取消" },
];

export default function OrdersPage() {
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [orders, setOrders] = useState<OrderSummary[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<OrderDetail | null>(null);
  const [storeFilter, setStoreFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");

  const storeNameMap = useMemo(
    () => new Map(stores.map((store) => [store.store_id, store.name])),
    [stores],
  );

  const totalSales = useMemo(
    () => orders.reduce((sum, order) => sum + (order.total_amount ?? 0), 0),
    [orders],
  );

  const activeOrders = useMemo(
    () =>
      orders.filter((order) => {
        const status = order.status.toLowerCase();
        return !["delivered", "cancelled", "completed"].includes(status);
      }).length,
    [orders],
  );

  const unsyncedOrders = useMemo(
    () => orders.filter((order) => !order.last_synced_at).length,
    [orders],
  );

  useEffect(() => {
    void loadStoresAndOrders();
  }, []);

  async function loadStoresAndOrders() {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const storeData = await apiFetch<StoreListResponse>("/api/v1/stores");
      setStores(storeData.stores);
      await loadOrders();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载订单中心失败");
      setStores([]);
      setOrders([]);
      setSelectedOrder(null);
      setIsLoading(false);
    }
  }

  async function loadOrders(targetOrderId?: string | null) {
    setIsLoading(true);
    setErrorMessage("");

    try {
      const params = new URLSearchParams();
      if (storeFilter !== "all") params.set("store_id", storeFilter);
      if (statusFilter !== "all") params.set("status", statusFilter);
      if (query.trim()) params.set("q", query.trim());

      const data = await apiFetch<OrderListResponse>(
        `/api/v1/orders${params.toString() ? `?${params}` : ""}`,
      );

      setOrders(data.orders);

      const nextId =
        targetOrderId && data.orders.some((order) => order.order_id === targetOrderId)
          ? targetOrderId
          : data.orders[0]?.order_id ?? null;

      if (nextId) {
        await loadOrderDetail(nextId);
      } else {
        setSelectedOrder(null);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载订单失败");
      setOrders([]);
      setSelectedOrder(null);
    } finally {
      setIsLoading(false);
    }
  }

  async function loadOrderDetail(orderId: string) {
    try {
      const detail = await apiFetch<OrderDetail>(
        `/api/v1/orders/${encodeURIComponent(orderId)}`,
      );
      setSelectedOrder(detail);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载订单详情失败");
    }
  }

  return (
    <div className="space-y-4 bg-[#FAFAFA] text-[#000000]">
      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-medium text-[#595959]">订单中心</div>
          <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
            订单中心
          </h1>
          <p className="text-sm leading-6 text-[#595959]">
            后台自动同步订单，页面只保留金额、履约状态和平台事件。
          </p>
        </div>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="订单数" value={isLoading ? "--" : String(orders.length)} />
        <MetricCard label="销售额" value={isLoading ? "--" : formatMoney(totalSales)} />
        <MetricCard label="待处理" value={isLoading ? "--" : String(activeOrders)} />
        <MetricCard label="未同步" value={isLoading ? "--" : String(unsyncedOrders)} />
      </section>

      <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-3">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center">
          <select
            value={storeFilter}
            onChange={(event) => setStoreFilter(event.target.value)}
            className="h-9 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none"
          >
            <option value="all">全部店铺</option>
            {stores.map((store) => (
              <option key={store.store_id} value={store.store_id}>
                {store.name}
              </option>
            ))}
          </select>

          <select
            value={statusFilter}
            onChange={(event) => setStatusFilter(event.target.value)}
            className="h-9 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none"
          >
            {STATUS_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>

          <label className="relative min-w-0 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索订单号 / SKU"
              className="h-9 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] pl-9 pr-3 text-sm text-[#000000] outline-none placeholder:text-[#595959]"
            />
          </label>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void loadOrders(null)}
              className="inline-flex h-9 items-center justify-center rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm font-medium text-[#000000]"
            >
              应用筛选
            </button>
            <span className="whitespace-nowrap text-sm text-[#595959]">
              {isLoading ? "加载中" : `${orders.length} 条订单`}
            </span>
          </div>
        </div>
      </section>

      <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_420px]">
        <div className="overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
          <div className="overflow-x-auto">
            <table className="min-w-[900px] w-full border-collapse text-left">
              <thead>
                <tr className="border-b border-[#EBEBEB] text-xs text-[#595959]">
                  <th className="h-11 px-4 font-medium">订单号</th>
                  <th className="h-11 px-4 font-medium">店铺</th>
                  <th className="h-11 px-4 font-medium">下单时间</th>
                  <th className="h-11 px-4 text-right font-medium">金额</th>
                  <th className="h-11 px-4 text-right font-medium">商品数</th>
                  <th className="h-11 px-4 font-medium">订单状态</th>
                  <th className="h-11 px-4 font-medium">履约状态</th>
                  <th className="h-11 px-4 font-medium">最近同步</th>
                </tr>
              </thead>
              <tbody>
                {orders.map((order) => (
                  <OrderRow
                    key={order.order_id}
                    order={order}
                    storeName={storeNameMap.get(order.store_id) ?? shortId(order.store_id)}
                    active={selectedOrder?.order_id === order.order_id}
                    onSelect={() => void loadOrderDetail(order.order_id)}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {!isLoading && orders.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[#595959]">
              暂无订单。可以先同步店铺订单。
            </div>
          ) : null}
        </div>

        <aside className="hidden 2xl:block">
          <OrderDetailPanel
            order={selectedOrder}
            storeName={
              selectedOrder
                ? storeNameMap.get(selectedOrder.store_id) ?? shortId(selectedOrder.store_id)
                : ""
            }
          />
        </aside>
      </section>

      {selectedOrder ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/10 2xl:hidden">
          <aside className="h-screen w-full max-w-[460px] border-l border-[#EBEBEB] bg-[#FFFFFF]">
            <div className="flex h-full flex-col">
              <div className="flex items-center justify-between border-b border-[#EBEBEB] px-5 py-4">
                <div className="text-base font-semibold text-[#000000]">订单详情</div>
                <button
                  type="button"
                  onClick={() => setSelectedOrder(null)}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959]"
                  aria-label="关闭订单详情"
                >
                  <X className="h-4 w-4 stroke-[1.8]" />
                </button>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-5">
                <OrderDetailPanel
                  order={selectedOrder}
                  storeName={storeNameMap.get(selectedOrder.store_id) ?? shortId(selectedOrder.store_id)}
                  unframed
                />
              </div>
            </div>
          </aside>
        </div>
      ) : null}
    </div>
  );
}

function MetricCard({ label, value }: { label: string; value: string }) {
  return (
    <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4">
      <div className="text-sm text-[#595959]">{label}</div>
      <div className="mt-3 text-2xl font-semibold tracking-[-0.03em] text-[#000000]">
        {value}
      </div>
    </article>
  );
}

function OrderRow({
  order,
  storeName,
  active,
  onSelect,
}: {
  order: OrderSummary;
  storeName: string;
  active: boolean;
  onSelect: () => void;
}) {
  const primaryOrderNumber = order.order_number ?? order.external_order_id ?? order.order_id;
  const secondaryOrderNumber =
    order.external_order_id && order.external_order_id !== primaryOrderNumber
      ? order.external_order_id
      : null;

  return (
    <tr
      onClick={onSelect}
      className={[
        "cursor-pointer border-b border-[#EBEBEB] text-sm last:border-b-0 hover:bg-[#FAFAFA]",
        active ? "bg-[#FAFAFA]" : "",
      ].join(" ")}
    >
      <td className="px-4 py-3 align-top">
        <div className="font-medium leading-5 text-[#000000]">
          {primaryOrderNumber}
        </div>
        {secondaryOrderNumber ? (
          <div className="mt-1 max-w-[220px] truncate text-xs text-[#595959]">
            {secondaryOrderNumber}
          </div>
        ) : null}
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top text-[#000000]">
        {storeName}
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top text-[#595959]">
        {formatDateTime(order.placed_at)}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right align-top font-medium text-[#000000]">
        {formatMoney(order.total_amount, order.currency)}
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-right align-top text-[#595959]">
        {order.item_count}
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top">
        <StatusText status={formatOrderStatus(order.status)} />
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top text-[#595959]">
        {formatFulfillment(order.fulfillment_status)}
      </td>
      <td className="whitespace-nowrap px-4 py-3 align-top text-[#595959]">
        {formatDateTime(order.last_synced_at)}
      </td>
    </tr>
  );
}

function OrderDetailPanel({
  order,
  storeName,
  unframed = false,
}: {
  order: OrderDetail | null;
  storeName: string;
  unframed?: boolean;
}) {
  if (!order) {
    return (
      <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-6 py-10 text-center text-sm text-[#595959]">
        选择订单查看详情。
      </div>
    );
  }
  const primaryOrderNumber = order.order_number ?? order.external_order_id ?? order.order_id;
  const secondaryOrderNumber =
    order.external_order_id && order.external_order_id !== primaryOrderNumber
      ? order.external_order_id
      : null;

  return (
    <div
      className={[
        "space-y-5",
        unframed ? "" : "rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-5",
      ].join(" ")}
    >
      <section className="space-y-3">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="text-xs text-[#595959]">{storeName}</div>
            <div className="mt-1 break-words text-xl font-semibold tracking-[-0.03em] text-[#000000]">
              {primaryOrderNumber}
            </div>
            {secondaryOrderNumber ? (
              <div className="mt-2 text-xs text-[#595959]">
                {secondaryOrderNumber}
              </div>
            ) : null}
          </div>
          <StatusText status={formatOrderStatus(order.status)} />
        </div>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <DetailMetric label="金额" value={formatMoney(order.total_amount, order.currency)} />
        <DetailMetric label="商品数" value={`${order.item_count} 件`} />
        <DetailMetric label="履约" value={formatFulfillment(order.fulfillment_status)} />
        <DetailMetric label="同步" value={formatDateTime(order.last_synced_at)} />
      </section>

      <DetailSection title="商品明细" icon={Package}>
        {order.items.length > 0 ? (
          <div className="divide-y divide-[#EBEBEB]">
            {order.items.map((item) => (
              <OrderItemRow key={item.item_id} item={item} currency={order.currency} />
            ))}
          </div>
        ) : (
          <EmptyLine text="暂无商品明细" />
        )}
      </DetailSection>

      <DetailSection title="订单事件" icon={ShoppingBag}>
        {order.events.length > 0 ? (
          <div className="divide-y divide-[#EBEBEB]">
            {order.events.slice(0, 6).map((event) => (
              <OrderEventRow key={event.event_id} event={event} />
            ))}
          </div>
        ) : (
          <EmptyLine text="暂无事件" />
        )}
      </DetailSection>

      <div className="text-xs leading-5 text-[#595959]">
        Order ID: {order.order_id}
      </div>
    </div>
  );
}

function DetailMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2.5">
      <div className="text-xs text-[#595959]">{label}</div>
      <div className="mt-1 text-sm font-medium text-[#000000]">{value}</div>
    </div>
  );
}

function DetailSection({
  title,
  icon: Icon,
  children,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
}) {
  return (
    <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
      <div className="flex items-center gap-2 border-b border-[#EBEBEB] px-4 py-3 text-sm font-medium text-[#000000]">
        <Icon className="h-4 w-4 text-[#595959] stroke-[1.8]" />
        {title}
      </div>
      <div className="px-4">{children}</div>
    </section>
  );
}

function OrderItemRow({ item, currency }: { item: OrderItem; currency: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 text-sm">
      <div className="min-w-0">
        <div className="font-medium text-[#000000]">{item.sku}</div>
        <div className="mt-1 line-clamp-2 text-xs leading-5 text-[#595959]">
          {item.title ?? "未命名商品"}
        </div>
      </div>
      <div className="whitespace-nowrap text-right text-[#595959]">
        {formatMoney(item.unit_price, currency)} x {item.quantity}
      </div>
    </div>
  );
}

function OrderEventRow({ event }: { event: OrderEvent }) {
  return (
    <div className="flex items-start justify-between gap-4 py-3 text-sm">
      <div className="min-w-0">
        <div className="font-medium text-[#000000]">{event.event_type}</div>
        <div className="mt-1 line-clamp-2 text-xs leading-5 text-[#595959]">
          {event.message ?? "无说明"}
        </div>
      </div>
      <div className="whitespace-nowrap text-xs text-[#595959]">
        {formatDateTime(event.occurred_at)}
      </div>
    </div>
  );
}

function StatusText({ status }: { status: string }) {
  const isCancelled = status === "已取消";

  return (
    <span
      className={[
        "inline-flex items-center gap-2 text-sm",
        isCancelled ? "text-[#D9363E]" : "text-[#000000]",
      ].join(" ")}
    >
      <span
        className={[
          "h-1.5 w-1.5 rounded-full",
          isCancelled ? "bg-[#D9363E]" : "bg-[#000000]",
        ].join(" ")}
      />
      {status}
    </span>
  );
}

function EmptyLine({ text }: { text: string }) {
  return <div className="py-6 text-center text-sm text-[#595959]">{text}</div>;
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function formatOrderStatus(status: string) {
  const normalized = status.toLowerCase();
  if (normalized === "delivered" || normalized === "completed") return "已完成";
  if (normalized === "cancelled" || normalized === "canceled") return "已取消";
  if (normalized === "new") return "新订单";
  return "处理中";
}

function formatFulfillment(status: string | null) {
  if (!status) return "未更新";
  const normalized = status.toLowerCase();
  if (normalized === "fulfilled" || normalized.includes("delivered")) return "已履约";
  if (normalized === "pending" || normalized.includes("awaiting")) return "待处理";
  return status;
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

function formatMoney(value: number | null | undefined, currency = "ZAR") {
  if (value == null) return "R 0";
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}
