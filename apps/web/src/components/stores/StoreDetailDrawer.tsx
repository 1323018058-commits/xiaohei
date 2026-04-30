"use client";

import { useEffect, useState } from "react";
import { Check, ClipboardPaste, Copy, Pencil, X } from "lucide-react";
import { toast } from "sonner";

type StoreDetailDrawerProps = {
  open: boolean;
  storeName: string;
  sellerId: string;
  businessStatus: string;
  leadtimeLabel: string;
  tenureLabel: string;
  webhookUrl: string;
  maskedApiKey?: string | null;
  canManage?: boolean;
  isValidatingCredentials?: boolean;
  isRemoving?: boolean;
  onClose: () => void;
  onValidateCredentials?: () => void | Promise<void>;
  onSubmitStoreName?: (name: string) => void | Promise<void>;
  onSubmitCredentials?: (payload: { apiKey: string; apiSecret: string }) => void | Promise<void>;
  onRemoveStore?: () => void | Promise<void>;
};

export default function StoreDetailDrawer({
  open,
  storeName,
  sellerId,
  businessStatus,
  leadtimeLabel,
  tenureLabel,
  webhookUrl,
  maskedApiKey,
  canManage = false,
  isValidatingCredentials = false,
  isRemoving = false,
  onClose,
  onValidateCredentials,
  onSubmitStoreName,
  onSubmitCredentials,
  onRemoveStore,
}: StoreDetailDrawerProps) {
  const [isEditingName, setIsEditingName] = useState(false);
  const [draftStoreName, setDraftStoreName] = useState(storeName);
  const [isSubmittingName, setIsSubmittingName] = useState(false);
  const [isEditingKey, setIsEditingKey] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  useEffect(() => {
    setDraftStoreName(storeName);
    if (!open) {
      setIsEditingName(false);
      setIsEditingKey(false);
      setApiKey("");
      setIsSubmittingName(false);
      setIsSubmitting(false);
    }
  }, [open, storeName]);

  if (!open) {
    return null;
  }

  async function handleCopy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("已复制");
    } catch {
      toast.info("当前浏览器无法写入剪贴板");
    }
  }

  async function handlePasteApiKey() {
    try {
      const value = await navigator.clipboard.readText();
      if (value.trim()) {
        setApiKey(value.trim());
        toast.success("已粘贴 API Key");
      }
    } catch {
      toast.info("无法读取剪贴板", {
        description: "请使用系统快捷键或右键粘贴。",
      });
    }
  }

  async function handleConfirmKeyUpdate() {
    if (!canManage || !onSubmitCredentials) return;
    if (!apiKey.trim()) return;

    setIsSubmitting(true);
    try {
      await onSubmitCredentials({
        apiKey: apiKey.trim(),
        apiSecret: apiKey.trim(),
      });
      setIsEditingKey(false);
      setApiKey("");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleConfirmNameUpdate() {
    const nextName = draftStoreName.trim();
    if (!canManage || !onSubmitStoreName || !nextName || nextName === storeName) {
      setDraftStoreName(storeName);
      setIsEditingName(false);
      return;
    }

    setIsSubmittingName(true);
    try {
      await onSubmitStoreName(nextName);
      setIsEditingName(false);
    } finally {
      setIsSubmittingName(false);
    }
  }

  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/18">
      <aside className="h-screen w-full max-w-[480px] overflow-hidden border-l border-[#EBEBEB] bg-[#FFFFFF]">
        <div className="flex h-full flex-col">
          <div className="border-b border-[#EBEBEB] px-6 py-5">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <div className="text-lg font-bold tracking-[-0.02em] text-[#000000]">
                  店铺详情
                </div>
              </div>
              <button
                type="button"
                onClick={onClose}
                className="inline-flex h-8 w-8 items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none transition-colors hover:text-[#000000] focus-visible:border-[#000000]"
                aria-label="关闭"
              >
                <X className="h-4 w-4 stroke-[1.8]" />
              </button>
            </div>

            <div className="mt-6 space-y-2">
              {isEditingName ? (
                <div className="flex items-center gap-2">
                  <input
                    value={draftStoreName}
                    onChange={(event) => setDraftStoreName(event.target.value)}
                    className="h-11 min-w-0 flex-1 rounded-[6px] border border-[#EBEBEB] bg-[#FFFFFF] px-3 text-xl font-semibold tracking-[-0.03em] text-[#000000] outline-none focus-visible:border-[#000000]"
                    autoFocus
                  />
                  <button
                    type="button"
                    onClick={() => void handleConfirmNameUpdate()}
                    disabled={isSubmittingName || !draftStoreName.trim()}
                    className={[
                      "inline-flex h-11 w-11 items-center justify-center rounded-[6px] border outline-none focus-visible:border-[#000000]",
                      isSubmittingName || !draftStoreName.trim()
                        ? "cursor-not-allowed border-[#EBEBEB] text-[#B3B3B3]"
                        : "border-[#000000] text-[#000000]",
                    ].join(" ")}
                    aria-label="保存店铺名称"
                  >
                    <Check className="h-4 w-4 stroke-[1.8]" />
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDraftStoreName(storeName);
                      setIsEditingName(false);
                    }}
                    className="inline-flex h-11 w-11 items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000]"
                    aria-label="取消编辑店铺名称"
                  >
                    <X className="h-4 w-4 stroke-[1.8]" />
                  </button>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <div className="min-w-0 truncate text-[28px] font-semibold tracking-[-0.04em] text-[#000000]">
                    {storeName}
                  </div>
                  <button
                    type="button"
                    onClick={() => setIsEditingName(true)}
                    disabled={!canManage}
                    className={[
                      "inline-flex h-8 w-8 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] outline-none focus-visible:border-[#000000]",
                      canManage
                        ? "text-[#595959] hover:text-[#000000]"
                        : "cursor-not-allowed text-[#B3B3B3]",
                    ].join(" ")}
                    aria-label="编辑店铺名称"
                  >
                    <Pencil className="h-3.5 w-3.5 stroke-[1.8]" />
                  </button>
                </div>
              )}

              <div className="flex items-center gap-2 text-sm text-[#595959]">
                <span>Seller ID: {sellerId}</span>
                <button
                  type="button"
                  onClick={() => void handleCopy(sellerId)}
                  disabled={sellerId === "验证 API Key 后显示"}
                  className="inline-flex h-7 w-7 items-center justify-center rounded-[4px] border border-[#EBEBEB] text-[#595959] outline-none transition-colors hover:text-[#000000] focus-visible:border-[#000000]"
                  aria-label="复制 Seller ID"
                >
                  <Copy className="h-3.5 w-3.5 stroke-[1.8]" />
                </button>
              </div>
            </div>
          </div>

          <div className="flex-1 overflow-y-auto px-6 py-6">
            <section className="grid grid-cols-1 gap-4 border-b border-[#EBEBEB] pb-6 sm:grid-cols-3">
              <MetricItem
                label="营业状态"
                value={
                  <span className="inline-flex items-center gap-2 font-semibold text-[#000000]">
                    <span className="text-[10px] leading-none">●</span>
                    <span>{businessStatus}</span>
                  </span>
                }
              />
              <MetricItem
                label="直邮时效"
                value={<span className="font-semibold text-[#000000]">{leadtimeLabel}</span>}
              />
              <MetricItem
                label="入驻时长"
                value={<span className="font-semibold text-[#000000]">{tenureLabel}</span>}
              />
            </section>

            <section className="border-b border-[#EBEBEB] py-6">
              <div className="mb-3 text-sm font-medium text-[#000000]">Webhook URL</div>

              <div className="flex gap-3">
                <div className="min-h-[52px] flex-1 rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] px-4 py-3 text-sm leading-6 text-[#595959] break-all">
                  {webhookUrl}
                </div>

                <button
                  type="button"
                  onClick={() => void handleCopy(webhookUrl)}
                  className="inline-flex h-[52px] w-[52px] flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] bg-[#FAFAFA] text-[#595959] outline-none transition-colors hover:text-[#000000] focus-visible:border-[#000000]"
                  aria-label="复制 Webhook URL"
                >
                  <Copy className="h-4 w-4 stroke-[1.8]" />
                </button>
              </div>

              <p className="mt-3 text-xs leading-5 text-[#595959]">
                状态：等待平台回传验证
              </p>
              <ol className="mt-3 list-decimal space-y-1 pl-4 text-xs leading-5 text-[#595959]">
                <li>复制 Callback URL。</li>
                <li>打开 Takealot Seller Portal → Settings → Webhooks。</li>
                <li>把 URL 粘贴到 Callback URL，并保存启用。</li>
                <li>ERP 收到 Takealot 签名回调后，才能标记 Webhook 已验证。</li>
              </ol>
            </section>

            <section className="border-b border-[#EBEBEB] py-6">
              <div className="text-sm font-medium text-[#000000]">API Key</div>
              {maskedApiKey ? (
                <div className="mt-2 text-xs text-[#595959]">当前：{maskedApiKey}</div>
              ) : null}

              {!isEditingKey ? (
                <div className="mt-4 flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    onClick={() => void onValidateCredentials?.()}
                    disabled={!canManage || isValidatingCredentials}
                    className={[
                      "inline-flex h-10 items-center justify-center rounded-[6px] border border-[#EBEBEB] px-4 text-sm font-medium outline-none transition-colors focus-visible:border-[#000000]",
                      canManage && !isValidatingCredentials
                        ? "text-[#000000] hover:bg-[#FAFAFA]"
                        : "cursor-not-allowed text-[#B3B3B3]",
                    ].join(" ")}
                  >
                    {isValidatingCredentials ? "校验中..." : "验证 API Key"}
                  </button>

                  <button
                    type="button"
                    onClick={() => setIsEditingKey(true)}
                    disabled={!canManage}
                    className={[
                      "inline-flex h-10 items-center justify-center rounded-[6px] border border-[#EBEBEB] px-4 text-sm font-medium outline-none transition-colors focus-visible:border-[#000000]",
                      canManage
                        ? "text-[#000000] hover:bg-[#FAFAFA]"
                        : "cursor-not-allowed text-[#B3B3B3]",
                    ].join(" ")}
                  >
                    更新 API Key
                  </button>

                  <button
                    type="button"
                    onClick={() => void onRemoveStore?.()}
                    disabled={!canManage || isRemoving}
                    className={[
                      "inline-flex h-10 items-center justify-center rounded-[6px] px-1 text-sm font-medium outline-none focus-visible:ring-1 focus-visible:ring-[#000000]",
                      canManage && !isRemoving ? "text-[#D9363E]" : "cursor-not-allowed text-[#B3B3B3]",
                    ].join(" ")}
                  >
                    {isRemoving ? "移除中..." : "移除店铺"}
                  </button>
                </div>
              ) : (
                <div className="mt-4 space-y-3">
                  <div className="flex gap-2">
                    <input
                      value={apiKey}
                      onChange={(event) => setApiKey(event.target.value)}
                      placeholder="粘贴新的 Takealot API Key"
                      className="h-11 min-w-0 flex-1 rounded-[6px] border border-[#EBEBEB] bg-white px-4 text-sm text-[#000000] outline-none placeholder:text-[#595959]"
                    />
                    <button
                      type="button"
                      onClick={() => void handlePasteApiKey()}
                      className="inline-flex h-11 w-11 flex-none items-center justify-center rounded-[6px] border border-[#EBEBEB] text-[#595959] outline-none hover:text-[#000000] focus-visible:border-[#000000]"
                      aria-label="粘贴 API Key"
                      title="粘贴 API Key"
                    >
                      <ClipboardPaste className="h-4 w-4 stroke-[1.8]" />
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      onClick={handleConfirmKeyUpdate}
                      disabled={!apiKey.trim() || isSubmitting}
                      className={[
                        "inline-flex h-10 items-center justify-center rounded-[6px] border px-4 text-sm font-medium outline-none focus-visible:border-[#000000]",
                        apiKey.trim() && !isSubmitting
                          ? "border-[#000000] bg-[#FFFFFF] text-[#000000]"
                          : "cursor-not-allowed border-[#EBEBEB] bg-[#FAFAFA] text-[#B3B3B3]",
                      ].join(" ")}
                    >
                      {isSubmitting ? "提交中..." : "确认更换"}
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setIsEditingKey(false);
                        setApiKey("");
                      }}
                      className="inline-flex h-10 items-center justify-center rounded-[6px] px-1 text-sm font-medium text-[#595959] outline-none focus-visible:ring-1 focus-visible:ring-[#000000]"
                    >
                      取消
                    </button>
                  </div>
                </div>
              )}
            </section>

          </div>
        </div>
      </aside>
    </div>
  );
}

function MetricItem({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="space-y-2">
      <div className="text-xs text-[#595959]">{label}</div>
      <div className="text-sm text-[#000000]">{value}</div>
    </div>
  );
}
