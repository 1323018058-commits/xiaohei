const STORAGE_KEYS = {
  erpBaseUrl: "erpBaseUrl",
  extensionToken: "extensionToken",
  defaultStoreId: "defaultStoreId",
  defaultStockQty: "defaultStockQty",
  extensionUser: "extensionUser",
  extensionStores: "extensionStores",
  pricingDrafts: "pricingDrafts",
  sellerPortalToken: "sellerPortalToken",
  sellerPortalSeenAt: "sellerPortalSeenAt",
  sellerPortalOrigin: "sellerPortalOrigin",
};

const DEFAULT_ERP_BASE_URL = "http://127.0.0.1:8000";
const PRODUCT_SCRIPT_ID = "xh-product-overlay";
const TAKEALOT_PRODUCT_MATCHES = ["https://www.takealot.com/*"];
const SELLER_PORTAL_MATCHES = [
  "https://seller.takealot.com/*",
  "https://sellers.takealot.com/*",
];
const SELLER_PORTAL_HOME_URL = "https://seller.takealot.com/";
const LIST_NOW_POLL_INTERVAL_MS = 3000;
const LIST_NOW_MAX_WAIT_MS = 90000;
const SELLER_PORTAL_TOKEN_MAX_AGE_MS = 12 * 60 * 60 * 1000;

async function getSettings() {
  const values = await chrome.storage.local.get(Object.values(STORAGE_KEYS));
  return {
    erpBaseUrl: String(values[STORAGE_KEYS.erpBaseUrl] || DEFAULT_ERP_BASE_URL).trim().replace(/\/+$/, ""),
    extensionToken: String(values[STORAGE_KEYS.extensionToken] || "").trim(),
    defaultStoreId: String(values[STORAGE_KEYS.defaultStoreId] || "").trim(),
    defaultStockQty: String(values[STORAGE_KEYS.defaultStockQty] || "").trim(),
    extensionUser: values[STORAGE_KEYS.extensionUser] || null,
    extensionStores: Array.isArray(values[STORAGE_KEYS.extensionStores]) ? values[STORAGE_KEYS.extensionStores] : [],
    pricingDrafts: values[STORAGE_KEYS.pricingDrafts] || {},
    sellerPortalToken: String(values[STORAGE_KEYS.sellerPortalToken] || "").trim(),
    sellerPortalSeenAt: String(values[STORAGE_KEYS.sellerPortalSeenAt] || "").trim(),
    sellerPortalOrigin: String(values[STORAGE_KEYS.sellerPortalOrigin] || "").trim(),
  };
}

async function saveSession({ erpBaseUrl, token, defaultStoreId, user, stores }) {
  const nextStoreId =
    defaultStoreId ||
    (Array.isArray(stores) && stores.length === 1 ? stores[0].store_id : "") ||
    "";

  await chrome.storage.local.set({
    [STORAGE_KEYS.erpBaseUrl]: erpBaseUrl,
    [STORAGE_KEYS.extensionToken]: token,
    [STORAGE_KEYS.defaultStoreId]: nextStoreId,
    [STORAGE_KEYS.defaultStockQty]: "",
    [STORAGE_KEYS.extensionUser]: user || null,
    [STORAGE_KEYS.extensionStores]: Array.isArray(stores) ? stores : [],
  });

  return nextStoreId;
}

async function clearSellerPortalContext() {
  await chrome.storage.local.remove([
    STORAGE_KEYS.sellerPortalToken,
    STORAGE_KEYS.sellerPortalSeenAt,
    STORAGE_KEYS.sellerPortalOrigin,
  ]);
}

async function clearSession() {
  await chrome.storage.local.remove([
    STORAGE_KEYS.extensionToken,
    STORAGE_KEYS.defaultStoreId,
    STORAGE_KEYS.defaultStockQty,
    STORAGE_KEYS.extensionUser,
    STORAGE_KEYS.extensionStores,
  ]);
  await clearSellerPortalContext();
}

async function saveSellerPortalContext({ token, origin }) {
  if (!token) {
    return;
  }
  await chrome.storage.local.set({
    [STORAGE_KEYS.sellerPortalToken]: token,
    [STORAGE_KEYS.sellerPortalSeenAt]: new Date().toISOString(),
    [STORAGE_KEYS.sellerPortalOrigin]: origin || "",
  });
}

async function requestJson({ baseUrl, path, payload, token }) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload ?? {}),
  });

  return parseJsonResponse(response);
}

async function requestGetJson({ baseUrl, path, token }) {
  const response = await fetch(`${baseUrl}${path}`, {
    method: "GET",
    headers: {
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  });

  return parseJsonResponse(response);
}

async function parseJsonResponse(response) {
  const text = await response.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch (_) {
    data = { raw: text };
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object"
        ? data.detail || data.message || data.error || text
        : text;
    const error = new Error(detail || `Request failed (${response.status})`);
    error.status = response.status;
    error.payload = data;
    throw error;
  }

  return data;
}

async function postJson(path, payload) {
  const settings = await getSettings();
  if (!settings.erpBaseUrl) {
    throw new Error("连接配置未初始化");
  }
  if (!settings.extensionToken) {
    throw new Error("Extension Token 未配置");
  }
  return requestJson({
    baseUrl: settings.erpBaseUrl,
    path,
    payload,
    token: settings.extensionToken,
  });
}

async function getJson(path) {
  const settings = await getSettings();
  if (!settings.erpBaseUrl) {
    throw new Error("连接配置未初始化");
  }
  if (!settings.extensionToken) {
    throw new Error("Extension Token 未配置");
  }
  return requestGetJson({
    baseUrl: settings.erpBaseUrl,
    path,
    token: settings.extensionToken,
  });
}

async function validateSession() {
  const settings = await getSettings();
  if (!settings.erpBaseUrl || !settings.extensionToken) {
    return { connected: false, reason: "missing_session" };
  }
  try {
    const profile = await requestGetJson({
      baseUrl: settings.erpBaseUrl,
      path: "/api/extension/profile",
      token: settings.extensionToken,
    });
    const stores = Array.isArray(profile?.stores) ? profile.stores : [];
    const defaultStoreId =
      settings.defaultStoreId ||
      (stores.length === 1 ? stores[0].store_id : "");
    await chrome.storage.local.set({
      [STORAGE_KEYS.extensionUser]: profile?.user || null,
      [STORAGE_KEYS.extensionStores]: stores,
      [STORAGE_KEYS.defaultStoreId]: defaultStoreId,
    });
    return {
      connected: true,
      user: profile?.user || null,
      stores,
      defaultStoreId,
      defaultStockQty: settings.defaultStockQty,
      erpBaseUrl: settings.erpBaseUrl,
    };
  } catch (error) {
    await clearSession();
    return {
      connected: false,
      reason: error instanceof Error ? error.message : String(error),
    };
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForTabReady(tabId, timeoutMs = 10000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") {
      return;
    }
    await sleep(250);
  }
}

async function ensureProductContentScriptRegistered() {
  const scripts = await chrome.scripting.getRegisteredContentScripts({
    ids: [PRODUCT_SCRIPT_ID],
  });
  if (scripts.length > 0) {
    return;
  }
  try {
    await registerProductContentScript();
  } catch (error) {
    if (!isBenignInjectionError(error)) {
      throw error;
    }
    await unregisterProductContentScript();
    try {
      await registerProductContentScript();
    } catch (retryError) {
      if (!isBenignInjectionError(retryError)) {
        throw retryError;
      }
    }
  }
}

async function registerProductContentScript() {
  await chrome.scripting.registerContentScripts([
    {
      id: PRODUCT_SCRIPT_ID,
      matches: TAKEALOT_PRODUCT_MATCHES,
      js: ["content.js"],
      css: ["styles/panel.css"],
      runAt: "document_idle",
      persistAcrossSessions: false,
    },
  ]);
}

function isBenignInjectionError(error) {
  const message = String(error?.message || error || "");
  return /duplicate|already exists|overlap|stylesheet|style sheet|重复|重叠|样式表/i.test(message);
}

async function unregisterProductContentScript() {
  try {
    await chrome.scripting.unregisterContentScripts({
      ids: [PRODUCT_SCRIPT_ID],
    });
  } catch (_) {
    // Ignore if script was not registered.
  }
}

async function notifyTakealotTabs() {
  const tabs = await chrome.tabs.query({ url: TAKEALOT_PRODUCT_MATCHES });
  for (const tab of tabs) {
    if (!tab.id) {
      continue;
    }
    try {
      await chrome.tabs.sendMessage(tab.id, { type: "xh:session-updated" });
    } catch (_) {
      // Ignore tabs without injected script.
    }
  }
}

async function ensureProductPanelOnTab(tabId) {
  try {
    await chrome.tabs.sendMessage(tabId, { type: "xh:session-updated" });
    return;
  } catch (_) {
    // Fall through and inject.
  }

  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ["styles/panel.css"],
    });
  } catch (_) {
    // Ignore CSS injection failures on tabs that are gone.
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"],
  });
}

async function injectProductPanelIntoOpenTabs() {
  const tabs = await chrome.tabs.query({ url: TAKEALOT_PRODUCT_MATCHES });
  for (const tab of tabs) {
    if (!tab.id) {
      continue;
    }
    try {
      await ensureProductPanelOnTab(tab.id);
    } catch (_) {
      // Ignore tabs that no longer exist.
    }
  }
}

async function refreshProductInjectionState({ forceInjectOpenTabs = false } = {}) {
  const session = await validateSession();
  if (!session.connected) {
    await unregisterProductContentScript();
    await notifyTakealotTabs();
    return session;
  }

  await ensureProductContentScriptRegistered();
  if (forceInjectOpenTabs) {
    await injectProductPanelIntoOpenTabs();
  }
  return session;
}

function buildListingCenterUrl(baseUrl, automation) {
  if (!baseUrl || !automation?.listingJobId) {
    return null;
  }
  const url = new URL("/listing", baseUrl);
  url.searchParams.set("job", automation.listingJobId);
  if (automation.taskId) {
    url.searchParams.set("task", automation.taskId);
  }
  if (automation.storeId) {
    url.searchParams.set("store", automation.storeId);
  }
  if (automation.offerId) {
    url.searchParams.set("offer", String(automation.offerId));
  }
  url.searchParams.set("from", "extension");
  return url.toString();
}

async function openOrFocusListingCenter(url) {
  if (!url) {
    return false;
  }
  const target = new URL(url);
  const pattern = `${target.origin}/listing*`;
  const existingTabs = await chrome.tabs.query({ url: [pattern] });
  const existingTab = existingTabs[0];
  if (existingTab?.id) {
    await chrome.tabs.update(existingTab.id, { url, active: true });
    if (existingTab.windowId) {
      await chrome.windows.update(existingTab.windowId, { focused: true });
    }
    return true;
  }
  await chrome.tabs.create({ url, active: true });
  return true;
}

function readSellerPortalAuthInPage() {
  try {
    const raw = localStorage.getItem("usr_st_auth");
    const parsed = raw ? JSON.parse(raw) : null;
    return {
      token: typeof parsed?.api_key === "string" ? parsed.api_key : "",
      origin: window.location.origin,
    };
  } catch (error) {
    return {
      token: "",
      origin: window.location.origin,
      error: String(error),
    };
  }
}

async function captureSellerPortalContext({ openIfNeeded = true } = {}) {
  const settings = await getSettings();
  const seenAtMs = settings.sellerPortalSeenAt
    ? Date.parse(settings.sellerPortalSeenAt)
    : NaN;
  if (
    settings.sellerPortalToken &&
    Number.isFinite(seenAtMs) &&
    Date.now() - seenAtMs <= SELLER_PORTAL_TOKEN_MAX_AGE_MS
  ) {
    return {
      token: settings.sellerPortalToken,
      origin: settings.sellerPortalOrigin || "",
      source: "storage",
    };
  }

  let tabs = await chrome.tabs.query({ url: SELLER_PORTAL_MATCHES });
  let createdTabId = null;
  let targetTab = tabs[0] || null;

  if (!targetTab && openIfNeeded) {
    targetTab = await chrome.tabs.create({
      url: SELLER_PORTAL_HOME_URL,
      active: false,
    });
    createdTabId = targetTab.id || null;
  }

  if (!targetTab?.id) {
    return null;
  }

  try {
    await waitForTabReady(targetTab.id, 15000);
    const execution = await chrome.scripting.executeScript({
      target: { tabId: targetTab.id },
      func: readSellerPortalAuthInPage,
    });
    const result = execution?.[0]?.result || null;
    if (result?.token) {
      await saveSellerPortalContext({
        token: result.token,
        origin: result.origin || targetTab.url || "",
      });
      return {
        token: result.token,
        origin: result.origin || targetTab.url || "",
        source: createdTabId ? "opened_tab" : "existing_tab",
      };
    }
    return null;
  } finally {
    if (createdTabId) {
      try {
        await chrome.tabs.remove(createdTabId);
      } catch (_) {
        // Ignore.
      }
    }
  }
}

async function sellerPortalPatch(offerId, token, body) {
  const response = await fetch(`https://seller-api.takealot.com/v2/offers/offer/${offerId}`, {
    method: "PATCH",
    headers: {
      Authorization: `Bearer ${token}`,
      "Content-Type": "application/json",
      Accept: "application/json, text/plain, */*",
    },
    body: JSON.stringify(body),
  });
  return parseJsonResponse(response);
}

async function applySellerBuyablePatch({
  offerId,
  quantity,
  leadtimeDays,
  merchantWarehouseId,
}) {
  let sellerContext = await captureSellerPortalContext({ openIfNeeded: true });
  if (!sellerContext?.token) {
    return {
      ok: false,
      code: "SELLER_PORTAL_AUTH_MISSING",
      message: "浏览器未检测到 Takealot Seller 登录态，已保留报价记录",
    };
  }

  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      await sellerPortalPatch(offerId, sellerContext.token, {
        leadtime_days: Math.max(1, Number(leadtimeDays || 14)),
      });
      const finalPayload = await sellerPortalPatch(offerId, sellerContext.token, {
        leadtime_stock: [
          {
            merchant_warehouse_id: Number(merchantWarehouseId),
            quantity: Math.max(1, Number(quantity || 1)),
          },
        ],
        status_action: "Re-enable",
      });
      return {
        ok: true,
        code: "BUYABLE_PATCHED",
        message: "官方报价已自动补成 Buyable",
        payload: finalPayload,
      };
    } catch (error) {
      const status = error?.status;
      if ((status === 401 || status === 403) && attempt === 0) {
        await clearSellerPortalContext();
        sellerContext = await captureSellerPortalContext({ openIfNeeded: true });
        if (sellerContext?.token) {
          continue;
        }
      }
      return {
        ok: false,
        code: "SELLER_PORTAL_PATCH_FAILED",
        message: error instanceof Error ? error.message : String(error),
      };
    }
  }

  return {
    ok: false,
    code: "SELLER_PORTAL_PATCH_FAILED",
    message: "自动补全 Buyable 失败",
  };
}

async function getExtensionListNowStatus(taskId) {
  return getJson(`/api/extension/list-now/${taskId}`);
}

async function refreshExtensionListNowStatus(taskId) {
  return postJson(`/api/extension/list-now/${taskId}/refresh-status`, {});
}

function summarizeListNowAutomation(status, { timedOut = false, patchMessage = "" } = {}) {
  if (!status) {
    return {
      outcome: timedOut ? "pending" : "queued",
      terminal: timedOut,
      message: "上架任务已创建，等待 worker 处理",
    };
  }

  const buyable =
    String(status.offer_status || "").toLowerCase() === "buyable" ||
    status.listing_status === "ready_to_submit";
  const offerLabel = status.offer_id ? `Offer ${status.offer_id}` : "报价";

  if (buyable) {
    return {
      outcome: "buyable",
      terminal: true,
      message: `${offerLabel} 已创建并可售`,
      taskId: status.task_id,
      storeId: status.store_id,
      listingJobId: status.listing_job_id,
      offerId: status.offer_id,
      offerStatus: status.offer_status,
    };
  }

  if (status.task_status === "failed" || status.listing_status === "failed") {
    return {
      outcome: "failed",
      terminal: true,
      message: status.note || "上架失败",
      taskId: status.task_id,
      storeId: status.store_id,
      listingJobId: status.listing_job_id,
      offerId: status.offer_id,
      offerStatus: status.offer_status,
    };
  }

  if (patchMessage) {
    return {
      outcome: "offer_created_pending",
      terminal: true,
      message: `${offerLabel} 已创建，${patchMessage}`,
      taskId: status.task_id,
      storeId: status.store_id,
      listingJobId: status.listing_job_id,
      offerId: status.offer_id,
      offerStatus: status.offer_status,
    };
  }

  if (status.offer_id && status.needs_buyable_patch && !status.can_auto_make_buyable) {
    return {
      outcome: "offer_created_pending",
      terminal: true,
      message: `${offerLabel} 已创建，等待店铺 leadtime 配置补齐后自动补成 Buyable`,
      taskId: status.task_id,
      storeId: status.store_id,
      listingJobId: status.listing_job_id,
      offerId: status.offer_id,
      offerStatus: status.offer_status,
    };
  }

  if (timedOut) {
    return {
      outcome: status.offer_id ? "offer_created_pending" : "pending",
      terminal: true,
      message: status.note || "任务仍在处理中，可稍后在 ERP Listing 记录查看",
      taskId: status.task_id,
      storeId: status.store_id,
      listingJobId: status.listing_job_id,
      offerId: status.offer_id,
      offerStatus: status.offer_status,
    };
  }

  return {
    outcome: status.offer_id ? "offer_created_pending" : "pending",
    terminal: false,
    message: status.note || "任务处理中",
    taskId: status.task_id,
    storeId: status.store_id,
    listingJobId: status.listing_job_id,
    offerId: status.offer_id,
    offerStatus: status.offer_status,
  };
}

async function automateListNowLifecycle(taskInfo) {
  const startedAt = Date.now();
  let lastStatus = null;
  let patchMessage = "";
  let patchAttempted = false;

  while (Date.now() - startedAt <= LIST_NOW_MAX_WAIT_MS) {
    if (lastStatus?.listing_job_id) {
      lastStatus = await refreshExtensionListNowStatus(taskInfo.task_id);
    } else {
      lastStatus = await getExtensionListNowStatus(taskInfo.task_id);
    }

    if (
      lastStatus?.offer_id &&
      lastStatus.needs_buyable_patch &&
      lastStatus.can_auto_make_buyable &&
      !patchAttempted
    ) {
      patchAttempted = true;
      const patchResult = await applySellerBuyablePatch({
        offerId: lastStatus.offer_id,
        quantity: taskInfo.quantity,
        leadtimeDays: lastStatus.default_leadtime_days,
        merchantWarehouseId: lastStatus.leadtime_merchant_warehouse_id,
      });
      if (patchResult.ok) {
        lastStatus = await refreshExtensionListNowStatus(taskInfo.task_id);
      } else {
        patchMessage = patchResult.message;
      }
    }

    const summary = summarizeListNowAutomation(lastStatus, { patchMessage });
    if (summary.terminal) {
      return summary;
    }

    await sleep(LIST_NOW_POLL_INTERVAL_MS);
  }

  return summarizeListNowAutomation(lastStatus, {
    timedOut: true,
    patchMessage,
  });
}

chrome.runtime.onInstalled.addListener(() => {
  void refreshProductInjectionState({ forceInjectOpenTabs: true });
});

chrome.runtime.onStartup.addListener(() => {
  void refreshProductInjectionState({ forceInjectOpenTabs: true });
});

void refreshProductInjectionState({ forceInjectOpenTabs: true });

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  (async () => {
    try {
      if (message?.type === "xh:get-settings") {
        sendResponse({ ok: true, data: await getSettings() });
        return;
      }

      if (message?.type === "xh:get-session") {
        sendResponse({ ok: true, data: await validateSession() });
        return;
      }

      if (message?.type === "xh:login") {
        const settings = await getSettings();
        const erpBaseUrl = String(message.erpBaseUrl || settings.erpBaseUrl || DEFAULT_ERP_BASE_URL).trim().replace(/\/+$/, "");
        const username = String(message.username || "").trim();
        const password = String(message.password || "").trim();
        if (!username || !password) {
          throw new Error("账号、密码都不能为空");
        }

        const data = await requestJson({
          baseUrl: erpBaseUrl,
          path: "/api/extension/login",
          payload: { username, password },
          token: null,
        });

        const defaultStoreId = await saveSession({
          erpBaseUrl,
          token: data.token,
          defaultStoreId: data.store_id || "",
          user: data.user,
          stores: data.stores,
        });

        await refreshProductInjectionState({ forceInjectOpenTabs: true });
        await notifyTakealotTabs();

        sendResponse({
          ok: true,
          data: {
            ...data,
            defaultStoreId,
          },
        });
        return;
      }

      if (message?.type === "xh:logout") {
        await clearSession();
        await unregisterProductContentScript();
        await notifyTakealotTabs();
        sendResponse({ ok: true });
        return;
      }

      if (message?.type === "xh:set-store") {
        const storeId = String(message.storeId || "").trim();
        await chrome.storage.local.set({
          [STORAGE_KEYS.defaultStoreId]: storeId,
        });
        await notifyTakealotTabs();
        sendResponse({ ok: true, data: { defaultStoreId: storeId } });
        return;
      }

      if (message?.type === "xh:set-default-stock") {
        const defaultStockQty = String(message.defaultStockQty || "").trim();
        await chrome.storage.local.set({
          [STORAGE_KEYS.defaultStockQty]: defaultStockQty,
        });
        sendResponse({ ok: true, data: { defaultStockQty } });
        return;
      }

      if (message?.type === "xh:get-pricing-draft") {
        const settings = await getSettings();
        const draftKey = `${message.storeId || settings.defaultStoreId}:${message.plid}`;
        sendResponse({
          ok: true,
          data: settings.pricingDrafts[draftKey] || null,
        });
        return;
      }

      if (message?.type === "xh:set-pricing-draft") {
        const settings = await getSettings();
        const draftKey = `${message.storeId || settings.defaultStoreId}:${message.plid}`;
        const nextDrafts = {
          ...settings.pricingDrafts,
          [draftKey]: {
            airFreightUnitCnyPerKg: message.airFreightUnitCnyPerKg ?? null,
            purchasePriceCny: message.purchasePriceCny ?? null,
            salePriceZar: message.salePriceZar ?? null,
            actualWeightKg: message.actualWeightKg ?? null,
            lengthCm: message.lengthCm ?? null,
            widthCm: message.widthCm ?? null,
            heightCm: message.heightCm ?? null,
          },
        };
        await chrome.storage.local.set({
          [STORAGE_KEYS.pricingDrafts]: nextDrafts,
        });
        sendResponse({ ok: true });
        return;
      }

      if (message?.type === "xh:profit-preview") {
        const settings = await getSettings();
        const payload = {
          store_id: message.storeId || settings.defaultStoreId,
          plid: message.plid,
          title: message.title || null,
          category_path: message.categoryPath || null,
          air_freight_unit_cny_per_kg: message.airFreightUnitCnyPerKg ?? null,
          purchase_price_cny: message.purchasePriceCny ?? null,
          sale_price_zar: message.salePriceZar ?? null,
          actual_weight_kg: message.actualWeightKg ?? null,
          length_cm: message.lengthCm ?? null,
          width_cm: message.widthCm ?? null,
          height_cm: message.heightCm ?? null,
          force_refresh_facts: Boolean(message.forceRefreshFacts),
        };
        const data = await postJson("/api/extension/profit-preview", payload);
        sendResponse({ ok: true, data });
        return;
      }

      if (message?.type === "xh:protected-floor") {
        const settings = await getSettings();
        const payload = {
          store_id: message.storeId || settings.defaultStoreId,
          plid: message.plid,
          title: message.title || null,
          protected_floor_price: Number(message.protectedFloorPrice),
        };
        const data = await postJson("/api/extension/protected-floor", payload);
        sendResponse({ ok: true, data });
        return;
      }

      if (message?.type === "xh:list-now") {
        const settings = await getSettings();
        const payload = {
          store_id: message.storeId || settings.defaultStoreId,
          plid: message.plid,
          title: message.title || null,
          sale_price_zar: message.salePriceZar ?? null,
          quantity: message.quantity ?? (settings.defaultStockQty ? Number(settings.defaultStockQty) : null),
        };
        const data = await postJson("/api/extension/list-now", payload);

        let automation = null;
        try {
          automation = await automateListNowLifecycle({
            task_id: data.task_id,
            quantity: payload.quantity,
          });
        } catch (error) {
          automation = {
            outcome: "pending",
            message: error instanceof Error ? error.message : String(error),
            taskId: data.task_id,
          };
        }

        const listingCenterUrl = buildListingCenterUrl(settings.erpBaseUrl, automation);
        const openedListingCenter =
          automation?.listingJobId != null && ["buyable", "failed"].includes(String(automation?.outcome || ""))
            ? await openOrFocusListingCenter(listingCenterUrl)
            : false;

        sendResponse({
          ok: true,
          data: {
            ...data,
            automation: {
              ...automation,
              listingCenterUrl,
              openedListingCenter,
            },
          },
        });
        return;
      }

      sendResponse({ ok: false, error: "未知消息类型" });
    } catch (error) {
      sendResponse({
        ok: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  })();

  return true;
});
