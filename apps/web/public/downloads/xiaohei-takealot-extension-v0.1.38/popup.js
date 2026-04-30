const DEFAULT_ERP_BASE_URL = "http://127.0.0.1:8000";
const DEFAULT_ERP_WEB_URL = "http://127.0.0.1:3001";

let lastSession = null;
let busy = false;

function getEl(id) {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`弹窗缺少节点: ${id}`);
  }
  return element;
}

function setStatus(message, mode = "default") {
  const status = getEl("status");
  status.textContent = message;
  status.dataset.mode = mode;
}

function setBusy(isBusy) {
  busy = isBusy;
  for (const id of ["refreshButton", "openSellerButton", "openErpButton", "logoutButton"]) {
    getEl(id).disabled = isBusy;
  }
}

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        const lastError = chrome.runtime.lastError;
        if (lastError) {
          reject(new Error(lastError.message || "扩展后台未响应，请在扩展管理页重新加载。"));
          return;
        }
        resolve(response);
      });
    } catch (error) {
      reject(error);
    }
  });
}

function renderErp(session) {
  const card = getEl("erpCard");
  const badge = getEl("erpBadge");
  const text = getEl("erpText");
  if (session?.connected) {
    const stores = Array.isArray(session.stores) ? session.stores : [];
    card.dataset.mode = "success";
    badge.textContent = "已连接";
    text.textContent = `${session.user?.username || "已登录"} · ${stores.length} 个店铺`;
    getEl("logoutButton").classList.remove("hidden");
    return;
  }
  card.dataset.mode = "error";
  badge.textContent = "未连接";
  text.textContent = formatErpReason(session);
  getEl("logoutButton").classList.add("hidden");
}

function formatErpReason(session) {
  const reason = session?.reason || "";
  if (!reason || reason === "missing_session") {
    return "请先在同一个浏览器登录 ERP，登录后点刷新状态";
  }
  return reason;
}

function renderSeller(status) {
  const card = getEl("sellerCard");
  const badge = getEl("sellerBadge");
  const text = getEl("sellerText");
  if (status?.connected) {
    card.dataset.mode = "success";
    badge.textContent = "已登录";
    text.textContent = "已检测到 Seller Center 登录态";
    return;
  }
  card.dataset.mode = "warn";
  badge.textContent = "未检测";
  text.textContent = "上架和重量尺寸查询前，请先登录 Takealot Seller";
}

async function loadStatus() {
  if (busy) {
    return;
  }
  setBusy(true);
  setStatus("正在检测登录状态...");
  try {
    const [sessionResponse, sellerResponse] = await Promise.all([
      sendMessage({ type: "xh:get-session" }),
      sendMessage({ type: "xh:get-seller-status" }),
    ]);
    if (!sessionResponse?.ok) {
      throw new Error(sessionResponse?.error || "读取 ERP 状态失败");
    }
    if (!sellerResponse?.ok) {
      throw new Error(sellerResponse?.error || "读取 Takealot 登录态失败");
    }
    let session = sessionResponse.data || null;
    if (!session?.connected) {
      setStatus("正在读取 ERP 网页登录态并授权插件...");
      const bindResponse = await sendMessage({ type: "xh:bind-erp-session" });
      if (bindResponse?.ok && bindResponse.data) {
        session = bindResponse.data;
      }
    }
    lastSession = session;
    renderErp(lastSession);
    renderSeller(sellerResponse.data || null);
    if (lastSession?.connected) {
      setStatus("ERP 已连接。业务参数请在商品页点击“一键上架”后填写。", "success");
    } else {
      setStatus("插件未拿到 ERP 授权。请在同一个浏览器打开 ERP 登录，登录后点刷新状态。", "error");
    }
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setBusy(false);
  }
}

async function logout() {
  setBusy(true);
  try {
    await sendMessage({ type: "xh:logout" });
    lastSession = null;
    renderErp({ connected: false, reason: "已断开 ERP 连接" });
    setStatus("已断开 ERP，Takealot 页面将停止注入。", "success");
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setBusy(false);
  }
}

async function openSeller() {
  const response = await sendMessage({ type: "xh:open-seller-center" });
  if (!response?.ok) {
    throw new Error(response?.error || "打开 Seller Center 失败");
  }
  setStatus("已打开 Takealot Seller，登录后回来刷新状态。", "success");
}

async function openErp() {
  const response = await sendMessage({ type: "xh:open-erp" });
  if (!response?.ok) {
    const url = getErpWebUrl(lastSession?.erpBaseUrl);
    await chrome.tabs.create({ url, active: true });
  }
  setStatus("已打开 ERP。登录完成后回到插件点刷新状态。", "success");
}

function getErpWebUrl(apiBaseUrl) {
  try {
    const url = new URL(apiBaseUrl || DEFAULT_ERP_BASE_URL);
    if ((url.hostname === "127.0.0.1" || url.hostname === "localhost") && url.port === "8000") {
      url.port = "3001";
      url.pathname = "/";
      url.search = "";
      url.hash = "";
      return url.toString();
    }
    if (url.pathname.startsWith("/api")) {
      url.pathname = "/";
      url.search = "";
      url.hash = "";
      return url.toString();
    }
    return DEFAULT_ERP_WEB_URL;
  } catch {
    return DEFAULT_ERP_WEB_URL;
  }
}

getEl("refreshButton").addEventListener("click", () => {
  void loadStatus();
});

getEl("logoutButton").addEventListener("click", () => {
  void logout();
});

getEl("openSellerButton").addEventListener("click", () => {
  openSeller().catch((error) => setStatus(error instanceof Error ? error.message : String(error), "error"));
});

getEl("openErpButton").addEventListener("click", () => {
  openErp().catch((error) => setStatus(error instanceof Error ? error.message : String(error), "error"));
});

void loadStatus();
