"use client";

import { useEffect, useMemo, useState, type FormEvent } from "react";
import { ClipboardPaste, Plus, RefreshCcw, Search } from "lucide-react";
import { Toaster, toast } from "sonner";

import StoreDetailDrawer from "@/components/stores/StoreDetailDrawer";
import type { components } from "@/generated/api-types";
import { ApiError, apiFetch } from "@/lib/api";

type SessionInfoResponse = components["schemas"]["SessionInfoResponse"];
type StoreListResponse = components["schemas"]["StoreListResponse"];
type StoreSummary = components["schemas"]["StoreSummary"];
type StoreDetail = components["schemas"]["StoreDetail"];
type TaskCreatedResponse = components["schemas"]["TaskCreatedResponse"];
type StoreCredentialValidationResponse = {
  store_id: string;
  status: string;
  message: string;
  platform_profile?: StorePlatformProfile | null;
  store: StoreDetail;
};
type StoreDeleteResponse = {
  store_id: string;
  deleted: boolean;
};
type StorePlatformProfile = {
  seller_id?: string | null;
  display_name?: string | null;
  business_status?: string | null;
  on_vacation?: boolean | null;
  leadtime_label?: string | null;
  tenure_label?: string | null;
  validated_at?: string | null;
};

const ADMIN_ROLES = new Set(["super_admin", "tenant_admin"]);
const initialCreateForm = { name: "", apiKey: "" };

export default function StoresPage() {
  const [session, setSession] = useState<SessionInfoResponse | null>(null);
  const [stores, setStores] = useState<StoreSummary[]>([]);
  const [selectedStoreId, setSelectedStoreId] = useState<string | null>(null);
  const [selectedStore, setSelectedStore] = useState<StoreDetail | null>(null);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(initialCreateForm);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [isLoadingStores, setIsLoadingStores] = useState(true);
  const [isLoadingDetail, setIsLoadingDetail] = useState(false);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState("");
  const [origin, setOrigin] = useState("");

  const canManageStores = session ? ADMIN_ROLES.has(session.user.role) : false;

  const selectedSummary = useMemo(
    () => stores.find((store) => store.store_id === selectedStoreId) ?? null,
    [stores, selectedStoreId],
  );

  const visibleStores = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    if (!keyword) return stores;
    return stores.filter(
      (store) =>
        store.name.toLowerCase().includes(keyword),
    );
  }, [query, stores]);

  useEffect(() => {
    void loadStores();
    setOrigin(window.location.origin);
  }, []);

  useEffect(() => {
    if (!selectedStoreId || !drawerOpen) {
      return;
    }
    void loadStoreWorkspace(selectedStoreId);
  }, [drawerOpen, selectedStoreId]);

  async function loadStores(targetStoreId?: string | null) {
    setIsLoadingStores(true);
    setErrorMessage("");
    try {
      const [sessionData, storeData] = await Promise.all([
        apiFetch<SessionInfoResponse>("/api/auth/me").catch(() => null),
        apiFetch<StoreListResponse>("/api/v1/stores"),
      ]);
      setSession(sessionData);
      setStores(storeData.stores);
      setSelectedStoreId((current) => pickStoreId(storeData.stores, targetStoreId ?? current));
    } catch (error) {
      setStores([]);
      setSelectedStoreId(null);
      setErrorMessage(formatError(error, "加载店铺失败"));
    } finally {
      setIsLoadingStores(false);
    }
  }

  async function loadStoreWorkspace(storeId: string) {
    setIsLoadingDetail(true);
    setErrorMessage("");
    try {
      const detail = await apiFetch<StoreDetail>(`/api/v1/stores/${encodeURIComponent(storeId)}`);
      setSelectedStore(detail);
    } catch (error) {
      setSelectedStore(null);
      setErrorMessage(formatError(error, "加载店铺详情失败"));
    } finally {
      setIsLoadingDetail(false);
    }
  }

  async function submitCreateStore(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canManageStores) {
      toast.error("当前账号不能新建店铺");
      return;
    }

    setBusyAction("create");
    try {
      const created = await apiFetch<StoreDetail>("/api/v1/stores", {
        method: "POST",
        body: JSON.stringify({
          name: createForm.name.trim(),
          platform: "takealot",
          api_key: createForm.apiKey.trim(),
          api_secret: createForm.apiKey.trim(),
          status: "active",
        }),
      });
      setCreateForm(initialCreateForm);
      setShowCreate(false);
      toast.success("店铺已创建", { description: "已自动打开新店铺详情。" });
      await loadStores(created.store_id);
      setSelectedStoreId(created.store_id);
      setDrawerOpen(true);
    } catch (error) {
      toast.error("新建店铺失败", {
        description: formatCreateStoreError(error),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function pasteCreateApiKey() {
    try {
      const value = await navigator.clipboard.readText();
      if (value.trim()) {
        setCreateForm((current) => ({ ...current, apiKey: value.trim() }));
        toast.success("已粘贴 API Key");
      }
    } catch {
      toast.info("无法读取剪贴板", {
        description: "请使用系统快捷键或右键粘贴。",
      });
    }
  }

  async function submitCredentials(payload: { apiKey: string; apiSecret: string }) {
    if (!selectedStoreId || !canManageStores) {
      toast.error("当前账号不能更新凭证");
      return;
    }

    setBusyAction("credentials");
    try {
      await apiFetch<TaskCreatedResponse>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}/credentials`,
        {
          method: "POST",
          body: JSON.stringify({
            api_key: payload.apiKey,
            api_secret: payload.apiSecret,
            reason: "店铺详情抽屉更新凭证",
          }),
        },
      );
      toast.success("凭证更新已提交", { description: "系统会自动校验。" });
      await loadStoreWorkspace(selectedStoreId);
    } catch (error) {
      toast.error("更新凭证失败", {
        description: formatError(error, "请确认凭证格式。"),
      });
      throw error;
    } finally {
      setBusyAction(null);
    }
  }

  async function validateSelectedCredentials() {
    if (!selectedStoreId || !canManageStores) {
      toast.error("当前账号不能验证凭证");
      return;
    }

    setBusyAction("validate-credentials");
    try {
      const result = await apiFetch<StoreCredentialValidationResponse>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}/credentials/validate`,
        { method: "POST" },
      );
      setSelectedStore(result.store);
      setStores((current) =>
        current.map((store) =>
          store.store_id === result.store.store_id
            ? {
                ...store,
                name: result.store.name,
                status: result.store.status,
                api_key_status: result.store.api_key_status,
                credential_status: result.store.credential_status,
                last_synced_at: result.store.last_synced_at,
                feature_policies: result.store.feature_policies,
                updated_at: result.store.updated_at,
                version: result.store.version,
              }
            : store,
        ),
      );
      toast.success("API Key 已验证", {
        description: result.platform_profile?.seller_id
          ? `Seller ID: ${result.platform_profile.seller_id}`
          : result.message,
      });
    } catch (error) {
      toast.error("验证 API Key 失败", {
        description: formatError(error, "请稍后再试。"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function removeSelectedStore() {
    if (!selectedStoreId || !canManageStores) {
      toast.error("当前账号不能移除店铺");
      return;
    }
    const targetStoreId = selectedStoreId;
    const targetName = drawerStore?.name ?? "该店铺";
    if (!window.confirm(`确认移除「${targetName}」？`)) {
      return;
    }

    setBusyAction("remove-store");
    try {
      await apiFetch<StoreDeleteResponse>(
        `/api/v1/stores/${encodeURIComponent(targetStoreId)}`,
        { method: "DELETE" },
      );
      toast.success("店铺已移除");
      setDrawerOpen(false);
      setSelectedStore(null);
      await loadStores(null);
    } catch (error) {
      toast.error("移除店铺失败", {
        description: formatError(error, "请稍后再试。"),
      });
    } finally {
      setBusyAction(null);
    }
  }

  async function submitStoreName(name: string) {
    if (!selectedStoreId || !canManageStores) {
      toast.error("当前账号不能编辑店铺");
      return;
    }

    setBusyAction("store-name");
    try {
      const updated = await apiFetch<StoreDetail>(
        `/api/v1/stores/${encodeURIComponent(selectedStoreId)}`,
        {
          method: "POST",
          body: JSON.stringify({ name }),
        },
      );
      setSelectedStore(updated);
      setStores((current) =>
        current.map((store) =>
          store.store_id === updated.store_id ? { ...store, name: updated.name } : store,
        ),
      );
      toast.success("店铺名称已更新");
    } catch (error) {
      toast.error("更新店铺名称失败", {
        description: formatError(error, "请稍后再试。"),
      });
      throw error;
    } finally {
      setBusyAction(null);
    }
  }

  function openStoreDrawer(storeId: string) {
    setSelectedStoreId(storeId);
    setDrawerOpen(true);
  }

  const selectedDetail = selectedStore?.store_id === selectedStoreId ? selectedStore : null;
  const drawerStore = selectedDetail ?? selectedSummary;
  const platformProfile = getPlatformProfile(selectedDetail);
  const sellerId = textOrFallback(platformProfile?.seller_id, "验证 API Key 后显示");
  const businessStatus = storeBusinessStatus(platformProfile, selectedDetail);
  const leadtimeLabel = textOrFallback(platformProfile?.leadtime_label, "待验证");
  const tenureLabel = textOrFallback(platformProfile?.tenure_label, "待验证");
  const webhookUrl = `${origin || ""}/api/v1/webhooks/takealot`;
  const maskedApiKey = selectedStore?.masked_api_key ?? null;

  return (
    <div className="space-y-4 text-[#000000]">
      <Toaster
        richColors={false}
        position="top-right"
        toastOptions={{
          style: { background: "#111", color: "#fff", border: "1px solid #333" },
        }}
      />

      <header className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div className="space-y-1">
          <h1 className="text-[24px] font-semibold tracking-[-0.03em]">店铺管理</h1>
        </div>

        <button
          type="button"
          onClick={() => setShowCreate((value) => !value)}
          disabled={!canManageStores}
          className={[
            "inline-flex h-9 w-fit items-center justify-center gap-2 self-start rounded-[6px] border px-3 text-sm font-medium outline-none focus-visible:border-[#000000] xl:self-auto",
            canManageStores
              ? "border-[#EBEBEB] bg-[#FFFFFF] text-[#000000]"
              : "cursor-not-allowed border-[#EBEBEB] bg-[#FAFAFA] text-[#B3B3B3]",
          ].join(" ")}
        >
          <Plus className="h-4 w-4 stroke-[1.8]" />
          <span>新增店铺</span>
        </button>
      </header>

      {errorMessage ? (
        <div className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-4 py-3 text-sm text-[#D9363E]">
          {errorMessage}
        </div>
      ) : null}

      {showCreate ? (
        <form
          onSubmit={(event) => void submitCreateStore(event)}
          className="grid gap-3 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto]"
        >
          <Field label="店铺名称">
            <input
              required
              minLength={2}
              value={createForm.name}
              onChange={(event) =>
                setCreateForm((current) => ({ ...current, name: event.target.value }))
              }
              className={inputClassName}
            />
          </Field>
          <Field label="API Key">
            <div className="flex gap-2">
              <input
                required
                minLength={8}
                value={createForm.apiKey}
                onChange={(event) =>
                  setCreateForm((current) => ({ ...current, apiKey: event.target.value }))
                }
                className={inputClassName}
              />
              <button
                type="button"
                onClick={() => void pasteCreateApiKey()}
                className="inline-flex h-10 w-10 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000]"
                aria-label="粘贴 API Key"
                title="粘贴 API Key"
              >
                <ClipboardPaste className="h-4 w-4 stroke-[1.8]" />
              </button>
            </div>
          </Field>
          <button
            type="submit"
            disabled={busyAction === "create"}
            className={[
              "h-10 self-end rounded-[6px] border px-4 text-sm font-medium outline-none focus-visible:border-[#000000]",
              busyAction === "create"
                ? "cursor-not-allowed border-[#EBEBEB] bg-[#FAFAFA] text-[#B3B3B3]"
                : "border-[#000000] bg-[#FFFFFF] text-[#000000]",
            ].join(" ")}
          >
            {busyAction === "create" ? "校验中..." : "验证并创建"}
          </button>
        </form>
      ) : null}

      <section className="rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] p-4">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <label className="relative block min-w-[260px]">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[#595959]" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索店铺名称"
                className={`pl-10 ${inputClassName}`}
              />
            </label>

            <button
              type="button"
              onClick={() => void loadStores()}
              className="inline-flex h-10 items-center gap-2 rounded-[6px] border border-[#EBEBEB] px-3 text-sm text-[#000000] outline-none focus-visible:border-[#000000]"
            >
              <RefreshCcw className="h-4 w-4 stroke-[1.8]" />
              <span>刷新</span>
            </button>
          </div>

          <div className="text-sm text-[#595959]">
            {isLoadingStores ? "加载中..." : `共 ${stores.length} 家`}
          </div>
        </div>
      </section>

      <section className="overflow-hidden rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF]">
        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-[#EBEBEB] text-xs text-[#595959]">
                <th className="h-11 px-4 font-medium">店铺名称</th>
                <th className="h-11 px-4 font-medium">状态</th>
                <th className="h-11 px-4 font-medium">凭证状态</th>
              </tr>
            </thead>
            <tbody>
              {visibleStores.map((store) => (
                <tr
                  key={store.store_id}
                  onClick={() => openStoreDrawer(store.store_id)}
                  className={[
                    "cursor-pointer border-b border-[#EBEBEB] text-sm last:border-b-0",
                    store.store_id === selectedStoreId && drawerOpen ? "bg-[#FAFAFA]" : "hover:bg-[#FAFAFA]",
                  ].join(" ")}
                >
                  <td className="px-4 py-4 align-middle">
                    <div className="font-medium text-[#000000]">{store.name}</div>
                  </td>
                  <td className="px-4 py-4 align-middle text-[#000000]">
                    <span className="inline-flex items-center gap-2">
                      <span
                        className={[
                          "h-2 w-2 rounded-full",
                          store.status === "active" ? "bg-[#000000]" : "bg-[#D9363E]",
                        ].join(" ")}
                      />
                      <span>{formatStoreStatus(store.status)}</span>
                    </span>
                  </td>
                  <td className="px-4 py-4 align-middle text-[#595959]">
                    {formatCredentialStatus(store.credential_status)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!isLoadingStores && visibleStores.length === 0 ? (
          <div className="px-6 py-10 text-center text-sm text-[#595959]">暂无店铺</div>
        ) : null}
      </section>

      {drawerStore ? (
        <StoreDetailDrawer
          open={drawerOpen}
          onClose={() => {
            setDrawerOpen(false);
            setSelectedStore(null);
          }}
          storeName={drawerStore.name}
          sellerId={sellerId}
          businessStatus={businessStatus}
          leadtimeLabel={leadtimeLabel}
          tenureLabel={tenureLabel}
          webhookUrl={webhookUrl}
          maskedApiKey={maskedApiKey}
          canManage={canManageStores}
          isValidatingCredentials={busyAction === "validate-credentials"}
          isRemoving={busyAction === "remove-store"}
          onValidateCredentials={validateSelectedCredentials}
          onSubmitStoreName={submitStoreName}
          onSubmitCredentials={submitCredentials}
          onRemoveStore={removeSelectedStore}
        />
      ) : null}
    </div>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="grid gap-2">
      <span className="text-xs text-[#595959]">{label}</span>
      {children}
    </label>
  );
}

const inputClassName =
  "h-10 w-full rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-sm text-[#000000] outline-none placeholder:text-[#595959]";

function pickStoreId(stores: StoreSummary[], preferredId?: string | null) {
  return preferredId && stores.some((store) => store.store_id === preferredId)
    ? preferredId
    : stores[0]?.store_id ?? null;
}

function formatError(error: unknown, fallback: string) {
  return error instanceof ApiError
    ? error.detail || fallback
    : error instanceof Error
      ? error.message
      : fallback;
}

function formatCredentialStatus(status: string | null) {
  const normalized = (status ?? "").toLowerCase();
  if (["valid", "verified"].includes(normalized)) return "已验证";
  if (normalized === "validating") return "校验中";
  if (["expired", "stale", "invalid"].includes(normalized)) return "API Key 有误";
  return "待验证";
}

function formatCreateStoreError(error: unknown) {
  if (error instanceof ApiError && error.status === 401) {
    return "API Key 校验失败，请确认 Takealot API Key 是否正确。";
  }
  if (error instanceof ApiError && error.status === 503) {
    return "Takealot 暂时无法完成 API Key 校验，请稍后再试。";
  }
  return formatError(error, "请检查店铺名称和 API Key。");
}

function formatStoreStatus(status: string) {
  return status === "active" ? "启用" : "停用";
}

function getPlatformProfile(store: StoreDetail | null): StorePlatformProfile | null {
  const profile = (store as (StoreDetail & { platform_profile?: StorePlatformProfile | null }) | null)
    ?.platform_profile;
  return profile ?? null;
}

function textOrFallback(value: string | null | undefined, fallback: string) {
  return value?.trim() || fallback;
}

function storeBusinessStatus(profile: StorePlatformProfile | null, store: StoreDetail | null) {
  if (profile?.on_vacation === true) return "休假中";
  if (profile?.on_vacation === false) return "营业中";

  const status = profile?.business_status?.trim();
  if (status && status !== "待验证") return status;

  // Legacy cached profiles did not persist on_vacation, but may already contain verified seller facts.
  if (status === "待验证" && isCredentialVerified(store) && hasSellerProfileFacts(profile)) {
    return "营业中";
  }

  return status || "待验证";
}

function isCredentialVerified(store: StoreDetail | null) {
  const status = `${store?.credential_status ?? ""} ${store?.api_key_status ?? ""}`.toLowerCase();
  return status.includes("valid") || status.includes("verified");
}

function hasSellerProfileFacts(profile: StorePlatformProfile | null) {
  return Boolean(profile?.seller_id || profile?.leadtime_label || profile?.tenure_label);
}
