"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ChevronLeft,
  ChevronRight,
  Pencil,
  PauseCircle,
  PlayCircle,
  RefreshCcw,
  Search,
  Upload,
  X,
} from "lucide-react";
import { Toaster, toast } from "sonner";

import type { components } from "@/generated/api-types";
import { ApiError, apiFetch } from "@/lib/api";

type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type StoreListingListResponse = components["schemas"]["StoreListingListResponse"];
type StoreListing = components["schemas"]["StoreListingResponse"];
type BiddingRuleListResponse = components["schemas"]["BiddingRuleListResponse"];
type BiddingRuleLogListResponse = components["schemas"]["BiddingRuleLogListResponse"];
type BiddingRule = components["schemas"]["BiddingRuleResponse"];
type BiddingStoreStatus = components["schemas"]["BiddingStoreStatusResponse"];
type BulkImportBiddingRuleResponse = components["schemas"]["BulkImportBiddingRuleResponse"];
type StoreSyncTaskListResponse = components["schemas"]["StoreSyncTaskListResponse"];
type StoreSyncTask = StoreSyncTaskListResponse["tasks"][number];
type TaskCreatedResponse = components["schemas"]["TaskCreatedResponse"];

type BiddingRow = {
  id: string;
  title: string;
  sku: string;
  listingId: string | null;
  offerId: string | null;
  plid: string | null;
  imageUrl: string | null;
  currentPrice: number | null;
  currency: string;
  stockQuantity: number | null;
  rawPayload: { [key: string]: unknown } | null;
  rule: BiddingRule | null;
};

type BiddingStatusFilter =
  | "all"
  | "active"
  | "with_floor"
  | "won"
  | "lost"
  | "alerts"
  | "blocked"
  | "paused"
  | "unconfigured";

type BiddingRowState =
  | "unconfigured"
  | "paused"
  | "needs_floor"
  | "won"
  | "lost"
  | "lost_floor"
  | "blocked"
  | "retrying"
  | "pending";

const templateHref = "/downloads/auto-bidding-floor-template.xlsx";
const tablePageSize = 100;
const syncTaskPollMs = 5_000;
const syncTaskFreshWindowMs = 15 * 60_000;
const queuedSyncTaskFreshWindowMs = 2 * 60_000;
const activeSyncTaskTypes = new Set(["SYNC_STORE_LISTINGS", "store.sync.full"]);
const activeSyncStatuses = new Set(["queued", "leased", "running"]);
const failedSyncStatuses = new Set(["failed", "failed_final", "dead_letter", "timed_out"]);
const manualSyncStorageKey = "xiaohei.bidding.manualSyncAt.v1";

export default function AutoBiddingPage() {
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [listings, setListings] = useState<StoreListing[]>([]);
  const [totalListings, setTotalListings] = useState(0);
  const [rules, setRules] = useState<BiddingRule[]>([]);
  const [logRules, setLogRules] = useState<BiddingRule[]>([]);
  const [storeStatus, setStoreStatus] = useState<BiddingStoreStatus | null>(null);
  const [searchText, setSearchText] = useState("");
  const [statusFilter, setStatusFilter] = useState<BiddingStatusFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [floorDrafts, setFloorDrafts] = useState<Record<string, string>>({});
  const [modalOpen, setModalOpen] = useState(false);
  const [selectedFileName, setSelectedFileName] = useState("");
  const [importItems, setImportItems] = useState<Array<{ sku: string; floor_price: number }>>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);
  const [isStartingSync, setIsStartingSync] = useState(false);
  const [activeSyncByStore, setActiveSyncByStore] = useState<Record<string, boolean>>({});
  const [lastManualSyncByStore, setLastManualSyncByStore] = useState<Record<string, string>>({});
  const [savingSku, setSavingSku] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [imagePreview, setImagePreview] = useState<{ title: string; imageUrl: string } | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const selectedStore = stores.find((store) => store.store_id === selectedStoreId) ?? null;
  const selectedStoreIsSyncing = Boolean(selectedStoreId && activeSyncByStore[selectedStoreId]);
  const lastSyncTime =
    (selectedStoreId ? lastManualSyncByStore[selectedStoreId] : null) ??
    selectedStore?.last_synced_at ??
    null;

  const rows = useMemo(() => {
    const ruleBySku = new Map(rules.map((rule) => [rule.sku, rule]));
    const listingRows: BiddingRow[] = listings.map((listing) => {
      const rule = ruleBySku.get(listing.sku) ?? null;
      return {
        id: listing.listing_id,
        title: listing.title,
        sku: listing.sku,
        listingId: listing.listing_id,
        offerId: listing.external_listing_id,
        plid: normalizePlid(listing.platform_product_id ?? payloadString(listing.raw_payload, "productline_id")),
        imageUrl: payloadImageUrl(listing.raw_payload),
        currentPrice: listing.platform_price,
        currency: listing.currency,
        stockQuantity: biddingStockQuantity(listing.raw_payload, listing.stock_quantity),
        rawPayload: listing.raw_payload,
        rule: isEmptyInactiveRule(rule) ? null : rule,
      };
    });

    return listingRows;
  }, [listings, rules]);

  const dashboardMetrics = useMemo(() => buildBiddingMetrics(rows, storeStatus), [rows, storeStatus]);

  const filteredRows = useMemo(() => {
    const keyword = searchText.trim().toLowerCase();
    return rows.filter((row) => {
      const matchesKeyword =
        !keyword ||
        [row.title, row.sku, row.offerId, row.plid]
        .filter(Boolean)
        .join(" ")
        .toLowerCase()
          .includes(keyword);
      return matchesKeyword && rowMatchesFilter(row, statusFilter);
    });
  }, [rows, searchText, statusFilter]);

  const isServerPagedFilter = statusFilter === "all" || statusFilter === "with_floor";
  const totalFilteredRows = isServerPagedFilter ? totalListings : filteredRows.length;
  const totalPages = Math.max(1, Math.ceil(totalFilteredRows / tablePageSize));
  const pageStart = totalFilteredRows === 0 ? 0 : (currentPage - 1) * tablePageSize + 1;
  const pageEnd = Math.min(currentPage * tablePageSize, totalFilteredRows);
  const pagedRows = filteredRows;
  const isInitialWorkspaceLoading = isLoading || (isRefreshing && listings.length === 0 && rows.length === 0);
  const hasRows = pagedRows.length > 0;
  const hasActiveRows = pagedRows.some((row) => row.rule?.is_active);
  const hasEnableableRows = pagedRows.some((row) => row.listingId && getFloorValue(row, floorDrafts) !== null);

  useEffect(() => {
    void loadStores();
  }, []);

  useEffect(() => {
    setCurrentPage(1);
  }, [searchText, selectedStoreId, statusFilter]);

  useEffect(() => {
    if (!selectedStoreId) return;
    void loadWorkspace(selectedStoreId);
  }, [currentPage, searchText, selectedStoreId, statusFilter]);

  useEffect(() => {
    setCurrentPage((page) => Math.min(Math.max(page, 1), totalPages));
  }, [totalPages]);

  useEffect(() => {
    if (!selectedStoreId) return;
    let isCancelled = false;
    let wasSyncing = Boolean(activeSyncByStore[selectedStoreId]);

    async function pollSyncTask() {
      const syncState = await fetchStoreSyncTaskState(selectedStoreId);
      const active = syncState.active;
      if (isCancelled) return;
      setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: active }));
      if (wasSyncing && !active) {
        if (syncState.latestStatus && failedSyncStatuses.has(syncState.latestStatus)) {
          toast.error("商品同步未完成", {
            description: syncState.latestError || "同步任务排队超时，已自动释放按钮，请重新点击同步。",
          });
        } else {
          toast.success("商品同步已完成", {
            description: "已重新读取店铺商品，竞价台现在使用最新列表。",
          });
        }
        await loadStores();
        await loadWorkspace(selectedStoreId);
      }
      wasSyncing = active;
    }

    void pollSyncTask();
    const timer = window.setInterval(() => void pollSyncTask(), syncTaskPollMs);
    return () => {
      isCancelled = true;
      window.clearInterval(timer);
    };
  }, [selectedStoreId]);

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

  async function loadStores() {
    setIsLoading(true);
    setErrorMessage("");
    try {
      const storeData = await apiFetch<StoreListResponse>("/api/v1/stores");
      setStores(storeData.stores);
      setSelectedStoreId((current) => current || storeData.stores[0]?.store_id || "");
      if (storeData.stores.length === 0) {
        setListings([]);
        setTotalListings(0);
        setRules([]);
        setLogRules([]);
        setStoreStatus(null);
        setIsLoading(false);
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载店铺失败");
      setStores([]);
      setSelectedStoreId("");
      setListings([]);
      setTotalListings(0);
      setRules([]);
      setLogRules([]);
      setStoreStatus(null);
      setIsLoading(false);
    }
  }

  async function loadWorkspace(
    storeId: string,
    filter: BiddingStatusFilter = statusFilter,
    page: number = currentPage,
  ) {
    setIsRefreshing(true);
    setErrorMessage("");
    try {
      const [ruleData, listingData, logData, statusData] = await Promise.all([
        apiFetch<BiddingRuleListResponse>(`/api/v1/bidding/rules?store_id=${encodeURIComponent(storeId)}`),
        fetchStoreListingPage(storeId, filter, page).catch(() => ({ listings: [], total: 0 })),
        apiFetch<BiddingRuleLogListResponse>(`/api/v1/bidding/stores/${encodeURIComponent(storeId)}/log`),
        apiFetch<BiddingStoreStatus>(`/api/v1/bidding/stores/${encodeURIComponent(storeId)}/status`),
      ]);
      setRules(ruleData.rules);
      setListings(listingData.listings);
      setTotalListings(listingData.total);
      setLogRules(logData.rules);
      setStoreStatus(statusData);
      setFloorDrafts({});
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "加载竞价数据失败");
      setRules([]);
      setListings([]);
      setTotalListings(0);
      setLogRules([]);
      setStoreStatus(null);
    } finally {
      setIsLoading(false);
      setIsRefreshing(false);
    }
  }

  async function fetchStoreListingPage(
    storeId: string,
    filter: BiddingStatusFilter = statusFilter,
    page: number = currentPage,
  ) {
    const params = new URLSearchParams({
      limit: String(tablePageSize),
      offset: String((page - 1) * tablePageSize),
      status_group: "buyable",
      sort_by: "createdAt",
      sort_dir: "desc",
    });
    const keyword = searchText.trim();
    if (keyword) {
      params.set("q", keyword);
    }
    if (filter === "with_floor") {
      params.set("bidding_filter", "with_floor");
    }
    const pageData = await apiFetch<StoreListingListResponse>(
      `/api/v1/stores/${encodeURIComponent(storeId)}/listings?${params.toString()}`,
    );
    return { listings: pageData.listings, total: pageData.total ?? pageData.listings.length };
  }

  async function startStoreSync() {
    if (!selectedStoreId || isStartingSync || selectedStoreIsSyncing) return;
    setIsStartingSync(true);
    try {
      if (await hasActiveStoreSyncTask(selectedStoreId)) {
        setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
        toast.info("商品同步正在进行", {
          description: "商品多时会花几分钟；完成后竞价台会自动刷新。",
        });
        return;
      }

      await apiFetch<TaskCreatedResponse>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}/sync`,
        {
          method: "POST",
          body: JSON.stringify({
            reason: "用户在自动竞价页手动同步商品数据",
            sync_scope: "bidding",
          }),
        },
      );
      const syncedAt = new Date().toISOString();
      setLastManualSyncByStore((current) => {
        const next = { ...current, [selectedStoreId]: syncedAt };
        window.localStorage.setItem(manualSyncStorageKey, JSON.stringify(next));
        return next;
      });
      setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
      toast.success("同步任务已提交");
      await loadStores();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        setActiveSyncByStore((current) => ({ ...current, [selectedStoreId]: true }));
        toast.info("商品同步正在进行", {
          description: "商品多时会花几分钟；完成后竞价台会自动刷新。",
        });
        return;
      }
      toast.error("同步提交失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
    } finally {
      setIsStartingSync(false);
    }
  }

  function updateFloorDraft(sku: string, nextValue: string) {
    setFloorDrafts((current) => ({ ...current, [sku]: nextValue }));
  }

  async function saveFloorPrice(row: BiddingRow, activateAfterCreate = false) {
    if (!selectedStoreId) return null;
    const floorPrice = getFloorValue(row, floorDrafts);
    const draftValue = floorDrafts[row.sku];
    const hasDraft = draftValue !== undefined;
    const trimmedDraft = (draftValue ?? "").trim();

    if (floorPrice === null) {
      if (!activateAfterCreate && hasDraft && trimmedDraft.length === 0) {
        if (!row.rule || row.rule.floor_price === null) return row.rule ?? null;
        setSavingSku(row.sku);
        try {
          const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(row.rule.rule_id)}`, {
            method: "PATCH",
            body: JSON.stringify({
              listing_id: row.listingId,
              floor_price: null,
              is_active: false,
            }),
          });
          mergeRules([updated]);
          setFloorDrafts((current) => ({ ...current, [row.sku]: "" }));
          toast.success("已清空保护底价，并暂停该商品监控");
          return updated;
        } catch (error) {
          toast.error("清空底价失败", {
            description: error instanceof Error ? error.message : "请稍后再试",
          });
          setFloorDrafts((current) => ({ ...current, [row.sku]: String(row.rule?.floor_price ?? "") }));
          return row.rule ?? null;
        } finally {
          setSavingSku(null);
        }
      }
      if (activateAfterCreate) {
        toast.error("请先填写大于 0 的保护底价");
      } else if (hasDraft && trimmedDraft.length > 0) {
        toast.error("保护底价必须大于 0");
      }
      if (row.rule?.floor_price != null) {
        setFloorDrafts((current) => ({ ...current, [row.sku]: String(row.rule?.floor_price ?? "") }));
      }
      return row.rule ?? null;
    }

    if (row.rule && (row.rule.floor_price ?? null) === floorPrice && row.rule.listing_id === row.listingId) {
      return row.rule;
    }

    setSavingSku(row.sku);
    try {
      if (row.rule) {
        const payload: { listing_id: string | null; floor_price: number | null } = {
          listing_id: row.listingId,
          floor_price: floorPrice,
        };
        const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(row.rule.rule_id)}`, {
          method: "PATCH",
          body: JSON.stringify(payload),
        });
        mergeRules([updated]);
        return updated;
      }

      const imported = await apiFetch<BulkImportBiddingRuleResponse>(
        `/api/v1/bidding/rules/bulk-import?store_id=${encodeURIComponent(selectedStoreId)}`,
        {
          method: "POST",
          body: JSON.stringify([{ sku: row.sku, floor_price: floorPrice }]),
        },
      );
      const created = imported.rules[0] ?? null;
      if (!created) return null;
      const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(created.rule_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ listing_id: row.listingId, is_active: activateAfterCreate }),
      });
      mergeRules([updated]);
      return updated;
    } catch (error) {
      toast.error("保存底价失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
      return null;
    } finally {
      setSavingSku(null);
    }
  }

  async function toggleMonitoring(row: BiddingRow) {
    if (!selectedStoreId) return;
    const desiredActive = !row.rule?.is_active;

    if (desiredActive && getFloorValue(row, floorDrafts) === null) {
      toast.error("请先填写大于 0 的保护底价");
      return;
    }

    setSavingSku(row.sku);
    try {
      if (!desiredActive && row.rule) {
        const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(row.rule.rule_id)}`, {
          method: "PATCH",
          body: JSON.stringify({ listing_id: row.listingId, is_active: false }),
        });
        mergeRules([updated]);
        return;
      }

      const rule = await saveFloorPrice(row, desiredActive);
      if (!rule) return;
      if (rule.is_active === desiredActive) {
        return;
      }
      const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(rule.rule_id)}`, {
        method: "PATCH",
        body: JSON.stringify({ listing_id: row.listingId, is_active: desiredActive }),
      });
      mergeRules([updated]);
    } catch (error) {
      toast.error("更新监控状态失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
    } finally {
      setSavingSku(null);
    }
  }

  async function enableAllBidding() {
    if (!selectedStoreId || !hasRows) return;
    setIsRefreshing(true);
    try {
      const updatedRules: BiddingRule[] = [];
      let skippedCount = 0;
      for (const row of pagedRows) {
        if (!row.listingId || getFloorValue(row, floorDrafts) === null) {
          skippedCount += 1;
          continue;
        }
        const rule = row.rule ?? (await saveFloorPrice(row, true));
        if (!rule || rule.is_active) continue;
        const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(rule.rule_id)}`, {
          method: "PATCH",
          body: JSON.stringify({ listing_id: row.listingId, is_active: true }),
        });
        updatedRules.push(updated);
      }
      if (updatedRules.length) mergeRules(updatedRules);
      if (updatedRules.length) {
        toast.success("已开启本页可竞价商品", {
          description: skippedCount ? `已跳过 ${skippedCount} 个未填写保护底价的商品` : undefined,
        });
      } else if (skippedCount) {
        toast.error("没有可开启的商品", {
          description: "请先填写大于 0 的保护底价",
        });
      } else {
        toast.success("可竞价商品已是开启状态");
      }
    } catch (error) {
      toast.error("批量开启失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
    } finally {
      setIsRefreshing(false);
    }
  }

  async function disableAllBidding() {
    if (!selectedStoreId || !hasActiveRows) return;
    setIsRefreshing(true);
    try {
      const updatedRules: BiddingRule[] = [];
      for (const row of pagedRows) {
        if (!row.rule?.is_active) continue;
        const updated = await apiFetch<BiddingRule>(`/api/v1/bidding/rules/${encodeURIComponent(row.rule.rule_id)}`, {
          method: "PATCH",
          body: JSON.stringify({ listing_id: row.listingId, is_active: false }),
        });
        updatedRules.push(updated);
      }
      if (updatedRules.length) mergeRules(updatedRules);
      toast.success(`已暂停本页 ${updatedRules.length} 个商品`);
    } catch (error) {
      toast.error("批量暂停失败", {
        description: error instanceof Error ? error.message : "请稍后再试",
      });
    } finally {
      setIsRefreshing(false);
    }
  }

  function mergeRules(nextRules: BiddingRule[]) {
    setRules((current) => {
      const byId = new Map(current.map((rule) => [rule.rule_id, rule]));
      nextRules.forEach((rule) => byId.set(rule.rule_id, rule));
      return Array.from(byId.values());
    });
  }

  function closeModal() {
    setModalOpen(false);
    setSelectedFileName("");
    setImportItems([]);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleFileSelection(fileList: FileList | null) {
    const file = fileList?.[0];
    if (!file) return;
    setSelectedFileName(file.name);
    try {
      if (!/\.xlsx$/i.test(file.name)) {
        throw new Error("只支持 .xlsx 模板文件");
      }
      const items = await parseXlsxFloorPrices(await file.arrayBuffer());
      setImportItems(items);
      if (items.length === 0) {
        toast.error("没有读取到可导入的底价", {
          description: "请确认表格第一列是 SKU，第二列是保护底价。",
        });
      }
    } catch {
      setImportItems([]);
      toast.error("文件解析失败", {
        description: "请使用页面下载的 .xlsx 模板。",
      });
    }
  }

  async function confirmBulkImport() {
    if (!selectedStoreId || importItems.length === 0) return;
    setIsImporting(true);
    try {
      const result = await apiFetch<BulkImportBiddingRuleResponse>(
        `/api/v1/bidding/rules/bulk-import?store_id=${encodeURIComponent(selectedStoreId)}`,
        {
          method: "POST",
          body: JSON.stringify(importItems),
        },
      );
      mergeRules(result.rules);
      toast.success(`已导入 ${result.imported_count} 条底价`);
      closeModal();
      setStatusFilter("with_floor");
      setCurrentPage(1);
      await loadWorkspace(selectedStoreId, "with_floor", 1);
    } catch (error) {
      toast.error("批量导入失败", {
        description: error instanceof Error ? error.message : "请检查文件内容",
      });
    } finally {
      setIsImporting(false);
    }
  }

  return (
    <div className="min-h-[720px] w-full min-w-0 rounded-[6px] border border-[#E7E2D8] bg-[#FCFBF7] text-[#171717]">
      <Toaster
        richColors={false}
        position="top-right"
        toastOptions={{
          style: {
            background: "#FFFFFF",
            color: "#171717",
            border: "1px solid #E7E2D8",
            borderRadius: "6px",
            boxShadow: "0 12px 32px rgba(23, 23, 23, 0.08)",
          },
        }}
      />

      <div className="min-w-0 space-y-5 px-6 py-5">
        <header>
          <h1 className="text-[28px] font-semibold text-[#171717]">自动竞价</h1>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <select
              value={selectedStoreId}
              onChange={(event) => setSelectedStoreId(event.target.value)}
              className="h-9 min-w-[190px] rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm outline-none focus:border-[#2F6F63]"
            >
              {stores.map((store) => (
                <option key={store.store_id} value={store.store_id}>
                  {store.name}
                </option>
              ))}
            </select>
            <span className="text-xs text-[#706A5F]">
              {isInitialWorkspaceLoading ? "商品读取中" : `已加载商品 ${listings.length}/${totalListings}`}
            </span>
            <span className="text-xs text-[#706A5F]">同步 {formatDateTime(lastSyncTime)}</span>
          </div>
        </header>

        {errorMessage ? (
          <div className="rounded-[6px] border border-[#E4B4A7] bg-[#FFF7F4] px-4 py-3 text-sm text-[#A33A24]">
            {errorMessage}
          </div>
        ) : null}

        <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <BiddingMetricCard
            label="监控中商品"
            value={dashboardMetrics.active}
            caption="已开启自动监控"
            active={statusFilter === "active"}
            tone="default"
            onClick={() => setStatusFilter("active")}
          />
          <BiddingMetricCard
            label="赢得 BuyBox"
            value={dashboardMetrics.won}
            caption="当前由我方占领"
            active={statusFilter === "won"}
            tone="success"
            onClick={() => setStatusFilter("won")}
          />
          <BiddingMetricCard
            label="丢失 BuyBox"
            value={dashboardMetrics.lost}
            caption="需关注竞对价格"
            active={statusFilter === "lost"}
            tone="danger"
            onClick={() => setStatusFilter("lost")}
          />
          <BiddingMetricCard
            label="异常预警"
            value={dashboardMetrics.alerts}
            caption="触底价 / 缺货 / 阻断"
            active={statusFilter === "alerts"}
            tone="critical"
            onClick={() => setStatusFilter("alerts")}
          />
        </section>

        <div className="overflow-hidden rounded-[6px] border border-[#D9D2C6] bg-white">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E7E2D8] bg-[#FCFBF7] px-4 py-3">
            <div className="flex flex-1 flex-wrap items-center gap-3">
              <label className="relative block min-w-[280px] flex-1 max-w-[420px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#706A5F]" />
                <input
                  value={searchText}
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="搜索 SKU / 标题 / PLID"
                  className="h-9 w-full rounded-[6px] border border-[#D9D2C6] bg-white pl-9 pr-3 text-sm outline-none placeholder:text-[#8C8578] focus:border-[#2F6F63]"
                />
              </label>
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as BiddingStatusFilter)}
                className="h-9 min-w-[150px] rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm text-[#3E3A34] outline-none focus:border-[#2F6F63]"
              >
                <option value="all">全部状态</option>
                <option value="active">监控中</option>
                <option value="with_floor">有保护底价</option>
                <option value="won">占领中</option>
                <option value="lost">已丢失</option>
                <option value="alerts">异常预警</option>
                <option value="blocked">已阻断</option>
                <option value="paused">已暂停</option>
                <option value="unconfigured">未配置</option>
              </select>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              <a
                href={templateHref}
                download="auto-bidding-floor-template.xlsx"
                className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm text-[#3E3A34]"
              >
                <ArrowDownToLine className="h-4 w-4" />
                模板
              </a>
              <button
                type="button"
                onClick={() => setModalOpen(true)}
                className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm font-medium text-[#171717]"
              >
                <Upload className="h-4 w-4" />
                导入底价
              </button>
              <button
                type="button"
                disabled={!selectedStoreId || isStartingSync || selectedStoreIsSyncing}
                onClick={() => void startStoreSync()}
                className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm font-medium text-[#171717] disabled:cursor-not-allowed disabled:opacity-40"
                title={selectedStoreIsSyncing ? "商品同步正在进行" : "从 Takealot 同步店铺商品"}
              >
                <RefreshCcw className={["h-4 w-4", isStartingSync || selectedStoreIsSyncing ? "animate-spin" : ""].join(" ")} />
                {selectedStoreIsSyncing ? "同步中" : isStartingSync ? "提交中" : "同步商品"}
              </button>
              <button
                type="button"
                disabled={!hasRows || !hasEnableableRows || isRefreshing}
                onClick={() => void enableAllBidding()}
                className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm font-medium text-[#171717] disabled:cursor-not-allowed disabled:opacity-40"
                title={hasEnableableRows ? "开启当前页已填写底价的商品" : "请先填写保护底价"}
              >
                <PlayCircle className="h-4 w-4" />
                批量开启
              </button>
              <button
                type="button"
                disabled={!hasActiveRows || isRefreshing}
                onClick={() => void disableAllBidding()}
                className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm font-medium text-[#171717] disabled:cursor-not-allowed disabled:opacity-40"
              >
                <PauseCircle className="h-4 w-4" />
                批量暂停
              </button>
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[1180px] border-collapse text-left">
              <thead>
                <tr className="border-b border-[#E7E2D8] bg-[#F7F4ED] text-xs text-[#706A5F]">
                  <th className="h-11 min-w-[360px] px-4 font-medium">商品信息</th>
                  <th className="h-11 whitespace-nowrap px-4 text-right font-medium">当前价</th>
                  <th className="h-11 min-w-[220px] px-4 font-medium">竞价状态 & 当前 BuyBox</th>
                  <th className="h-11 whitespace-nowrap px-4 text-right font-medium">保底价设置</th>
                  <th className="h-11 whitespace-nowrap px-4 text-right font-medium">库存</th>
                  <th className="h-11 whitespace-nowrap px-4 font-medium">下次检查</th>
                  <th className="h-11 whitespace-nowrap px-4 font-medium">监控</th>
                </tr>
              </thead>
              <tbody>
                {isInitialWorkspaceLoading ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-sm text-[#706A5F]">
                      正在读取店铺商品和竞价规则...
                    </td>
                  </tr>
                ) : null}
                {pagedRows.map((row) => (
                  <BiddingTableRow
                    key={row.id}
                    row={row}
                    floorDraft={floorDrafts[row.sku]}
                    isSaving={savingSku === row.sku}
                    onFloorChange={(value) => updateFloorDraft(row.sku, value)}
                    onFloorBlur={() => void saveFloorPrice(row)}
                    onToggle={() => void toggleMonitoring(row)}
                    onImagePreview={(title, imageUrl) => setImagePreview({ title, imageUrl })}
                  />
                ))}
              </tbody>
            </table>
          </div>

          {!isLoading && filteredRows.length === 0 ? (
            <div className="px-6 py-12 text-center text-sm text-[#706A5F]">当前筛选下暂无可竞价商品。</div>
          ) : null}

          {filteredRows.length > 0 ? (
            <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#E7E2D8] bg-[#FCFBF7] px-4 py-3 text-sm text-[#706A5F]">
              <span>
                第 {pageStart}-{pageEnd} 行 / 共 {totalFilteredRows} 行 · 每页 {tablePageSize}
              </span>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={currentPage <= 1}
                  onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#D9D2C6] bg-white text-[#3E3A34] disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="上一页"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="min-w-[76px] text-center text-xs font-medium text-[#3E3A34]">
                  {currentPage} / {totalPages}
                </span>
                <button
                  type="button"
                  disabled={currentPage >= totalPages}
                  onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                  className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#D9D2C6] bg-white text-[#3E3A34] disabled:cursor-not-allowed disabled:opacity-40"
                  aria-label="下一页"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : null}

          <details className="border-t border-[#E7E2D8] bg-white px-4 py-3 text-sm text-[#706A5F]">
            <summary className="cursor-pointer text-xs font-medium text-[#706A5F]">折叠动作日志</summary>
            <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {logRules
                .filter((rule) => rule.last_action || rule.last_cycle_error || rule.last_suggested_price !== null)
                .slice(0, 6)
                .map((rule) => (
                  <div key={rule.rule_id} className="rounded-[6px] border border-[#EFE9DF] bg-[#FCFBF7] px-3 py-2">
                    <div className="truncate text-xs font-semibold text-[#171717]">{rule.sku}</div>
                    <div className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-xs">
                      <span>{actionLabel(rule.last_action) || "暂无动作"}</span>
                      <span>BuyBox {formatMoney(rule.last_buybox_price)}</span>
                      <span>建议 {formatMoney(rule.last_suggested_price)}</span>
                    </div>
                  </div>
                ))}
              {logRules.filter((rule) => rule.last_action || rule.last_cycle_error || rule.last_suggested_price !== null).length === 0 ? (
                <div className="text-xs text-[#706A5F]">暂无扫描日志。</div>
              ) : null}
            </div>
          </details>
        </div>
      </div>

      {modalOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 px-4">
          <div className="w-full max-w-[460px] rounded-[6px] border border-[#D9D2C6] bg-white">
            <div className="flex items-start justify-between border-b border-[#E7E2D8] px-5 py-4">
              <div>
                <div className="text-base font-semibold text-[#171717]">批量导入底价</div>
                <div className="mt-1 text-xs text-[#706A5F]">按当前店铺导入或更新 SKU 保护底价</div>
              </div>
              <button
                type="button"
                onClick={closeModal}
                className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#D9D2C6] text-[#706A5F]"
                aria-label="关闭批量导入"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-4 px-5 py-5">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="flex min-h-[150px] w-full flex-col items-center justify-center rounded-[6px] border border-dashed border-[#B8AD9B] bg-[#FCFBF7] px-6 text-center"
              >
                <Upload className="h-5 w-5 text-[#706A5F]" />
                <div className="mt-3 text-sm font-medium text-[#171717]">
                  {selectedFileName || "点击选择 XLSX 文件"}
                </div>
                <div className="mt-1 text-xs text-[#706A5F]">格式：第一列 SKU，第二列保护底价</div>
                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                  className="hidden"
                  onChange={(event) => void handleFileSelection(event.target.files)}
                />
              </button>

              <div className="flex items-center justify-between text-sm">
                <a
                  href={templateHref}
                  download="auto-bidding-floor-template.xlsx"
                  className="inline-flex items-center gap-2 text-[#706A5F] underline decoration-[#706A5F]/30 underline-offset-4"
                >
                  <ArrowDownToLine className="h-4 w-4" />
                  下载模板
                </a>
                <span className="text-xs text-[#706A5F]">
                  {importItems.length ? `${importItems.length} 条待导入` : "未选择文件"}
                </span>
              </div>

              <div className="flex justify-end gap-3 border-t border-[#E7E2D8] pt-4">
                <button
                  type="button"
                  onClick={closeModal}
                  className="inline-flex h-9 items-center rounded-[6px] border border-[#D9D2C6] bg-white px-3 text-sm text-[#706A5F]"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={!importItems.length || isImporting}
                  onClick={() => void confirmBulkImport()}
                  className="inline-flex h-9 items-center rounded-[6px] border border-[#2F6F63] bg-[#2F6F63] px-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {isImporting ? "导入中" : "确认导入"}
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}

      {imagePreview ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 px-4 py-6"
          onClick={() => setImagePreview(null)}
        >
          <div
            className="max-h-full w-full max-w-[760px] overflow-hidden rounded-[6px] border border-[#D9D2C6] bg-white shadow-[0_24px_80px_rgba(0,0,0,0.28)]"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-start justify-between gap-4 border-b border-[#E7E2D8] px-4 py-3">
              <div className="line-clamp-2 text-sm font-semibold text-[#171717]">{imagePreview.title}</div>
              <button
                type="button"
                onClick={() => setImagePreview(null)}
                className="inline-flex h-8 w-8 flex-none items-center justify-center rounded-[6px] border border-[#D9D2C6] text-[#706A5F]"
                aria-label="关闭图片预览"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="flex max-h-[72vh] items-center justify-center bg-[#FCFBF7] p-4">
              <img
                src={imagePreview.imageUrl}
                alt={imagePreview.title}
                className="max-h-[68vh] max-w-full rounded-[6px] object-contain"
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function BiddingMetricCard({
  label,
  value,
  caption,
  active,
  tone,
  onClick,
}: {
  label: string;
  value: number;
  caption: string;
  active: boolean;
  tone: "default" | "success" | "danger" | "critical";
  onClick: () => void;
}) {
  const toneClass = {
    default: "border-[#D9D2C6] bg-white text-[#171717]",
    success: "border-[#BFD8C7] bg-[#F4FBF5] text-[#245B32]",
    danger: "border-[#E4B4A7] bg-[#FFF7F4] text-[#A33A24]",
    critical: "border-[#D9363E] bg-[#FFF1F0] text-[#A33A24]",
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "group rounded-[6px] border px-4 py-3 text-left transition hover:-translate-y-px hover:shadow-[0_10px_24px_rgba(23,23,23,0.06)]",
        toneClass,
        active ? "ring-2 ring-[#171717]/10" : "",
      ].join(" ")}
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-medium text-[#706A5F]">{label}</span>
        <span className={["h-2 w-2 rounded-full", tone === "success" ? "bg-[#2F7D3D]" : tone === "danger" || tone === "critical" ? "bg-[#A33A24]" : "bg-[#B8AD9B]"].join(" ")} />
      </div>
      <div className="mt-2 text-3xl font-semibold leading-none">{value}</div>
      <div className="mt-2 text-xs text-[#706A5F]">{caption}</div>
    </button>
  );
}

async function hasActiveStoreSyncTask(storeId: string) {
  return (await fetchStoreSyncTaskState(storeId)).active;
}

async function fetchStoreSyncTaskState(storeId: string) {
  try {
    const taskData = await apiFetch<StoreSyncTaskListResponse>(
      `/api/v1/stores/${encodeURIComponent(storeId)}/sync-tasks`,
    );
    const syncTasks = taskData.tasks.filter((task) => activeSyncTaskTypes.has(task.task_type));
    const latestTask = syncTasks[0] ?? null;
    return {
      active: syncTasks.some((task) => isFreshActiveSyncTask(task)),
      latestStatus: latestTask?.status ?? null,
      latestError: latestTask?.error_msg ?? null,
    };
  } catch {
    return { active: false, latestStatus: null, latestError: null };
  }
}

function isFreshActiveSyncTask(task: StoreSyncTask) {
  if (!activeSyncTaskTypes.has(task.task_type) || !activeSyncStatuses.has(task.status)) {
    return false;
  }
  const timestamp = Date.parse(task.updated_at || task.created_at);
  if (!Number.isFinite(timestamp)) {
    return false;
  }
  const maxAge = task.status === "queued" ? queuedSyncTaskFreshWindowMs : syncTaskFreshWindowMs;
  return Date.now() - timestamp <= maxAge;
}

function isEmptyInactiveRule(rule: BiddingRule | null | undefined) {
  return Boolean(
    rule &&
      !rule.is_active &&
      rule.floor_price === null &&
      !rule.last_action &&
      !rule.last_cycle_error &&
      !rule.repricing_blocked_reason,
  );
}

function buildBiddingMetrics(rows: BiddingRow[], storeStatus: BiddingStoreStatus | null) {
  if (storeStatus) {
    return {
      active: storeStatus.active_rule_count,
      won: storeStatus.won_buybox_count ?? 0,
      lost: storeStatus.lost_buybox_count ?? 0,
      alerts: storeStatus.alert_count ?? 0,
    };
  }
  return rows.reduce(
    (acc, row) => {
      const state = biddingRowState(row);
      if (row.rule?.is_active) acc.active += 1;
      if (state === "won") acc.won += 1;
      if (state === "lost" || state === "lost_floor") acc.lost += 1;
      if (isAlertRow(row, state)) acc.alerts += 1;
      return acc;
    },
    { active: 0, won: 0, lost: 0, alerts: 0 },
  );
}

function rowMatchesFilter(row: BiddingRow, filter: BiddingStatusFilter) {
  const state = biddingRowState(row);
  if (filter === "all") return true;
  if (filter === "active") return Boolean(row.rule?.is_active);
  if (filter === "with_floor") return row.rule?.floor_price !== null && row.rule?.floor_price !== undefined;
  if (filter === "won") return state === "won";
  if (filter === "lost") return state === "lost" || state === "lost_floor";
  if (filter === "alerts") return isAlertRow(row, state);
  if (filter === "blocked") return state === "blocked";
  if (filter === "paused") return state === "paused";
  if (filter === "unconfigured") return state === "unconfigured" || state === "needs_floor";
  return true;
}

function biddingRowState(row: BiddingRow): BiddingRowState {
  const rule = row.rule;
  if (!rule) return "unconfigured";
  if (!rule.is_active) return "paused";
  if (rule.floor_price === null) return "needs_floor";
  if (rule.buybox_status === "blocked") return "blocked";
  if (rule.buybox_status === "retrying") return "retrying";
  if (rule.buybox_status === "fresh" || (rule.last_buybox_price !== null && rule.last_buybox_price !== undefined)) {
    if (ownsBuybox(rule)) return "won";
    return isBelowFloorLoss(row) ? "lost_floor" : "lost";
  }
  return "pending";
}

function isAlertRow(row: BiddingRow, state = biddingRowState(row)) {
  const rule = row.rule;
  return Boolean(
    state === "lost_floor" ||
      state === "blocked" ||
      state === "needs_floor" ||
      (row.stockQuantity !== null && row.stockQuantity <= 0 && rule?.is_active) ||
      rule?.last_cycle_error ||
      rule?.repricing_blocked_reason ||
      rule?.last_action === "floor",
  );
}

function ownsBuybox(rule: BiddingRule) {
  const decision = rule.last_decision as Record<string, unknown> | null | undefined;
  return decision?.owns_buybox === true;
}

function isBelowFloorLoss(row: BiddingRow) {
  const rule = row.rule;
  if (!rule || rule.floor_price === null || rule.last_buybox_price === null || ownsBuybox(rule)) return false;
  return Number(rule.last_buybox_price) < Number(rule.floor_price);
}

function BiddingTableRow({
  row,
  floorDraft,
  isSaving,
  onFloorChange,
  onFloorBlur,
  onToggle,
  onImagePreview,
}: {
  row: BiddingRow;
  floorDraft: string | undefined;
  isSaving: boolean;
  onFloorChange: (value: string) => void;
  onFloorBlur: () => void;
  onToggle: () => void;
  onImagePreview: (title: string, imageUrl: string) => void;
}) {
  const floorValue = floorDraft ?? (row.rule?.floor_price != null ? String(row.rule.floor_price) : "");
  const hasFloor = floorValue.trim().length > 0 && Number.parseFloat(floorValue) > 0;
  const toggleDisabled = isSaving || (!hasFloor && !row.rule?.is_active);
  const state = biddingRowState(row);
  const alertRow = isAlertRow(row, state);

  return (
    <tr
      className={[
        "border-b border-[#EFE9DF] text-sm last:border-b-0 hover:bg-[#FCFBF7]",
        state === "lost_floor" ? "bg-[#FFF7F4]" : alertRow ? "bg-[#FFFCF8]" : "",
      ].join(" ")}
    >
      <td className="px-4 py-3 align-top">
        <div className="flex items-start gap-3">
          <BiddingProductImage title={row.title} imageUrl={row.imageUrl} onPreview={onImagePreview} />
          <div className="min-w-0">
            <a
              href={productLink(row)}
              target="_blank"
              rel="noreferrer"
              className="line-clamp-2 font-medium leading-5 text-[#171717] underline-offset-4 hover:text-[#2F6F63] hover:underline"
              title="打开商品链接"
            >
              {row.title}
            </a>
            <div className="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-[#706A5F]">
              <span>SKU {row.sku}</span>
              {row.plid ? <span>{row.plid}</span> : null}
              {row.offerId ? <span>Offer {row.offerId}</span> : null}
            </div>
          </div>
        </div>
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-right align-top font-medium text-[#171717]">
        {formatMoney(row.currentPrice)}
      </td>

      <td className="px-4 py-3 align-top">
        <BiddingStatusCell row={row} state={state} />
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-right align-top">
        <label className="inline-flex h-8 items-center gap-1 rounded-[6px] px-2 text-right hover:bg-white">
          <Pencil className="h-3.5 w-3.5 text-[#706A5F]" />
          <input
            value={floorValue}
            onChange={(event) => onFloorChange(event.target.value)}
            onBlur={onFloorBlur}
            onKeyDown={(event) => {
              if (event.key === "Enter") event.currentTarget.blur();
            }}
            placeholder="--"
            className="w-[92px] border-0 border-b border-dashed border-[#8C8578] bg-transparent px-1 text-right text-sm font-semibold text-[#171717] outline-none placeholder:text-[#8C8578] focus:border-[#2F6F63]"
            aria-label={`编辑 ${row.sku} 保底价`}
          />
        </label>
      </td>

      <td className="whitespace-nowrap px-4 py-3 text-right align-top text-[#706A5F]">{row.stockQuantity ?? "--"}</td>

      <td className="whitespace-nowrap px-4 py-3 align-top text-[#706A5F]">
        {formatDateTime(row.rule?.next_check_at)}
      </td>

      <td className="whitespace-nowrap px-4 py-3 align-top">
        <button
          type="button"
          disabled={toggleDisabled}
          onClick={onToggle}
          className={[
            "relative inline-flex h-6 w-11 items-center rounded-full border transition",
            hasFloor ? "border-[#2F6F63]" : "border-[#D9D2C6]",
            row.rule?.is_active ? "bg-[#2F6F63]" : "bg-white",
            toggleDisabled ? "cursor-not-allowed opacity-50" : "",
          ].join(" ")}
          aria-label="切换监控状态"
          title={hasFloor || row.rule?.is_active ? "切换监控状态" : "请先填写保护底价"}
        >
          <span
            className={[
              "inline-block h-4 w-4 rounded-full border transition",
              row.rule?.is_active
                ? "translate-x-6 border-white bg-white"
                : "translate-x-1 border-[#D9D2C6] bg-white",
            ].join(" ")}
          />
        </button>
      </td>
    </tr>
  );
}

function BiddingStatusCell({ row, state }: { row: BiddingRow; state: BiddingRowState }) {
  const rule = row.rule;
  const buyboxPrice = rule?.last_buybox_price;
  const stateMeta: Record<BiddingRowState, { label: string; className: string }> = {
    won: { label: "占领中", className: "border-[#BFD8C7] bg-[#F1FAF3] text-[#245B32]" },
    lost: { label: "已丢失", className: "border-[#E4B4A7] bg-[#FFF7F4] text-[#A33A24]" },
    lost_floor: { label: "已丢失", className: "border-[#D9363E] bg-[#FFF1F0] text-[#A33A24]" },
    blocked: { label: "已阻断", className: "border-[#E4B4A7] bg-[#FFF7F4] text-[#A33A24]" },
    retrying: { label: "重试中", className: "border-[#E8D3A0] bg-[#FFF9EA] text-[#8A5B14]" },
    pending: { label: "待扫描", className: "border-[#D9D2C6] bg-white text-[#706A5F]" },
    paused: { label: "已暂停", className: "border-[#D9D2C6] bg-white text-[#706A5F]" },
    needs_floor: { label: "待补底价", className: "border-[#E8D3A0] bg-[#FFF9EA] text-[#8A5B14]" },
    unconfigured: { label: "未配置", className: "border-[#D9D2C6] bg-white text-[#706A5F]" },
  };
  const meta = stateMeta[state];

  return (
    <div className="space-y-1.5">
      <span className={["inline-flex h-7 items-center rounded-[6px] border px-2.5 text-xs font-semibold", meta.className].join(" ")}>
        {meta.label}
      </span>
      {state === "won" ? (
        <div className="text-xs text-[#245B32]">当前 BuyBox {formatMoney(buyboxPrice ?? row.currentPrice)}</div>
      ) : null}
      {state === "lost" || state === "lost_floor" ? (
        <div className="text-xs text-[#A33A24]">
          竞对 BuyBox {formatMoney(buyboxPrice)}
        </div>
      ) : null}
      {state === "lost_floor" ? (
        <div className="text-xs font-medium text-[#A33A24]">对方价格已低于我的保底价</div>
      ) : null}
      {state === "blocked" && rule?.repricing_blocked_reason ? (
        <div className="text-xs text-[#A33A24]">{reasonLabel(rule.repricing_blocked_reason)}</div>
      ) : null}
      {row.stockQuantity !== null && row.stockQuantity <= 0 && rule?.is_active ? (
        <div className="text-xs text-[#A33A24]">缺货阻断风险</div>
      ) : null}
    </div>
  );
}

function BiddingProductImage({
  title,
  imageUrl,
  onPreview,
}: {
  title: string;
  imageUrl: string | null;
  onPreview: (title: string, imageUrl: string) => void;
}) {
  const [hasFailed, setHasFailed] = useState(false);
  if (imageUrl && !hasFailed) {
    return (
      <button
        type="button"
        onClick={() => onPreview(title, imageUrl)}
        className="group h-11 w-11 flex-none overflow-hidden rounded-[6px] border border-[#E7E2D8] bg-[#FCFBF7] outline-none focus:border-[#2F6F63]"
        title="放大图片"
      >
        <img
          src={imageUrl}
          alt={title}
          className="h-full w-full object-cover transition group-hover:scale-105"
          loading="lazy"
          onError={() => setHasFailed(true)}
        />
      </button>
    );
  }
  return (
    <div className="flex h-11 w-11 flex-none items-center justify-center rounded-[6px] border border-[#E7E2D8] bg-[#FCFBF7] text-xs font-semibold text-[#706A5F]">
      {title.slice(0, 2).toUpperCase()}
    </div>
  );
}

function productLink(row: BiddingRow) {
  if (row.plid) {
    return `https://www.takealot.com/${takealotSlug(row.title)}/${row.plid}`;
  }
  return `/products?sku=${encodeURIComponent(row.sku)}`;
}

function takealotSlug(value: string) {
  const slug = value
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return slug || "product";
}

function getFloorValue(row: BiddingRow, drafts: Record<string, string>) {
  const value = drafts[row.sku] ?? (row.rule?.floor_price != null ? String(row.rule.floor_price) : "");
  const numeric = Number.parseFloat(value);
  return Number.isFinite(numeric) && numeric > 0 ? numeric : null;
}

async function parseXlsxFloorPrices(buffer: ArrayBuffer) {
  const entries = await unzipXlsxEntries(buffer);
  const sharedStrings = parseSharedStrings(entries.get("xl/sharedStrings.xml") ?? "");
  const sheetName =
    Array.from(entries.keys()).find((name) => /^xl\/worksheets\/sheet\d+\.xml$/i.test(name)) ??
    "xl/worksheets/sheet1.xml";
  const sheetXml = entries.get(sheetName);
  if (!sheetXml) return [];

  return parseWorksheetRows(sheetXml, sharedStrings)
    .slice(1)
    .map((row) => {
      const sku = String(row[0] ?? "").trim();
      const numeric = parseMoneyNumber(row[1]);
      if (!sku || numeric === null || numeric <= 0) return null;
      return { sku, floor_price: numeric };
    })
    .filter((item): item is { sku: string; floor_price: number } => item !== null);
}

async function unzipXlsxEntries(buffer: ArrayBuffer) {
  const view = new DataView(buffer);
  const bytes = new Uint8Array(buffer);
  const eocdOffset = findZipEndOfCentralDirectory(view);
  const entryCount = view.getUint16(eocdOffset + 10, true);
  let cursor = view.getUint32(eocdOffset + 16, true);
  const entries = new Map<string, string>();
  const decoder = new TextDecoder("utf-8");

  for (let index = 0; index < entryCount; index += 1) {
    if (view.getUint32(cursor, true) !== 0x02014b50) {
      throw new Error("Invalid XLSX central directory");
    }
    const compression = view.getUint16(cursor + 10, true);
    const compressedSize = view.getUint32(cursor + 20, true);
    const fileNameLength = view.getUint16(cursor + 28, true);
    const extraLength = view.getUint16(cursor + 30, true);
    const commentLength = view.getUint16(cursor + 32, true);
    const localHeaderOffset = view.getUint32(cursor + 42, true);
    const name = decoder.decode(bytes.slice(cursor + 46, cursor + 46 + fileNameLength)).replace(/\\/g, "/");
    const localNameLength = view.getUint16(localHeaderOffset + 26, true);
    const localExtraLength = view.getUint16(localHeaderOffset + 28, true);
    const dataStart = localHeaderOffset + 30 + localNameLength + localExtraLength;
    const compressedData = bytes.slice(dataStart, dataStart + compressedSize);
    if (name.endsWith(".xml")) {
      const xmlBytes = compression === 0 ? compressedData : await inflateRaw(compressedData, compression);
      entries.set(name, decoder.decode(xmlBytes));
    }
    cursor += 46 + fileNameLength + extraLength + commentLength;
  }
  return entries;
}

function findZipEndOfCentralDirectory(view: DataView) {
  for (let offset = view.byteLength - 22; offset >= Math.max(0, view.byteLength - 66000); offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) {
      return offset;
    }
  }
  throw new Error("Invalid XLSX file");
}

async function inflateRaw(data: Uint8Array, compression: number) {
  if (compression !== 8 || typeof DecompressionStream === "undefined") {
    throw new Error("Unsupported XLSX compression");
  }
  const input = new ArrayBuffer(data.byteLength);
  new Uint8Array(input).set(data);
  const stream = new Blob([input]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

function parseSharedStrings(xml: string) {
  if (!xml) return [];
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  return Array.from(doc.getElementsByTagName("si")).map((node) =>
    Array.from(node.getElementsByTagName("t"))
      .map((textNode) => textNode.textContent ?? "")
      .join(""),
  );
}

function parseWorksheetRows(xml: string, sharedStrings: string[]) {
  const doc = new DOMParser().parseFromString(xml, "application/xml");
  return Array.from(doc.getElementsByTagName("row")).map((rowNode) => {
    const row: string[] = [];
    for (const cell of Array.from(rowNode.getElementsByTagName("c"))) {
      const index = xlsxColumnIndex(cell.getAttribute("r") ?? "");
      const type = cell.getAttribute("t");
      const rawValue = cell.getElementsByTagName("v")[0]?.textContent ?? "";
      const inlineText = Array.from(cell.getElementsByTagName("t"))
        .map((node) => node.textContent ?? "")
        .join("");
      row[index] = type === "s" ? sharedStrings[Number(rawValue)] ?? "" : inlineText || rawValue;
    }
    return row;
  });
}

function xlsxColumnIndex(cellRef: string) {
  const letters = (cellRef.match(/[A-Z]+/i)?.[0] ?? "A").toUpperCase();
  let index = 0;
  for (const letter of letters) {
    index = index * 26 + letter.charCodeAt(0) - 64;
  }
  return Math.max(0, index - 1);
}

function parseMoneyNumber(value: unknown) {
  const cleaned = String(value ?? "").replace(/[^\d.-]/g, "");
  const numeric = Number.parseFloat(cleaned);
  return Number.isFinite(numeric) ? numeric : null;
}

function biddingStockQuantity(payload: { [key: string]: unknown } | null, fallback: number | null) {
  return sellerWarehouseStock(payload) ?? officialWarehouseStock(payload) ?? fallback;
}

function sellerWarehouseStock(payload: { [key: string]: unknown } | null) {
  const direct = payloadNumber(payload, "total_merchant_stock") ?? payloadNumber(payload, "seller_stock_quantity");
  if (direct !== null) return direct;
  return sumWarehouseStock(payload?.seller_warehouse_stock);
}

function officialWarehouseStock(payload: { [key: string]: unknown } | null) {
  const direct =
    payloadNumber(payload, "total_takealot_stock") ??
    payloadNumber(payload, "stock_at_takealot_total") ??
    payloadNumber(payload, "takealot_stock_quantity");
  if (direct !== null) return direct;
  return sumWarehouseStock(payload?.takealot_warehouse_stock);
}

function sumWarehouseStock(value: unknown) {
  if (!Array.isArray(value)) return null;
  let total = 0;
  let hasValue = false;
  for (const item of value) {
    if (!isRecord(item)) continue;
    const quantity = numericValue(item.quantity_available) ?? numericValue(item.quantityAvailable) ?? numericValue(item.quantity);
    if (quantity === null) continue;
    total += quantity;
    hasValue = true;
  }
  return hasValue ? total : null;
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
  for (const key of ["image", "images", "media", "product", "offer", "takealot"]) {
    const nested = imageUrlFromUnknown(payload?.[key], 0);
    if (nested) return nested;
  }
  return null;
}

function imageUrlFromUnknown(value: unknown, depth: number): string | null {
  if (depth > 3) return null;
  if (typeof value === "string") return normalizeImageUrl(value);
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = imageUrlFromUnknown(item, depth + 1);
      if (nested) return nested;
    }
    return null;
  }
  if (!isRecord(value)) return null;
  for (const key of ["url", "src", "href", "image_url", "imageUrl", "thumbnail", "thumbnail_url", "large", "medium", "small"]) {
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
  if (trimmed.startsWith("http://") || trimmed.startsWith("https://") || trimmed.startsWith("data:image/") || trimmed.startsWith("/")) {
    return trimmed;
  }
  return null;
}

function normalizePlid(value: string | null) {
  if (!value) return null;
  const match = value.match(/(?:PLID)?(\d+)/i);
  return match ? `PLID${match[1]}` : null;
}

function payloadNumber(payload: { [key: string]: unknown } | null, key: string) {
  return numericValue(payload?.[key]);
}

function numericValue(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string") {
    const numeric = Number.parseFloat(value.replace("R", "").replace(",", "").trim());
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function formatMoney(value: number | null | undefined) {
  if (value === null || value === undefined) return "--";
  return `R ${Number(value).toFixed(2)}`;
}

function formatDateTime(value: string | null | undefined) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return `${date.getMonth() + 1}/${date.getDate()} ${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function actionLabel(value: string | null | undefined) {
  const labels: Record<string, string> = {
    raised: "建议涨价",
    lowered: "建议降价",
    floor: "回到底价",
    unchanged: "保持不变",
    buybox_refresh_failed: "刷新失败",
    missing_plid: "缺少 PLID",
    missing_offer_id: "缺少 Offer",
    offer_match_untrusted: "匹配不可信",
    api_error: "写价失败",
  };
  return value ? labels[value] ?? value : "";
}

function reasonLabel(value: string) {
  const labels: Record<string, string> = {
    missing_plid: "缺少 PLID",
    missing_offer_id: "缺少 Offer",
    offer_match_untrusted: "Offer 匹配不可信",
    listing_missing: "未同步商品",
    missing_price: "价格缺失",
    buybox_refresh_failed: "BuyBox 刷新失败",
    missing_buybox_price: "BuyBox 价格缺失",
  };
  return labels[value] ?? value;
}
