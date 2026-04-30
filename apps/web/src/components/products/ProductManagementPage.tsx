"use client";

import { type Ref, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Boxes,
  CheckCircle2,
  RefreshCw,
  RotateCcw,
  Search,
  Settings2,
  SlidersHorizontal,
  X,
} from "lucide-react";
import { Toaster, toast } from "sonner";

import type { components } from "@/generated/api-types";
import { ApiError, apiFetch } from "@/lib/api";

type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type StoreListingListResponse = components["schemas"]["StoreListingListResponse"];
type StoreListing = components["schemas"]["StoreListingResponse"];
type StoreListingMetricListResponse = components["schemas"]["StoreListingMetricListResponse"];
type StoreSyncTaskListResponse = components["schemas"]["StoreSyncTaskListResponse"];
type TaskCreatedResponse = components["schemas"]["TaskCreatedResponse"];

type SortDirection = "asc" | "desc";
type SortField =
  | "createdAt"
  | "stockOnHand"
  | "availableStock"
  | "sellingPrice"
  | "sales30d"
  | "pageViews30d"
  | "cvr30d"
  | "wishlist30d"
  | "returns30d";

type ListingStatusGroup = "buyable" | "not_buyable" | "platform_disabled" | "seller_disabled";
type ListingStatusFilter = "all" | ListingStatusGroup;

type ProductRow = {
  id: string;
  title: string;
  productUrl: string;
  sku: string;
  plid: string;
  imageUrl: string | null;
  currency: string;
  createdAt: string;
  store: string;
  listingStatus: ListingStatusGroup;
  stockOnHand: string;
  availableStock: string;
  sellerStockValue: number | null;
  sellerStockEnabled: boolean;
  sellingPrice: string;
  sellingPriceValue: number | null;
  sales30d: string;
  pageViews30d: string;
  cvr30d: string;
  wishlist30d: string;
  returns30d: string;
};

type EditableField = "sellerStock" | "sellingPrice";
type InlineEditOptions = { sellerStockEnabled?: boolean };

type ImagePreview = {
  title: string;
  imageUrl: string;
};

type CachedProductPage = {
  listings: StoreListing[];
  total: number;
  salesMetrics: Map<string, number>;
  statusCounts: Partial<Record<ListingStatusFilter, number>>;
  fetchedAt: number;
};

type ColumnCategory = "基础信息" | "库存数据" | "价格与竞价" | "运营指标";

type ColumnDefinition = {
  id:
    | "product"
    | "createdAt"
    | "store"
    | "listingStatus"
    | "stockOnHand"
    | "availableStock"
    | "sellingPrice"
    | "sales30d"
    | "pageViews30d"
    | "cvr30d"
    | "wishlist30d"
    | "returns30d";
  label: string;
  category: ColumnCategory;
  fixed?: boolean;
  defaultVisible?: boolean;
};

const columnDefinitions: ColumnDefinition[] = [
  { id: "product", label: "商品信息", category: "基础信息", fixed: true, defaultVisible: true },
  { id: "createdAt", label: "创建日期", category: "基础信息", defaultVisible: true },
  { id: "store", label: "店铺", category: "基础信息", defaultVisible: true },
  { id: "listingStatus", label: "状态", category: "基础信息", defaultVisible: true },
  { id: "stockOnHand", label: "官方仓库存", category: "库存数据", defaultVisible: true },
  { id: "availableStock", label: "卖家仓库存", category: "库存数据", defaultVisible: true },
  { id: "sellingPrice", label: "当前售价", category: "价格与竞价", defaultVisible: true },
  { id: "sales30d", label: "销量", category: "运营指标", defaultVisible: true },
  { id: "pageViews30d", label: "浏览量", category: "运营指标", defaultVisible: true },
  { id: "cvr30d", label: "转化率", category: "运营指标", defaultVisible: true },
  { id: "wishlist30d", label: "愿望清单", category: "运营指标", defaultVisible: true },
  { id: "returns30d", label: "退货", category: "运营指标", defaultVisible: true },
];

const categoryOrder: ColumnCategory[] = ["基础信息", "库存数据", "价格与竞价", "运营指标"];
const columnPreferenceKey = "xiaohei.product.columns.v5";
const manualSyncStorageKey = "xiaohei.product.manualSyncAt.v1";
const storeCacheStorageKey = "xiaohei.product.storeCache.v1";
const productCacheStoragePrefix = "xiaohei.product.pageCache.v4:";
const pageSize = 100;
const storeCacheTtlMs = 60_000;
const productCacheTtlMs = 30 * 60_000;
const syncTaskPollMs = 5_000;
const activeSyncTaskTypes = new Set(["SYNC_STORE_LISTINGS", "store.sync.full"]);
const activeSyncStatuses = new Set(["queued", "leased", "running", "waiting_retry"]);

const listingStatusFilters: Array<{ value: ListingStatusFilter; label: string }> = [
  { value: "all", label: "全部" },
  { value: "buyable", label: "可购买" },
  { value: "not_buyable", label: "不可购买" },
  { value: "platform_disabled", label: "平台禁用" },
  { value: "seller_disabled", label: "卖家禁用" },
];

const listingStatusMeta: Record<ListingStatusGroup, { label: string; color: string; shadow: string }> = {
  buyable: { label: "可购买", color: "#16A34A", shadow: "#A7F3D0" },
  not_buyable: { label: "不可购买", color: "#F59E0B", shadow: "#FDE68A" },
  platform_disabled: { label: "平台禁用", color: "#D9363E", shadow: "#FCA5A5" },
  seller_disabled: { label: "卖家禁用", color: "#8C8C8C", shadow: "#D9D9D9" },
};

const buyableStatusPattern =
  /(^|[^a-z])(active|buyable|enabled|live|listed|published|available|synced|webhook_synced)([^a-z]|$)/;
const disabledStatusPattern =
  /(^|[^a-z])(disabled|inactive|unavailable|out_of_stock|not_buyable|rejected|blocked)([^a-z]|$)/;
const platformDisabledTokens = [
  "disabled_by_takealot",
  "takealot_disabled",
  "platform_disabled",
  "disabled by takealot",
  "disabled_by_platform",
];
const sellerDisabledTokens = [
  "disabled_by_seller",
  "seller_disabled",
  "merchant_disabled",
  "disabled_by_merchant",
  "disabled by seller",
];

const sortableColumns = new Set<ColumnDefinition["id"]>([
  "createdAt",
  "stockOnHand",
  "availableStock",
  "sellingPrice",
  "sales30d",
  "pageViews30d",
  "cvr30d",
  "wishlist30d",
  "returns30d",
]);

const numericColumns = new Set<ColumnDefinition["id"]>([
  "stockOnHand",
  "availableStock",
  "sellingPrice",
  "sales30d",
  "pageViews30d",
  "cvr30d",
  "wishlist30d",
  "returns30d",
]);

let cachedStoreList: { stores: StoreSummary[]; fetchedAt: number } | null = null;
const productPageCache = new Map<string, CachedProductPage>();

const initialVisibility = columnDefinitions.reduce<Record<string, boolean>>((acc, column) => {
  acc[column.id] = column.fixed ? true : Boolean(column.defaultVisible);
  return acc;
}, {});

export default function ProductManagementPage() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [queryText, setQueryText] = useState("");
  const [statusFilter, setStatusFilter] = useState<ListingStatusFilter>("all");
  const [sortField, setSortField] = useState<SortField>("createdAt");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [listings, setListings] = useState<StoreListing[]>([]);
  const [salesMetrics, setSalesMetrics] = useState<Map<string, number>>(new Map());
  const [statusCounts, setStatusCounts] = useState<Partial<Record<ListingStatusFilter, number>>>({});
  const [totalProducts, setTotalProducts] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingLocal, setIsRefreshingLocal] = useState(false);
  const [isStartingSync, setIsStartingSync] = useState(false);
  const [activeSyncByStore, setActiveSyncByStore] = useState<Record<string, boolean>>({});
  const [lastManualSyncByStore, setLastManualSyncByStore] = useState<Record<string, string>>({});
  const [errorMessage, setErrorMessage] = useState("");
  const [columnVisibility, setColumnVisibility] =
    useState<Record<string, boolean>>(initialVisibility);
  const [columnPrefsReady, setColumnPrefsReady] = useState(false);
  const [imagePreview, setImagePreview] = useState<ImagePreview | null>(null);
  const [savingCells, setSavingCells] = useState<Record<string, boolean>>({});
  const latestLoadRequestRef = useRef(0);

  const selectedStore = stores.find((store) => store.store_id === selectedStoreId) ?? null;
  const selectedStoreIsSyncing = Boolean(selectedStoreId && activeSyncByStore[selectedStoreId]);
  const lastSyncTime =
    (selectedStoreId ? lastManualSyncByStore[selectedStoreId] : null) ??
    selectedStore?.last_synced_at ??
    null;

  const storeNameMap = useMemo(
    () => new Map(stores.map((store) => [store.store_id, store.name])),
    [stores],
  );

  const visibleColumns = useMemo(() => {
    return columnDefinitions.filter((column) => column.fixed || columnVisibility[column.id]);
  }, [columnVisibility]);

  const groupedColumns = useMemo(() => {
    return categoryOrder.reduce<Record<ColumnCategory, ColumnDefinition[]>>((acc, category) => {
      acc[category] = columnDefinitions.filter((column) => column.category === category);
      return acc;
    }, {} as Record<ColumnCategory, ColumnDefinition[]>);
  }, []);

  const rows = useMemo(() => {
    return listings.map((listing) =>
      toProductRow(listing, storeNameMap, salesMetrics),
    );
  }, [listings, salesMetrics, storeNameMap]);

  const totalPages = Math.max(1, Math.ceil(totalProducts / pageSize));
  const pageStart = totalProducts === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = Math.min(currentPage * pageSize, totalProducts);
  const isTableBusy = isLoading || isRefreshingLocal;

  useEffect(() => {
    void loadStores();
  }, []);

  useEffect(() => {
    const handle = window.setTimeout(() => {
      setQueryText(searchText.trim());
      setCurrentPage(1);
    }, 300);

    return () => window.clearTimeout(handle);
  }, [searchText]);

  useEffect(() => {
    if (!selectedStoreId) return;
    void loadProducts(selectedStoreId, currentPage, queryText, statusFilter, sortField, sortDirection);
  }, [currentPage, queryText, selectedStoreId, statusFilter, sortDirection, sortField]);

  useEffect(() => {
    if (!selectedStoreId) return;
    let isCancelled = false;

    async function pollSyncTask() {
      const active = await hasActiveSyncTask(selectedStoreId);
      if (isCancelled) return;
      setActiveSyncByStore((current) => {
        const wasActive = Boolean(current[selectedStoreId]);
        if (wasActive && !active) {
          clearProductCacheForStore(selectedStoreId);
          void loadProducts(
            selectedStoreId,
            currentPage,
            queryText,
            statusFilter,
            sortField,
            sortDirection,
            { force: true, background: true },
          );
        }
        return { ...current, [selectedStoreId]: active };
      });
    }

    void pollSyncTask();
    const timer = window.setInterval(() => void pollSyncTask(), syncTaskPollMs);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [currentPage, queryText, selectedStoreId, sortDirection, sortField, statusFilter]);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(manualSyncStorageKey);
      if (stored) {
        setLastManualSyncByStore(JSON.parse(stored) as Record<string, string>);
      }
    } catch {
      setLastManualSyncByStore({});
    }
  }, []);

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(columnPreferenceKey);
      if (stored) {
        setColumnVisibility(normalizeColumnVisibility(JSON.parse(stored)));
      }
    } catch {
      setColumnVisibility(initialVisibility);
    } finally {
      setColumnPrefsReady(true);
    }
  }, []);

  useEffect(() => {
    if (!columnPrefsReady) return;
    window.localStorage.setItem(columnPreferenceKey, JSON.stringify(columnVisibility));
  }, [columnPrefsReady, columnVisibility]);

  async function loadStores(options: { force?: boolean } = {}) {
    setErrorMessage("");

    try {
      if (
        !options.force &&
        cachedStoreList &&
        cachedStoreList.stores.length > 0 &&
        isFresh(cachedStoreList.fetchedAt, storeCacheTtlMs)
      ) {
        applyStoreList(cachedStoreList.stores);
        return;
      }

      if (!options.force) {
        const stored = readStoreCache();
        if (stored && stored.stores.length > 0) {
          cachedStoreList = stored;
          applyStoreList(stored.stores);
          if (isFresh(stored.fetchedAt, storeCacheTtlMs)) return;
        }
      }

      const storeData = await apiFetch<StoreListResponse>("/api/v1/stores");
      cachedStoreList = { stores: storeData.stores, fetchedAt: Date.now() };
      writeStoreCache(cachedStoreList);
      applyStoreList(storeData.stores);
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载店铺失败");
      setStores([]);
      setSelectedStoreId("");
      setListings([]);
      setSalesMetrics(new Map());
      setStatusCounts({});
      setTotalProducts(0);
      setIsLoading(false);
    }
  }

  function applyStoreList(nextStores: StoreSummary[]) {
    setStores(nextStores);
    setSelectedStoreId((current) =>
      nextStores.some((store) => store.store_id === current)
        ? current
        : nextStores[0]?.store_id || "",
    );
    if (nextStores.length === 0) {
      setListings([]);
      setSalesMetrics(new Map());
      setStatusCounts({});
      setTotalProducts(0);
      setIsLoading(false);
    }
  }

  async function loadProducts(
    storeId: string,
    page: number,
    query: string,
    nextStatusFilter: ListingStatusFilter,
    nextSortField: SortField,
    nextSortDirection: SortDirection,
    options: { force?: boolean; background?: boolean } = {},
  ) {
    const requestId = latestLoadRequestRef.current + 1;
    latestLoadRequestRef.current = requestId;
    const cacheKey = productCacheKey(
      storeId,
      page,
      query,
      nextStatusFilter,
      nextSortField,
      nextSortDirection,
    );
    const cached = productPageCache.get(cacheKey) ?? readProductPageCache(cacheKey);

    setErrorMessage("");

    if (!options.force && cached) {
      applyProductPage(cached);
      setIsLoading(false);
      if (isFresh(cached.fetchedAt, productCacheTtlMs)) {
        void prefetchProducts(
          storeId,
          page + 1,
          query,
          nextStatusFilter,
          nextSortField,
          nextSortDirection,
          cached.total,
        );
        return;
      }
      setIsRefreshingLocal(true);
    } else if (options.background) {
      setIsRefreshingLocal(true);
    } else {
      setIsLoading(true);
    }

    if (options.force) {
      productPageCache.delete(cacheKey);
    }

    try {
      const pageData = await fetchProductPage(
        storeId,
        page,
        query,
        nextStatusFilter,
        nextSortField,
        nextSortDirection,
      );
      if (requestId !== latestLoadRequestRef.current) return;

      const nextTotalPages = Math.max(1, Math.ceil(pageData.total / pageSize));
      if (page > nextTotalPages) {
        setCurrentPage(nextTotalPages);
        return;
      }

      productPageCache.set(cacheKey, pageData);
      writeProductPageCache(cacheKey, pageData);
      applyProductPage(pageData);
      void prefetchProducts(
        storeId,
        page + 1,
        query,
        nextStatusFilter,
        nextSortField,
        nextSortDirection,
        pageData.total,
      );
    } catch (error) {
      if (requestId !== latestLoadRequestRef.current) return;
      if (cached) {
        setErrorMessage(error instanceof Error ? `本地数据已缓存，后台刷新失败：${error.message}` : "本地数据已缓存，后台刷新失败");
        return;
      }
      setErrorMessage(error instanceof Error ? error.message : "加载商品失败");
      setListings([]);
      setSalesMetrics(new Map());
      setStatusCounts({});
      setTotalProducts(0);
    } finally {
      if (requestId === latestLoadRequestRef.current) {
        setIsLoading(false);
        setIsRefreshingLocal(false);
      }
    }
  }

  function applyProductPage(pageData: CachedProductPage) {
    setListings(pageData.listings);
    setTotalProducts(pageData.total);
    setSalesMetrics(new Map(pageData.salesMetrics));
    setStatusCounts(pageData.statusCounts);
  }

  async function saveInlineListingEdit(
    row: ProductRow,
    field: EditableField,
    value: number,
    options: InlineEditOptions = {},
  ) {
    if (!selectedStoreId) return;
    const payload: { selling_price?: number; seller_stock?: number; seller_stock_enabled?: boolean } = {};
    if (field === "sellerStock") {
      const normalizedStock = Math.max(0, Math.round(value));
      const requestedEnabled = options.sellerStockEnabled;
      const stockChanged = row.sellerStockValue !== normalizedStock;
      const enabledChanged =
        typeof requestedEnabled === "boolean" && row.sellerStockEnabled !== requestedEnabled;
      if (!stockChanged && !enabledChanged) return;
      if (stockChanged || typeof requestedEnabled === "boolean") {
        payload.seller_stock = requestedEnabled === false ? 0 : normalizedStock;
      }
      if (typeof requestedEnabled === "boolean") {
        payload.seller_stock_enabled = requestedEnabled;
      }
    }
    if (field === "sellingPrice") {
      if (sameNumber(row.sellingPriceValue, value)) return;
      payload.selling_price = Math.max(0, value);
    }
    if (Object.keys(payload).length === 0) return;

    const key = cellSavingKey(row.id, field);
    setSavingCells((current) => ({ ...current, [key]: true }));
    try {
      const updated = await apiFetch<StoreListing>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}/listings/${encodeURIComponent(row.id)}`,
        {
          method: "PATCH",
          body: JSON.stringify(payload),
        },
      );
      clearProductCacheForStore(selectedStoreId);
      setListings((current) =>
        current.map((listing) => (listing.listing_id === row.id ? updated : listing)),
      );
      toast.success("修改完毕", {
        icon: <CheckCircle2 className="h-5 w-5 text-[#16A34A]" />,
        duration: 2200,
        style: {
          background: "#F2FFE8",
          border: "2px solid #000000",
          borderRadius: "2px",
          boxShadow: "4px 4px 0 #16A34A",
          color: "#000000",
          fontFamily: "monospace",
          minHeight: "58px",
        },
      });
    } catch (error) {
      toast.error("保存失败", {
        description: error instanceof Error ? error.message : "请稍后重试",
      });
      throw error;
    } finally {
      setSavingCells((current) => {
        const next = { ...current };
        delete next[key];
        return next;
      });
    }
  }

  async function startStoreSync() {
    if (!selectedStoreId || isStartingSync || selectedStoreIsSyncing) return;
    setIsStartingSync(true);
    try {
      if (await hasActiveSyncTask(selectedStoreId)) {
        setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
        toast.info("商品同步正在进行", {
          description: "通常几十秒到几分钟；商品多或 Takealot 响应慢时会更久，可在任务中心查看进度。",
        });
        return;
      }
      await apiFetch<TaskCreatedResponse>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}/sync`,
        {
          method: "POST",
          body: JSON.stringify({ reason: "用户在商品管理页手动同步商品数据" }),
        },
      );
      const syncedAt = new Date().toISOString();
      setLastManualSyncByStore((current) => {
        const next = { ...current, [selectedStoreId]: syncedAt };
        window.localStorage.setItem(manualSyncStorageKey, JSON.stringify(next));
        return next;
      });
      clearProductCacheForStore(selectedStoreId);
      setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
      toast.success("同步任务已提交", {
        description: "页面先继续使用本地数据，任务完成后会自动读取新结果。通常几十秒到几分钟；商品多或 Takealot 响应慢时会更久，可在任务中心查看进度。",
      });
      await loadStores({ force: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
        toast.info("商品同步正在进行", {
          description: "通常几十秒到几分钟；商品多或 Takealot 响应慢时会更久，可在任务中心查看进度。",
        });
        return;
      }
      toast.error("同步提交失败", {
        description: error instanceof Error ? error.message : "请稍后重试",
      });
    } finally {
      setIsStartingSync(false);
    }
  }

  async function hasActiveSyncTask(storeId: string) {
    try {
      const taskData = await apiFetch<StoreSyncTaskListResponse>(
        `/api/v1/stores/${encodeURIComponent(storeId)}/sync-tasks`,
      );
      return taskData.tasks.some(
        (task) => activeSyncTaskTypes.has(task.task_type) && activeSyncStatuses.has(task.status),
      );
    } catch {
      return false;
    }
  }

  async function fetchProductPage(
    storeId: string,
    page: number,
    query: string,
    nextStatusFilter: ListingStatusFilter,
    nextSortField: SortField,
    nextSortDirection: SortDirection,
  ): Promise<CachedProductPage> {
    const listingParams = new URLSearchParams({
      limit: String(pageSize),
      offset: String((page - 1) * pageSize),
      sort_by: nextSortField,
      sort_dir: nextSortDirection,
    });
    if (query) listingParams.set("q", query);
    if (nextStatusFilter !== "all") listingParams.set("status_group", nextStatusFilter);

    const listingData = await apiFetch<StoreListingListResponse>(
      `/api/v1/stores/${encodeURIComponent(storeId)}/listings?${listingParams.toString()}`,
    );
    const visibleSkus = uniqueStrings(listingData.listings.map((listing) => listing.sku));
    const metricData = await loadVisibleMetrics(storeId, visibleSkus);

    return {
      listings: listingData.listings,
      total: listingData.total ?? listingData.listings.length,
      salesMetrics: buildSalesMetricMap(metricData.metrics),
      statusCounts: normalizeStatusCounts(
        (listingData as StoreListingListResponse & { status_counts?: unknown }).status_counts,
        listingData.total ?? listingData.listings.length,
      ),
      fetchedAt: Date.now(),
    };
  }

  async function prefetchProducts(
    storeId: string,
    page: number,
    query: string,
    nextStatusFilter: ListingStatusFilter,
    nextSortField: SortField,
    nextSortDirection: SortDirection,
    total: number,
  ) {
    if (page > Math.max(1, Math.ceil(total / pageSize))) return;
    const cacheKey = productCacheKey(
      storeId,
      page,
      query,
      nextStatusFilter,
      nextSortField,
      nextSortDirection,
    );
    if (productPageCache.has(cacheKey)) return;

    try {
      const pageData = await fetchProductPage(
        storeId,
        page,
        query,
        nextStatusFilter,
        nextSortField,
        nextSortDirection,
      );
      productPageCache.set(cacheKey, pageData);
      writeProductPageCache(cacheKey, pageData);
    } catch {
      // Keep foreground navigation fast; failed prefetches can be retried on demand.
    }
  }

  async function loadVisibleMetrics(storeId: string, skus: string[]) {
    if (skus.length === 0) return { metrics: [] } satisfies StoreListingMetricListResponse;

    const params = new URLSearchParams();
    for (const sku of skus) {
      params.append("sku", sku);
    }

    return apiFetch<StoreListingMetricListResponse>(
      `/api/v1/stores/${encodeURIComponent(storeId)}/listing-metrics?${params.toString()}`,
    ).catch(() => ({ metrics: [] }));
  }

  function toggleColumn(columnId: ColumnDefinition["id"]) {
    const column = columnDefinitions.find((item) => item.id === columnId);
    if (!column || column.fixed) return;
    setColumnVisibility((current) => ({
      ...current,
      [columnId]: !current[columnId],
    }));
  }

  function resetColumns() {
    setColumnVisibility(initialVisibility);
  }

  function toggleSort(columnId: ColumnDefinition["id"]) {
    if (!isSortableColumn(columnId)) return;
    setCurrentPage(1);
    if (sortField === columnId) {
      setSortDirection((current) => (current === "asc" ? "desc" : "asc"));
      return;
    }
    setSortField(columnId);
    setSortDirection(defaultSortDirection(columnId));
  }

  return (
    <div className="relative overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] text-[#000000]">
      <Toaster
        richColors={false}
        position="top-right"
        toastOptions={{
          style: {
            background: "#FFFDF2",
            color: "#000000",
            border: "2px solid #000000",
            borderRadius: "2px",
            boxShadow: "4px 4px 0 #D9D9D9",
            fontFamily: "monospace",
            minHeight: "58px",
          },
        }}
      />
      <div className="border-b border-[#EBEBEB] px-5 py-4">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="space-y-1">
            <h1 className="text-[28px] font-semibold tracking-[-0.03em] text-[#000000]">
              商品管理
            </h1>
          </div>

          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <select
              value={selectedStoreId}
              onChange={(event) => {
                setSelectedStoreId(event.target.value);
                setCurrentPage(1);
              }}
              disabled={stores.length === 0}
              className="h-9 min-w-[180px] rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none disabled:text-[#595959]"
              aria-label="选择店铺"
            >
              {stores.length === 0 ? (
                <option value="">暂无店铺</option>
              ) : (
                stores.map((store) => (
                  <option key={store.store_id} value={store.store_id}>
                    {store.name}
                  </option>
                ))
              )}
            </select>

            <label className="relative block min-w-[260px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
              <input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="搜索标题 / SKU"
                className="h-9 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] pl-9 pr-3 text-sm text-[#000000] outline-none placeholder:text-[#595959]"
              />
            </label>

            <div className="flex flex-wrap items-center gap-1 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] p-1">
              {listingStatusFilters.map((item) => (
                (() => {
                  const isActive = statusFilter === item.value;
                  return (
                    <button
                      key={item.value}
                      type="button"
                      aria-pressed={isActive}
                      onClick={() => {
                        setStatusFilter(item.value);
                        setCurrentPage(1);
                      }}
                      className={[
                        "inline-flex h-7 items-center gap-1.5 rounded-[5px] border px-2.5 text-xs font-medium outline-none transition focus-visible:border-[#000000]",
                        isActive
                          ? "border-[#000000] bg-[#FFFFFF] text-[#000000] shadow-[inset_0_-2px_0_#000000]"
                          : "border-transparent text-[#595959] hover:bg-[#FFFFFF] hover:text-[#000000]",
                      ].join(" ")}
                    >
                      <span>{item.label}</span>
                      <span
                        className={[
                          "rounded-full px-1.5 text-[11px]",
                          isActive ? "bg-[#F5F5F5] text-[#000000]" : "text-[#8C8C8C]",
                        ].join(" ")}
                      >
                        {formatCompactInteger(statusCounts[item.value] ?? 0)}
                      </span>
                      {isActive && isTableBusy ? (
                        <RefreshCw className="h-3 w-3 animate-spin stroke-[1.8]" />
                      ) : null}
                    </button>
                  );
                })()
              ))}
            </div>

            <button
              type="button"
              onClick={() => void startStoreSync()}
              disabled={!selectedStoreId || isStartingSync || selectedStoreIsSyncing}
              className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#BFBFBF] bg-[#FFFFFF] px-3 text-sm font-medium text-[#000000] outline-none hover:border-[#000000] hover:bg-[#FAFAFA] focus-visible:border-[#000000] disabled:cursor-not-allowed disabled:border-[#D9D9D9] disabled:bg-[#F5F5F5] disabled:text-[#8C8C8C]"
            >
              <RefreshCw className={["h-4 w-4 stroke-[1.8]", isStartingSync || selectedStoreIsSyncing ? "animate-spin" : ""].join(" ")} />
              <span>{selectedStoreIsSyncing ? "同步中" : isStartingSync ? "提交中" : "同步商品"}</span>
            </button>

            <button
              type="button"
              onClick={() => setDrawerOpen(true)}
              className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm font-medium text-[#000000]"
            >
              <Settings2 className="h-4 w-4 stroke-[1.8]" />
              <span>自定义显示</span>
            </button>
          </div>
        </div>
      </div>

      <div className="border-b border-[#EBEBEB] px-5 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-[#595959]">
          <div className="flex flex-wrap items-center gap-3">
            <span>
              {selectedStore ? selectedStore.name : "暂无店铺"}
            </span>
            <span>·</span>
            <span>
              同步时间 {formatDateTime(lastSyncTime)}
            </span>
            <span>·</span>
            <span>
              第 {pageStart}-{pageEnd} 条
            </span>
            <span>·</span>
            <div className="inline-flex items-center gap-2">
              <SlidersHorizontal className="h-4 w-4 stroke-[1.8]" />
              <span>已启用字段 {visibleColumns.length} 项</span>
            </div>
          </div>
          {errorMessage ? <span className="text-[#D9363E]">{errorMessage}</span> : null}
        </div>
      </div>

      <div className="relative overflow-x-auto">
        {isTableBusy ? (
          <div className="absolute left-0 right-0 top-0 z-30 h-1 overflow-hidden bg-[#F5F5F5]">
            <div className="h-full w-1/2 animate-pulse bg-[#000000]" />
          </div>
        ) : null}
        <table className="min-w-full border-collapse text-left">
          <thead className="sticky top-0 z-10 bg-[#FFFFFF]">
            <tr className="border-b border-[#EBEBEB] text-xs text-[#595959]">
              {visibleColumns.map((column) => (
                <th
                  key={column.id}
                  aria-sort={
                    isSortableColumn(column.id) && sortField === column.id
                      ? sortDirection === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                  className={[
                    "h-11 whitespace-nowrap font-medium",
                    column.id === "listingStatus" ? "px-2 text-center" : "px-4",
                    column.id === "product"
                      ? "sticky left-0 z-20 min-w-[360px] bg-[#FFFFFF]"
                      : column.id === "listingStatus"
                        ? "w-[56px] min-w-[56px]"
                        : column.id === "availableStock"
                          ? "min-w-[188px]"
                      : "min-w-[128px]",
                    isNumericColumn(column.id) ? "text-right" : "",
                  ].join(" ")}
                >
                  {isSortableColumn(column.id) ? (
                    <button
                      type="button"
                      onClick={() => toggleSort(column.id)}
                      className={[
                        "group inline-flex h-7 items-center gap-1.5 rounded-[5px] border px-2 text-left outline-none transition focus-visible:border-[#000000]",
                        isNumericColumn(column.id) ? "ml-auto" : "",
                        sortField === column.id
                          ? "border-[#000000] bg-[#FFFFFF] font-semibold text-[#000000] shadow-[inset_0_-2px_0_#000000]"
                          : "border-transparent text-[#595959] hover:border-[#D9D9D9] hover:bg-[#FAFAFA] hover:text-[#000000]",
                      ].join(" ")}
                      aria-label={`按${column.label}排序`}
                      title={`按${column.label}${sortField === column.id && sortDirection === "desc" ? "升序" : "降序"}`}
                    >
                      <span>{column.label}</span>
                      <SortIcon
                        active={sortField === column.id}
                        direction={sortDirection}
                      />
                    </button>
                  ) : (
                    <span className={column.id === "listingStatus" ? "sr-only" : ""}>
                      {column.label}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className={isTableBusy ? "opacity-60 transition-opacity" : "transition-opacity"}>
            {rows.map((row) => (
              <tr
                key={row.id}
                className="border-b border-[#EBEBEB] text-sm last:border-b-0 hover:bg-[#FAFAFA]"
              >
                {visibleColumns.map((column) => (
                  <td
                    key={`${row.id}-${column.id}`}
                    className={[
                      "py-3 align-top",
                      column.id === "listingStatus" ? "px-2 text-center" : "px-4",
                      column.id === "product"
                        ? "sticky left-0 z-10 min-w-[360px] bg-[#FFFFFF]"
                        : column.id === "listingStatus"
                          ? "w-[56px] min-w-[56px]"
                          : column.id === "availableStock"
                            ? "min-w-[188px] whitespace-nowrap text-[#595959]"
                        : "whitespace-nowrap text-[#595959]",
                      isNumericColumn(column.id) ? "text-right" : "",
                    ].join(" ")}
                  >
                    {renderCell(
                      row,
                      column.id,
                      setImagePreview,
                      saveInlineListingEdit,
                      savingCells,
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {!isLoading && rows.length === 0 ? (
        <div className="px-6 py-12 text-center text-sm text-[#595959]">
          {queryText ? "没有匹配的商品。" : "当前没有商品。请先在店铺管理中同步商品。"}
        </div>
      ) : null}

      <div className="flex flex-col gap-3 border-t border-[#EBEBEB] px-5 py-3 text-sm text-[#595959] sm:flex-row sm:items-center sm:justify-between">
        <div>
          每页 {pageSize} 条
          {queryText ? <span> · 搜索“{queryText}”</span> : null}
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
            disabled={currentPage <= 1 || isLoading}
            className="inline-flex h-8 items-center justify-center rounded-[6px] border border-[#EBEBEB] px-3 text-xs font-medium text-[#000000] disabled:cursor-not-allowed disabled:text-[#595959]"
          >
            上一页
          </button>
          <span className="min-w-[96px] text-center">
            {currentPage} / {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
            disabled={currentPage >= totalPages || isLoading}
            className="inline-flex h-8 items-center justify-center rounded-[6px] border border-[#EBEBEB] px-3 text-xs font-medium text-[#000000] disabled:cursor-not-allowed disabled:text-[#595959]"
          >
            下一页
          </button>
        </div>
      </div>

      {drawerOpen ? (
        <div className="fixed inset-0 z-40 flex justify-end bg-black/10">
          <aside className="h-screen w-full max-w-[420px] border-l border-[#EBEBEB] bg-[#FFFFFF]">
            <div className="flex h-full flex-col">
              <div className="flex items-start justify-between border-b border-[#EBEBEB] px-5 py-4">
                <div>
                  <div className="text-base font-semibold text-[#000000]">配置列表字段</div>
                  <div className="mt-1 text-xs text-[#595959]">
                    已显示 {visibleColumns.length}/{columnDefinitions.length} 项，修改后立即生效并保存在本机。
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={resetColumns}
                    className="inline-flex h-8 shrink-0 items-center justify-center gap-1.5 whitespace-nowrap rounded-[6px] border border-[#EBEBEB] px-3 text-xs font-medium text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000]"
                    title="恢复默认字段"
                  >
                    <RotateCcw className="h-3.5 w-3.5 stroke-[1.8]" />
                    恢复默认
                  </button>
                  <button
                    type="button"
                    onClick={() => setDrawerOpen(false)}
                    className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000]"
                    aria-label="关闭字段配置"
                  >
                    <X className="h-4 w-4 stroke-[1.8]" />
                  </button>
                </div>
              </div>

              <div className="flex-1 overflow-y-auto px-5 py-5">
                {categoryOrder.map((category) => (
                  <section key={category} className="mb-6 last:mb-0">
                    <div className="mb-3 text-sm font-medium text-[#000000]">{category}</div>
                    <div className="divide-y divide-[#EBEBEB] rounded-[6px] border border-[#EBEBEB]">
                      {groupedColumns[category].map((column) => (
                        <button
                          key={column.id}
                          type="button"
                          disabled={column.fixed}
                          onClick={() => toggleColumn(column.id)}
                          className={[
                            "flex w-full items-center justify-between px-4 py-3 text-left",
                            column.fixed ? "cursor-not-allowed" : "",
                          ].join(" ")}
                        >
                          <div>
                            <div className="text-sm font-medium text-[#000000]">
                              {column.label}
                            </div>
                            <div className="mt-1 text-xs text-[#595959]">
                              {column.fixed
                                ? "固定列"
                                : columnVisibility[column.id]
                                  ? "显示"
                                  : "隐藏"}
                            </div>
                          </div>
                          <span
                            className={[
                              "relative inline-flex h-6 w-11 items-center rounded-full border transition",
                              columnVisibility[column.id]
                                ? "border-[#000000] bg-[#000000]"
                                : "border-[#D9D9D9] bg-[#FFFFFF]",
                              column.fixed ? "opacity-50" : "",
                            ].join(" ")}
                          >
                            <span
                              className={[
                                "inline-block h-4 w-4 rounded-full border bg-[#FFFFFF] transition",
                                columnVisibility[column.id]
                                  ? "translate-x-6 border-[#FFFFFF]"
                                  : "translate-x-1 border-[#D9D9D9]",
                              ].join(" ")}
                            />
                          </span>
                        </button>
                      ))}
                    </div>
                  </section>
                ))}
              </div>
            </div>
          </aside>
        </div>
      ) : null}

      {imagePreview ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-6"
          onClick={() => setImagePreview(null)}
        >
          <div className="relative max-h-full max-w-[920px]" onClick={(event) => event.stopPropagation()}>
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

function renderCell(
  row: ProductRow,
  columnId: ColumnDefinition["id"],
  onPreviewImage: (preview: ImagePreview) => void,
  onCommitEdit: (
    row: ProductRow,
    field: EditableField,
    value: number,
    options?: InlineEditOptions,
  ) => Promise<void>,
  savingCells: Record<string, boolean>,
) {
  if (columnId === "product") {
    return (
      <div className="flex items-start gap-3">
        <ProductImage title={row.title} imageUrl={row.imageUrl} onPreview={onPreviewImage} />
        <div className="min-w-0">
          <a
            href={row.productUrl}
            target="_blank"
            rel="noreferrer"
            title="打开商品页"
            className="line-clamp-2 font-medium leading-5 text-[#000000] underline-offset-2 hover:text-[#0F766E] hover:underline"
          >
            {row.title}
          </a>
          <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs text-[#595959]">
            <span>SKU: {row.sku}</span>
            <span>{row.plid}</span>
          </div>
        </div>
      </div>
    );
  }

  if (columnId === "createdAt") {
    return <span>{formatDate(row.createdAt)}</span>;
  }

  if (columnId === "listingStatus") {
    return <ListingStatusDot status={row.listingStatus} />;
  }

  if (columnId === "availableStock") {
    return (
      <SellerWarehouseStockCell
        value={row.sellerStockValue}
        enabled={row.sellerStockEnabled}
        fallbackText={row.availableStock}
        saving={Boolean(savingCells[cellSavingKey(row.id, "sellerStock")])}
        onCommit={(value, enabled) =>
          onCommitEdit(
            row,
            "sellerStock",
            value,
            typeof enabled === "boolean" ? { sellerStockEnabled: enabled } : undefined,
          )
        }
      />
    );
  }

  if (columnId === "sellingPrice") {
    return (
      <EditableNumberCell
        value={row.sellingPriceValue}
        fallbackText={row.sellingPrice}
        prefix={currencyPrefix(row.currency)}
        saving={Boolean(savingCells[cellSavingKey(row.id, "sellingPrice")])}
        onCommit={(value) => onCommitEdit(row, "sellingPrice", value)}
      />
    );
  }

  return <span>{row[columnId]}</span>;
}

function ListingStatusDot({ status }: { status: ListingStatusGroup }) {
  const meta = listingStatusMeta[status];
  return (
    <span className="inline-flex w-full items-center justify-center">
      <span
        aria-label={meta.label}
        title={meta.label}
        className="inline-flex h-[15px] w-[15px] rounded-full border-2 border-[#000000]"
        style={{ backgroundColor: meta.color, boxShadow: `2px 2px 0 ${meta.shadow}` }}
      />
    </span>
  );
}

function ProductImage({
  title,
  imageUrl,
  onPreview,
}: {
  title: string;
  imageUrl: string | null;
  onPreview: (preview: ImagePreview) => void;
}) {
  const imageCandidates = useMemo(() => buildImageCandidates(imageUrl), [imageUrl]);
  const [candidateIndex, setCandidateIndex] = useState(0);

  useEffect(() => {
    setCandidateIndex(0);
  }, [imageUrl]);

  const currentImageUrl = imageCandidates[candidateIndex] ?? null;

  if (currentImageUrl) {
    return (
      <button
        type="button"
        onClick={() => onPreview({ title, imageUrl: currentImageUrl })}
        className="h-12 w-12 flex-none overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] outline-none transition hover:border-[#BFBFBF] focus-visible:border-[#000000]"
        title="查看大图"
      >
        <img
          src={currentImageUrl}
          alt={title}
          className="h-full w-full object-contain"
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setCandidateIndex((index) => index + 1)}
        />
      </button>
    );
  }

  return (
    <div className="flex h-12 w-12 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] text-[#595959]">
      <Boxes className="h-4 w-4 stroke-[1.8]" />
    </div>
  );
}

function SellerWarehouseStockCell({
  value,
  enabled,
  fallbackText,
  saving,
  onCommit,
}: {
  value: number | null;
  enabled: boolean;
  fallbackText: string;
  saving: boolean;
  onCommit: (value: number, enabled?: boolean) => Promise<void>;
}) {
  const persistedOpen = enabled;
  const [manualOpen, setManualOpen] = useState(false);
  const [focusToken, setFocusToken] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const isOpen = persistedOpen || manualOpen;
  const displayValue = persistedOpen ? value ?? 0 : 0;

  useEffect(() => {
    setManualOpen(false);
  }, [persistedOpen]);

  useEffect(() => {
    if (!focusToken || !isOpen || saving) return;
    const handle = window.setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    return () => window.clearTimeout(handle);
  }, [focusToken, isOpen, saving]);

  async function toggleSellerWarehouse() {
    if (saving) return;
    if (isOpen) {
      setManualOpen(false);
      try {
        await onCommit(0, false);
      } catch {
        setManualOpen(true);
      }
      return;
    }

    setManualOpen(true);
    try {
      await onCommit(0, true);
      setFocusToken((token) => token + 1);
    } catch {
      setManualOpen(false);
    }
  }

  return (
    <span className="inline-flex min-w-[168px] items-center justify-end gap-2">
      <button
        type="button"
        role="switch"
        aria-checked={isOpen}
        aria-label={isOpen ? "关闭直邮库存" : "打开直邮库存"}
        title={isOpen ? "关闭后卖家仓库存设为 0" : "打开后库存保持 0，请手动填写"}
        disabled={saving}
        onClick={() => void toggleSellerWarehouse()}
        className={[
          "relative h-7 w-[46px] flex-none rounded-[2px] border-2 border-[#000000] transition",
          isOpen
            ? "bg-[#EAF2FF] shadow-[3px_3px_0_#AFCBFF]"
            : "bg-[#F5F5F5] shadow-[3px_3px_0_#D9D9D9]",
          saving ? "cursor-wait opacity-70" : "hover:translate-x-[1px] hover:translate-y-[1px] hover:shadow-[1px_1px_0_#000000]",
        ].join(" ")}
      >
        <span
          className={[
            "absolute top-1/2 h-4 w-4 -translate-y-1/2 rounded-[2px] border-2 border-[#000000] transition",
            isOpen ? "left-[24px] bg-[#2F6FDB]" : "left-[4px] bg-[#8C8C8C]",
          ].join(" ")}
        />
        {saving ? (
          <RefreshCw className="absolute left-1/2 top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 animate-spin text-[#000000]" />
        ) : null}
      </button>

      <EditableNumberCell
        value={displayValue}
        fallbackText={isOpen ? "0" : fallbackText}
        integer
        saving={saving}
        disabled={!isOpen}
        inputRef={inputRef}
        ariaLabel="编辑卖家仓库存"
        onCommit={onCommit}
      />
    </span>
  );
}

function EditableNumberCell({
  value,
  fallbackText,
  prefix,
  integer = false,
  saving,
  disabled = false,
  inputRef,
  ariaLabel,
  onCommit,
}: {
  value: number | null;
  fallbackText: string;
  prefix?: string;
  integer?: boolean;
  saving: boolean;
  disabled?: boolean;
  inputRef?: Ref<HTMLInputElement>;
  ariaLabel?: string;
  onCommit: (value: number) => Promise<void>;
}) {
  const normalizedValue = value === null ? "" : formatDraftNumber(value, integer);
  const [draft, setDraft] = useState(normalizedValue);
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) setDraft(normalizedValue);
  }, [focused, normalizedValue]);

  async function commitDraft() {
    const parsed = parseEditableNumber(draft, integer);
    if (parsed === null) {
      setDraft(normalizedValue);
      return;
    }
    if (sameNumber(value, parsed)) {
      setDraft(normalizedValue);
      return;
    }
    try {
      await onCommit(parsed);
    } catch {
      setDraft(normalizedValue);
    }
  }

  return (
    <span
      className={[
        "inline-flex h-9 w-[116px] min-w-[116px] max-w-[116px] box-border items-center justify-end gap-1 rounded-[2px] border-2 px-2 font-mono transition",
        disabled
          ? "border-[#000000] bg-[#F5F5F5] shadow-[3px_3px_0_#D9D9D9]"
          : focused
          ? "translate-x-[1px] translate-y-[1px] border-[#000000] bg-[#FFFFFF] shadow-[1px_1px_0_#000000]"
          : "border-[#000000] bg-[#FFFDF2] shadow-[3px_3px_0_#D9D9D9] hover:bg-[#FFFFFF] hover:shadow-[2px_2px_0_#BFBFBF]",
      ].join(" ")}
    >
      {prefix ? <span className="text-xs font-semibold text-[#595959]">{prefix}</span> : null}
      <input
        value={draft}
        inputMode={integer ? "numeric" : "decimal"}
        disabled={saving || disabled}
        ref={inputRef}
        aria-label={ariaLabel ?? (prefix ? "编辑当前售价" : "编辑卖家仓库存")}
        placeholder={fallbackText === "--" ? "" : fallbackText}
        onFocus={(event) => {
          setFocused(true);
          event.currentTarget.select();
        }}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => {
          setFocused(false);
          void commitDraft();
        }}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
          if (event.key === "Escape") {
            setDraft(normalizedValue);
            event.currentTarget.blur();
          }
        }}
        className="w-[70px] bg-transparent text-right text-sm font-semibold text-[#000000] outline-none placeholder:text-[#8C8C8C] disabled:cursor-not-allowed disabled:opacity-60"
      />
      <span className="flex h-3 w-3 flex-none items-center justify-center">
        <RefreshCw
          className={[
            "h-3 w-3 text-[#595959] transition-opacity",
            saving ? "animate-spin opacity-100" : "opacity-0",
          ].join(" ")}
          aria-hidden={!saving}
        />
      </span>
    </span>
  );
}

function SortIcon({ active, direction }: { active: boolean; direction: SortDirection }) {
  if (!active) {
    return (
      <ArrowUpDown className="h-3 w-3 stroke-[1.8] text-[#BFBFBF] transition group-hover:text-[#595959]" />
    );
  }
  return direction === "asc" ? (
    <ArrowUp className="h-3 w-3 stroke-[2] text-[#000000]" />
  ) : (
    <ArrowDown className="h-3 w-3 stroke-[2] text-[#000000]" />
  );
}

function toProductRow(
  listing: StoreListing,
  storeNameMap: Map<string, string>,
  salesMetrics: Map<string, number>,
): ProductRow {
  const officialStock = officialWarehouseStock(listing.raw_payload) ?? listing.stock_quantity ?? 0;
  const sellerStock = sellerWarehouseStock(listing.raw_payload);
  const sellerStockEnabled = sellerWarehouseEnabled(listing.raw_payload);
  const apiSales30d = sales30dFromPayload(listing.raw_payload);
  const fallbackSales30d = salesMetrics.get(metricKey(listing.store_id, listing.sku)) ?? null;
  const platformProductId =
    listing.platform_product_id ??
    payloadString(listing.raw_payload, "productline_id") ??
    payloadString(listing.raw_payload, "productlineId") ??
    payloadString(listing.raw_payload, "product_line_id") ??
    listing.external_listing_id;
  const pageViews30d =
    payloadNumber(listing.raw_payload, "page_views_30_days") ??
    payloadNumber(listing.raw_payload, "page_views_30d") ??
    payloadNumber(listing.raw_payload, "page_views_7_days") ??
    payloadNumber(listing.raw_payload, "page_views_7d");
  const conversion30d =
    payloadNumber(listing.raw_payload, "conversion_percentage_30_days") ??
    payloadNumber(listing.raw_payload, "conversion_rate_30_days") ??
    payloadNumber(listing.raw_payload, "conversion_rate") ??
    payloadNumber(listing.raw_payload, "cvr");
  const returns30d =
    payloadNumber(listing.raw_payload, "quantity_returned_30_days") ??
    payloadNumber(listing.raw_payload, "returns_30_days") ??
    payloadNumber(listing.raw_payload, "returns_30d") ??
    payloadNumber(listing.raw_payload, "quantity_returned_30d");

  return {
    id: listing.listing_id,
    title: listing.title,
    productUrl: buildTakealotProductUrl(listing.title, platformProductId),
    sku: listing.sku,
    plid: formatPlatformProductId(platformProductId),
    imageUrl: payloadImageUrl(listing.raw_payload),
    currency: listing.currency,
    createdAt: listing.created_at,
    store: storeNameMap.get(listing.store_id) ?? shortId(listing.store_id),
    listingStatus: listingStatusGroup(listing),
    stockOnHand: String(officialStock),
    availableStock: String(sellerStock ?? 0),
    sellerStockValue: sellerStock,
    sellerStockEnabled,
    sellingPrice: formatMoney(listing.platform_price, listing.currency),
    sellingPriceValue: listing.platform_price,
    sales30d: formatInteger(apiSales30d ?? fallbackSales30d ?? 0),
    pageViews30d: formatInteger(pageViews30d ?? 0),
    cvr30d: formatPercentage(conversion30d ?? inferConversionRate(apiSales30d ?? fallbackSales30d, pageViews30d) ?? 0),
    wishlist30d: formatInteger(
      payloadNumber(listing.raw_payload, "wishlist_30_days") ??
        payloadNumber(listing.raw_payload, "wishlist_30d") ??
        payloadNumber(listing.raw_payload, "total_wishlist") ??
        0,
    ),
    returns30d: formatInteger(returns30d ?? 0),
  };
}

function buildSalesMetricMap(metrics: StoreListingMetricListResponse["metrics"]) {
  return new Map(metrics.map((metric) => [metricKey(metric.store_id, metric.sku), metric.sales_30d]));
}

function metricKey(storeId: string, sku: string) {
  return `${storeId}:${sku}`;
}

function cellSavingKey(listingId: string, field: EditableField) {
  return `${listingId}:${field}`;
}

function sameNumber(current: number | null, next: number) {
  if (current === null) return false;
  return Math.abs(current - next) < 0.005;
}

function formatDraftNumber(value: number, integer: boolean) {
  return integer ? String(Math.round(value)) : String(Number(value.toFixed(2)));
}

function parseEditableNumber(value: string, integer: boolean) {
  const normalized = value.replace(/[^\d.]/g, "");
  if (!normalized) return null;
  const parsed = integer ? Number.parseInt(normalized, 10) : Number.parseFloat(normalized);
  if (!Number.isFinite(parsed) || parsed < 0) return null;
  return integer ? Math.round(parsed) : parsed;
}

function currencyPrefix(currency: string) {
  if (currency === "ZAR") return "R";
  return currency;
}

function productCacheKey(
  storeId: string,
  page: number,
  query: string,
  nextStatusFilter: ListingStatusFilter,
  nextSortField: SortField,
  nextSortDirection: SortDirection,
) {
  return `${storeId}:${page}:${query.trim().toLowerCase()}:${nextStatusFilter}:${nextSortField}:${nextSortDirection}`;
}

function isFresh(fetchedAt: number, ttlMs: number) {
  return Date.now() - fetchedAt <= ttlMs;
}

function clearProductCacheForStore(storeId: string) {
  for (const key of productPageCache.keys()) {
    if (key.startsWith(`${storeId}:`)) {
      productPageCache.delete(key);
    }
  }
  if (typeof window === "undefined") return;
  const prefix = `${productCacheStoragePrefix}${storeId}:`;
  for (let index = window.sessionStorage.length - 1; index >= 0; index -= 1) {
    const key = window.sessionStorage.key(index);
    if (key?.startsWith(prefix)) window.sessionStorage.removeItem(key);
  }
}

function readStoreCache() {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.sessionStorage.getItem(storeCacheStorageKey);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as { stores?: StoreSummary[]; fetchedAt?: number };
    if (!Array.isArray(parsed.stores) || typeof parsed.fetchedAt !== "number") return null;
    return { stores: parsed.stores, fetchedAt: parsed.fetchedAt };
  } catch {
    return null;
  }
}

function writeStoreCache(cache: { stores: StoreSummary[]; fetchedAt: number }) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(storeCacheStorageKey, JSON.stringify(cache));
  } catch {
    // Session cache is an optimization only.
  }
}

function readProductPageCache(cacheKey: string): CachedProductPage | null {
  if (typeof window === "undefined") return null;
  try {
    const stored = window.sessionStorage.getItem(`${productCacheStoragePrefix}${cacheKey}`);
    if (!stored) return null;
    const parsed = JSON.parse(stored) as {
      listings?: StoreListing[];
      total?: number;
      salesMetrics?: Array<[string, number]>;
      statusCounts?: Partial<Record<ListingStatusFilter, number>>;
      fetchedAt?: number;
    };
    if (!Array.isArray(parsed.listings) || typeof parsed.fetchedAt !== "number") return null;
    const cache: CachedProductPage = {
      listings: parsed.listings,
      total: typeof parsed.total === "number" ? parsed.total : parsed.listings.length,
      salesMetrics: new Map(parsed.salesMetrics ?? []),
      statusCounts: parsed.statusCounts ?? {},
      fetchedAt: parsed.fetchedAt,
    };
    productPageCache.set(cacheKey, cache);
    return cache;
  } catch {
    return null;
  }
}

function writeProductPageCache(cacheKey: string, cache: CachedProductPage) {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(
      `${productCacheStoragePrefix}${cacheKey}`,
      JSON.stringify({
        listings: cache.listings,
        total: cache.total,
        salesMetrics: Array.from(cache.salesMetrics.entries()),
        statusCounts: cache.statusCounts,
        fetchedAt: cache.fetchedAt,
      }),
    );
  } catch {
    // Session cache is an optimization only.
  }
}

function uniqueStrings(values: Array<string | null | undefined>) {
  return Array.from(
    new Set(values.map((value) => value?.trim()).filter((value): value is string => Boolean(value))),
  );
}

function normalizeColumnVisibility(value: unknown) {
  const stored = isRecord(value) ? value : {};
  const next = { ...initialVisibility };

  for (const column of columnDefinitions) {
    next[column.id] = column.fixed ? true : Boolean(stored[column.id] ?? initialVisibility[column.id]);
  }

  return next;
}

function normalizeStatusCounts(value: unknown, total: number) {
  const source = isRecord(value) ? value : {};
  const next: Partial<Record<ListingStatusFilter, number>> = {
    all: numericValue(source.all) ?? total,
    buyable: numericValue(source.buyable) ?? 0,
    not_buyable: numericValue(source.not_buyable) ?? 0,
    platform_disabled: numericValue(source.platform_disabled) ?? 0,
    seller_disabled: numericValue(source.seller_disabled) ?? 0,
  };
  return next;
}

function listingStatusGroup(listing: StoreListing): ListingStatusGroup {
  const statusText = listingStatusText(listing);
  const platformDisabled = platformDisabledTokens.some((token) => statusText.includes(token));
  const sellerDisabled = sellerDisabledTokens.some((token) => statusText.includes(token));
  const buyable =
    buyableStatusPattern.test(statusText) &&
    !disabledStatusPattern.test(statusText) &&
    !platformDisabled &&
    !sellerDisabled;

  if (platformDisabled) return "platform_disabled";
  if (sellerDisabled) return "seller_disabled";
  if (buyable) return "buyable";
  return "not_buyable";
}

function listingStatusText(listing: StoreListing) {
  const values: unknown[] = [];
  appendNestedPayloadStatus(listing.raw_payload, values);
  values.push(listing.sync_status);
  return values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => String(value).toLowerCase())
    .join(" ");
}

function appendNestedPayloadStatus(payload: unknown, values: unknown[]) {
  appendPayloadStatus(payload, values);
  if (!isRecord(payload)) return;
  appendPayloadStatus(payload.payload, values);
  appendPayloadStatus(payload.offer, values);
}

function appendPayloadStatus(payload: unknown, values: unknown[]) {
  if (!isRecord(payload)) return;
  for (const key of ["status", "offer_status", "availability", "state"]) {
    values.push(payload[key]);
  }
}

function isSortableColumn(columnId: ColumnDefinition["id"]): columnId is SortField {
  return sortableColumns.has(columnId);
}

function isNumericColumn(columnId: ColumnDefinition["id"]) {
  return numericColumns.has(columnId);
}

function defaultSortDirection(columnId: SortField): SortDirection {
  if (columnId === "createdAt") return "desc";
  return "desc";
}

function offerPayload(payload: { [key: string]: unknown } | null) {
  if (!payload) return null;
  return isRecord(payload.offer) ? payload.offer : payload;
}

function officialWarehouseStock(payload: { [key: string]: unknown } | null) {
  const direct =
    payloadNumber(payload, "total_takealot_stock") ??
    payloadNumber(payload, "stock_at_takealot_total") ??
    payloadNumber(payload, "takealot_stock_quantity");
  if (direct !== null) return direct;
  return sumWarehouseStock(payload?.takealot_warehouse_stock);
}

function sellerWarehouseEnabled(payload: { [key: string]: unknown } | null) {
  const source = offerPayload(payload);
  const explicitEnabled =
    payloadBoolean(source, "leadtime_enabled") ?? payloadBoolean(source, "leadtimeEnabled");
  if (explicitEnabled === false) return false;
  const leadtimeDays =
    payloadNumber(source, "leadtime_days") ??
    payloadNumber(source, "minimum_leadtime_days") ??
    payloadNumber(source, "minimum_leadtime");
  if (leadtimeDays !== null) return leadtimeDays > 0;
  if (explicitEnabled === true) return true;
  const fallbackSellerStock = sumWarehouseStock(source?.seller_warehouse_stock);
  return fallbackSellerStock !== null && fallbackSellerStock > 0 && payloadLooksBuyable(payload);
}

function sellerWarehouseStock(payload: { [key: string]: unknown } | null) {
  const source = offerPayload(payload);
  if (!sellerWarehouseEnabled(payload)) return 0;
  const leadtimeStock =
    sumWarehouseStock(source?.leadtime_stock) ??
    sumWarehouseStock(source?.merchant_warehouse_stock);
  if (leadtimeStock !== null) return leadtimeStock;
  const direct =
    payloadNumber(source, "total_merchant_stock") ??
    payloadNumber(source, "seller_stock_quantity");
  if (direct !== null) return direct;
  return sumWarehouseStock(source?.seller_warehouse_stock) ?? 0;
}

function sales30dFromPayload(payload: { [key: string]: unknown } | null) {
  const direct =
    payloadNumber(payload, "quantity_sold_30_days") ??
    payloadNumber(payload, "sales_30_days") ??
    payloadNumber(payload, "sales_30d") ??
    payloadNumber(payload, "quantity_sold_30d");
  if (direct !== null) return direct;

  return sumWarehouseMetric(payload?.takealot_warehouse_stock, [
    "quantity_sold_30_days",
    "quantitySold30Days",
  ]);
}

function inferConversionRate(sales: number | null, pageViews: number | null) {
  if (sales === null || pageViews === null || pageViews <= 0) return null;
  return (sales / pageViews) * 100;
}

function sumWarehouseStock(value: unknown) {
  if (!Array.isArray(value)) return null;

  let total = 0;
  let hasValue = false;
  for (const item of value) {
    if (!isRecord(item)) continue;
    const quantity =
      numericValue(item.quantity_available) ??
      numericValue(item.quantityAvailable) ??
      numericValue(item.quantity);
    if (quantity === null) continue;
    total += quantity;
    hasValue = true;
  }

  return hasValue ? total : null;
}

function sumWarehouseMetric(value: unknown, keys: string[]) {
  if (!Array.isArray(value)) return null;

  let total = 0;
  let hasValue = false;
  for (const item of value) {
    if (!isRecord(item)) continue;
    for (const key of keys) {
      const quantity = numericValue(item[key]);
      if (quantity === null) continue;
      total += quantity;
      hasValue = true;
      break;
    }
  }

  return hasValue ? total : null;
}

function payloadLooksBuyable(payload: unknown) {
  const values: unknown[] = [];
  appendNestedPayloadStatus(payload, values);
  const statusText = values
    .filter((value) => value !== null && value !== undefined && value !== "")
    .map((value) => String(value).toLowerCase())
    .join(" ");
  const platformDisabled = platformDisabledTokens.some((token) => statusText.includes(token));
  const sellerDisabled = sellerDisabledTokens.some((token) => statusText.includes(token));
  return (
    buyableStatusPattern.test(statusText) &&
    !disabledStatusPattern.test(statusText) &&
    !platformDisabled &&
    !sellerDisabled
  );
}

function payloadImageUrl(payload: { [key: string]: unknown } | null) {
  const directKeys = [
    "image_url",
    "imageUrl",
    "main_image",
    "mainImage",
    "thumbnail",
    "thumbnail_url",
    "thumbnailUrl",
    "product_image",
    "productImage",
    "primary_image",
    "primaryImage",
  ];

  for (const key of directKeys) {
    const direct = normalizeImageUrl(payloadString(payload, key));
    if (direct) return direct;
  }

  const nestedKeys = ["image", "images", "media", "product", "offer", "takealot"];
  for (const key of nestedKeys) {
    const nested = imageUrlFromUnknown(payload?.[key], 0);
    if (nested) return nested;
  }

  return null;
}

function buildImageCandidates(imageUrl: string | null) {
  const normalized = normalizeImageUrl(imageUrl);
  if (!normalized) return [];

  const candidates: string[] = [];
  const addCandidate = (candidate: string) => {
    if (!candidates.includes(candidate)) candidates.push(candidate);
  };

  if (normalized.includes("/s-300x300.file")) {
    addCandidate(normalized.replace("/s-300x300.file", "/s-pdpxl.file"));
    addCandidate(normalized.replace("/s-300x300.file", "/s-zoom.file"));
  }

  if (normalized.endsWith("-300x300.jpg")) {
    addCandidate(normalized.replace("-300x300.jpg", "-pdpxl.jpg"));
    addCandidate(normalized.replace("-300x300.jpg", "-zoom.jpg"));
  }

  addCandidate(normalized);
  return candidates;
}

function imageUrlFromUnknown(value: unknown, depth: number): string | null {
  if (depth > 3) return null;

  if (typeof value === "string") {
    return normalizeImageUrl(value);
  }

  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = imageUrlFromUnknown(item, depth + 1);
      if (nested) return nested;
    }
    return null;
  }

  if (!isRecord(value)) return null;

  const likelyKeys = [
    "url",
    "src",
    "href",
    "image_url",
    "imageUrl",
    "thumbnail",
    "thumbnail_url",
    "large",
    "medium",
    "small",
  ];

  for (const key of likelyKeys) {
    const nested = imageUrlFromUnknown(value[key], depth + 1);
    if (nested) return nested;
  }

  return null;
}

function normalizeImageUrl(value: string | null) {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("//")) return `https:${trimmed}`;
  if (
    trimmed.startsWith("http://") ||
    trimmed.startsWith("https://") ||
    trimmed.startsWith("data:image/") ||
    trimmed.startsWith("/")
  ) {
    return trimmed;
  }
  return null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function payloadNumber(payload: { [key: string]: unknown } | null, key: string) {
  return numericValue(payload?.[key]);
}

function payloadBoolean(payload: { [key: string]: unknown } | null, key: string) {
  return booleanValue(payload?.[key]);
}

function booleanValue(value: unknown) {
  if (typeof value === "boolean") return value;
  if (value === 0 || value === 1) return Boolean(value);
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes", "y"].includes(normalized)) return true;
    if (["false", "0", "no", "n"].includes(normalized)) return false;
  }
  return null;
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const numeric = Number.parseFloat(value);
    if (Number.isFinite(numeric)) return numeric;
  }
  return null;
}

function payloadString(payload: { [key: string]: unknown } | null, key: string) {
  const value = payload?.[key];
  if (typeof value === "string" && value.trim()) return value.trim();
  if (typeof value === "number") return String(value);
  return null;
}

function formatMoney(value: number | null, currency = "ZAR") {
  if (value === null) return "--";
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(value);
}

function formatInteger(value: number | null) {
  if (value === null) return "--";
  return new Intl.NumberFormat("en-ZA", {
    maximumFractionDigits: 0,
  }).format(value);
}

function formatCompactInteger(value: number | null) {
  if (value === null) return "--";
  return new Intl.NumberFormat("en-ZA", {
    notation: value >= 10000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
}

function formatDate(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function formatPercentage(value: number | null) {
  if (value === null) return "--";
  const percent = value >= 0 && value <= 1 ? value * 100 : value;
  return `${new Intl.NumberFormat("en-ZA", {
    maximumFractionDigits: percent < 10 ? 1 : 0,
  }).format(percent)}%`;
}

function shortId(value: string) {
  return value.slice(0, 8);
}

function buildTakealotProductUrl(title: string, platformProductId: string | null | undefined) {
  const normalizedProductId = normalizePlatformProductId(platformProductId);
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `https://www.takealot.com/${slug || "product"}/${normalizedProductId || platformProductId || ""}`;
}

function normalizePlatformProductId(value: string | null | undefined) {
  const compact = (value ?? "").trim().replace(/\s+/g, "");
  const numeric = compact.replace(/^(PLID)+/i, "");
  return numeric ? `PLID${numeric}` : "";
}

function formatPlatformProductId(value: string | null | undefined) {
  const normalized = normalizePlatformProductId(value);
  return normalized ? normalized.replace(/^PLID/i, "PLID ") : "--";
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "未同步";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "未同步";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}
