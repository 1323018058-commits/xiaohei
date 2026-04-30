"use client";

import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import {
  AlertCircle,
  Bot,
  ChevronDown,
  CheckCircle2,
  ClipboardCheck,
  FileSpreadsheet,
  ImageIcon,
  Loader2,
  PackagePlus,
  RefreshCcw,
  Search,
  Sparkles,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
import { Toaster, toast } from "sonner";

import type { components } from "@/generated/api-types";
import { ApiError, apiFetch } from "@/lib/api";

type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type CategoryMatchRequest = components["schemas"]["CategoryMatchRequest"];
type CategoryMatchResponse = components["schemas"]["CategoryMatchResponse"];
type CategoryMatchSuggestion = components["schemas"]["CategoryMatchSuggestion"];
type CategoryRequirements = components["schemas"]["TakealotCategoryRequirementsResponse"];
type CategorySearchResponse = components["schemas"]["TakealotCategorySearchResponse"];
type CategoryItem = components["schemas"]["TakealotCategoryItem"];
type BrandSearchResponse = components["schemas"]["TakealotBrandSearchResponse"];
type BrandItem = components["schemas"]["TakealotBrandItem"];
type DynamicAttributeDraft = components["schemas"]["DynamicAttributeDraft"];
type AiAutopilotRequest = components["schemas"]["ListingAiAutopilotRequest"];
type AiAutopilotResponse = components["schemas"]["ListingAiAutopilotResponse"];
type ImageUrlValidateRequest = components["schemas"]["ListingImageUrlValidateRequest"];
type ImageUrlValidateResponse = components["schemas"]["ListingImageUrlValidateResponse"];
type ImageRequirementCheckRequest = components["schemas"]["ListingImageRequirementCheckRequest"];
type ImageRequirementCheckResponse = components["schemas"]["ListingImageRequirementCheckResponse"];
type ImageUploadResponse = components["schemas"]["ListingImageUploadResponse"];
type ListingImageAsset = components["schemas"]["ListingImageAsset"];
type LoadsheetPreviewRequest = components["schemas"]["ListingLoadsheetPreviewRequest"];
type LoadsheetPreviewResponse = components["schemas"]["ListingLoadsheetPreviewResponse"];
type ValidationIssue = components["schemas"]["ListingLoadsheetValidationIssue"];
type SubmissionCreateRequest = components["schemas"]["ListingSubmissionCreateRequest"];
type SubmissionCreateResponse = components["schemas"]["ListingSubmissionCreateResponse"];
type SubmissionListResponse = components["schemas"]["ListingSubmissionListResponse"];
type SubmissionItem = components["schemas"]["ListingSubmissionItem"];
type SubmissionDetail = components["schemas"]["ListingSubmissionDetailResponse"];

type ListingForm = {
  productDescription: string;
  categoryId: string;
  sku: string;
  barcode: string;
  title: string;
  subtitle: string;
  description: string;
  whatsInTheBox: string;
  sellingPrice: string;
  rrp: string;
  stockQuantity: string;
  minimumLeadtimeDays: string;
  sellerWarehouseId: string;
  lengthCm: string;
  widthCm: string;
  heightCm: string;
  weightG: string;
  brandId: string;
  brandName: string;
};

type ListingDraftPayload = {
  version: 1;
  selectedStoreId: string;
  form: ListingForm;
  imageUrlsText: string;
  uploadedAssets: ListingImageAsset[];
  dynamicAttributes: DynamicAttributeDraft[];
  savedAt: string;
};

type BusyAction =
  | "match"
  | "requirements"
  | "ai"
  | "validate-images"
  | "check-images"
  | "upload-images"
  | "preview"
  | "submit"
  | "submission-detail";

type AttributeSpec = {
  key: string;
  label: string;
  required: boolean;
  inputType: string;
  options: AttributeOption[];
  placeholder: string;
  precision: number;
};

type AttributeOption = {
  value: string;
  label: string;
};

type UiIssue = {
  level: "error" | "warning";
  field: string;
  message: string;
};

const initialForm: ListingForm = {
  productDescription: "",
  categoryId: "",
  sku: "",
  barcode: "",
  title: "",
  subtitle: "",
  description: "",
  whatsInTheBox: "",
  sellingPrice: "",
  rrp: "",
  stockQuantity: "",
  minimumLeadtimeDays: "",
  sellerWarehouseId: "",
  lengthCm: "",
  widthCm: "",
  heightCm: "",
  weightG: "",
  brandId: "",
  brandName: "",
};

const inputClassName =
  "h-10 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#595959] focus:border-[#000000] disabled:cursor-not-allowed disabled:bg-[#FAFAFA] disabled:text-[#B3B3B3]";

const textareaClassName =
  "min-h-24 w-full resize-y rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2 text-sm leading-6 text-[#000000] outline-none placeholder:text-[#595959] focus:border-[#000000] disabled:cursor-not-allowed disabled:bg-[#FAFAFA] disabled:text-[#B3B3B3]";

const listingDraftStorageKey = "xiaohei_listing_new_draft_v1";
const takealotSkuMaxLength = 128;
const categoryMatchTimeoutMs = 3000;

const fieldLabelMap: Record<string, string> = {
  asset_ids: "图片资产",
  barcode: "条码",
  brand_id: "品牌 ID",
  brand_name: "品牌名称",
  category: "类目",
  category_id: "类目 ID",
  created_at: "创建时间",
  description: "商品描述",
  dynamic_attributes: "类目属性",
  height_cm: "高度",
  image_urls: "图片链接",
  length_cm: "长度",
  minimum_leadtime_days: "备货期",
  optional_attributes: "选填属性",
  product_description: "商品描述",
  required_attributes: "必填属性",
  rrp: "建议零售价",
  seller_warehouse_id: "Takealot 仓库 ID",
  selling_price: "售价",
  sku: "SKU",
  stock_quantity: "库存数量",
  store_id: "店铺",
  subtitle: "商品副标题",
  task_id: "任务 ID",
  title: "商品标题",
  updated_at: "更新时间",
  weight_g: "重量",
  whats_in_the_box: "包装清单",
  width_cm: "宽度",
};

export default function NewListingPage() {
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState("");
  const [isLoadingStores, setIsLoadingStores] = useState(true);
  const [storeError, setStoreError] = useState("");

  const [form, setForm] = useState<ListingForm>(initialForm);
  const [categoryMatch, setCategoryMatch] = useState<CategoryMatchResponse | null>(null);
  const [categoryError, setCategoryError] = useState("");
  const [categoryMatchElapsedMs, setCategoryMatchElapsedMs] = useState<number | null>(null);
  const [requirements, setRequirements] = useState<CategoryRequirements | null>(null);
  const [categorySearchQuery, setCategorySearchQuery] = useState("");
  const [categoryOptions, setCategoryOptions] = useState<CategoryItem[]>([]);
  const [categorySearchLoading, setCategorySearchLoading] = useState(false);
  const [categorySearchError, setCategorySearchError] = useState("");

  const [brandOptions, setBrandOptions] = useState<BrandItem[]>([]);
  const [brandSearchLoading, setBrandSearchLoading] = useState(false);
  const [brandSearchError, setBrandSearchError] = useState("");

  const [imageUrlsText, setImageUrlsText] = useState("");
  const [imageValidations, setImageValidations] = useState<Record<string, ImageUrlValidateResponse>>({});
  const [imageCheck, setImageCheck] = useState<ImageRequirementCheckResponse | null>(null);
  const [imageError, setImageError] = useState("");
  const [uploadedAssets, setUploadedAssets] = useState<ListingImageAsset[]>([]);

  const [dynamicAttributes, setDynamicAttributes] = useState<DynamicAttributeDraft[]>([]);
  const [customAttributeKey, setCustomAttributeKey] = useState("");
  const [aiResult, setAiResult] = useState<AiAutopilotResponse | null>(null);
  const [preview, setPreview] = useState<LoadsheetPreviewResponse | null>(null);
  const [submissionResult, setSubmissionResult] = useState<SubmissionCreateResponse | null>(null);

  const [submissions, setSubmissions] = useState<SubmissionItem[]>([]);
  const [submissionsError, setSubmissionsError] = useState("");
  const [isLoadingSubmissions, setIsLoadingSubmissions] = useState(false);
  const [selectedSubmissionId, setSelectedSubmissionId] = useState("");
  const [submissionDetail, setSubmissionDetail] = useState<SubmissionDetail | null>(null);

  const [busyAction, setBusyAction] = useState<BusyAction | null>(null);
  const [formCheckOpen, setFormCheckOpen] = useState(false);
  const [optionalAttributesOpen, setOptionalAttributesOpen] = useState(false);
  const [draftStatus, setDraftStatus] = useState("");
  const brandSearchRequestRef = useRef(0);
  const categorySearchRequestRef = useRef(0);
  const categorySearchSelectionRef = useRef("");
  const draftHydratedRef = useRef(false);
  const skipNextDraftSaveRef = useRef(false);
  const lastAutoSkuRef = useRef("");
  const categoryAttributeKeysRef = useRef<Set<string>>(new Set());

  const selectedStore = useMemo(
    () => stores.find((store) => store.store_id === selectedStoreId) ?? null,
    [selectedStoreId, stores],
  );
  const categoryId = useMemo(() => parsePositiveInteger(form.categoryId), [form.categoryId]);
  const imageUrls = useMemo(() => parseImageUrls(imageUrlsText), [imageUrlsText]);
  const assetIds = useMemo(() => uploadedAssets.map((asset) => asset.id).filter(isPresent), [uploadedAssets]);
  const imageCount = imageUrls.length + assetIds.length;
  const minRequiredImages = requirements?.min_required_images ?? selectedSuggestionMinImages(categoryMatch, categoryId);
  const selectedCategorySuggestion = useMemo(
    () => (categoryId ? (categoryMatch?.suggestions ?? []).find((suggestion) => suggestion.category_id === categoryId) ?? null : null),
    [categoryId, categoryMatch],
  );
  const attributeSpecs = useMemo(() => buildAttributeSpecs(requirements), [requirements]);
  const requiredAttributeSpecs = useMemo(
    () => attributeSpecs.filter((attribute) => attribute.required),
    [attributeSpecs],
  );
  const optionalAttributeSpecs = useMemo(
    () => attributeSpecs.filter((attribute) => !attribute.required),
    [attributeSpecs],
  );
  const listedAttributeKeys = useMemo(
    () => new Set(attributeSpecs.map((attribute) => attribute.key)),
    [attributeSpecs],
  );
  const customAttributes = useMemo(
    () => dynamicAttributes.filter((attribute) => !listedAttributeKeys.has(attribute.key)),
    [dynamicAttributes, listedAttributeKeys],
  );
  const localIssues = useMemo(
    () =>
      collectLocalIssues({
        form,
        selectedStoreId,
        categoryId,
        imageUrls,
        assetIds,
        minRequiredImages,
        requiredAttributeSpecs,
        dynamicAttributes,
      }),
    [
      assetIds,
      categoryId,
      dynamicAttributes,
      form,
      imageUrls,
      minRequiredImages,
      requiredAttributeSpecs,
      selectedStoreId,
    ],
  );
  const hasLocalErrors = localIssues.some((issue) => issue.level === "error");
  const previewHasErrors = Boolean(preview?.issues?.some((issue) => issue.level === "error"));
  const localErrorCount = localIssues.filter((issue) => issue.level === "error").length;
  const localWarningCount = localIssues.filter((issue) => issue.level === "warning").length;
  const previewIssues = useMemo(() => toUiIssues(preview?.issues ?? []), [preview]);
  const previewErrorCount = previewIssues.filter((issue) => issue.level === "error").length;
  const previewWarningCount = previewIssues.filter((issue) => issue.level === "warning").length;
  const validatedImages = useMemo(() => Object.values(imageValidations), [imageValidations]);
  const validImageCount = validatedImages.filter((result) => result.valid).length;
  const invalidImageCount = validatedImages.filter((result) => !result.valid).length;

  useEffect(() => {
    const restoredStoreId = restoreListingDraft();
    void loadStores(restoredStoreId);
  }, []);

  useEffect(() => {
    if (!draftHydratedRef.current) return;
    if (skipNextDraftSaveRef.current) {
      skipNextDraftSaveRef.current = false;
      return;
    }
    const handle = window.setTimeout(() => {
      saveListingDraft();
    }, 700);
    return () => window.clearTimeout(handle);
  }, [dynamicAttributes, form, imageUrlsText, selectedStoreId, uploadedAssets]);

  useEffect(() => {
    if (!selectedStoreId) {
      setSubmissions([]);
      return;
    }
    void loadSubmissions(selectedStoreId);
  }, [selectedStoreId]);

  useEffect(() => {
    const query = form.brandName.trim();
    if (query.length < 2) {
      setBrandOptions([]);
      setBrandSearchError("");
      return;
    }

    const handle = window.setTimeout(() => {
      void searchBrands(query);
    }, 300);

    return () => window.clearTimeout(handle);
  }, [form.brandName]);

  useEffect(() => {
    const query = categorySearchQuery.trim();
    if (query.length < 2) {
      setCategoryOptions([]);
      setCategorySearchError("");
      return;
    }
    if (query === categorySearchSelectionRef.current) {
      setCategoryOptions([]);
      setCategorySearchError("");
      return;
    }

    const handle = window.setTimeout(() => {
      void searchCategories(query);
    }, 300);

    return () => window.clearTimeout(handle);
  }, [categorySearchQuery]);

  function restoreListingDraft() {
    try {
      const rawDraft = window.localStorage.getItem(listingDraftStorageKey);
      if (!rawDraft) {
        draftHydratedRef.current = true;
        return "";
      }
      const draft = JSON.parse(rawDraft) as Partial<ListingDraftPayload>;
      if (draft.version !== 1 || !draft.form) {
        window.localStorage.removeItem(listingDraftStorageKey);
        draftHydratedRef.current = true;
        return "";
      }
      const restoredStoreId = typeof draft.selectedStoreId === "string" ? draft.selectedStoreId : "";
      setSelectedStoreId(restoredStoreId);
      setForm({ ...initialForm, ...draft.form });
      setImageUrlsText(typeof draft.imageUrlsText === "string" ? draft.imageUrlsText : "");
      setUploadedAssets(Array.isArray(draft.uploadedAssets) ? draft.uploadedAssets : []);
      setDynamicAttributes(Array.isArray(draft.dynamicAttributes) ? draft.dynamicAttributes : []);
      setDraftStatus(draft.savedAt ? `已恢复 ${formatDateTime(draft.savedAt)}` : "已恢复草稿");
      return restoredStoreId;
    } catch {
      window.localStorage.removeItem(listingDraftStorageKey);
      setDraftStatus("草稿不可用，已重置");
      return "";
    } finally {
      draftHydratedRef.current = true;
    }
  }

  function saveListingDraft() {
    try {
      const payload: ListingDraftPayload = {
        version: 1,
        selectedStoreId,
        form,
        imageUrlsText,
        uploadedAssets,
        dynamicAttributes,
        savedAt: new Date().toISOString(),
      };
      window.localStorage.setItem(listingDraftStorageKey, JSON.stringify(payload));
      setDraftStatus("草稿已保存");
    } catch {
      setDraftStatus("草稿保存失败");
    }
  }

  function clearListingDraft() {
    skipNextDraftSaveRef.current = true;
    window.localStorage.removeItem(listingDraftStorageKey);
    lastAutoSkuRef.current = "";
    categoryAttributeKeysRef.current = new Set();
    setForm(initialForm);
    setImageUrlsText("");
    setUploadedAssets([]);
    setDynamicAttributes([]);
    setOptionalAttributesOpen(false);
    setPreview(null);
    setSubmissionResult(null);
    setImageValidations({});
    setImageCheck(null);
    setCategoryMatch(null);
    setRequirements(null);
    setCategorySearchQuery("");
    setCategoryOptions([]);
    setDraftStatus("草稿已清空");
  }

  async function loadStores(preferredStoreId = "") {
    setIsLoadingStores(true);
    setStoreError("");
    try {
      const data = await apiFetch<StoreListResponse>("/api/v1/stores");
      setStores(data.stores);
      setSelectedStoreId((current) =>
        data.stores.some((store) => store.store_id === (preferredStoreId || current))
          ? preferredStoreId || current
          : data.stores.some((store) => store.store_id === current)
          ? current
          : data.stores[0]?.store_id ?? "",
      );
    } catch (error) {
      setStores([]);
      setSelectedStoreId("");
      setStoreError(formatError(error, "加载店铺失败"));
    } finally {
      setIsLoadingStores(false);
    }
  }

  async function loadSubmissions(storeId: string) {
    setIsLoadingSubmissions(true);
    setSubmissionsError("");
    try {
      const data = await apiFetch<SubmissionListResponse>(
        `/api/listing/stores/${encodeURIComponent(storeId)}/submissions?page=1&page_size=8`,
      );
      setSubmissions(data.items);
    } catch (error) {
      setSubmissions([]);
      setSubmissionsError(formatError(error, "加载提交记录失败"));
    } finally {
      setIsLoadingSubmissions(false);
    }
  }

  async function searchBrands(query: string) {
    const requestId = brandSearchRequestRef.current + 1;
    brandSearchRequestRef.current = requestId;
    setBrandSearchLoading(true);
    setBrandSearchError("");
    try {
      const params = new URLSearchParams({ q: query, page: "1", page_size: "8" });
      const data = await apiFetch<BrandSearchResponse>(`/api/listing/brands/search?${params}`);
      if (requestId !== brandSearchRequestRef.current) return;
      setBrandOptions(data.items);
      if (!data.catalog_ready && data.message) {
        setBrandSearchError(data.message);
      }
    } catch (error) {
      if (requestId !== brandSearchRequestRef.current) return;
      setBrandOptions([]);
      setBrandSearchError(formatError(error, "品牌搜索失败"));
    } finally {
      if (requestId === brandSearchRequestRef.current) {
        setBrandSearchLoading(false);
      }
    }
  }

  async function searchCategories(query: string) {
    const requestId = categorySearchRequestRef.current + 1;
    categorySearchRequestRef.current = requestId;
    setCategorySearchLoading(true);
    setCategorySearchError("");
    try {
      const params = new URLSearchParams({ q: query, page: "1", page_size: "8" });
      const data = await apiFetch<CategorySearchResponse>(`/api/listing/categories/search?${params}`);
      if (requestId !== categorySearchRequestRef.current) return;
      setCategoryOptions(data.items);
      if (data.message) {
        setCategorySearchError(data.message);
      } else if (data.items.length === 0) {
        setCategorySearchError("没有找到匹配类目");
      }
    } catch (error) {
      if (requestId !== categorySearchRequestRef.current) return;
      setCategoryOptions([]);
      setCategorySearchError(formatError(error, "类目搜索失败"));
    } finally {
      if (requestId === categorySearchRequestRef.current) {
        setCategorySearchLoading(false);
      }
    }
  }

  function updateForm<Key extends keyof ListingForm>(key: Key, value: ListingForm[Key]) {
    if (key === "sku" && String(value).trim() !== lastAutoSkuRef.current) {
      lastAutoSkuRef.current = "";
    }
    setForm((current) => ({ ...current, [key]: value }));
    if (key === "categoryId") {
      setPreview(null);
      setImageCheck(null);
      categorySearchSelectionRef.current = "";
      setCategorySearchQuery("");
      setCategoryOptions([]);
    }
  }

  async function matchCategories() {
    if (!form.productDescription.trim()) {
      toast.error("请先填写商品描述");
      return;
    }

    setBusyAction("match");
    setCategoryError("");
    setCategoryMatchElapsedMs(null);
    const startedAt = performance.now();
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), categoryMatchTimeoutMs);
    let recordedElapsed = false;
    try {
      const payload: CategoryMatchRequest = {
        description: form.productDescription.trim(),
        language_hint: "zh-CN",
        limit: 5,
        use_ai: true,
      };
      const data = await apiFetch<CategoryMatchResponse>("/api/listing/categories/match", {
        method: "POST",
        body: JSON.stringify(payload),
        signal: controller.signal,
      });
      const elapsedMs = Math.round(performance.now() - startedAt);
      const elapsedText = formatElapsedMs(elapsedMs);
      setCategoryMatchElapsedMs(elapsedMs);
      recordedElapsed = true;
      setCategoryMatch(data);
      const topSuggestion = data.suggestions[0];
      if (topSuggestion && topSuggestion.confidence >= 0.9) {
        await applyCategory(topSuggestion, { autoGenerateContent: false, showToast: false });
        toast.success("已匹配并套用推荐类目", {
          description: `${topSuggestion.path_zh || topSuggestion.path_en || String(topSuggestion.category_id)} · ${elapsedText}`,
        });
      } else {
        toast.success(data.suggestions.length ? "已完成类目匹配" : "没有匹配到可用类目", {
          description: elapsedText,
        });
      }
    } catch (error) {
      const message =
        error instanceof Error && error.name === "AbortError"
          ? "类目匹配超过 3 秒，已停止等待。请重试或先构建类目向量索引提升长尾匹配速度。"
          : formatError(error, "类目匹配失败");
      setCategoryError(message);
      toast.error("类目匹配失败", { description: message });
    } finally {
      window.clearTimeout(timeoutId);
      if (!recordedElapsed) {
        setCategoryMatchElapsedMs(Math.round(performance.now() - startedAt));
      }
      setBusyAction(null);
    }
  }

  async function applyCategory(
    suggestion: CategoryMatchSuggestion,
    options: { autoGenerateContent?: boolean; showToast?: boolean } = {},
  ) {
    const shouldGenerateContent = options.autoGenerateContent ?? true;
    const shouldShowToast = options.showToast ?? true;
    setImageCheck(null);
    setPreview(null);
    setForm((current) => {
      const nextSku = shouldRefreshGeneratedSku(current.sku, lastAutoSkuRef.current)
        ? buildGeneratedSku(current, suggestion)
        : current.sku;
      if (nextSku !== current.sku) {
        lastAutoSkuRef.current = nextSku;
      }
      return { ...current, categoryId: String(suggestion.category_id), sku: nextSku };
    });
    const label = categoryItemDisplayPath(suggestion);
    categorySearchSelectionRef.current = label;
    setCategorySearchQuery(label);
    setCategoryOptions([]);
    const loadedRequirements = await loadCategoryRequirements(suggestion.category_id);
    if (shouldShowToast) {
      toast.success("已套用类目", {
        description: suggestion.path_zh || suggestion.path_en || String(suggestion.category_id),
      });
    }
    if (shouldGenerateContent && form.productDescription.trim()) {
      await generateAiContent(suggestion.category_id, loadedRequirements, { auto: true });
    }
  }

  async function selectCategory(category: CategoryItem) {
    setImageCheck(null);
    setPreview(null);
    setForm((current) => {
      const nextSku = shouldRefreshGeneratedSku(current.sku, lastAutoSkuRef.current)
        ? buildGeneratedSku(current, category)
        : current.sku;
      if (nextSku !== current.sku) {
        lastAutoSkuRef.current = nextSku;
      }
      return { ...current, categoryId: String(category.category_id), sku: nextSku };
    });
    const label = categoryItemDisplayPath(category);
    categorySearchSelectionRef.current = label;
    setCategorySearchQuery(label);
    setCategoryOptions([]);
    const loadedRequirements = await loadCategoryRequirements(category.category_id);
    toast.success("已套用类目", {
      description: category.path_zh || category.path_en || String(category.category_id),
    });
    if (form.productDescription.trim()) {
      await generateAiContent(category.category_id, loadedRequirements, { auto: true });
    }
  }

  async function loadCategoryRequirements(targetCategoryId = categoryId) {
    if (!targetCategoryId) {
      toast.error("请先填写类目 ID");
      return null;
    }

    setBusyAction("requirements");
    setCategoryError("");
    try {
      const data = await apiFetch<CategoryRequirements>(
        `/api/listing/categories/${encodeURIComponent(String(targetCategoryId))}/requirements`,
      );
      setRequirements(data);
      // Category attributes are template-scoped. When the category changes,
      // keep custom/manual extras but remove stale attributes from the previous
      // category so required and optional fields always match the selected row.
      syncDynamicAttributesForCategory(buildAttributeSpecs(data));
      return data;
    } catch (error) {
      const message = formatError(error, "读取类目要求失败");
      setRequirements(null);
      setCategoryError(message);
      toast.error("读取类目要求失败", { description: message });
      return null;
    } finally {
      setBusyAction(null);
    }
  }

  async function generateAiContent(
    targetCategoryId = categoryId,
    targetRequirements: CategoryRequirements | null = requirements,
    options: { auto?: boolean } = {},
  ) {
    if (!targetCategoryId) {
      toast.error("请先套用或填写类目 ID");
      return;
    }
    if (!form.productDescription.trim()) {
      if (!options.auto) {
        toast.error("请先填写商品描述");
      }
      return;
    }

    setBusyAction("ai");
    try {
      const payload: AiAutopilotRequest = {
        product_description: form.productDescription.trim(),
        category_id: targetCategoryId,
        brand_name: form.brandName.trim(),
        required_attributes: targetRequirements?.required_attributes ?? [],
        optional_attributes: targetRequirements?.optional_attributes ?? [],
        language_hint: "zh-CN",
        use_ai: true,
      };
      const data = await apiFetch<AiAutopilotResponse>("/api/listing/ai/autopilot", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setAiResult(data);
      setForm((current) => ({
        ...current,
        categoryId: String(data.category_id || current.categoryId),
        title: data.title || current.title,
        subtitle: data.subtitle || current.subtitle,
        description: data.description || current.description,
        whatsInTheBox: data.whats_in_the_box || current.whatsInTheBox,
        lengthCm: numberToInput(data.length_cm, current.lengthCm),
        widthCm: numberToInput(data.width_cm, current.widthCm),
        heightCm: numberToInput(data.height_cm, current.heightCm),
        weightG: numberToInput(data.weight_g, current.weightG),
      }));
      mergeDynamicAttributes(data.dynamic_attributes ?? []);
      toast.success(data.fallback_used ? "已用兜底规则生成内容" : "AI 内容已回填");
    } catch (error) {
      toast.error("AI 生成失败", {
        description: formatError(error, "请稍后重试"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function validateImageUrls() {
    if (imageUrls.length === 0) {
      toast.error("请先输入图片 URL");
      return;
    }

    setBusyAction("validate-images");
    setImageError("");
    try {
      const results = await Promise.allSettled(
        imageUrls.map((imageUrl) => {
          const payload: ImageUrlValidateRequest = { image_url: imageUrl, check_remote: true };
          return apiFetch<ImageUrlValidateResponse>("/api/listing/images/validate-url", {
            method: "POST",
            body: JSON.stringify(payload),
          });
        }),
      );
      const next: Record<string, ImageUrlValidateResponse> = {};
      let failedCount = 0;
      results.forEach((result, index) => {
        const imageUrl = imageUrls[index];
        if (!imageUrl) return;
        if (result.status === "fulfilled") {
          next[imageUrl] = result.value;
          if (!result.value.valid) failedCount += 1;
          return;
        }
        failedCount += 1;
        next[imageUrl] = {
          image_url: imageUrl,
          valid: false,
          warnings: [],
          errors: [formatError(result.reason, "图片 URL 校验失败")],
        };
      });
      setImageValidations(next);
      if (failedCount > 0) {
        toast.warning("图片 URL 校验完成", { description: `${failedCount} 个 URL 需要处理` });
      } else {
        toast.success("图片 URL 校验通过");
      }
    } catch (error) {
      const message = formatError(error, "图片 URL 校验失败");
      setImageError(message);
      toast.error("图片 URL 校验失败", { description: message });
    } finally {
      setBusyAction(null);
    }
  }

  async function checkImageRequirements() {
    if (!categoryId) {
      toast.error("请先套用或填写类目 ID");
      return;
    }
    if (imageUrls.length === 0 && assetIds.length === 0) {
      toast.error("请先输入图片 URL 或上传图片");
      return;
    }

    setBusyAction("check-images");
    setImageError("");
    try {
      const payload: ImageRequirementCheckRequest = {
        category_id: categoryId,
        image_urls: imageUrls,
        asset_ids: assetIds,
      };
      const data = await apiFetch<ImageRequirementCheckResponse>(
        "/api/listing/images/check-requirements",
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setImageCheck(data);
      if (data.passed) {
        toast.success("图片数量满足类目要求");
      } else {
        toast.warning("图片数量不足", { description: `还差 ${data.missing_count} 张` });
      }
    } catch (error) {
      const message = formatError(error, "图片要求检查失败");
      setImageError(message);
      toast.error("图片要求检查失败", { description: message });
    } finally {
      setBusyAction(null);
    }
  }

  async function uploadImages(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    event.target.value = "";
    if (files.length === 0) return;
    if (!selectedStoreId) {
      toast.error("请先选择店铺");
      return;
    }

    setBusyAction("upload-images");
    setImageError("");
    try {
      const formData = new FormData();
      formData.append("store_id", selectedStoreId);
      files.forEach((file) => formData.append("files", file));
      const data = await fetchMultipart<ImageUploadResponse>("/api/listing/images", formData);
      setUploadedAssets((current) => [...current, ...data.items]);
      if (data.warnings?.length) {
        toast.warning("图片已上传", { description: data.warnings.join("；") });
      } else {
        toast.success(`已上传 ${data.items.length} 张图片`);
      }
    } catch (error) {
      const message = formatError(error, "图片上传失败");
      setImageError(message);
      toast.error("图片上传失败", { description: message });
    } finally {
      setBusyAction(null);
    }
  }

  async function previewLoadsheet() {
    if (hasLocalErrors) {
      setFormCheckOpen(true);
      toast.error("请先修复表单检查中的错误");
      return;
    }
    if (!categoryId) return;

    setBusyAction("preview");
    try {
      const payload: LoadsheetPreviewRequest = {
        store_id: selectedStoreId,
        ...buildSubmissionPayload(categoryId),
      };
      const data = await apiFetch<LoadsheetPreviewResponse>("/api/listing/loadsheet/preview", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      setPreview(data);
      if (data.valid) {
        toast.success("上架表预检通过");
      } else {
        toast.warning("上架表预检未通过", {
          description: `${data.issues?.length ?? 0} 个问题需要处理`,
        });
      }
    } catch (error) {
      toast.error("上架表预检失败", {
        description: formatError(error, "请稍后重试"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function submitListing() {
    if (hasLocalErrors) {
      setFormCheckOpen(true);
      toast.error("请先修复表单检查中的错误");
      return;
    }
    if (previewHasErrors) {
      toast.error("上架表预检还有错误", {
        description: "请先修复预检问题后再提交上架。",
      });
      return;
    }
    if (!categoryId || !selectedStoreId) return;

    setBusyAction("submit");
    try {
      const payload: SubmissionCreateRequest = buildSubmissionPayload(categoryId);
      const data = await apiFetch<SubmissionCreateResponse>(
        `/api/listing/stores/${encodeURIComponent(selectedStoreId)}/submissions`,
        {
          method: "POST",
          body: JSON.stringify(payload),
        },
      );
      setSubmissionResult(data);
      if (data.takealot_submission_id || data.submit_succeeded) {
        toast.success("Takealot 提交成功", {
          description: data.takealot_submission_id
            ? `官方 submission id：${data.takealot_submission_id}`
            : data.message,
        });
      } else if (data.submit_succeeded === false || submissionCreateFailed(data)) {
        toast.error("Takealot 提交失败", {
          description: data.error_message || data.message,
        });
      } else {
        toast.info("已创建上架提交", {
          description: data.message,
        });
      }
      await loadSubmissions(selectedStoreId);
    } catch (error) {
      toast.error("提交上架失败", {
        description: formatError(error, "请稍后重试"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function openSubmissionDetail(submissionId: string) {
    setSelectedSubmissionId(submissionId);
    setSubmissionDetail(null);
    setBusyAction("submission-detail");
    try {
      const data = await apiFetch<SubmissionDetail>(
        `/api/listing/submissions/${encodeURIComponent(submissionId)}`,
      );
      setSubmissionDetail(data);
    } catch (error) {
      toast.error("加载提交详情失败", {
        description: formatError(error, "请稍后重试"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  function selectBrand(brand: BrandItem) {
    setForm((current) => ({
      ...current,
      brandId: brand.brand_id,
      brandName: brand.brand_name,
    }));
    setBrandOptions([]);
  }

  function syncDynamicAttributesForCategory(attributes: AttributeSpec[]) {
    const previousCategoryKeys = categoryAttributeKeysRef.current;
    const nextCategoryKeys = new Set(attributes.map((attribute) => attribute.key));
    categoryAttributeKeysRef.current = nextCategoryKeys;
    setOptionalAttributesOpen(false);
    setDynamicAttributes((current) => {
      const existingKeys = new Set(current.map((attribute) => attribute.key));
      const additions = attributes
        .filter((attribute) => !existingKeys.has(attribute.key))
        .map<DynamicAttributeDraft>((attribute) => ({
          key: attribute.key,
          value: "",
          source: "manual",
        }));
      const carried = current.filter(
        (attribute) => nextCategoryKeys.has(attribute.key) || !previousCategoryKeys.has(attribute.key),
      );
      return additions.length ? [...carried, ...additions] : carried;
    });
  }

  function mergeDynamicAttributes(nextAttributes: DynamicAttributeDraft[]) {
    setDynamicAttributes((current) => {
      const merged = new Map(current.map((attribute) => [attribute.key, attribute]));
      nextAttributes.forEach((attribute) => {
        if (!attribute.key) return;
        merged.set(attribute.key, {
          ...merged.get(attribute.key),
          ...attribute,
          source: attribute.source || merged.get(attribute.key)?.source || "ai",
        });
      });
      return Array.from(merged.values());
    });
  }

  function updateDynamicAttribute(key: string, value: string) {
    const normalizedKey = key.trim();
    if (!normalizedKey) return;
    setDynamicAttributes((current) => {
      const exists = current.some((attribute) => attribute.key === normalizedKey);
      if (exists) {
        return current.map((attribute) =>
          attribute.key === normalizedKey
            ? { ...attribute, value, source: attribute.source || "manual" }
            : attribute,
        );
      }
      return [...current, { key: normalizedKey, value, source: "manual" }];
    });
  }

  function addCustomAttribute() {
    const key = customAttributeKey.trim();
    if (!key) return;
    updateDynamicAttribute(key, "");
    setCustomAttributeKey("");
  }

  function removeCustomAttribute(key: string) {
    setDynamicAttributes((current) => current.filter((attribute) => attribute.key !== key));
  }

  function removeUploadedAsset(assetId: string | null | undefined) {
    setUploadedAssets((current) => current.filter((asset) => asset.id !== assetId));
    setImageCheck(null);
  }

  function buildSubmissionPayload(targetCategoryId: number): SubmissionCreateRequest {
    return {
      category_id: targetCategoryId,
      brand_id: emptyToNull(form.brandId),
      brand_name: form.brandName.trim(),
      sku: form.sku.trim(),
      barcode: form.barcode.trim(),
      title: form.title.trim(),
      subtitle: form.subtitle.trim(),
      description: form.description.trim(),
      whats_in_the_box: form.whatsInTheBox.trim(),
      selling_price: parseOptionalNumber(form.sellingPrice),
      rrp: parseOptionalNumber(form.rrp),
      stock_quantity: parseOptionalInteger(form.stockQuantity),
      minimum_leadtime_days: parseOptionalInteger(form.minimumLeadtimeDays),
      seller_warehouse_id: form.sellerWarehouseId.trim(),
      length_cm: parseOptionalNumber(form.lengthCm),
      width_cm: parseOptionalNumber(form.widthCm),
      height_cm: parseOptionalNumber(form.heightCm),
      weight_g: parseOptionalNumber(form.weightG),
      image_urls: imageUrls,
      asset_ids: assetIds,
      dynamic_attributes: cleanDynamicAttributes(dynamicAttributes),
      submit_immediately: true,
    };
  }

  return (
    <div className="space-y-4 text-[#000000]">
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

      <header className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="space-y-1">
          <div className="text-xs font-medium text-[#595959]">上架工作台</div>
          <h1 className="text-[28px] font-semibold text-[#000000]">
            上架新品
          </h1>
          <p className="max-w-[760px] text-sm leading-6 text-[#595959]">
            先完成类目、内容、图片和上架表预检，再创建上架提交；后端不可用时页面会保留当前输入并显示错误。
          </p>
          <div className="flex flex-wrap items-center gap-3 text-xs text-[#595959]">
            <span>{draftStatus || "草稿待保存"}</span>
            <button
              type="button"
              onClick={clearListingDraft}
              className="h-7 rounded-[6px] border border-[#EBEBEB] px-2 text-xs text-[#595959] hover:text-[#000000]"
            >
              清空草稿
            </button>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            icon={FileSpreadsheet}
            loading={busyAction === "preview"}
            onClick={() => void previewLoadsheet()}
          >
            上架表预检
          </ActionButton>
          <ActionButton
            icon={PackagePlus}
            loading={busyAction === "submit"}
            onClick={() => void submitListing()}
          >
            提交上架
          </ActionButton>
        </div>
      </header>

      {storeError ? <ErrorBanner message={storeError} /> : null}

      <WorkflowSummary
        storeName={selectedStore?.name ?? ""}
        categoryId={categoryId}
        imageCount={imageCount}
        minRequiredImages={minRequiredImages}
        localErrorCount={localErrorCount}
        localWarningCount={localWarningCount}
        preview={preview}
        previewErrorCount={previewErrorCount}
        previewWarningCount={previewWarningCount}
        submissionResult={submissionResult}
      />

      <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-[#000000]">AI 上架代驾</h2>
              <StatusPill tone={categoryId ? "success" : "muted"}>
                {categoryId ? `已套用类目 ${categoryId}` : "等待类目匹配"}
              </StatusPill>
            </div>
            <p className="mt-1 text-xs leading-5 text-[#595959]">
              输入商品品类、型号或卖点后，先匹配 Takealot 类目；套用后自动生成 SKU、同步图片限制、证书和属性字段。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <ActionButton
              icon={Sparkles}
              loading={busyAction === "match"}
              disabled={!form.productDescription.trim()}
              onClick={() => void matchCategories()}
            >
              智能匹配类目
            </ActionButton>
            <ActionButton
              icon={Bot}
              loading={busyAction === "ai"}
              disabled={!categoryId || !form.productDescription.trim()}
              onClick={() => void generateAiContent()}
            >
              AI 生成内容
            </ActionButton>
          </div>
        </div>

        <div className="grid gap-3 xl:grid-cols-[240px_minmax(0,1fr)]">
          <Field label="店铺" required>
            <select
              value={selectedStoreId}
              onChange={(event) => setSelectedStoreId(event.target.value)}
              disabled={isLoadingStores || stores.length === 0}
              className={inputClassName}
            >
              <option value="">
                {isLoadingStores ? "加载店铺中..." : stores.length ? "请选择店铺" : "暂无店铺"}
              </option>
              {stores.map((store) => (
                <option key={store.store_id} value={store.store_id}>
                  {store.name}
                </option>
              ))}
            </select>
            {selectedStore ? (
              <div className="mt-1 text-xs text-[#595959]">店铺 ID：{shortId(selectedStore.store_id)}</div>
            ) : null}
          </Field>

          <Field label="产品简短描述 / 型号" required>
            <input
              value={form.productDescription}
              onChange={(event) => updateForm("productDescription", event.target.value)}
              placeholder="例如：空气炸锅 6L 可视窗口 / Bluetooth gaming keyboard"
              className={inputClassName}
              maxLength={1000}
            />
          </Field>
        </div>

        <div className="mt-4 border-t border-[#EBEBEB] pt-4">
          <div className="mb-3 flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
            <div>
              <div className="text-sm font-semibold text-[#000000]">智能类目匹配结果</div>
              <div className="mt-1 text-xs leading-5 text-[#595959]">
                从候选中点击“套用”，系统会加载该类目的图片、证书、必填项和选填项。
              </div>
            </div>
            {categoryMatch ? (
              <div className="flex flex-wrap gap-2 text-xs text-[#595959]">
                <StatusPill tone={categoryMatch.catalog_ready ? "success" : "warning"}>
                  {categoryMatch.catalog_ready ? "类目库可用" : "类目库未就绪"}
                </StatusPill>
                <StatusPill tone={categoryMatch.ai_used ? "success" : "muted"}>
                  {categoryMatch.ai_used ? "已使用 AI" : "规则匹配"}
                </StatusPill>
                {categoryMatchElapsedMs !== null ? (
                  <StatusPill tone={categoryMatchElapsedMs <= categoryMatchTimeoutMs ? "success" : "warning"}>
                    用时 {formatElapsedMs(categoryMatchElapsedMs)}
                  </StatusPill>
                ) : null}
                <StatusPill tone="muted">候选 {categoryMatch.total_candidates}</StatusPill>
              </div>
            ) : null}
          </div>
          {categoryError ? <InlineError message={categoryError} /> : null}
          {busyAction === "match" ? <LoadingLine text="正在匹配类目" /> : null}
          {categoryMatch?.message ? (
            <div className="mb-3 text-xs leading-5 text-[#595959]">{categoryMatch.message}</div>
          ) : null}
          {categoryMatch?.suggestions.length ? (
            <div className="grid gap-2 lg:grid-cols-2 2xl:grid-cols-3">
              {categoryMatch.suggestions.map((suggestion) => (
                <CategorySuggestionRow
                  key={suggestion.category_id}
                  suggestion={suggestion}
                  active={suggestion.category_id === categoryId}
                  onApply={() => void applyCategory(suggestion)}
                />
              ))}
            </div>
          ) : (
            <EmptyLine text="点击智能匹配类目后，这里会展示最多 5 个候选类目。" />
          )}
          {categoryId ? (
            <SelectedCategorySummary
              requirements={requirements}
              suggestion={selectedCategorySuggestion}
              imageCount={imageCount}
              requiredAttributes={requiredAttributeSpecs}
              optionalAttributes={optionalAttributeSpecs}
            />
          ) : null}
        </div>
      </section>

      <section className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_430px]">
        <main className="overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
          <FormBlock title="基础信息">
            <div className="grid gap-4">
              <Field label="SKU" required>
                <input
                  value={form.sku}
                  onChange={(event) => updateForm("sku", event.target.value)}
                  className={inputClassName}
                  maxLength={takealotSkuMaxLength}
                  placeholder="内部 SKU"
                />
                <div className="mt-1 text-xs leading-5 text-[#595959]">
                  套用类目后自动生成，格式为品类/商品关键词-日期-随机数，最长 {takealotSkuMaxLength} 位。
                </div>
              </Field>
              <Field label="条码" required>
                <input
                  value={form.barcode}
                  onChange={(event) => updateForm("barcode", event.target.value)}
                  className={inputClassName}
                  placeholder="EAN / UPC"
                />
              </Field>
            </div>

            <div className="mt-4 grid items-start gap-3 md:grid-cols-2">
              <Field label="类目 ID" required>
                <div className="flex gap-2">
                  <input
                    value={form.categoryId}
                    onChange={(event) => updateForm("categoryId", event.target.value)}
                    className={inputClassName}
                    inputMode="numeric"
                    placeholder="类目 ID"
                  />
                  <button
                    type="button"
                    onClick={() => void loadCategoryRequirements()}
                    disabled={!categoryId || busyAction === "requirements"}
                    className="inline-flex h-10 w-10 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000] disabled:cursor-not-allowed disabled:bg-[#FAFAFA] disabled:text-[#B3B3B3]"
                    title="读取类目要求"
                    aria-label="读取类目要求"
                  >
                    {busyAction === "requirements" ? (
                      <Loader2 className="h-4 w-4 animate-spin stroke-[1.8]" />
                    ) : (
                      <RefreshCcw className="h-4 w-4 stroke-[1.8]" />
                    )}
                  </button>
                </div>
              </Field>
              <Field label="Takealot 仓库 ID">
                <input
                  value={form.sellerWarehouseId}
                  onChange={(event) => updateForm("sellerWarehouseId", event.target.value)}
                  className={inputClassName}
                  placeholder="可选"
                />
              </Field>
            </div>

            <div className="mt-4 grid items-start gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_220px]">
              <Field label="类目搜索">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
                  <input
                    value={categorySearchQuery}
                    onChange={(event) => setCategorySearchQuery(event.target.value)}
                    className={`${inputClassName} pl-9`}
                    placeholder="输入中文品类、英文类目或类目 ID"
                  />
                  {categorySearchLoading ? (
                    <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-[#595959]" />
                  ) : null}
                  {categoryOptions.length > 0 ? (
                    <div className="absolute left-0 right-0 top-[44px] z-30 max-h-72 overflow-y-auto rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] shadow-sm">
                      {categoryOptions.map((category) => (
                        <button
                          key={`${category.id}-${category.category_id}`}
                          type="button"
                          onClick={() => void selectCategory(category)}
                          className="block w-full border-b border-[#EBEBEB] px-3 py-2 text-left text-sm last:border-b-0 hover:bg-[#FAFAFA]"
                        >
                          <span className="line-clamp-1 font-medium text-[#000000]">
                            {category.path_zh || category.path_en || category.lowest_category_raw}
                          </span>
                          <span className="mt-1 line-clamp-1 text-xs text-[#595959]">
                            {category.path_en || category.lowest_category_name || "英文类目待同步"}
                          </span>
                          <span className="mt-1 block text-xs text-[#595959]">
                            ID {category.category_id} · 至少 {category.min_required_images} 张图 ·{" "}
                            {category.attributes_ready ? "属性模板已同步" : "属性模板待同步"}
                          </span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                {categorySearchError ? <InlineError message={categorySearchError} /> : null}
              </Field>

              <Field label="品牌名称">
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
                  <input
                    value={form.brandName}
                    onChange={(event) => updateForm("brandName", event.target.value)}
                    className={`${inputClassName} pl-9`}
                    placeholder="输入品牌后自动搜索"
                  />
                  {brandSearchLoading ? (
                    <Loader2 className="absolute right-3 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-[#595959]" />
                  ) : null}
                  {brandOptions.length > 0 ? (
                    <div className="absolute left-0 right-0 top-[44px] z-30 max-h-64 overflow-y-auto rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] shadow-sm">
                      {brandOptions.map((brand) => (
                        <button
                          key={brand.id}
                          type="button"
                          onClick={() => selectBrand(brand)}
                          className="flex w-full items-center justify-between gap-3 border-b border-[#EBEBEB] px-3 py-2 text-left text-sm last:border-b-0 hover:bg-[#FAFAFA]"
                        >
                          <span className="font-medium text-[#000000]">{brand.brand_name}</span>
                          <span className="text-xs text-[#595959]">{brand.brand_id}</span>
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
                {brandSearchError ? <InlineError message={brandSearchError} /> : null}
              </Field>
              <Field label="品牌 ID">
                <input
                  value={form.brandId}
                  onChange={(event) => updateForm("brandId", event.target.value)}
                  className={inputClassName}
                  placeholder="选择品牌后回填"
                />
              </Field>
            </div>
          </FormBlock>

          <FormBlock title="商品内容">
            <div className="grid gap-3 xl:grid-cols-2">
              <Field label="商品标题" required>
                <input
                  value={form.title}
                  onChange={(event) => updateForm("title", event.target.value)}
                  className={inputClassName}
                  maxLength={255}
                />
              </Field>
              <Field label="商品副标题">
                <input
                  value={form.subtitle}
                  onChange={(event) => updateForm("subtitle", event.target.value)}
                  className={inputClassName}
                  maxLength={255}
                />
              </Field>
            </div>
            <div className="mt-3 grid gap-3 xl:grid-cols-2">
              <Field label="商品描述" required>
                <textarea
                  value={form.description}
                  onChange={(event) => updateForm("description", event.target.value)}
                  className={`${textareaClassName} min-h-36`}
                />
              </Field>
              <Field label="包装清单" required>
                <textarea
                  value={form.whatsInTheBox}
                  onChange={(event) => updateForm("whatsInTheBox", event.target.value)}
                  className={`${textareaClassName} min-h-36`}
                  placeholder="逐行填写包装清单"
                />
              </Field>
            </div>
          </FormBlock>

          <FormBlock title="价格、库存和尺寸">
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Field label="售价" required>
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.sellingPrice}
                  onChange={(event) => updateForm("sellingPrice", event.target.value)}
                  className={inputClassName}
                  placeholder="R"
                />
              </Field>
              <Field label="建议零售价">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={form.rrp}
                  onChange={(event) => updateForm("rrp", event.target.value)}
                  className={inputClassName}
                  placeholder="R"
                />
              </Field>
              <Field label="库存数量" required>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.stockQuantity}
                  onChange={(event) => updateForm("stockQuantity", event.target.value)}
                  className={inputClassName}
                />
              </Field>
              <Field label="备货期" required>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.minimumLeadtimeDays}
                  onChange={(event) => updateForm("minimumLeadtimeDays", event.target.value)}
                  className={inputClassName}
                />
              </Field>
            </div>
            <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Field label="长度" required>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={form.lengthCm}
                  onChange={(event) => updateForm("lengthCm", event.target.value)}
                  className={inputClassName}
                />
              </Field>
              <Field label="宽度" required>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={form.widthCm}
                  onChange={(event) => updateForm("widthCm", event.target.value)}
                  className={inputClassName}
                />
              </Field>
              <Field label="高度" required>
                <input
                  type="number"
                  min="0"
                  step="0.1"
                  value={form.heightCm}
                  onChange={(event) => updateForm("heightCm", event.target.value)}
                  className={inputClassName}
                />
              </Field>
              <Field label="重量" required>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={form.weightG}
                  onChange={(event) => updateForm("weightG", event.target.value)}
                  className={inputClassName}
                />
              </Field>
            </div>
          </FormBlock>

          <FormBlock title="图片">
            <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_260px]">
              <Field label="图片链接">
                <textarea
                  value={imageUrlsText}
                  onChange={(event) => {
                    setImageUrlsText(event.target.value);
                    setImageCheck(null);
                  }}
                  className={`${textareaClassName} min-h-32`}
                  placeholder="每行一个公网图片 URL"
                />
              </Field>
              <div className="space-y-3">
                <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2">
                  <div className="text-xs text-[#595959]">图片数量</div>
                  <div className="mt-1 text-sm font-medium text-[#000000]">
                    {imageCount} / {minRequiredImages || "--"}
                  </div>
                  {minRequiredImages > 0 && imageCount < minRequiredImages ? (
                    <div className="mt-1 text-xs leading-5 text-[#92400E]">
                      当前类目还差 {minRequiredImages - imageCount} 张图片
                    </div>
                  ) : null}
                </div>
                {requirements?.image_requirement_texts?.length ? (
                  <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2 text-xs leading-5 text-[#595959]">
                    {requirements.image_requirement_texts.slice(0, 3).map((text) => (
                      <div key={text}>{text}</div>
                    ))}
                  </div>
                ) : null}
                <label className="inline-flex h-10 w-full cursor-pointer items-center justify-center gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm font-medium text-[#000000] hover:bg-[#FAFAFA]">
                  {busyAction === "upload-images" ? (
                    <Loader2 className="h-4 w-4 animate-spin stroke-[1.8]" />
                  ) : (
                    <Upload className="h-4 w-4 stroke-[1.8]" />
                  )}
                  上传图片
                  <input
                    type="file"
                    accept="image/*"
                    multiple
                    className="hidden"
                    onChange={(event) => void uploadImages(event)}
                    disabled={busyAction === "upload-images"}
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <ActionButton
                    icon={ImageIcon}
                    loading={busyAction === "validate-images"}
                    disabled={imageUrls.length === 0}
                    onClick={() => void validateImageUrls()}
                  >
                    校验 URL
                  </ActionButton>
                  <ActionButton
                    icon={ClipboardCheck}
                    loading={busyAction === "check-images"}
                    disabled={!categoryId || imageCount === 0}
                    onClick={() => void checkImageRequirements()}
                  >
                    检查数量
                  </ActionButton>
                </div>
              </div>
            </div>

            {imageError ? <InlineError message={imageError} /> : null}

            {uploadedAssets.length > 0 ? (
              <div className="mt-4 overflow-hidden rounded-[6px] border border-[#EBEBEB]">
                <div className="border-b border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2 text-xs font-medium text-[#595959]">
                  已上传图片
                </div>
                <div className="divide-y divide-[#EBEBEB]">
                  {uploadedAssets.map((asset) => (
                    <div
                      key={asset.id ?? `${asset.file_name}-${asset.storage_path}`}
                      className="grid gap-2 px-3 py-2 text-sm md:grid-cols-[minmax(0,1fr)_auto]"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium text-[#000000]">
                          {asset.original_file_name ?? asset.file_name ?? asset.id ?? "image"}
                        </div>
                        <div className="mt-1 truncate text-xs text-[#595959]">
                          {asset.public_url ?? asset.storage_path ?? asset.external_url ?? "--"}
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => removeUploadedAsset(asset.id)}
                        className="inline-flex h-8 items-center justify-center gap-1 rounded-[6px] border border-[#EBEBEB] px-2 text-xs text-[#595959] hover:text-[#D9363E]"
                      >
                        <X className="h-3.5 w-3.5 stroke-[1.8]" />
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </FormBlock>

          <FormBlock title="类目属性">
            {attributeSpecs.length === 0 ? (
              <EmptyLine text="套用类目后会在这里显示必填属性和选填属性。" />
            ) : (
              <CategoryAttributeEditor
                requirements={requirements}
                requiredAttributes={requiredAttributeSpecs}
                optionalAttributes={optionalAttributeSpecs}
                dynamicAttributes={dynamicAttributes}
                optionalOpen={optionalAttributesOpen}
                onToggleOptional={() => setOptionalAttributesOpen((current) => !current)}
                onChange={updateDynamicAttribute}
              />
            )}

            <div className="mt-4 border-t border-[#EBEBEB] pt-4">
              <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-end">
                <Field label="新增类目属性">
                  <input
                    value={customAttributeKey}
                    onChange={(event) => setCustomAttributeKey(event.target.value)}
                    className={inputClassName}
                    placeholder="例如 材质 / material"
                  />
                </Field>
                <button
                  type="button"
                  onClick={addCustomAttribute}
                  className="h-10 rounded-[6px] border border-[#EBEBEB] px-3 text-sm font-medium text-[#000000] hover:bg-[#FAFAFA]"
                >
                  添加
                </button>
              </div>

              {customAttributes.length > 0 ? (
                <div className="divide-y divide-[#EBEBEB] rounded-[6px] border border-[#EBEBEB]">
                  {customAttributes.map((attribute) => (
                    <div
                      key={attribute.key}
                      className="grid gap-2 px-3 py-2 md:grid-cols-[180px_minmax(0,1fr)_auto]"
                    >
                      <div className="truncate text-sm font-medium text-[#000000]">{attribute.key}</div>
                      <input
                        value={attributeInputValue(attribute.value)}
                        onChange={(event) => updateDynamicAttribute(attribute.key, event.target.value)}
                        className={inputClassName}
                      />
                      <button
                        type="button"
                        onClick={() => removeCustomAttribute(attribute.key)}
                        className="inline-flex h-10 items-center justify-center rounded-[6px] border border-[#EBEBEB] px-3 text-sm text-[#595959] hover:text-[#D9363E]"
                      >
                        移除
                      </button>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          </FormBlock>

          <FormBlock title="表单检查" last>
            <CollapsibleIssueList
              issues={localIssues}
              open={formCheckOpen}
              onToggle={() => setFormCheckOpen((current) => !current)}
              emptyText="当前表单检查未发现阻塞项。仍建议运行上架表预检。"
            />
          </FormBlock>
        </main>

        <aside className="space-y-4 2xl:sticky 2xl:top-[70px] 2xl:self-start">
          <Panel title="类目要求" icon={ClipboardCheck}>
            {busyAction === "requirements" ? <LoadingLine text="正在读取类目要求" /> : null}
            {requirements ? (
              <CategoryRequirementMatrix
                requirements={requirements}
                imageCount={imageCount}
                requiredAttributes={requiredAttributeSpecs}
                optionalAttributes={optionalAttributeSpecs}
              />
            ) : (
              <EmptyLine text="请先套用 Takealot 末级类目。" />
            )}
          </Panel>

          <Panel title="图片校验" icon={ImageIcon}>
            <div className="mb-3 grid grid-cols-3 gap-2 text-center">
              <Metric label="图片" value={`${imageCount}/${minRequiredImages || "--"}`} />
              <Metric label="有效 URL" value={validatedImages.length ? String(validImageCount) : "--"} />
              <Metric label="异常 URL" value={validatedImages.length ? String(invalidImageCount) : "--"} />
            </div>
            {imageUrls.some((url) => !isPublicHttpUrl(url)) ? (
              <div className="mb-3 rounded-[6px] border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2 text-xs leading-5 text-[#92400E]">
                检测到不是公网 http(s) 的图片 URL，提交前建议替换。
              </div>
            ) : null}
            {validatedImages.length > 0 ? (
              <ImageValidationRows results={validatedImages} />
            ) : (
              <EmptyLine text="可以先校验 URL，再检查是否满足类目图片要求。" />
            )}
            {imageCheck ? (
              <div className="mt-3 space-y-2 text-sm">
                <StatusPill tone={imageCheck.passed ? "success" : "warning"}>
                  {imageCheck.passed ? "已满足图片要求" : `还差 ${imageCheck.missing_count} 张`}
                </StatusPill>
                <KeyValue label="有效图片" value={`${imageCheck.current_count} / ${imageCheck.required_count}`} />
                <MessageList messages={imageCheck.warnings ?? []} />
              </div>
            ) : null}
          </Panel>

          <Panel title="AI 生成" icon={Bot}>
            {aiResult ? (
              <div className="space-y-3 text-sm">
                <div className="flex flex-wrap gap-2">
                  <StatusPill tone={aiResult.ai_used ? "success" : "muted"}>
                    {aiResult.ai_used ? "已使用 AI" : "未使用 AI"}
                  </StatusPill>
                  <StatusPill tone={aiResult.fallback_used ? "warning" : "success"}>
                    {aiResult.fallback_used ? "使用兜底规则" : "无兜底"}
                  </StatusPill>
                </div>
                <KeyValue label="类目路径" value={aiResult.category_path_zh || "--"} />
                <MessageList messages={aiResult.warnings ?? []} />
              </div>
            ) : (
              <EmptyLine text="选择类目后可让 AI 回填标题、描述、尺寸和动态属性。" />
            )}
          </Panel>

          <Panel title="上架表预检" icon={FileSpreadsheet}>
            {preview ? (
              <div className="space-y-3">
                <div className="text-xs leading-5 text-[#595959]">
                  提交前检查类目、图片、必填字段和上架表文件是否完整。
                </div>
                <div className="grid grid-cols-3 gap-2 text-center">
                  <Metric label="是否通过" value={preview.valid ? "通过" : "未通过"} />
                  <Metric label="错误" value={String(previewErrorCount)} />
                  <Metric label="提醒" value={String(previewWarningCount)} />
                </div>
                <IssueList
                  issues={previewIssues}
                  emptyText="预检未返回问题清单。"
                />
                <TokenList
                  label="缺失必填项"
                  values={(preview.missing_required_fields ?? []).map(displayFieldLabel)}
                />
                <TokenList
                  label="已生成字段"
                  values={Object.keys(preview.generated_fields ?? {}).map(displayFieldLabel)}
                />
                <MessageList messages={preview.warnings ?? []} />
                {preview.loadsheet_asset ? <AssetView asset={preview.loadsheet_asset} /> : null}
              </div>
            ) : (
              <EmptyLine text="提交前检查类目、图片、必填字段和上架表文件是否完整。" />
            )}
          </Panel>

          <Panel title="提交记录" icon={PackagePlus}>
            {submissionResult ? (
              <div className="mb-3 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2 text-sm">
                <div className="font-medium text-[#000000]">{submissionResult.message}</div>
                <div className="mt-1 space-y-0.5 text-xs text-[#595959]">
                  <div>提交 ID：{submissionResult.submission_id ?? "--"}</div>
                  <div>任务 ID：{submissionResult.task_id ?? "--"}</div>
                </div>
                <div className="mt-2 flex flex-wrap gap-2">
                  <StatusPill tone={statusTone(submissionResult.status)}>
                    {formatStatusLabel(submissionResult.status)}
                  </StatusPill>
                  <StatusPill tone="muted">{formatStatusLabel(submissionResult.stage)}</StatusPill>
                </div>
              </div>
            ) : null}
            <div className="mb-3 flex items-center justify-between">
              <span className="text-xs text-[#595959]">
                {isLoadingSubmissions ? "加载中..." : `最近 ${submissions.length} 条`}
              </span>
              <button
                type="button"
                onClick={() => selectedStoreId && void loadSubmissions(selectedStoreId)}
                disabled={!selectedStoreId || isLoadingSubmissions}
                className="inline-flex h-8 items-center gap-1 rounded-[6px] border border-[#EBEBEB] px-2 text-xs text-[#595959] hover:text-[#000000] disabled:cursor-not-allowed disabled:text-[#B3B3B3]"
              >
                <RefreshCcw className="h-3.5 w-3.5 stroke-[1.8]" />
                刷新
              </button>
            </div>
            {submissionsError ? <InlineError message={submissionsError} /> : null}
            {submissions.length > 0 ? (
              <div className="divide-y divide-[#EBEBEB] border-y border-[#EBEBEB]">
                {submissions.map((submission) => (
                  <button
                    key={submission.submission_id}
                    type="button"
                    onClick={() => void openSubmissionDetail(submission.submission_id)}
                    className={[
                      "block w-full px-1 py-3 text-left text-sm hover:bg-[#FAFAFA]",
                      selectedSubmissionId === submission.submission_id ? "bg-[#FAFAFA]" : "",
                    ].join(" ")}
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <div className="line-clamp-1 font-medium text-[#000000]">{submission.title || "--"}</div>
                        <div className="mt-1 text-xs text-[#595959]">
                          SKU：{submission.sku || "--"} / {formatDateTime(submission.created_at)}
                        </div>
                      </div>
                      <StatusPill tone={statusTone(submission.status)}>
                        {formatStatusLabel(submission.status)}
                      </StatusPill>
                    </div>
                  </button>
                ))}
              </div>
            ) : !isLoadingSubmissions ? (
              <EmptyLine text="暂无提交记录。" />
            ) : null}
            {busyAction === "submission-detail" ? <LoadingLine text="正在加载提交详情" /> : null}
            {submissionDetail ? (
              <SubmissionDetailView detail={submissionDetail} />
            ) : null}
          </Panel>
        </aside>
      </section>
    </div>
  );
}

function WorkflowSummary({
  storeName,
  categoryId,
  imageCount,
  minRequiredImages,
  localErrorCount,
  localWarningCount,
  preview,
  previewErrorCount,
  previewWarningCount,
  submissionResult,
}: {
  storeName: string;
  categoryId: number | null;
  imageCount: number;
  minRequiredImages: number;
  localErrorCount: number;
  localWarningCount: number;
  preview: LoadsheetPreviewResponse | null;
  previewErrorCount: number;
  previewWarningCount: number;
  submissionResult: SubmissionCreateResponse | null;
}) {
  const imageReady = minRequiredImages > 0 ? imageCount >= minRequiredImages : imageCount > 0;
  const validationReady = localErrorCount === 0;
  const previewReady = Boolean(preview?.valid);

  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
      <SummaryCard
        label="店铺"
        value={storeName || "未选择"}
        tone={storeName ? "success" : "muted"}
        detail={storeName ? "已绑定提交目标" : "先选择店铺"}
      />
      <SummaryCard
        label="类目"
        value={categoryId ? String(categoryId) : "未套用"}
        tone={categoryId ? "success" : "muted"}
        detail={categoryId ? "类目要求可读取" : "等待匹配"}
      />
      <SummaryCard
        label="图片"
        value={`${imageCount}/${minRequiredImages || "--"}`}
        tone={imageReady ? "success" : "warning"}
        detail={minRequiredImages ? "按类目最小图片数检查" : "等待类目要求"}
      />
      <SummaryCard
        label="校验"
        value={validationReady ? "可预检" : `${localErrorCount} 项待修复`}
        tone={validationReady ? "success" : "danger"}
        detail={localWarningCount ? `${localWarningCount} 项提醒` : "前端必填项"}
      />
      <SummaryCard
        label="上架表"
        value={preview ? (preview.valid ? "通过" : "未通过") : "未预检"}
        tone={previewReady ? "success" : preview ? "danger" : "muted"}
        detail={
          preview
            ? `${previewErrorCount} 个错误 / ${previewWarningCount} 个提醒`
            : formatStatusLabel(submissionResult?.status) || "提交前建议预检"
        }
      />
    </section>
  );
}

function SummaryCard({
  label,
  value,
  detail,
  tone,
}: {
  label: string;
  value: string;
  detail: string;
  tone: "success" | "warning" | "danger" | "muted";
}) {
  const dotClass =
    tone === "success"
      ? "bg-[#22C55E]"
      : tone === "warning"
        ? "bg-[#D9A441]"
        : tone === "danger"
          ? "bg-[#D9363E]"
          : "bg-[#B8B8B8]";

  return (
    <article className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3">
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs text-[#595959]">{label}</span>
        <span className={`h-2 w-2 rounded-full ${dotClass}`} />
      </div>
      <div className="mt-2 truncate text-sm font-semibold text-[#000000]">{value}</div>
      <div className="mt-1 truncate text-xs text-[#595959]">{detail}</div>
    </article>
  );
}

function ActionButton({
  icon: Icon,
  children,
  loading = false,
  disabled = false,
  variant = "secondary",
  onClick,
}: {
  icon: LucideIcon;
  children: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  variant?: "primary" | "secondary";
  onClick: () => void;
}) {
  const isDisabled = disabled || loading;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={isDisabled}
      className={[
        "inline-flex h-10 items-center justify-center gap-2 rounded-[6px] border px-3 text-sm font-medium outline-none focus-visible:border-[#000000]",
        variant === "primary" && !isDisabled
          ? "border-[#000000] bg-[#000000] text-[#FFFFFF] hover:bg-[#1F1F1F]"
          : "",
        variant === "secondary" && !isDisabled
          ? "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000] hover:bg-[#FAFAFA]"
          : "",
        isDisabled ? "cursor-not-allowed border-[#EBEBEB] bg-[#FAFAFA] text-[#B3B3B3]" : "",
      ].join(" ")}
    >
      {loading ? (
        <Loader2 className="h-4 w-4 animate-spin stroke-[1.8]" />
      ) : (
        <Icon className="h-4 w-4 stroke-[1.8]" />
      )}
      <span>{children}</span>
    </button>
  );
}

function Field({
  label,
  required = false,
  children,
}: {
  label: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="grid min-w-0 gap-1.5">
      <span className="flex min-h-6 items-center text-xs font-medium leading-5 text-[#595959]">
        {label}
        {required ? <span className="ml-1 text-[#D9363E]">*</span> : null}
      </span>
      {children}
    </label>
  );
}

function FormBlock({
  title,
  children,
  last = false,
}: {
  title: string;
  children: ReactNode;
  last?: boolean;
}) {
  return (
    <section className={["p-4", last ? "" : "border-b border-[#EBEBEB]"].join(" ")}>
      <div className="mb-4 text-sm font-semibold text-[#000000]">{title}</div>
      {children}
    </section>
  );
}

function Panel({
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
      <div className="flex items-center gap-2 border-b border-[#EBEBEB] px-4 py-3 text-sm font-semibold text-[#000000]">
        <Icon className="h-4 w-4 text-[#595959] stroke-[1.8]" />
        {title}
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function SelectedCategorySummary({
  requirements,
  suggestion,
  imageCount,
  requiredAttributes,
  optionalAttributes,
}: {
  requirements: CategoryRequirements | null;
  suggestion: CategoryMatchSuggestion | null;
  imageCount: number;
  requiredAttributes: AttributeSpec[];
  optionalAttributes: AttributeSpec[];
}) {
  const categoryId = requirements?.category_id ?? suggestion?.category_id;
  if (!categoryId) return null;

  const pathZh = requirements?.path_zh || suggestion?.path_zh || requirements?.lowest_category_raw || "";
  const pathEn = requirements?.path_en || suggestion?.path_en || suggestion?.lowest_category_raw || "";
  const minImages = requirements?.min_required_images ?? suggestion?.min_required_images ?? 0;
  const missingImages = Math.max(0, minImages - imageCount);
  const requiredCount = requiredAttributes.length || (suggestion?.required_attributes ?? []).length;
  const optionalCount = optionalAttributes.length || (suggestion?.optional_attributes ?? []).length;
  const attributesReady = requirements?.attributes_ready ?? suggestion?.attributes_ready ?? false;

  return (
    <div className="mt-4 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] p-3">
      <div className="mb-3 flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[#000000]">已套用类目要求</div>
          <div className="mt-1 text-xs leading-5 text-[#595959]">
            类目匹配成功后，下面的图片限制、必填项和选填项会跟随当前类目刷新。
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill tone="success">类目 ID {categoryId}</StatusPill>
          <StatusPill tone={attributesReady ? "success" : "warning"}>
            {attributesReady ? "属性模板已同步" : "属性模板待同步"}
          </StatusPill>
        </div>
      </div>

      <div className="grid gap-2 lg:grid-cols-2">
        <SummaryCell label="中文类目">{pathZh || "--"}</SummaryCell>
        <SummaryCell label="英文类目">{pathEn || "--"}</SummaryCell>
        <SummaryCell label="图片限制">
          <div className="flex flex-wrap items-center gap-2">
            <span>至少 {minImages || "--"} 张图</span>
            <StatusPill tone={missingImages ? "warning" : "success"}>
              {missingImages ? `还差 ${missingImages} 张` : "已满足"}
            </StatusPill>
          </div>
        </SummaryCell>
        <SummaryCell label="属性字段">
          <div className="flex flex-wrap gap-2">
            <StatusPill tone={requiredCount ? "danger" : "muted"}>{requiredCount} 个必填项</StatusPill>
            <StatusPill tone="muted">{optionalCount} 个选填项</StatusPill>
          </div>
        </SummaryCell>
      </div>
    </div>
  );
}

function SummaryCell({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 py-2">
      <div className="text-xs font-medium text-[#595959]">{label}</div>
      <div className="min-h-6 break-words text-sm leading-6 text-[#000000]">{children}</div>
    </div>
  );
}

function CategorySuggestionRow({
  suggestion,
  active,
  onApply,
}: {
  suggestion: CategoryMatchSuggestion;
  active: boolean;
  onApply: () => void;
}) {
  const confidencePercent = Math.max(0, Math.min(100, Math.round((suggestion.confidence > 1 ? suggestion.confidence : suggestion.confidence * 100))));

  return (
    <div
      className={[
        "rounded-[6px] border p-3",
        active ? "border-[#000000] bg-[#FAFAFA]" : "border-[#EBEBEB] bg-[#FFFFFF]",
      ].join(" ")}
    >
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="line-clamp-2 text-sm font-medium leading-5 text-[#000000]">
            {suggestion.path_zh || suggestion.path_en}
          </div>
          <div className="mt-1 line-clamp-2 text-xs leading-5 text-[#595959]">
            {suggestion.path_en || "英文类目待同步"}
          </div>
        </div>
        <button
          type="button"
          onClick={onApply}
          className={[
            "h-8 rounded-[6px] border px-2.5 text-xs font-medium",
            active
              ? "border-[#000000] bg-[#000000] text-[#FFFFFF]"
              : "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000] hover:bg-[#FAFAFA]",
          ].join(" ")}
        >
          {active ? "已套用" : "套用"}
        </button>
      </div>
      <div className="mb-2 grid grid-cols-[70px_minmax(0,1fr)_42px] items-center gap-2 text-xs text-[#595959]">
        <span>匹配度</span>
        <span className="h-1.5 overflow-hidden rounded-full bg-[#EBEBEB]">
          <span
            className={[
              "block h-full rounded-full",
              confidenceTone(suggestion.confidence) === "success"
                ? "bg-[#22C55E]"
                : confidenceTone(suggestion.confidence) === "warning"
                  ? "bg-[#D9A441]"
                  : "bg-[#B8B8B8]",
            ].join(" ")}
            style={{ width: `${confidencePercent}%` }}
          />
        </span>
        <span className="text-right font-medium text-[#000000]">{formatPercent(suggestion.confidence)}</span>
      </div>
      <div className="flex flex-wrap gap-2 text-xs text-[#595959]">
        <StatusPill>类目 ID：{suggestion.category_id}</StatusPill>
        <StatusPill tone="muted">最少图片数：{suggestion.min_required_images}</StatusPill>
        <StatusPill tone={(suggestion.required_attributes ?? []).length ? "danger" : "muted"}>
          必填项：{(suggestion.required_attributes ?? []).length}
        </StatusPill>
        <StatusPill tone="muted">选填项：{(suggestion.optional_attributes ?? []).length}</StatusPill>
        <StatusPill tone={suggestion.attributes_ready ? "success" : "warning"}>
          {suggestion.attributes_ready ? "属性模板已同步" : "属性模板待同步"}
        </StatusPill>
        {(suggestion.compliance_certificates ?? []).map((certificate) => (
          <StatusPill key={certificate} tone="warning">
            {certificate}
          </StatusPill>
        ))}
      </div>
      {suggestion.match_reasons?.length ? (
        <div className="mt-2 line-clamp-2 text-xs leading-5 text-[#595959]">
          {suggestion.match_reasons.join("；")}
        </div>
      ) : null}
    </div>
  );
}

function CategoryAttributeEditor({
  requirements,
  requiredAttributes,
  optionalAttributes,
  dynamicAttributes,
  optionalOpen,
  onToggleOptional,
  onChange,
}: {
  requirements: CategoryRequirements | null;
  requiredAttributes: AttributeSpec[];
  optionalAttributes: AttributeSpec[];
  dynamicAttributes: DynamicAttributeDraft[];
  optionalOpen: boolean;
  onToggleOptional: () => void;
  onChange: (key: string, value: string) => void;
}) {
  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
      <div className="flex flex-col gap-2 border-b border-[#EBEBEB] bg-[#FAFAFA] px-3 py-3 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-[#000000]">类目专属必填项</div>
          <div className="mt-1 line-clamp-1 text-xs text-[#595959]">
            官方类目：{requirements?.path_en || requirements?.lowest_category_raw || "--"}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <StatusPill tone={requiredAttributes.length ? "danger" : "muted"}>
            {requiredAttributes.length} 个必填项
          </StatusPill>
          <StatusPill tone="muted">{optionalAttributes.length} 个选填项</StatusPill>
        </div>
      </div>

      <div className="p-3">
        {requiredAttributes.length ? (
          <AttributeGrid
            title="必填项"
            attributes={requiredAttributes}
            dynamicAttributes={dynamicAttributes}
            onChange={onChange}
            tone="required"
          />
        ) : (
          <EmptyLine text="当前类目没有同步到必填属性。" />
        )}

        {optionalAttributes.length ? (
          <div className="mt-4 border-t border-[#EBEBEB] pt-3">
            <button
              type="button"
              onClick={onToggleOptional}
              className="flex w-full items-center justify-between gap-3 rounded-[6px] px-1 py-2 text-left text-sm font-medium text-[#000000] hover:bg-[#FAFAFA]"
            >
              <span>选填项（{optionalAttributes.length} 个，点击展开）</span>
              <ChevronDown
                className={[
                  "h-4 w-4 text-[#595959] transition-transform",
                  optionalOpen ? "rotate-180" : "",
                ].join(" ")}
              />
            </button>
            {optionalOpen ? (
              <div className="mt-2">
                <AttributeGrid
                  title="选填项"
                  attributes={optionalAttributes}
                  dynamicAttributes={dynamicAttributes}
                  onChange={onChange}
                  tone="optional"
                />
              </div>
            ) : (
              <div className="mt-2 flex flex-wrap gap-2">
                {optionalAttributes.slice(0, 12).map((attribute) => (
                  <StatusPill key={attribute.key} tone="muted">
                    {attribute.label}
                  </StatusPill>
                ))}
                {optionalAttributes.length > 12 ? (
                  <StatusPill tone="muted">+{optionalAttributes.length - 12}</StatusPill>
                ) : null}
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function AttributeGrid({
  title,
  attributes,
  dynamicAttributes,
  onChange,
  tone = "default",
}: {
  title: string;
  attributes: AttributeSpec[];
  dynamicAttributes: DynamicAttributeDraft[];
  onChange: (key: string, value: string) => void;
  tone?: "default" | "required" | "optional";
}) {
  if (attributes.length === 0) return null;
  const labelClass = tone === "required" ? "text-[#D9363E]" : tone === "optional" ? "text-[#595959]" : "text-[#000000]";
  const headerClass = tone === "required" ? "bg-[#FEF2F2]" : "bg-[#FAFAFA]";
  return (
    <section>
      <div className={`mb-2 flex items-center justify-between rounded-[6px] px-3 py-2 text-xs font-medium ${headerClass} ${labelClass}`}>
        <span>{title}</span>
        <span>{attributes.length} 项</span>
      </div>
      <div className="overflow-hidden rounded-[6px] border border-[#EBEBEB]">
        {attributes.map((attribute) => {
          const value = dynamicAttributes.find((item) => item.key === attribute.key)?.value;
          const inputValue = attributeInputValue(value);
          return (
            <div
              key={attribute.key}
              className="grid gap-2 border-b border-[#EBEBEB] px-3 py-3 last:border-b-0 md:grid-cols-[190px_minmax(0,1fr)] md:items-center"
            >
              <div className="min-w-0">
                <div className="flex items-start gap-1 text-sm font-medium leading-5 text-[#000000]">
                  <span className="break-words">{attribute.label}</span>
                  {attribute.required ? <span className="text-[#D9363E]">*</span> : null}
                </div>
                {attribute.key !== attribute.label ? (
                  <div className="mt-1 break-all text-xs leading-5 text-[#8C8C8C]">{attribute.key}</div>
                ) : null}
              </div>
              <AttributeControl attribute={attribute} inputValue={inputValue} onChange={onChange} />
            </div>
          );
        })}
      </div>
    </section>
  );
}

function AttributeControl({
  attribute,
  inputValue,
  onChange,
}: {
  attribute: AttributeSpec;
  inputValue: string;
  onChange: (key: string, value: string) => void;
}) {
  if (attribute.options.length > 0) {
    return (
      <select
        value={inputValue}
        onChange={(event) => onChange(attribute.key, event.target.value)}
        className={inputClassName}
      >
        <option value="">请选择</option>
        {attribute.options.map((option) => (
          <option key={`${attribute.key}-${option.value}`} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    );
  }

  if (isSwitchAttribute(attribute)) {
    return (
      <div className="inline-flex h-10 w-fit overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] text-sm">
        {["Yes", "No"].map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(attribute.key, option)}
            className={[
              "min-w-16 px-3 font-medium",
              inputValue === option ? "bg-[#000000] text-[#FFFFFF]" : "text-[#595959] hover:bg-[#FAFAFA]",
            ].join(" ")}
          >
            {option === "Yes" ? "是" : "否"}
          </button>
        ))}
      </div>
    );
  }

  if (isTextareaAttribute(attribute)) {
    return (
      <textarea
        value={inputValue}
        onChange={(event) => onChange(attribute.key, event.target.value)}
        className={textareaClassName}
        placeholder={attribute.placeholder || attribute.key}
      />
    );
  }

  return (
    <input
      type={isNumberAttribute(attribute) ? "number" : "text"}
      min={isNumberAttribute(attribute) ? "0" : undefined}
      step={isNumberAttribute(attribute) ? attributeStep(attribute) : undefined}
      value={inputValue}
      onChange={(event) => onChange(attribute.key, event.target.value)}
      className={inputClassName}
      placeholder={attribute.placeholder || attribute.key}
    />
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-2 py-2">
      <div className="text-xs text-[#595959]">{label}</div>
      <div className="mt-1 text-sm font-semibold text-[#000000]">{value}</div>
    </div>
  );
}

function ImageValidationRows({ results }: { results: ImageUrlValidateResponse[] }) {
  return (
    <div className="divide-y divide-[#EBEBEB] overflow-hidden rounded-[6px] border border-[#EBEBEB]">
      {results.map((result) => {
        const errors = result.errors ?? [];
        const warnings = result.warnings ?? [];
        return (
          <div key={result.image_url} className="px-3 py-2 text-xs">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="truncate font-medium text-[#000000]" title={result.image_url}>
                  {result.image_url}
                </div>
                <div className="mt-1 flex flex-wrap gap-2 text-[#595959]">
                  {result.content_type ? <span>{result.content_type}</span> : null}
                  {result.size_bytes ? <span>{formatFileSize(result.size_bytes)}</span> : null}
                  {!result.content_type && !result.size_bytes ? <span>未返回文件信息</span> : null}
                </div>
              </div>
              <StatusPill tone={result.valid ? "success" : "danger"}>
                {result.valid ? "有效" : "异常"}
              </StatusPill>
            </div>
            {errors.length || warnings.length ? (
              <div className="mt-2 space-y-1 leading-5 text-[#595959]">
                {errors.map((message) => (
                  <div key={`error-${message}`}>
                    <span className="font-medium text-[#B91C1C]">错误：</span>
                    {localizeBackendMessage(message)}
                  </div>
                ))}
                {warnings.map((message) => (
                  <div key={`warning-${message}`}>
                    <span className="font-medium text-[#92400E]">提醒：</span>
                    {localizeBackendMessage(message)}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function StatusPill({
  children,
  tone = "default",
}: {
  children: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "muted";
}) {
  const className =
    tone === "success"
      ? "border-[#BBF7D0] bg-[#F0FDF4] text-[#166534]"
      : tone === "warning"
        ? "border-[#FDE68A] bg-[#FFFBEB] text-[#92400E]"
        : tone === "danger"
          ? "border-[#FECACA] bg-[#FEF2F2] text-[#B91C1C]"
          : tone === "muted"
            ? "border-[#EBEBEB] bg-[#FAFAFA] text-[#595959]"
            : "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000]";
  return (
    <span className={`inline-flex min-h-6 items-center rounded-[6px] border px-2 text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}

function ErrorBanner({ message }: { message: string }) {
  return (
    <div className="flex items-start gap-2 rounded-[6px] border border-[#FECACA] bg-[#FEF2F2] px-4 py-3 text-sm text-[#B91C1C]">
      <AlertCircle className="mt-0.5 h-4 w-4 flex-none stroke-[1.8]" />
      <span>{message}</span>
    </div>
  );
}

function InlineError({ message }: { message: string }) {
  return <div className="mt-2 text-xs leading-5 text-[#D9363E]">{localizeBackendMessage(message)}</div>;
}

function EmptyLine({ text }: { text: string }) {
  return <div className="py-6 text-center text-sm text-[#595959]">{text}</div>;
}

function LoadingLine({ text }: { text: string }) {
  return (
    <div className="inline-flex h-9 items-center gap-2 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#595959]">
      <Loader2 className="h-4 w-4 animate-spin stroke-[1.8]" />
      {text}
    </div>
  );
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="grid grid-cols-[132px_minmax(0,1fr)] gap-3 border-b border-[#EBEBEB] py-2 text-sm last:border-b-0">
      <div className="text-xs text-[#595959]">{label}</div>
      <div className="min-w-0 break-words text-[#000000]">{value}</div>
    </div>
  );
}

function TokenList({ label, values }: { label: string; values: string[] }) {
  return (
    <div className="border-b border-[#EBEBEB] py-2 last:border-b-0">
      <div className="mb-2 text-xs text-[#595959]">{label}</div>
      {values.length ? (
        <div className="flex flex-wrap gap-2">
          {values.map((value) => (
            <StatusPill key={value} tone="muted">
              {value}
            </StatusPill>
          ))}
        </div>
      ) : (
        <span className="text-sm text-[#595959]">--</span>
      )}
    </div>
  );
}

function CategoryRequirementMatrix({
  requirements,
  imageCount,
  requiredAttributes,
  optionalAttributes,
}: {
  requirements: CategoryRequirements;
  imageCount: number;
  requiredAttributes: AttributeSpec[];
  optionalAttributes: AttributeSpec[];
}) {
  const certificateValues =
    requirements.compliance_certificates?.length ? requirements.compliance_certificates : ["无额外证书要求"];
  const missingImages = Math.max(0, requirements.min_required_images - imageCount);

  return (
    <div className="space-y-3 text-sm">
      <div className="overflow-hidden rounded-[6px] border border-[#EBEBEB]">
        <RequirementRow label="末级类目">
          {requirements.lowest_category_raw || `${requirements.lowest_category_name} (${requirements.category_id})`}
        </RequirementRow>
        <RequirementRow label="类目路径">{requirements.path_en || "--"}</RequirementRow>
        <RequirementRow label="中文路径">{requirements.path_zh || "--"}</RequirementRow>
        <RequirementRow label="最少图片数">
          <div className="flex flex-wrap items-center gap-2">
            <span>{requirements.min_required_images}</span>
            <StatusPill tone={missingImages ? "warning" : "success"}>
              {missingImages ? `还差 ${missingImages} 张` : "已满足"}
            </StatusPill>
          </div>
        </RequirementRow>
        <RequirementRow label="合规证书">
          <TagWrap values={certificateValues} tone="warning" />
        </RequirementRow>
        <RequirementRow label="必填项">
          <TagWrap values={requiredAttributes.map((attribute) => attribute.label)} tone="danger" emptyText="无必填项" />
        </RequirementRow>
        <RequirementRow label="选填项">
          <TagWrap values={optionalAttributes.map((attribute) => attribute.label)} tone="muted" emptyText="无选填项" />
        </RequirementRow>
      </div>
      <TokenList label="图片要求" values={requirements.image_requirement_texts ?? []} />
      <div className="flex flex-wrap gap-2">
        <StatusPill tone={requirements.attributes_ready ? "success" : "warning"}>
          {requirements.attributes_ready ? "属性模板已同步" : "属性模板待同步"}
        </StatusPill>
        <StatusPill tone="muted">类目 ID {requirements.category_id}</StatusPill>
      </div>
      {!requirements.attributes_ready && requirements.attribute_message ? (
        <InlineError message={requirements.attribute_message} />
      ) : null}
    </div>
  );
}

function RequirementRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[112px_minmax(0,1fr)] border-b border-[#EBEBEB] last:border-b-0">
      <div className="bg-[#F5F7FA] px-3 py-3 text-sm font-semibold leading-5 text-[#595959]">
        {label}
      </div>
      <div className="min-w-0 px-3 py-3 text-sm leading-6 text-[#000000]">{children}</div>
    </div>
  );
}

function TagWrap({
  values,
  tone,
  emptyText = "--",
}: {
  values: string[];
  tone: "warning" | "danger" | "muted";
  emptyText?: string;
}) {
  const cleanValues = values.map((value) => value.trim()).filter(Boolean);
  if (!cleanValues.length) return <span className="text-[#595959]">{emptyText}</span>;
  return (
    <div className="flex flex-wrap gap-2">
      {cleanValues.map((value) => (
        <StatusPill key={value} tone={tone}>
          {value}
        </StatusPill>
      ))}
    </div>
  );
}

function MessageList({ messages, label = "提醒" }: { messages: string[]; label?: string }) {
  if (messages.length === 0) return null;
  return (
    <div className="rounded-[6px] border border-[#FDE68A] bg-[#FFFBEB] px-3 py-2">
      <div className="mb-1 text-xs font-medium text-[#92400E]">{label}</div>
      <div className="space-y-1 text-xs leading-5 text-[#92400E]">
        {messages.map((message) => (
          <div key={message}>{localizeBackendMessage(message)}</div>
        ))}
      </div>
    </div>
  );
}

function CollapsibleIssueList({
  issues,
  open,
  onToggle,
  emptyText,
}: {
  issues: UiIssue[];
  open: boolean;
  onToggle: () => void;
  emptyText: string;
}) {
  const hasIssues = issues.length > 0;

  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA]">
      <button
        type="button"
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left"
      >
        <span className="min-w-0">
          <span className="block text-sm font-medium text-[#000000]">{formatIssueSummary(issues)}</span>
          <span className="mt-0.5 block text-xs text-[#595959]">
            详细问题默认收起，提交或预检被阻止时会自动展开。
          </span>
        </span>
        <span className="inline-flex h-8 items-center rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-2 text-xs font-medium text-[#000000]">
          {open ? "收起" : hasIssues ? "展开查看" : "查看"}
        </span>
      </button>
      {open ? (
        <div className="border-t border-[#EBEBEB] bg-[#FFFFFF] p-3">
          <IssueList issues={issues} emptyText={emptyText} />
        </div>
      ) : null}
    </div>
  );
}

function IssueList({ issues, emptyText }: { issues: UiIssue[]; emptyText: string }) {
  if (issues.length === 0) {
    return (
      <div className="flex items-center gap-2 rounded-[6px] border border-[#BBF7D0] bg-[#F0FDF4] px-3 py-2 text-sm text-[#166534]">
        <CheckCircle2 className="h-4 w-4 stroke-[1.8]" />
        {emptyText}
      </div>
    );
  }

  return (
    <div className="divide-y divide-[#EBEBEB] rounded-[6px] border border-[#EBEBEB]">
      {issues.map((issue) => (
        <div key={`${issue.field}-${issue.message}`} className="grid gap-1 px-3 py-2 text-sm">
          <div className="flex items-center justify-between gap-3">
            <span className="font-medium text-[#000000]">{displayFieldLabel(issue.field)}</span>
            <StatusPill tone={issue.level === "error" ? "danger" : "warning"}>
              {formatIssueLevel(issue.level)}
            </StatusPill>
          </div>
          <div className="text-xs leading-5 text-[#595959]">{localizeBackendMessage(issue.message)}</div>
        </div>
      ))}
    </div>
  );
}

function AssetView({ asset }: { asset: components["schemas"]["ListingLoadsheetAsset"] }) {
  return (
    <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-3 py-2 text-sm">
      <div className="font-medium text-[#000000]">上架表文件已生成</div>
      <div className="mt-1 break-words text-xs text-[#595959]">存储路径：{asset.storage_path ?? "--"}</div>
      {asset.public_url ? (
        <a
          href={asset.public_url}
          target="_blank"
          rel="noreferrer"
          className="mt-2 inline-flex text-xs font-medium text-[#000000] underline decoration-[#B8B8B8] decoration-dotted underline-offset-4"
        >
          打开文件链接
        </a>
      ) : null}
    </div>
  );
}

function SubmissionDetailView({ detail }: { detail: SubmissionDetail }) {
  return (
    <div className="mt-3 space-y-3 border-t border-[#EBEBEB] pt-3 text-sm">
      <div className="grid grid-cols-3 gap-2 text-center">
        <Metric label="状态" value={formatStatusLabel(detail.status)} />
        <Metric label="阶段" value={formatStatusLabel(detail.stage)} />
        <Metric label="审核" value={formatStatusLabel(detail.review_status)} />
      </div>
      <div className="space-y-1">
        <KeyValue label="提交 ID" value={detail.submission_id} />
        <KeyValue label="任务 ID" value={detail.task_id ?? "--"} />
        <KeyValue label="SKU" value={detail.sku || "--"} />
        <KeyValue label="类目" value={detail.category_path || String(detail.category_id)} />
        <KeyValue label="官方状态" value={formatStatusLabel(detail.official_status)} />
        <KeyValue label="更新时间" value={formatDateTime(detail.updated_at)} />
      </div>
      {detail.error_message ? <InlineError message={detail.error_message} /> : null}
      <IssueList
        issues={toUiIssues(detail.validation_issues ?? [])}
        emptyText="该提交没有校验问题。"
      />
      <MessageList messages={detail.warnings ?? []} />
      {detail.loadsheet_asset ? <AssetView asset={detail.loadsheet_asset} /> : null}
    </div>
  );
}

function collectLocalIssues({
  form,
  selectedStoreId,
  categoryId,
  imageUrls,
  assetIds,
  minRequiredImages,
  requiredAttributeSpecs,
  dynamicAttributes,
}: {
  form: ListingForm;
  selectedStoreId: string;
  categoryId: number | null;
  imageUrls: string[];
  assetIds: string[];
  minRequiredImages: number;
  requiredAttributeSpecs: AttributeSpec[];
  dynamicAttributes: DynamicAttributeDraft[];
}): UiIssue[] {
  const issues: UiIssue[] = [];
  const requireText = (field: keyof ListingForm, label: string) => {
    if (!form[field].trim()) {
      issues.push({ level: "error", field: label, message: "必填字段不能为空。" });
    }
  };

  if (!selectedStoreId) issues.push({ level: "error", field: "store_id", message: "请选择要提交的店铺。" });
  if (!categoryId) issues.push({ level: "error", field: "category_id", message: "请先匹配或填写有效类目 ID。" });
  requireText("sku", "sku");
  requireText("barcode", "barcode");
  requireText("title", "title");
  requireText("description", "description");
  requireText("whatsInTheBox", "whats_in_the_box");

  const sellingPrice = parseOptionalNumber(form.sellingPrice);
  const rrp = parseOptionalNumber(form.rrp);
  if (sellingPrice === null || sellingPrice <= 0) {
    issues.push({ level: "error", field: "selling_price", message: "售价必须大于 0。" });
  }
  if (rrp !== null && sellingPrice !== null && rrp < sellingPrice) {
    issues.push({ level: "warning", field: "rrp", message: "RRP 低于售价，请确认是否符合平台要求。" });
  }

  const stockQuantity = parseOptionalInteger(form.stockQuantity);
  if (stockQuantity === null || stockQuantity < 0) {
    issues.push({ level: "error", field: "stock_quantity", message: "库存必须是大于等于 0 的整数。" });
  }
  const leadtime = parseOptionalInteger(form.minimumLeadtimeDays);
  if (leadtime === null || leadtime < 0) {
    issues.push({ level: "error", field: "minimum_leadtime_days", message: "备货天数必须是大于等于 0 的整数。" });
  }

  ([
    ["length_cm", form.lengthCm],
    ["width_cm", form.widthCm],
    ["height_cm", form.heightCm],
    ["weight_g", form.weightG],
  ] as const).forEach(([field, value]) => {
    const parsed = parseOptionalNumber(value);
    if (parsed === null || parsed <= 0) {
      issues.push({ level: "error", field, message: "尺寸和重量必须大于 0。" });
    }
  });

  if (minRequiredImages > 0 && imageUrls.length + assetIds.length < minRequiredImages) {
    issues.push({
      level: "error",
      field: "image_urls",
      message: `当前图片数量不足，类目最少需要 ${minRequiredImages} 张。`,
    });
  }

  imageUrls
    .filter((imageUrl) => !isPublicHttpUrl(imageUrl))
    .forEach((imageUrl) => {
      issues.push({
        level: "warning",
        field: "image_urls",
        message: `${imageUrl} 不是公网 http(s) URL。`,
      });
    });

  requiredAttributeSpecs.forEach((attribute) => {
    const value = dynamicAttributes.find((item) => item.key === attribute.key)?.value;
    if (!attributeInputValue(value).trim()) {
      issues.push({
        level: "error",
        field: attribute.key,
        message: `${attribute.label} 是类目必填属性。`,
      });
    }
  });

  return issues;
}

function buildAttributeSpecs(requirements: CategoryRequirements | null): AttributeSpec[] {
  if (!requirements) return [];
  const specs = [
    ...(requirements.required_attributes ?? []).map((attribute) => normalizeAttributeSpec(attribute, true)),
    ...(requirements.optional_attributes ?? []).map((attribute) => normalizeAttributeSpec(attribute, false)),
  ].filter(isPresent);
  const seen = new Set<string>();
  return specs.filter((spec) => {
    if (seen.has(spec.key)) return false;
    seen.add(spec.key);
    return true;
  });
}

function normalizeAttributeSpec(value: unknown, required: boolean): AttributeSpec | null {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed
      ? {
          key: trimmed,
          label: trimmed,
          required,
          inputType: inferAttributeInputType(trimmed, []),
          options: [],
          placeholder: "",
          precision: inferAttributePrecision(trimmed),
        }
      : null;
  }
  if (!isRecord(value)) return null;
  const key = firstStringValue(value, [
    "submit_key",
    "submitKey",
    "field_path",
    "fieldPath",
    "key",
    "name",
    "field",
    "code",
    "attribute",
    "attribute_name",
    "id",
  ]);
  if (!key) return null;
  const label =
    firstStringValue(value, [
      "display_label",
      "displayLabel",
      "label_zh",
      "label",
      "display_name",
      "title",
      "name",
      "key",
    ]) ?? key;
  const options = normalizeAttributeOptions(firstArrayValue(value, ["options", "values", "enum_values", "enumValues"]));
  const inputType = (
    firstStringValue(value, ["input_type", "inputType", "type", "data_type", "dataType"]) ??
    inferAttributeInputType(label, options)
  ).toLowerCase();
  const placeholder = firstStringValue(value, ["placeholder", "hint", "description"]) ?? "";
  return {
    key,
    label,
    required,
    inputType,
    options,
    placeholder,
    precision: inferAttributePrecision(label),
  };
}

function normalizeAttributeOptions(value: unknown): AttributeOption[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<string>();
  return value
    .map((option) => {
      if (isRecord(option)) {
        const optionValue = firstStringValue(option, ["value", "id", "name", "label"]);
        if (!optionValue) return null;
        const optionLabel =
          firstStringValue(option, ["display_label", "displayLabel", "label_zh", "label", "name", "value"]) ??
          optionValue;
        return { value: optionValue, label: optionLabel };
      }
      if (typeof option === "string" || typeof option === "number" || typeof option === "boolean") {
        const optionValue = String(option).trim();
        return optionValue ? { value: optionValue, label: optionValue } : null;
      }
      return null;
    })
    .filter(isPresent)
    .filter((option) => {
      if (seen.has(option.value)) return false;
      seen.add(option.value);
      return true;
    });
}

function inferAttributeInputType(label: string, options: AttributeOption[]) {
  if (options.length > 0) return "select";
  const text = label.toLowerCase();
  if (/(description|note|instruction|comment|描述|说明|备注)/i.test(text)) return "textarea";
  if (/(yes|no|boolean|是否|可否|has_|is_)/i.test(text)) return "boolean";
  if (/(weight|height|width|length|depth|quantity|count|number|重量|高度|宽度|长度|数量)/i.test(text)) {
    return "number";
  }
  return "text";
}

function inferAttributePrecision(label: string) {
  return /(weight|height|width|length|depth|重量|高度|宽度|长度)/i.test(label) ? 2 : 0;
}

function isSwitchAttribute(attribute: AttributeSpec) {
  const text = `${attribute.inputType} ${attribute.key} ${attribute.label}`.toLowerCase();
  return /(boolean|bool|switch|yes_no|yes\/no|是否|可否)/i.test(text);
}

function isNumberAttribute(attribute: AttributeSpec) {
  const text = `${attribute.inputType} ${attribute.key} ${attribute.label}`.toLowerCase();
  return attribute.inputType === "number" || /(integer|decimal|float|weight|height|width|length|quantity|count|重量|高度|宽度|长度|数量)/i.test(text);
}

function isTextareaAttribute(attribute: AttributeSpec) {
  const text = `${attribute.inputType} ${attribute.key} ${attribute.label}`.toLowerCase();
  return attribute.inputType === "textarea" || /(description|note|instruction|comment|描述|说明|备注)/i.test(text);
}

function attributeStep(attribute: AttributeSpec) {
  return attribute.precision > 0 ? String(1 / 10 ** attribute.precision) : "1";
}

function cleanDynamicAttributes(attributes: DynamicAttributeDraft[]): DynamicAttributeDraft[] {
  return attributes
    .map((attribute) => ({
      key: attribute.key.trim(),
      value: normalizeDynamicValue(attribute.value),
      value_type: attribute.value_type ?? null,
      source: attribute.source || "manual",
      warning: attribute.warning ?? null,
    }))
    .filter((attribute) => attribute.key && !isEmptyDynamicValue(attribute.value));
}

function normalizeDynamicValue(value: unknown) {
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  if (!trimmed) return "";
  if (/^-?\d+(\.\d+)?$/.test(trimmed)) return Number(trimmed);
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  return trimmed;
}

function isEmptyDynamicValue(value: unknown) {
  return value === null || value === undefined || value === "";
}

function attributeInputValue(value: unknown) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function toUiIssues(issues: ValidationIssue[]): UiIssue[] {
  return issues.map((issue) => ({
    level: issue.level === "error" ? "error" : "warning",
    field: issue.field || "general",
    message: issue.message,
  }));
}

function formatIssueLevel(level: UiIssue["level"]) {
  return level === "error" ? "错误" : "提醒";
}

function formatIssueSummary(issues: UiIssue[]) {
  const errorCount = issues.filter((issue) => issue.level === "error").length;
  const warningCount = issues.filter((issue) => issue.level === "warning").length;
  if (!errorCount && !warningCount) return "未发现问题";
  if (errorCount && warningCount) return `${errorCount} 个错误，${warningCount} 个提醒`;
  if (errorCount) return `${errorCount} 项待修复`;
  return `${warningCount} 项提醒`;
}

function displayFieldLabel(field: string | null | undefined) {
  const raw = String(field ?? "").trim();
  if (!raw) return "未指定字段";
  const normalized = raw
    .replace(/\[\d+\]/g, "")
    .replace(/\./g, "_")
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .toLowerCase();
  const label = fieldLabelMap[normalized];
  if (label) return label;
  if (normalized.startsWith("dynamic_attributes_")) {
    const attributeName = raw.split(/\.|\[|\]/).filter(Boolean).pop() ?? raw;
    return `类目属性：${attributeName}`;
  }
  return raw;
}

function localizeBackendMessage(message: string | null | undefined) {
  let localized = String(message ?? "");
  Object.entries(fieldLabelMap)
    .sort(([left], [right]) => right.length - left.length)
    .forEach(([field, label]) => {
      localized = localized.replace(new RegExp(`\\b${escapeRegExp(field)}\\b`, "gi"), label);
    });
  return localized
    .replace(/\berror\b/gi, "错误")
    .replace(/\bwarning\b/gi, "提醒")
    .replace(/\bvalid\b/gi, "通过")
    .replace(/\binvalid\b/gi, "未通过")
    .replace(/\bvalidation issues?\b/gi, "校验问题")
    .replace(/\bLoadsheet\b/g, "上架表");
}

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function parseImageUrls(value: string) {
  return Array.from(
    new Set(
      value
        .split(/[\n,]/)
        .map((item) => item.trim())
        .filter(Boolean),
    ),
  );
}

function parsePositiveInteger(value: string) {
  const parsed = Number.parseInt(value.trim(), 10);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function parseOptionalInteger(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number.parseInt(trimmed, 10);
  return Number.isInteger(parsed) ? parsed : null;
}

function parseOptionalNumber(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

function emptyToNull(value: string) {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
}

function numberToInput(value: number, fallback: string) {
  return Number.isFinite(value) && value > 0 ? String(value) : fallback;
}

function selectedSuggestionMinImages(match: CategoryMatchResponse | null, categoryId: number | null) {
  if (!match || !categoryId) return 0;
  return match.suggestions.find((suggestion) => suggestion.category_id === categoryId)?.min_required_images ?? 0;
}

function shouldRefreshGeneratedSku(currentSku: string, lastAutoSku: string) {
  const normalized = currentSku.trim();
  return (
    !normalized ||
    Boolean(lastAutoSku && normalized === lastAutoSku) ||
    /^[A-Z0-9]+(?:-[A-Z0-9]+)*-\d{8}-\d{4}$/.test(normalized)
  );
}

function buildGeneratedSku(
  form: ListingForm,
  category: {
    category_id: number;
    path_en?: string | null;
    path_zh?: string | null;
    lowest_category_name?: string | null;
    lowest_category_raw?: string | null;
    main_category_name?: string | null;
  },
) {
  const productPrefix = toSkuPrefix([form.title, form.productDescription].join(" "));
  const categoryPrefix = toSkuPrefix(
    [
      category.lowest_category_name,
      category.lowest_category_raw,
      lastCategoryPathSegment(category.path_en),
      category.main_category_name,
      category.path_zh,
    ].join(" "),
  );
  const prefix = productPrefix || categoryPrefix || `CAT${category.category_id}` || "XH";
  const datePart = formatSkuDate(new Date());
  const randomPart = String(Math.floor(1000 + Math.random() * 9000));
  const suffix = `${datePart}-${randomPart}`;
  const maxPrefixLength = Math.max(2, takealotSkuMaxLength - suffix.length - 1);
  const clippedPrefix = prefix.slice(0, maxPrefixLength).replace(/-+$/g, "") || "XH";
  return `${clippedPrefix}-${suffix}`.slice(0, takealotSkuMaxLength);
}

function toSkuPrefix(value: string) {
  const tokens = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toUpperCase()
    .match(/[A-Z0-9]+/g);
  if (!tokens) return "";
  const ignored = new Set(["AND", "THE", "FOR", "WITH", "HOME", "FAMILY", "PERSONAL", "LIFESTYLE"]);
  return tokens
    .filter((token) => token.length > 1 && !ignored.has(token))
    .slice(0, 4)
    .join("-");
}

function lastCategoryPathSegment(path: string | null | undefined) {
  if (!path) return "";
  const parts = path.split(/>|->/).map((part) => part.trim()).filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

function formatSkuDate(date: Date) {
  const year = String(date.getFullYear());
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}${month}${day}`;
}

function categoryItemDisplayPath(item: {
  category_id: number;
  path_en?: string | null;
  path_zh?: string | null;
  lowest_category_raw?: string | null;
  lowest_category_name?: string | null;
}) {
  const zhPath = item.path_zh || item.lowest_category_raw || item.lowest_category_name || "";
  const enPath = item.path_en || "";
  const path = zhPath && enPath && zhPath !== enPath ? `${zhPath} / ${enPath}` : zhPath || enPath;
  return path ? `${path} · ID ${item.category_id}` : String(item.category_id);
}

function confidenceTone(confidence: number): "success" | "warning" | "muted" {
  if (confidence >= 0.75) return "success";
  if (confidence >= 0.45) return "warning";
  return "muted";
}

function formatPercent(value: number) {
  const percent = value > 1 ? value : value * 100;
  return `${Math.round(percent)}%`;
}

function formatElapsedMs(value: number) {
  if (!Number.isFinite(value)) return "--";
  if (value < 1000) return `${Math.max(1, Math.round(value))}ms`;
  return `${(value / 1000).toFixed(1)}s`;
}

function submissionCreateFailed(response: SubmissionCreateResponse) {
  const statusValue = `${response.status || ""} ${response.stage || ""}`.toLowerCase();
  return Boolean(response.error_code || statusValue.includes("failed") || statusValue.includes("error"));
}

function statusTone(status: string | null | undefined): "success" | "warning" | "danger" | "muted" {
  if (!status) return "muted";
  const normalized = status.toLowerCase();
  if (["success", "completed", "submitted", "ready"].some((token) => normalized.includes(token))) return "success";
  if (["failed", "error", "rejected"].some((token) => normalized.includes(token))) return "danger";
  if (["queued", "running", "pending", "draft"].some((token) => normalized.includes(token))) return "warning";
  return "muted";
}

function formatStatusLabel(status: string | null | undefined) {
  if (!status) return "--";
  const normalized = status.toLowerCase();
  const exactLabels: Record<string, string> = {
    ai_autopilot: "AI 生成",
    approved: "已通过",
    category_match: "类目匹配",
    completed: "已完成",
    created: "已创建",
    draft: "草稿",
    failed: "失败",
    image_check: "图片检查",
    loadsheet_preview: "上架表预检",
    offer_linking: "Offer 关联",
    pending: "待处理",
    queued: "排队中",
    ready: "就绪",
    rejected: "已拒绝",
    review_pending: "待审核",
    review_sync: "审核同步",
    reviewing: "审核中",
    running: "处理中",
    submission_created: "提交已创建",
    submitted: "已提交",
    success: "成功",
    synced: "已同步",
  };
  if (exactLabels[normalized]) return exactLabels[normalized];
  const partialLabels: Array<[string, string]> = [
    ["failed", "失败"],
    ["error", "错误"],
    ["rejected", "已拒绝"],
    ["completed", "已完成"],
    ["success", "成功"],
    ["submitted", "已提交"],
    ["approved", "已通过"],
    ["synced", "已同步"],
    ["running", "处理中"],
    ["queued", "排队中"],
    ["pending", "待处理"],
    ["review", "审核中"],
    ["draft", "草稿"],
  ];
  const match = partialLabels.find(([token]) => normalized.includes(token));
  return match ? match[1] : status.replace(/_/g, " ");
}

function isPublicHttpUrl(value: string) {
  return /^https?:\/\//i.test(value) && !/^https?:\/\/(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])/i.test(value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstStringValue(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) return String(value);
  }
  return null;
}

function firstArrayValue(record: Record<string, unknown>, keys: string[]) {
  for (const key of keys) {
    const value = record[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function isPresent<T>(value: T | null | undefined): value is T {
  return value !== null && value !== undefined;
}

function formatError(error: unknown, fallback: string) {
  if (error instanceof ApiError) {
    const detail = error.detail || fallback;
    return `HTTP ${error.status}: ${detail}`;
  }
  if (error instanceof Error) return error.message;
  return fallback;
}

async function fetchMultipart<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    body,
  });
  const text = await response.text();
  const data = parseJson<T & { detail?: string }>(text);
  if (!response.ok) {
    throw new ApiError(response.status, data?.detail ?? (text || "Request failed"));
  }
  return data as T;
}

function parseJson<T>(text: string): T | null {
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

function formatFileSize(value: number) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
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
