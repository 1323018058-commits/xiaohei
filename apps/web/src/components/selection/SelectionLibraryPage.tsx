"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  ImageIcon,
  Loader2,
  RotateCcw,
  Search,
  SlidersHorizontal,
  Sparkles,
  Star,
  X,
} from "lucide-react";

import type { components } from "@/generated/api-types";
import { apiFetch } from "@/lib/api";

type SelectionProductListResponse = components["schemas"]["SelectionProductListResponse"];
type SelectionProduct = components["schemas"]["SelectionProductResponse"];
type SelectionFilterOptionsResponse = components["schemas"]["SelectionFilterOptionsResponse"];

type SelectionFilterDraft = {
  q: string;
  mainCategory: string;
  categoryLevel1: string;
  categoryLevel2: string;
  categoryLevel3: string;
  brand: string;
  stockStatus: string;
  latestReviewWindow: string;
  minPrice: string;
  maxPrice: string;
  minRating: string;
  minReviews: string;
  minOfferCount: string;
  maxOfferCount: string;
};

type ImagePreview = {
  title: string;
  imageUrl: string;
};

const pageSize = 100;

const emptyFilters: SelectionFilterDraft = {
  q: "",
  mainCategory: "",
  categoryLevel1: "",
  categoryLevel2: "",
  categoryLevel3: "",
  brand: "",
  stockStatus: "",
  latestReviewWindow: "",
  minPrice: "",
  maxPrice: "",
  minRating: "",
  minReviews: "",
  minOfferCount: "",
  maxOfferCount: "",
};

const emptyFilterOptions: SelectionFilterOptionsResponse = {
  main_categories: [],
  category_level1: [],
  category_level2: [],
  category_level3: [],
  brands: [],
  stock_statuses: [],
  category_tree: {},
};

const brandPresenceOptions = ["__has_brand__", "__no_brand__"];
const stockGroupOptions = [
  "__in_stock__",
  "__ships_in__",
  "__direct_ship__",
  "__pre_order__",
  "__out_of_stock__",
];
const latestReviewWindowOptions = [
  "__last_30_days__",
  "__last_90_days__",
  "__last_180_days__",
  "__last_365_days__",
  "__has_latest_review__",
  "__missing_latest_review__",
];

export default function SelectionLibraryPage() {
  const [filters, setFilters] = useState<SelectionFilterDraft>(emptyFilters);
  const [appliedFilters, setAppliedFilters] = useState<SelectionFilterDraft>(emptyFilters);
  const [filterOptions, setFilterOptions] =
    useState<SelectionFilterOptionsResponse>(emptyFilterOptions);
  const [products, setProducts] = useState<SelectionProduct[]>([]);
  const [totalProducts, setTotalProducts] = useState(0);
  const [currentPage, setCurrentPage] = useState(1);
  const [isLoading, setIsLoading] = useState(true);
  const [, setIsFilterLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState("");
  const [imagePreview, setImagePreview] = useState<ImagePreview | null>(null);
  const latestLoadRequestRef = useRef(0);
  const latestFilterRequestRef = useRef(0);
  const productAbortRef = useRef<AbortController | null>(null);
  const filterAbortRef = useRef<AbortController | null>(null);

  const totalPages = Math.max(1, Math.ceil(totalProducts / pageSize));
  const pageStart = totalProducts === 0 ? 0 : (currentPage - 1) * pageSize + 1;
  const pageEnd = Math.min(currentPage * pageSize, totalProducts);
  const selectableFilterOptions = useMemo(
    () => normalizeFilterOptions(filterOptions, filters),
    [filterOptions, filters.mainCategory, filters.categoryLevel1],
  );
  const isInitialLoading = isLoading && products.length === 0;
  const isRefreshing = isLoading && products.length > 0;

  useEffect(() => {
    void loadFilterOptions(filters);
  }, [filters.mainCategory, filters.categoryLevel1, filters.categoryLevel2]);

  useEffect(() => {
    void loadProducts(currentPage, appliedFilters);
  }, [currentPage, appliedFilters]);

  useEffect(() => {
    setFilters((current) => sanitizeFiltersForOptions(current, selectableFilterOptions));
  }, [selectableFilterOptions]);

  useEffect(() => {
    return () => {
      productAbortRef.current?.abort();
      filterAbortRef.current?.abort();
    };
  }, []);

  async function loadFilterOptions(nextFilters: SelectionFilterDraft) {
    const requestId = latestFilterRequestRef.current + 1;
    latestFilterRequestRef.current = requestId;
    filterAbortRef.current?.abort();
    const controller = new AbortController();
    filterAbortRef.current = controller;
    setIsFilterLoading(true);
    try {
      const params = buildFilterOptionsQuery(nextFilters);
      const queryString = params.toString();
      const data = await apiFetch<SelectionFilterOptionsResponse>(
        `/api/v1/selection/filters${queryString ? `?${queryString}` : ""}`,
        { signal: controller.signal },
      );
      if (requestId !== latestFilterRequestRef.current) return;
      setFilterOptions(data);
    } catch {
      if (controller.signal.aborted) return;
      if (requestId !== latestFilterRequestRef.current) return;
      setFilterOptions(emptyFilterOptions);
    } finally {
      if (requestId === latestFilterRequestRef.current) {
        if (filterAbortRef.current === controller) filterAbortRef.current = null;
        setIsFilterLoading(false);
      }
    }
  }

  async function loadProducts(page: number, nextFilters: SelectionFilterDraft) {
    const requestId = latestLoadRequestRef.current + 1;
    latestLoadRequestRef.current = requestId;
    productAbortRef.current?.abort();
    const controller = new AbortController();
    productAbortRef.current = controller;
    setIsLoading(true);
    setErrorMessage("");

    try {
      const params = buildProductQuery(nextFilters, page);
      const data = await apiFetch<SelectionProductListResponse>(
        `/api/v1/selection/products?${params.toString()}`,
        { signal: controller.signal },
      );
      if (requestId !== latestLoadRequestRef.current) return;

      const nextTotalPages = Math.max(1, Math.ceil(data.total / pageSize));
      if (page > nextTotalPages) {
        setCurrentPage(nextTotalPages);
        return;
      }

      setProducts(data.products);
      setTotalProducts(data.total);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (requestId !== latestLoadRequestRef.current) return;
      setProducts([]);
      setTotalProducts(0);
      setErrorMessage(error instanceof Error ? error.message : "选品库加载失败");
    } finally {
      if (requestId === latestLoadRequestRef.current) {
        if (productAbortRef.current === controller) productAbortRef.current = null;
        setIsLoading(false);
      }
    }
  }

  function updateFilter(key: keyof SelectionFilterDraft, value: string) {
    if (key === "mainCategory") {
      setFilterOptions((currentOptions) => ({
        ...currentOptions,
        category_level1: [],
        category_level2: [],
        category_level3: [],
      }));
    }
    if (key === "categoryLevel1") {
      setFilterOptions((currentOptions) => ({
        ...currentOptions,
        category_level2: [],
        category_level3: [],
      }));
    }
    if (key === "categoryLevel2") {
      setFilterOptions((currentOptions) => ({
        ...currentOptions,
        category_level3: [],
      }));
    }

    setFilters((current) => {
      const next = { ...current, [key]: value };
      if (key === "mainCategory") {
        next.categoryLevel1 = "";
        next.categoryLevel2 = "";
        next.categoryLevel3 = "";
      }
      if (key === "categoryLevel1") {
        next.categoryLevel2 = "";
        next.categoryLevel3 = "";
      }
      if (key === "categoryLevel2") {
        next.categoryLevel3 = "";
      }
      return next;
    });
  }

  function applyFilters() {
    setCurrentPage(1);
    setAppliedFilters(sanitizeFiltersForOptions(normalizeFilters(filters), selectableFilterOptions));
  }

  function resetFilters() {
    setFilters(emptyFilters);
    setAppliedFilters(emptyFilters);
    setCurrentPage(1);
  }

  return (
    <div className="min-h-full overflow-x-hidden bg-[#F6F7F9] text-[#111827]">
      <div className="mx-auto flex min-w-0 w-full max-w-[1800px] flex-col gap-4 p-4 lg:p-6">
        <section className="min-w-0 overflow-hidden rounded-[8px] border border-[#DDE1E7] bg-white">
          <div className="border-b border-[#E5E7EB] px-5 py-4">
            <div className="min-w-0">
              <div className="mb-1 flex flex-wrap items-center gap-2 text-xs font-medium text-[#64748B]">
                <span className="inline-flex h-6 items-center rounded-[5px] border border-[#CBD5E1] px-2">
                  Takealot 全站商品池
                </span>
                <span className="inline-flex h-6 items-center gap-1 rounded-[5px] border border-[#BFD7C7] bg-[#F3FBF5] px-2 text-[#1C6B35]">
                  <Sparkles className="h-3.5 w-3.5 stroke-[1.8]" />
                  全量采集中
                </span>
              </div>
              <h1 className="text-[26px] font-semibold tracking-normal text-[#0F172A]">选品库</h1>
            </div>
          </div>

          <form
            className="border-b border-[#E5E7EB] px-5 py-4"
            onSubmit={(event) => {
              event.preventDefault();
              applyFilters();
            }}
          >
            <div className="mb-3 flex flex-col gap-2 xl:flex-row xl:items-center">
              <label className="relative block min-w-0 flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#64748B]" />
                <input
                  value={filters.q}
                  onChange={(event) => updateFilter("q", event.target.value)}
                  placeholder="搜索标题 / PLID / 品牌"
                  className="h-10 w-full rounded-[6px] border border-[#CBD5E1] bg-white pl-9 pr-3 text-sm text-[#0F172A] outline-none placeholder:text-[#94A3B8] focus:border-[#0F172A]"
                />
              </label>

              <div className="flex shrink-0 items-center gap-2">
                <button
                  type="submit"
                  className="inline-flex h-10 min-w-[112px] items-center justify-center gap-2 rounded-[6px] border border-[#99F6E4] bg-[#F0FDFA] px-4 text-sm font-medium text-[#0F766E] hover:border-[#5EEAD4] hover:bg-[#CCFBF1]"
                >
                  <SlidersHorizontal className="h-4 w-4 stroke-[1.8]" />
                  应用筛选
                </button>
                <button
                  type="button"
                  onClick={resetFilters}
                  className="inline-flex h-10 min-w-[86px] items-center justify-center gap-2 rounded-[6px] border border-[#CBD5E1] bg-white px-4 text-sm font-medium text-[#334155] hover:border-[#94A3B8] hover:text-[#0F172A]"
                >
                  <RotateCcw className="h-4 w-4 stroke-[1.8]" />
                  重置
                </button>
              </div>
            </div>

            <div className="grid gap-2">
              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-3">
                <FilterSelect
                  label="一级类目"
                  value={filters.mainCategory}
                  options={selectableFilterOptions.main_categories}
                  placeholder={
                    selectableFilterOptions.main_categories.length
                        ? "全部一级类目"
                        : "暂无一级类目"
                  }
                  onChange={(value) => updateFilter("mainCategory", value)}
                />
                <FilterSelect
                  label="二级类目"
                  value={filters.categoryLevel1}
                  options={selectableFilterOptions.category_level1}
                  placeholder={filters.mainCategory ? "全部二级类目" : "先选一级类目"}
                  onChange={(value) => updateFilter("categoryLevel1", value)}
                  disabled={!filters.mainCategory}
                />
                <FilterSelect
                  label="三级类目"
                  value={filters.categoryLevel2}
                  options={selectableFilterOptions.category_level2}
                  placeholder={filters.categoryLevel1 ? "全部三级类目" : "先选二级类目"}
                  onChange={(value) => updateFilter("categoryLevel2", value)}
                  disabled={!filters.categoryLevel1}
                />
              </div>

              <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-9">
                <FilterSelect
                  label="品牌"
                  value={filters.brand}
                  options={selectableFilterOptions.brands}
                  placeholder="全部品牌"
                  onChange={(value) => updateFilter("brand", value)}
                  formatOption={formatBrandPresence}
                />
                <FilterSelect
                  label="库存状态"
                  value={filters.stockStatus}
                  options={selectableFilterOptions.stock_statuses}
                  placeholder="全部状态"
                  onChange={(value) => updateFilter("stockStatus", value)}
                  formatOption={formatStockStatus}
                />
                <FilterSelect
                  label="最近评论"
                  value={filters.latestReviewWindow}
                  options={latestReviewWindowOptions}
                  placeholder="全部时间"
                  onChange={(value) => updateFilter("latestReviewWindow", value)}
                  formatOption={formatLatestReviewWindow}
                />
                <NumberFilter
                  label="最低价格"
                  value={filters.minPrice}
                  placeholder="R min"
                  onChange={(value) => updateFilter("minPrice", value)}
                />
                <NumberFilter
                  label="最高价格"
                  value={filters.maxPrice}
                  placeholder="R max"
                  onChange={(value) => updateFilter("maxPrice", value)}
                />
                <NumberFilter
                  label="最低评分"
                  value={filters.minRating}
                  placeholder="0-5"
                  step="0.1"
                  max="5"
                  onChange={(value) => updateFilter("minRating", value)}
                />
                <NumberFilter
                  label="最低评论数"
                  value={filters.minReviews}
                  placeholder="评论数"
                  onChange={(value) => updateFilter("minReviews", value)}
                />
                <NumberFilter
                  label="最少报价数"
                  value={filters.minOfferCount}
                  placeholder="min"
                  onChange={(value) => updateFilter("minOfferCount", value)}
                />
                <NumberFilter
                  label="最多报价数"
                  value={filters.maxOfferCount}
                  placeholder="max"
                  onChange={(value) => updateFilter("maxOfferCount", value)}
                />
              </div>
            </div>
          </form>

          <div className="relative min-h-[420px] overflow-hidden">
            {errorMessage ? (
              <div className="border-b border-[#FED7AA] bg-[#FFF7ED] px-5 py-2 text-sm text-[#C2410C]">
                {errorMessage}
              </div>
            ) : null}
            {isInitialLoading ? <LoadingLayer /> : null}
            {isRefreshing ? (
              <div className="absolute left-0 right-0 top-0 z-20 h-0.5 overflow-hidden bg-[#E2E8F0]">
                <div className="h-full w-1/3 animate-pulse bg-[#0F172A]" />
              </div>
            ) : null}

            <div className="overflow-x-auto">
              <table className="w-full min-w-[1440px] border-collapse text-left">
                <thead className="bg-[#F8FAFC]">
                  <tr className="border-b border-[#E5E7EB] text-xs font-medium text-[#475569]">
                    <TableHead className="sticky left-0 z-20 w-[390px] bg-[#F8FAFC]">
                      商品
                    </TableHead>
                    <TableHead className="w-[290px]">类目路径</TableHead>
                    <TableHead className="w-[150px]">品牌</TableHead>
                    <TableHead className="w-[140px]" align="right">
                      当前价格
                    </TableHead>
                    <TableHead className="w-[150px]">评分</TableHead>
                    <TableHead className="w-[230px]">评论分布</TableHead>
                    <TableHead className="w-[130px]">最近评论</TableHead>
                    <TableHead className="w-[130px]">库存</TableHead>
                    <TableHead className="w-[110px]" align="right">
                      报价数
                    </TableHead>
                    <TableHead className="w-[150px]">更新</TableHead>
                  </tr>
                </thead>
                <tbody>
                  {products.map((product) => (
                    <tr
                      key={product.product_id}
                      className="border-b border-[#EEF2F7] text-sm last:border-b-0 hover:bg-[#F8FAFC]"
                    >
                      <td className="sticky left-0 z-10 w-[390px] bg-white px-4 py-3 align-top shadow-[1px_0_0_#E5E7EB]">
                        <div className="flex items-start gap-3">
                          <ProductImage
                            title={product.title}
                            imageUrl={product.image_url}
                            onPreview={setImagePreview}
                          />
                          <div className="min-w-0">
                            <a
                              href={buildTakealotProductUrl(product)}
                              target="_blank"
                              rel="noreferrer"
                              title="打开商品页"
                              className="line-clamp-2 font-medium leading-5 text-[#0F172A] underline-offset-2 hover:text-[#0F766E] hover:underline"
                            >
                              {product.title}
                            </a>
                            <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[#64748B]">
                              <span>{formatPlatformProductId(product.platform_product_id)}</span>
                            </div>
                          </div>
                        </div>
                      </td>
                      <td className="max-w-[290px] px-4 py-3 align-top text-[#475569]">
                        <span className="line-clamp-3 leading-5">{formatCategoryPath(product)}</span>
                      </td>
                      <td className="px-4 py-3 align-top text-[#475569]">
                        <span className="line-clamp-2">{product.brand || "--"}</span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right align-top font-semibold text-[#0F172A]">
                        {formatMoney(product.current_price, product.currency)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 align-top">
                        <RatingSummary rating={product.rating} totalReviews={product.total_review_count} />
                      </td>
                      <td className="px-4 py-3 align-top">
                        <ReviewDistribution product={product} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 align-top text-[#475569]">
                        {product.latest_review_at ? formatDate(product.latest_review_at) : <MissingValue />}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 align-top">
                        <StockBadge value={product.stock_status} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right align-top text-[#475569]">
                        {product.offer_count == null ? <MissingValue align="right" /> : formatInteger(product.offer_count)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 align-top text-xs text-[#64748B]">
                        {formatDate(product.last_seen_at ?? product.updated_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {!isLoading && products.length === 0 ? (
              <div className="px-6 py-16 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-[8px] border border-[#CBD5E1] bg-[#F8FAFC] text-[#64748B]">
                  <Search className="h-5 w-5 stroke-[1.8]" />
                </div>
                <h2 className="mt-3 text-base font-semibold text-[#0F172A]">没有匹配商品</h2>
                <p className="mt-1 text-sm text-[#64748B]">
                  可以缩小类目、放宽价格区间，或清空筛选条件后重新查询。
                </p>
              </div>
            ) : null}
          </div>

          <div className="flex flex-col gap-3 border-t border-[#E5E7EB] px-5 py-3 text-sm text-[#64748B] sm:flex-row sm:items-center sm:justify-between">
            <span>
              {isLoading
                ? "正在加载商品"
                : `显示 ${formatInteger(pageStart)}-${formatInteger(pageEnd)} / ${formatInteger(totalProducts)}`}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setCurrentPage((page) => Math.max(1, page - 1))}
                disabled={currentPage <= 1 || isLoading}
                className="inline-flex h-9 min-w-[92px] items-center justify-center gap-1 rounded-[6px] border border-[#CBD5E1] bg-white px-3 text-xs font-medium text-[#0F172A] hover:border-[#94A3B8] disabled:cursor-not-allowed disabled:text-[#94A3B8]"
              >
                <ArrowLeft className="h-4 w-4 stroke-[1.8]" />
                上一页
              </button>
              <span className="min-w-[108px] text-center text-[#334155]">
                {formatInteger(currentPage)} / {formatInteger(totalPages)}
              </span>
              <button
                type="button"
                onClick={() => setCurrentPage((page) => Math.min(totalPages, page + 1))}
                disabled={currentPage >= totalPages || isLoading}
                className="inline-flex h-9 min-w-[92px] items-center justify-center gap-1 rounded-[6px] border border-[#CBD5E1] bg-white px-3 text-xs font-medium text-[#0F172A] hover:border-[#94A3B8] disabled:cursor-not-allowed disabled:text-[#94A3B8]"
              >
                下一页
                <ArrowRight className="h-4 w-4 stroke-[1.8]" />
              </button>
            </div>
          </div>
        </section>
      </div>

      {imagePreview ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[#020617]/70 p-6"
          onClick={() => setImagePreview(null)}
        >
          <div
            className="relative max-h-full max-w-[920px]"
            onClick={(event) => event.stopPropagation()}
          >
            <button
              type="button"
              onClick={() => setImagePreview(null)}
              className="absolute right-3 top-3 inline-flex h-9 w-9 items-center justify-center rounded-[6px] border border-white/20 bg-[#020617]/70 text-white"
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

function FilterSelect({
  label,
  value,
  options,
  placeholder,
  onChange,
  formatOption,
  disabled = false,
}: {
  label: string;
  value: string;
  options: string[];
  placeholder: string;
  onChange: (value: string) => void;
  formatOption?: (value: string | null | undefined) => string;
  disabled?: boolean;
}) {
  return (
    <label className="grid min-w-0 gap-1">
      <span className="text-xs font-medium text-[#475569]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        disabled={disabled}
        className={[
          "h-9 w-full min-w-0 rounded-[6px] border border-[#CBD5E1] bg-white px-3 text-sm text-[#0F172A] outline-none focus:border-[#0F172A]",
          disabled ? "cursor-not-allowed bg-[#F8FAFC] text-[#94A3B8]" : "",
        ].join(" ")}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option} value={option}>
            {formatOption ? formatOption(option) : option}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberFilter({
  label,
  value,
  placeholder,
  step = "1",
  max,
  onChange,
}: {
  label: string;
  value: string;
  placeholder: string;
  step?: string;
  max?: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="grid min-w-0 gap-1">
      <span className="text-xs font-medium text-[#475569]">{label}</span>
      <input
        type="number"
        min="0"
        max={max}
        step={step}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-9 w-full min-w-0 rounded-[6px] border border-[#CBD5E1] bg-white px-3 text-sm text-[#0F172A] outline-none placeholder:text-[#94A3B8] focus:border-[#0F172A]"
      />
    </label>
  );
}

function TableHead({
  children,
  className = "",
  align = "left",
}: {
  children: string;
  className?: string;
  align?: "left" | "right";
}) {
  return (
    <th
      className={[
        "h-11 whitespace-nowrap px-4 font-medium",
        align === "right" ? "text-right" : "text-left",
        className,
      ].join(" ")}
    >
      {children}
    </th>
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
        className="h-16 w-16 flex-none overflow-hidden rounded-[6px] border border-[#CBD5E1] bg-white outline-none transition hover:border-[#94A3B8] focus-visible:border-[#0F172A]"
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
    <div className="flex h-16 w-16 flex-none items-center justify-center rounded-[6px] border border-[#E2E8F0] bg-[#F8FAFC] text-[#94A3B8]">
      <ImageIcon className="h-5 w-5 stroke-[1.7]" />
    </div>
  );
}

function RatingSummary({
  rating,
  totalReviews,
}: {
  rating: number | null;
  totalReviews: number | null;
}) {
  return (
    <div className="grid gap-1">
      <span className="inline-flex items-center gap-1 font-semibold text-[#0F172A]">
        <Star className="h-4 w-4 fill-[#F59E0B] stroke-[#B45309]" />
        {rating == null ? "--" : rating.toFixed(1)}
      </span>
      <span className="text-xs text-[#64748B]">{formatInteger(totalReviews)} 评论</span>
    </div>
  );
}

function ReviewDistribution({ product }: { product: SelectionProduct }) {
  const total = product.total_review_count ?? 0;
  const rows = [
    ["5星", product.rating_5_count],
    ["4星", product.rating_4_count],
    ["3星", product.rating_3_count],
    ["2星", product.rating_2_count],
    ["1星", product.rating_1_count],
  ] as const;

  return (
    <div className="grid gap-1.5">
      {rows.map(([label, count]) => {
        const numeric = count ?? 0;
        const width = total > 0 ? Math.max(3, Math.round((numeric / total) * 100)) : 0;
        return (
          <div key={label} className="grid grid-cols-[34px_minmax(76px,1fr)_58px] items-center gap-2 text-xs">
            <span className="text-[#64748B]">{label}</span>
            <span className="h-1.5 overflow-hidden rounded-full bg-[#E2E8F0]">
              <span className="block h-full rounded-full bg-[#0F766E]" style={{ width: `${width}%` }} />
            </span>
            <span className="text-right text-[#64748B]">{formatInteger(count)}</span>
          </div>
        );
      })}
    </div>
  );
}

function StockBadge({ value }: { value: string | null }) {
  const label = formatStockStatus(value);
  const group = stockStatusGroup(value);
  const colorClass =
    !group
      ? "border-[#CBD5E1] bg-[#F8FAFC] text-[#64748B]"
      : group === "__out_of_stock__"
        ? "border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]"
        : group === "__direct_ship__"
          ? "border-[#BAE6FD] bg-[#F0F9FF] text-[#0369A1]"
        : group === "__ships_in__" || group === "__pre_order__"
          ? "border-[#FED7AA] bg-[#FFF7ED] text-[#C2410C]"
          : "border-[#BBF7D0] bg-[#F0FDF4] text-[#166534]";

  return (
    <span
      className={[
        "inline-flex min-h-7 max-w-[150px] items-center rounded-full border px-2.5 text-[12px] font-medium leading-4",
        colorClass,
      ].join(" ")}
      title={value ?? undefined}
    >
      {label}
    </span>
  );
}

function LoadingLayer() {
  return (
    <div className="absolute inset-0 z-30 flex items-start justify-center bg-white/70 pt-20 backdrop-blur-[1px]">
      <div className="inline-flex h-10 items-center gap-2 rounded-[6px] border border-[#CBD5E1] bg-white px-3 text-sm font-medium text-[#334155] shadow-sm">
        <Loader2 className="h-4 w-4 animate-spin stroke-[1.8]" />
        正在加载商品
      </div>
    </div>
  );
}

function MissingValue({ align = "left" }: { align?: "left" | "right" }) {
  return (
    <span
      className={[
        "inline-flex h-6 items-center rounded-[5px] border border-[#E2E8F0] bg-[#F8FAFC] px-2 text-xs font-medium text-[#94A3B8]",
        align === "right" ? "justify-end" : "",
      ].join(" ")}
    >
      待采集
    </span>
  );
}

function buildProductQuery(filters: SelectionFilterDraft, page: number) {
  const params = new URLSearchParams({
    limit: String(pageSize),
    offset: String((page - 1) * pageSize),
  });

  const normalized = normalizeFilters(filters);
  setTextParam(params, "q", normalized.q);
  setTextParam(params, "main_category", normalized.mainCategory);
  setTextParam(params, "category_level1", normalized.categoryLevel1);
  setTextParam(params, "category_level2", normalized.categoryLevel2);
  setTextParam(params, "brand", normalized.brand);
  setTextParam(params, "stock_status", normalized.stockStatus);
  setTextParam(params, "latest_review_window", normalized.latestReviewWindow);
  setNumberParam(params, "min_price", normalized.minPrice);
  setNumberParam(params, "max_price", normalized.maxPrice);
  setNumberParam(params, "min_rating", normalized.minRating);
  setNumberParam(params, "min_reviews", normalized.minReviews);
  setNumberParam(params, "min_offer_count", normalized.minOfferCount);
  setNumberParam(params, "max_offer_count", normalized.maxOfferCount);
  return params;
}

function buildFilterOptionsQuery(filters: SelectionFilterDraft) {
  const params = new URLSearchParams();
  const normalized = normalizeFilters(filters);
  setTextParam(params, "main_category", normalized.mainCategory);
  setTextParam(params, "category_level1", normalized.categoryLevel1);
  setTextParam(params, "category_level2", normalized.categoryLevel2);
  return params;
}

function setTextParam(params: URLSearchParams, key: string, value: string) {
  if (value) params.set(key, value);
}

function setNumberParam(params: URLSearchParams, key: string, value: string) {
  if (!value) return;
  const numeric = Number(value);
  if (Number.isFinite(numeric) && numeric >= 0) params.set(key, String(numeric));
}

function normalizeFilters(filters: SelectionFilterDraft): SelectionFilterDraft {
  const mainCategory = filters.mainCategory.trim();
  const categoryLevel1 = mainCategory ? filters.categoryLevel1.trim() : "";
  const categoryLevel2 = categoryLevel1 ? filters.categoryLevel2.trim() : "";
  const brand = filters.brand.trim();
  const stockStatus = filters.stockStatus.trim();
  const latestReviewWindow = filters.latestReviewWindow.trim();
  return {
    q: filters.q.trim(),
    mainCategory,
    categoryLevel1,
    categoryLevel2,
    categoryLevel3: "",
    brand,
    stockStatus,
    latestReviewWindow,
    minPrice: filters.minPrice.trim(),
    maxPrice: filters.maxPrice.trim(),
    minRating: filters.minRating.trim(),
    minReviews: filters.minReviews.trim(),
    minOfferCount: filters.minOfferCount.trim(),
    maxOfferCount: filters.maxOfferCount.trim(),
  };
}

function sanitizeFiltersForOptions(
  filters: SelectionFilterDraft,
  options: SelectionFilterOptionsResponse,
): SelectionFilterDraft {
  const normalized = normalizeFilters(filters);
  const next: SelectionFilterDraft = { ...normalized };

  if (!includesAvailableOption(options.main_categories, normalized.mainCategory)) {
    next.mainCategory = "";
    next.categoryLevel1 = "";
    next.categoryLevel2 = "";
  }
  if (!next.mainCategory || !includesAvailableOption(options.category_level1, normalized.categoryLevel1)) {
    next.categoryLevel1 = "";
    next.categoryLevel2 = "";
  }
  if (!next.categoryLevel1 || !includesAvailableOption(options.category_level2, normalized.categoryLevel2)) {
    next.categoryLevel2 = "";
  }
  if (!brandPresenceOptions.includes(normalized.brand)) next.brand = "";
  if (!stockGroupOptions.includes(normalized.stockStatus)) next.stockStatus = "";
  if (!latestReviewWindowOptions.includes(normalized.latestReviewWindow)) next.latestReviewWindow = "";

  if (areFiltersEqual(filters, next)) return filters;
  return next;
}

function includesAvailableOption(options: string[], value: string) {
  return !value || options.length === 0 || options.includes(value);
}

function areFiltersEqual(left: SelectionFilterDraft, right: SelectionFilterDraft) {
  return (Object.keys(emptyFilters) as Array<keyof SelectionFilterDraft>).every(
    (key) => left[key] === right[key],
  );
}

function normalizeFilterOptions(
  options: SelectionFilterOptionsResponse,
  filters: SelectionFilterDraft,
): SelectionFilterOptionsResponse {
  const tree = options.category_tree ?? {};
  const hasTree = Object.keys(tree).length > 0;
  const branch = filters.mainCategory ? tree[filters.mainCategory] ?? {} : {};
  const categoryLevel1 = filters.mainCategory
    ? hasTree
      ? Object.keys(branch)
      : options.category_level1
    : [];
  const categoryLevel2 =
    filters.mainCategory && filters.categoryLevel1
      ? hasTree
        ? branch[filters.categoryLevel1] ?? []
        : options.category_level2
      : [];

  return {
    main_categories: uniqueOptionList(hasTree ? Object.keys(tree) : options.main_categories),
    category_level1: uniqueOptionList(categoryLevel1),
    category_level2: uniqueOptionList(categoryLevel2),
    category_level3: [],
    brands: brandPresenceOptions,
    stock_statuses: stockGroupOptions,
    category_tree: tree,
  };
}

function uniqueOptionList(options: string[]) {
  const values = new Set<string>();
  for (const option of options) {
    if (option) values.add(option);
  }
  return Array.from(values);
}

function formatCategoryPath(product: SelectionProduct) {
  const parts = [
    product.main_category,
    product.category_level1,
    product.category_level2,
    product.category_level3,
  ].filter(Boolean);

  return parts.length ? parts.join(" / ") : "--";
}

function formatPlatformProductId(value: string) {
  const normalized = normalizePlatformProductId(value);
  return normalized ? normalized.replace(/^PLID/i, "PLID ") : "--";
}

function formatMoney(value: number | null, currency = "ZAR") {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-ZA", {
    style: "currency",
    currency,
    maximumFractionDigits: value < 100 ? 2 : 0,
  }).format(value);
}

function formatInteger(value: number | null) {
  if (value == null) return "--";
  return new Intl.NumberFormat("en-ZA", {
    maximumFractionDigits: 0,
  }).format(value);
}

function formatDate(value: string | null) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function formatStockStatus(value: string | null | undefined) {
  if (!value) return "--";
  const labels: Record<string, string> = {
    __in_stock__: "有库存",
    __ships_in__: "延迟发货",
    __direct_ship__: "直邮",
    __pre_order__: "预售",
    __out_of_stock__: "无库存",
    in_stock: "有库存",
    limited: "库存紧张",
    out_of_stock: "无库存",
    unavailable: "不可售",
  };
  if (value.startsWith("pre_order")) {
    const dateMatch = value.match(/(\d{1,2})_([a-z]{3})_,_(\d{4})/i);
    if (dateMatch) {
      const [, day, month, year] = dateMatch;
      return `预售 ${year}/${monthNameToNumber(month)}/${day.padStart(2, "0")} 发货`;
    }
    return "预售";
  }
  if (value === "ships_in_14___16_work_days") return "直邮 14-16 工作日";
  if (value.startsWith("ships_in")) {
    const dayNumbers = value.match(/\d+/g) ?? [];
    if (dayNumbers.length >= 2) return `${dayNumbers[0]}-${dayNumbers[1]} 工作日发货`;
    if (dayNumbers.length === 1) return `${dayNumbers[0]} 工作日发货`;
  }
  return labels[value] ?? value;
}

function formatBrandPresence(value: string | null | undefined) {
  if (value === "__has_brand__") return "有品牌";
  if (value === "__no_brand__") return "无品牌";
  return value || "--";
}

function formatLatestReviewWindow(value: string | null | undefined) {
  const labels: Record<string, string> = {
    __last_30_days__: "近 30 天",
    __last_90_days__: "近 90 天",
    __last_180_days__: "近 180 天",
    __last_365_days__: "近一年",
    __has_latest_review__: "已有评论时间",
    __missing_latest_review__: "待采集",
  };
  return value ? labels[value] ?? value : "--";
}

function stockStatusGroup(value: string | null | undefined) {
  if (!value) return "";
  if (value === "__direct_ship__" || value === "ships_in_14___16_work_days") return "__direct_ship__";
  if (value === "__in_stock__" || value === "in_stock" || value === "limited") return "__in_stock__";
  if (value === "__ships_in__" || value.startsWith("ships_in")) return "__ships_in__";
  if (value === "__pre_order__" || value.startsWith("pre_order")) return "__pre_order__";
  if (value === "__out_of_stock__" || value === "out_of_stock" || value === "unavailable") {
    return "__out_of_stock__";
  }
  return "";
}

function monthNameToNumber(month: string) {
  const monthNumbers: Record<string, string> = {
    jan: "01",
    feb: "02",
    mar: "03",
    apr: "04",
    may: "05",
    jun: "06",
    jul: "07",
    aug: "08",
    sep: "09",
    oct: "10",
    nov: "11",
    dec: "12",
  };
  return monthNumbers[month.toLowerCase()] ?? month;
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

function normalizeImageUrl(imageUrl: string | null) {
  const trimmed = imageUrl?.trim();
  if (!trimmed) return null;
  if (trimmed.startsWith("//")) return `https:${trimmed}`;
  return trimmed;
}

function buildTakealotProductUrl(product: SelectionProduct) {
  const platformProductId = normalizePlatformProductId(product.platform_product_id);
  const slug = product.title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `https://www.takealot.com/${slug || "product"}/${platformProductId || product.platform_product_id}`;
}

function normalizePlatformProductId(value: string | null | undefined) {
  const compact = (value ?? "").trim().replace(/\s+/g, "");
  const numeric = compact.replace(/^(PLID)+/i, "");
  return numeric ? `PLID${numeric}` : "";
}
