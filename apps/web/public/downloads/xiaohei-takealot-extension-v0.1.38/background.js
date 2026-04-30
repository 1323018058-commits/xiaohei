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
const DEFAULT_ERP_WEB_BASE_URL = "http://127.0.0.1:3001";
const PRODUCT_SCRIPT_ID = "xh-product-overlay";
const TAKEALOT_PRODUCT_MATCHES = [
  "https://www.takealot.com/*",
  "https://takealot.com/*",
];
const ERP_WEB_FALLBACK_BASE_URLS = [
  DEFAULT_ERP_WEB_BASE_URL,
  "http://localhost:3001",
];
const SELLER_PORTAL_MATCHES = [
  "https://seller.takealot.com/*",
  "https://sellers.takealot.com/*",
];
const SELLER_PORTAL_HOME_URL = "https://seller.takealot.com/";
const LIST_NOW_POLL_INTERVAL_MS = 3000;
const LIST_NOW_MAX_WAIT_MS = 90000;
const SELLER_PORTAL_TOKEN_MAX_AGE_MS = 12 * 60 * 60 * 1000;
const CATALOG_FACT_CACHE_MS = 60 * 1000;
const catalogFactCache = new Map();

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
    (Array.isArray(stores) && stores.length ? stores[0].store_id : "") ||
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

function normalizeBaseUrl(value, fallback = "") {
  try {
    const url = new URL(value || fallback);
    url.pathname = "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/+$/, "");
  } catch (_) {
    return String(fallback || "").replace(/\/+$/, "");
  }
}

function toErpWebBaseUrl(baseUrl) {
  try {
    const url = new URL(baseUrl || DEFAULT_ERP_BASE_URL);
    if ((url.hostname === "127.0.0.1" || url.hostname === "localhost") && url.port === "8000") {
      url.port = "3001";
    }
    url.pathname = "";
    url.search = "";
    url.hash = "";
    return url.toString().replace(/\/+$/, "");
  } catch (_) {
    return DEFAULT_ERP_WEB_BASE_URL;
  }
}

function uniqueStrings(values) {
  return Array.from(new Set(values.filter(Boolean)));
}

function getErpWebCandidateBaseUrls(settings) {
  return uniqueStrings([
    toErpWebBaseUrl(settings?.erpBaseUrl || DEFAULT_ERP_BASE_URL),
    ...ERP_WEB_FALLBACK_BASE_URLS,
  ]);
}

function getTabQueryPatternForBaseUrl(baseUrl) {
  try {
    const url = new URL(baseUrl);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return null;
    }
    return `${url.protocol}//${url.hostname}/*`;
  } catch (_) {
    return null;
  }
}

function getOrigin(value) {
  try {
    return new URL(value).origin;
  } catch (_) {
    return "";
  }
}

async function queryErpWebTabs(settings) {
  const candidates = getErpWebCandidateBaseUrls(settings);
  const candidateOrigins = new Set(candidates.map(getOrigin).filter(Boolean));
  const queryPatterns = uniqueStrings(candidates.map(getTabQueryPatternForBaseUrl));
  const tabs = queryPatterns.length ? await chrome.tabs.query({ url: queryPatterns }) : [];
  return {
    candidates,
    tabs: tabs.filter((tab) => candidateOrigins.has(getOrigin(tab.url || ""))),
  };
}

async function openOrFocusErpWeb() {
  const settings = await getSettings();
  const { candidates, tabs } = await queryErpWebTabs(settings);
  const existingTab = tabs.find((tab) => tab.id);
  if (existingTab?.id) {
    await chrome.tabs.update(existingTab.id, { active: true });
    if (existingTab.windowId) {
      await chrome.windows.update(existingTab.windowId, { focused: true });
    }
    return existingTab;
  }

  const url = `${candidates[0] || DEFAULT_ERP_WEB_BASE_URL}/`;
  return chrome.tabs.create({ url, active: true });
}

function requestExtensionAuthInErpPage() {
  return (async () => {
    try {
      const endpoint = new URL("/api/extension/auth", window.location.origin).toString();
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({}),
      });
      const text = await response.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : null;
      } catch (_) {
        data = { raw: text };
      }
      const detail =
        data && typeof data === "object"
          ? data.detail || data.message || data.error || text
          : text;
      return {
        ok: response.ok,
        status: response.status,
        origin: window.location.origin,
        data,
        error: response.ok ? "" : detail || `HTTP ${response.status}`,
      };
    } catch (error) {
      return {
        ok: false,
        status: 0,
        origin: window.location.origin,
        data: null,
        error: error instanceof Error ? error.message : String(error),
      };
    }
  })();
}

async function executeExtensionAuthOnErpTab(tabId) {
  try {
    const execution = await chrome.scripting.executeScript({
      target: { tabId },
      world: "MAIN",
      func: requestExtensionAuthInErpPage,
    });
    return execution?.[0]?.result || null;
  } catch (_) {
    const execution = await chrome.scripting.executeScript({
      target: { tabId },
      func: requestExtensionAuthInErpPage,
    });
    return execution?.[0]?.result || null;
  }
}

async function bindErpSessionFromWeb({ openIfNeeded = false } = {}) {
  const settings = await getSettings();
  let { candidates, tabs } = await queryErpWebTabs(settings);
  if (!tabs.length && openIfNeeded) {
    const openedTab = await openOrFocusErpWeb();
    tabs = openedTab ? [openedTab] : [];
  }

  if (!tabs.length) {
    return {
      connected: false,
      code: "ERP_TAB_MISSING",
      reason: "请先在同一个浏览器打开 ERP 并登录",
      erpWebUrl: `${candidates[0] || DEFAULT_ERP_WEB_BASE_URL}/`,
    };
  }

  let lastReason = "未检测到已登录的 ERP 网页";
  for (const tab of tabs) {
    if (!tab.id) {
      continue;
    }
    try {
      await waitForTabReady(tab.id, 15000);
      const authResult = await executeExtensionAuthOnErpTab(tab.id);
      if (authResult?.ok && authResult.data?.token) {
        const erpBaseUrl = normalizeBaseUrl(authResult.origin, settings.erpBaseUrl || DEFAULT_ERP_WEB_BASE_URL);
        const defaultStoreId = await saveSession({
          erpBaseUrl,
          token: authResult.data.token,
          defaultStoreId: authResult.data.store_id || settings.defaultStoreId || "",
          user: null,
          stores: [],
        });
        const session = await validateSession();
        if (session.connected) {
          await ensureProductContentScriptRegistered();
          await injectProductPanelIntoOpenTabs();
          await notifyTakealotTabs();
          return {
            ...session,
            defaultStoreId: session.defaultStoreId || defaultStoreId,
            source: "erp_web_session",
          };
        }
        lastReason = session.reason || "ERP 已授权，但插件读取用户信息失败";
        continue;
      }

      lastReason =
        authResult?.status === 401
          ? "ERP 网页登录已过期，请重新登录后刷新插件"
          : authResult?.error || lastReason;
    } catch (error) {
      lastReason = error instanceof Error ? error.message : String(error);
    }
  }

  return {
    connected: false,
    code: "ERP_WEB_AUTH_FAILED",
    reason: lastReason,
    erpWebUrl: `${candidates[0] || DEFAULT_ERP_WEB_BASE_URL}/`,
  };
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
  if (scripts.length > 0 && isRegisteredProductScriptCurrent(scripts[0])) {
    return;
  }
  if (scripts.length > 0) {
    await unregisterProductContentScript();
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

function isRegisteredProductScriptCurrent(script) {
  const matches = new Set(script?.matches || []);
  return (
    TAKEALOT_PRODUCT_MATCHES.every((match) => matches.has(match)) &&
    Array.isArray(script?.js) &&
    script.js.includes("content.js") &&
    Array.isArray(script?.css) &&
    script.css.includes("styles/panel.css")
  );
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

async function ensurePanelCssOnTab(tabId) {
  try {
    await chrome.scripting.insertCSS({
      target: { tabId },
      files: ["styles/panel.css"],
    });
  } catch (error) {
    if (!isBenignInjectionError(error)) {
      throw error;
    }
  }
}

async function ensureProductPanelOnTab(tabId) {
  try {
    await ensurePanelCssOnTab(tabId);
  } catch (_) {
    // Ignore CSS injection failures on tabs that are gone or not ready.
  }

  try {
    await chrome.tabs.sendMessage(tabId, { type: "xh:session-updated" });
    return;
  } catch (_) {
    // Fall through and inject.
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"],
  });

  try {
    await ensurePanelCssOnTab(tabId);
  } catch (_) {
    // The content script also links the stylesheet as a fallback.
  }
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

async function getSellerPortalStatus() {
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
      connected: true,
      source: "storage",
      seenAt: settings.sellerPortalSeenAt,
      origin: settings.sellerPortalOrigin || "",
    };
  }

  const sellerContext = await captureSellerPortalContext({ openIfNeeded: false });
  return {
    connected: Boolean(sellerContext?.token),
    source: sellerContext?.source || "",
    seenAt: sellerContext?.token ? new Date().toISOString() : "",
    origin: sellerContext?.origin || "",
  };
}

async function openSellerPortal() {
  const tabs = await chrome.tabs.query({ url: SELLER_PORTAL_MATCHES });
  const existingTab = tabs[0];
  if (existingTab?.id) {
    await chrome.tabs.update(existingTab.id, { active: true });
    if (existingTab.windowId) {
      await chrome.windows.update(existingTab.windowId, { focused: true });
    }
    return true;
  }
  await chrome.tabs.create({ url: SELLER_PORTAL_HOME_URL, active: true });
  return true;
}

function normalizeCatalogKey(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
}

function scalarCatalogValue(value) {
  if (value == null || value === "") {
    return null;
  }
  if (typeof value === "number") {
    return String(value);
  }
  if (typeof value === "string") {
    return value.trim() || null;
  }
  if (typeof value === "object" && !Array.isArray(value)) {
    const unit = scalarCatalogValue(
      value.unit || value.units || value.uom || value.unit_of_measure || value.unitOfMeasure,
    );
    for (const key of ["value", "display_value", "displayValue", "name", "label", "text"]) {
      const candidate = scalarCatalogValue(value[key]);
      if (candidate) {
        return unit && !/[a-zA-Z]/.test(candidate) ? `${candidate} ${unit}` : candidate;
      }
    }
  }
  return null;
}

function findCatalogValue(value, keys, depth = 0) {
  if (value == null || depth > 7) {
    return null;
  }
  if (Array.isArray(value)) {
    for (const item of value.slice(0, 80)) {
      const found = findCatalogValue(item, keys, depth + 1);
      if (found) {
        return found;
      }
    }
    return null;
  }
  if (typeof value === "object") {
    const label = normalizeCatalogKey(
      value.key || value.name || value.label || value.display_name || value.displayName,
    );
    if (keys.has(label)) {
      const direct = scalarCatalogValue(value.value);
      if (direct) {
        return direct;
      }
    }
    for (const [key, nested] of Object.entries(value)) {
      if (keys.has(normalizeCatalogKey(key))) {
        const direct = scalarCatalogValue(nested);
        if (direct) {
          return direct;
        }
      }
      const found = findCatalogValue(nested, keys, depth + 1);
      if (found) {
        return found;
      }
    }
  }
  return null;
}

function firstCatalogValue(payload, keys) {
  const normalized = new Set(keys.map(normalizeCatalogKey));
  return findCatalogValue(payload, normalized);
}

function cleanCatalogBarcode(value) {
  const text = scalarCatalogValue(value);
  if (!text) {
    return null;
  }
  const normalized = String(text).trim().replace(/\s+/g, "").replace(/[^0-9A-Za-z-]/g, "");
  return normalized.length >= 6 ? normalized : null;
}

function extractCatalogBarcode(payload) {
  return cleanCatalogBarcode(
    firstCatalogValue(payload, [
      "gtin",
      "gtin13",
      "global_trade_item_number",
      "barcode",
      "bar_code",
      "ean",
      "ean13",
      "upc",
      "isbn",
      "product_barcode",
      "product_gtin",
      "product_ean",
      "variant_gtin",
      "variant_barcode",
    ]),
  );
}

function numberFromCatalogText(value) {
  const text = scalarCatalogValue(value);
  if (!text) {
    return null;
  }
  const match = text.match(/([0-9]+(?:[.,][0-9]+)?)/);
  if (!match) {
    return null;
  }
  const number = Number(match[1].replace(",", "."));
  return Number.isFinite(number) ? number : null;
}

function parseCatalogWeightKg(value, sourceKey = "") {
  const text = scalarCatalogValue(value);
  const number = numberFromCatalogText(text);
  if (number == null || number <= 0) {
    return null;
  }
  const lowered = String(text || "").toLowerCase();
  const normalizedKey = normalizeCatalogKey(sourceKey);
  if (
    /\b(g|gram|grams)\b/.test(lowered) ||
    normalizedKey.includes("grams") ||
    normalizedKey.endsWith("g") ||
    number > 40
  ) {
    return number / 1000;
  }
  return number;
}

function parseCatalogDimensionCm(value, sourceKey = "") {
  const number = numberFromCatalogText(value);
  if (number == null || number <= 0) {
    return null;
  }
  const text = String(scalarCatalogValue(value) || "").toLowerCase();
  const normalizedKey = normalizeCatalogKey(sourceKey);
  return text.includes("mm") || normalizedKey.endsWith("mm") ? number / 10 : number;
}

function parseCatalogDimensionsText(value) {
  const text = scalarCatalogValue(value);
  if (!text) {
    return null;
  }
  const matches = String(text).match(/[0-9]+(?:[.,][0-9]+)?/g);
  if (!matches || matches.length < 3) {
    return null;
  }
  const values = matches.slice(0, 3).map((item) => Number(item.replace(",", ".")));
  if (values.some((item) => !Number.isFinite(item) || item <= 0)) {
    return null;
  }
  if (String(text).toLowerCase().includes("mm")) {
    return values.map((item) => item / 10);
  }
  return values;
}

function extractCatalogFacts(payload) {
  const barcode = extractCatalogBarcode(payload);
  const weightKeys = [
    "merchant_packaged_weight",
    "merchant_packaged_weight_grams",
    "merchant_package_weight",
    "merchant_package_weight_grams",
    "packaged_weight",
    "package_weight",
    "packaged_weight_grams",
    "package_weight_grams",
    "package_weight_g",
    "weight_grams",
    "weight_in_grams",
    "shipping_weight_grams",
    "shipping_weight",
    "mass",
    "weight",
  ];
  let actualWeightKg = null;
  for (const key of weightKeys) {
    actualWeightKg = parseCatalogWeightKg(firstCatalogValue(payload, [key]), key);
    if (actualWeightKg != null) {
      break;
    }
  }

  let dimensions = parseCatalogDimensionsText(
    firstCatalogValue(payload, [
      "merchant_packaged_dimensions",
      "merchant_packaged_dimensions_cm",
      "merchant_package_dimensions",
      "package_dimensions",
      "package_dimensions_cm",
      "package_dimensions_mm",
      "packaged_dimensions",
      "packaging_dimensions",
      "shipping_dimensions",
      "dimensions",
      "dimension",
    ]),
  );

  if (!dimensions) {
    const lengthCm = parseCatalogDimensionCm(
      firstCatalogValue(payload, [
        "length_cm",
        "package_length_cm",
        "packaged_length_cm",
        "merchant_packaged_length_cm",
        "length",
        "package_length",
        "packaged_length",
        "merchant_packaged_length",
        "length_mm",
        "package_length_mm",
        "merchant_packaged_length_mm",
      ]),
    );
    const widthCm = parseCatalogDimensionCm(
      firstCatalogValue(payload, [
        "width_cm",
        "package_width_cm",
        "packaged_width_cm",
        "merchant_packaged_width_cm",
        "width",
        "package_width",
        "packaged_width",
        "merchant_packaged_width",
        "width_mm",
        "package_width_mm",
        "merchant_packaged_width_mm",
      ]),
    );
    const heightCm = parseCatalogDimensionCm(
      firstCatalogValue(payload, [
        "height_cm",
        "depth_cm",
        "package_height_cm",
        "package_depth_cm",
        "packaged_height_cm",
        "merchant_packaged_height_cm",
        "height",
        "depth",
        "package_height",
        "package_depth",
        "packaged_height",
        "merchant_packaged_height",
        "height_mm",
        "package_height_mm",
        "merchant_packaged_height_mm",
      ]),
    );
    if (lengthCm != null && widthCm != null && heightCm != null) {
      dimensions = [lengthCm, widthCm, heightCm];
    }
  }

  return {
    barcode,
    actualWeightKg,
    lengthCm: dimensions?.[0] ?? null,
    widthCm: dimensions?.[1] ?? null,
    heightCm: dimensions?.[2] ?? null,
  };
}

function hasCompleteCatalogFacts(facts) {
  return Boolean(
    facts &&
      facts.actualWeightKg > 0 &&
      facts.lengthCm > 0 &&
      facts.widthCm > 0 &&
      facts.heightCm > 0
  );
}

function positiveNumberOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

function positiveIntegerOrNull(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : null;
}

async function fetchSellerCatalogFacts(plid, options = {}) {
  const cleanPlid = String(plid || "").replace(/^PLID/i, "").trim();
  if (!cleanPlid) {
    return null;
  }
  const cached = catalogFactCache.get(cleanPlid);
  if (
    cached &&
    Date.now() - cached.fetchedAt <= CATALOG_FACT_CACHE_MS &&
    (!options.requireBarcode || cached.facts?.barcode)
  ) {
    return cached.facts;
  }

  const sellerContext = await captureSellerPortalContext({ openIfNeeded: true });
  if (!sellerContext?.token) {
    return null;
  }

  try {
    let completeFactsFallback = null;
    for (const productId of [cleanPlid, `PLID${cleanPlid}`]) {
      const response = await fetch(`https://seller-api.takealot.com/1/catalogue/mpv/${productId}`, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${sellerContext.token}`,
          Accept: "application/json",
        },
      });
      if (response.status === 401 || response.status === 403) {
        await clearSellerPortalContext();
        return null;
      }
      if (!response.ok) {
        continue;
      }
      const payload = await response.json();
      if (!payload || typeof payload !== "object") {
        continue;
      }
      const facts = extractCatalogFacts(payload);
      if (facts.barcode) {
        catalogFactCache.set(cleanPlid, { fetchedAt: Date.now(), facts });
        return facts;
      }
      if (hasCompleteCatalogFacts(facts) && !completeFactsFallback) {
        completeFactsFallback = facts;
      }
    }
    if (completeFactsFallback) {
      catalogFactCache.set(cleanPlid, { fetchedAt: Date.now(), facts: completeFactsFallback });
      return completeFactsFallback;
    }
    return null;
  } catch (_) {
    return null;
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
  const requestedQuantity = positiveIntegerOrNull(quantity);
  if (requestedQuantity == null) {
    return {
      ok: false,
      code: "STOCK_QUANTITY_SKIPPED",
      message: "未填写库存数量，已跳过库存设置",
    };
  }
  if (!merchantWarehouseId) {
    return {
      ok: false,
      code: "LEADTIME_STOCK_SKIPPED",
      message: "店铺未配置或未开启 Leadtime 库存权限，已跳过库存设置",
    };
  }
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
            quantity: requestedQuantity,
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
      const message = error instanceof Error ? error.message : String(error);
      if (
        status === 400 ||
        status === 403 ||
        /leadtime|merchant.?warehouse|warehouse|stock|permission|forbidden|not allowed|unauthor/i.test(message)
      ) {
        return {
          ok: false,
          code: "LEADTIME_STOCK_SKIPPED",
          message: "店铺未开启 Leadtime 库存权限，已跳过库存设置，仅保留上架报价",
        };
      }
      return {
        ok: false,
        code: "SELLER_PORTAL_PATCH_FAILED",
        message,
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
      message: `${offerLabel} 已创建；店铺未开启 Leadtime 库存权限，已跳过库存设置`,
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
  const requestedQuantity = positiveIntegerOrNull(taskInfo.quantity);

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
      requestedQuantity == null &&
      !patchAttempted
    ) {
      patchAttempted = true;
      patchMessage = "未填写库存数量，已跳过库存设置";
    }

    if (
      lastStatus?.offer_id &&
      lastStatus.needs_buyable_patch &&
      lastStatus.can_auto_make_buyable &&
      requestedQuantity != null &&
      !patchAttempted
    ) {
      patchAttempted = true;
      const patchResult = await applySellerBuyablePatch({
        offerId: lastStatus.offer_id,
        quantity: requestedQuantity,
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

async function runListNowLifecycleInBackground(taskInfo, settings, tabId) {
  let automation = null;
  try {
    automation = await automateListNowLifecycle(taskInfo);
  } catch (error) {
    automation = {
      outcome: "pending",
      message: error instanceof Error ? error.message : String(error),
      taskId: taskInfo.task_id,
    };
  }

  const listingCenterUrl = buildListingCenterUrl(settings.erpBaseUrl, automation);
  const result = {
    ...automation,
    listingCenterUrl,
    openedListingCenter: false,
  };

  if (tabId) {
    try {
      await chrome.tabs.sendMessage(tabId, {
        type: "xh:list-now-result",
        automation: result,
      });
    } catch (_) {
      // The product tab may have navigated away; ERP still has the listing record.
    }
  }
}

chrome.runtime.onInstalled.addListener(() => {
  void refreshProductInjectionState({ forceInjectOpenTabs: true });
});

chrome.runtime.onStartup.addListener(() => {
  void refreshProductInjectionState({ forceInjectOpenTabs: true });
});

void refreshProductInjectionState({ forceInjectOpenTabs: true });

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
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

      if (message?.type === "xh:bind-erp-session") {
        sendResponse({
          ok: true,
          data: await bindErpSessionFromWeb({ openIfNeeded: Boolean(message.openIfNeeded) }),
        });
        return;
      }

      if (message?.type === "xh:get-seller-status") {
        sendResponse({ ok: true, data: await getSellerPortalStatus() });
        return;
      }

      if (message?.type === "xh:open-erp") {
        await openOrFocusErpWeb();
        sendResponse({ ok: true });
        return;
      }

      if (message?.type === "xh:open-seller-center") {
        await openSellerPortal();
        sendResponse({ ok: true });
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
        const suppliedFacts = {
          actualWeightKg: positiveNumberOrNull(message.actualWeightKg),
          lengthCm: positiveNumberOrNull(message.lengthCm),
          widthCm: positiveNumberOrNull(message.widthCm),
          heightCm: positiveNumberOrNull(message.heightCm),
        };
        const sellerCatalogFacts =
          message.forceRefreshFacts && !hasCompleteCatalogFacts(suppliedFacts)
            ? await fetchSellerCatalogFacts(message.plid)
            : null;
        const payload = {
          store_id: message.storeId || settings.defaultStoreId,
          plid: message.plid,
          title: message.title || null,
          category_path: message.categoryPath || null,
          barcode: cleanCatalogBarcode(message.barcode) ?? sellerCatalogFacts?.barcode ?? null,
          gtin: cleanCatalogBarcode(message.gtin) ?? sellerCatalogFacts?.barcode ?? null,
          air_freight_unit_cny_per_kg: positiveNumberOrNull(message.airFreightUnitCnyPerKg),
          purchase_price_cny: positiveNumberOrNull(message.purchasePriceCny),
          sale_price_zar: positiveNumberOrNull(message.salePriceZar),
          actual_weight_kg: suppliedFacts.actualWeightKg ?? sellerCatalogFacts?.actualWeightKg ?? null,
          length_cm: suppliedFacts.lengthCm ?? sellerCatalogFacts?.lengthCm ?? null,
          width_cm: suppliedFacts.widthCm ?? sellerCatalogFacts?.widthCm ?? null,
          height_cm: suppliedFacts.heightCm ?? sellerCatalogFacts?.heightCm ?? null,
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
        const sellerCatalogFacts = await fetchSellerCatalogFacts(message.plid, { requireBarcode: true });
        const payload = {
          store_id: message.storeId || settings.defaultStoreId,
          plid: message.plid,
          title: message.title || null,
          barcode: cleanCatalogBarcode(message.barcode) ?? sellerCatalogFacts?.barcode ?? null,
          gtin: cleanCatalogBarcode(message.gtin) ?? sellerCatalogFacts?.barcode ?? null,
          sale_price_zar: message.salePriceZar ?? null,
          quantity: positiveIntegerOrNull(message.quantity),
        };
        const data = await postJson("/api/extension/list-now", payload);

        sendResponse({
          ok: true,
          data: {
            ...data,
            automation: {
              outcome: "queued",
              terminal: false,
              message: "List-now task queued",
              taskId: data.task_id,
              storeId: payload.store_id,
              listingCenterUrl: null,
              openedListingCenter: false,
            },
          },
        });
        await runListNowLifecycleInBackground(
          {
            task_id: data.task_id,
            quantity: payload.quantity,
          },
          settings,
          sender?.tab?.id,
        );
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
