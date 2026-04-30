const DEFAULT_ERP_BASE_URL = "http://127.0.0.1:8000";

function getEl(id) {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`弹窗缺少节点: ${id}`);
  }
  return element;
}

function setConnection(mode, label) {
  getEl("connectionState").dataset.mode = mode;
  getEl("connectionLabel").textContent = label;
}

function setStatus(message, mode = "default") {
  const status = getEl("status");
  status.textContent = message;
  status.dataset.mode = mode;
}

function setBusy(isBusy) {
  for (const id of ["loginButton", "refreshButton", "logoutButton", "storeSelect", "defaultStockQty"]) {
    const element = document.getElementById(id);
    if (element) {
      element.disabled = isBusy;
    }
  }
}

function sendMessage(message) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendMessage(message, (response) => {
        const lastError = chrome.runtime.lastError;
        if (lastError) {
          reject(new Error(lastError.message || "扩展后台未响应，请在扩展管理页点重新加载。"));
          return;
        }
        resolve(response);
      });
    } catch (error) {
      reject(error);
    }
  });
}

function normalizeBaseUrl(value) {
  return String(value || "").trim().replace(/\/+$/, "");
}

function renderLoginView(settings = {}) {
  getEl("title").textContent = "扩展连接";
  getEl("loginView").classList.remove("hidden");
  getEl("connectedView").classList.add("hidden");
  setConnection("default", "未连接");
}

function renderConnectedView(session) {
  const stores = Array.isArray(session.stores) ? session.stores : [];

  getEl("title").textContent = "已连接";
  getEl("loginView").classList.add("hidden");
  getEl("connectedView").classList.remove("hidden");
  setConnection("success", "已连接");

  getEl("userMeta").textContent = `${session.user?.username || "已登录"} · ${stores.length} 个店铺`;

  const select = getEl("storeSelect");
  select.innerHTML = "";
  for (const store of stores) {
    const option = document.createElement("option");
    option.value = store.store_id;
    option.textContent = store.name || store.store_id;
    if (store.store_id === session.defaultStoreId) {
      option.selected = true;
    }
    select.appendChild(option);
  }

  getEl("defaultStockQty").value = session.defaultStockQty || "";
}

async function loadSession() {
  const response = await sendMessage({ type: "xh:get-session" });
  if (!response?.ok) {
    throw new Error(response?.error || "读取会话失败");
  }
  return response.data;
}

async function loadPopup() {
  setBusy(true);
  try {
    const session = await loadSession();
    if (session?.connected) {
      renderConnectedView(session);
      setStatus("扩展已连接。打开 Takealot 商品页后，页面右下角会出现小黑工具条。", "success");
      return;
    }

    const settingsResponse = await sendMessage({ type: "xh:get-settings" });
    if (!settingsResponse?.ok) {
      throw new Error(settingsResponse?.error || "读取配置失败");
    }
    renderLoginView(settingsResponse.data);
    setStatus("未连接时不会向 Takealot 页面注入任何内容。");
  } finally {
    setBusy(false);
  }
}

async function login() {
  const username = getEl("username").value.trim();
  const password = getEl("password").value.trim();
  if (!username || !password) {
    setConnection("error", "缺配置");
    setStatus("账号、密码都不能为空。", "error");
    return;
  }

  setBusy(true);
  setStatus("正在连接 ERP...");
  try {
    const response = await sendMessage({
      type: "xh:login",
      username,
      password,
    });
    if (!response?.ok) {
      throw new Error(response?.error || "登录失败");
    }
    const session = await loadSession();
    renderConnectedView(session);
    setStatus("连接成功。现在可以回到 Takealot 商品页测试上架流程。", "success");
  } finally {
    setBusy(false);
  }
}

async function refreshSession() {
  setBusy(true);
  try {
    const session = await loadSession();
    if (session?.connected) {
      renderConnectedView(session);
      setStatus("连接状态已刷新。", "success");
      return;
    }
    renderLoginView();
    setConnection("error", "已断开");
    setStatus("登录已失效，请重新连接 ERP。", "error");
  } finally {
    setBusy(false);
  }
}

async function logout() {
  setBusy(true);
  try {
    await sendMessage({ type: "xh:logout" });
    renderLoginView();
    setStatus("已断开连接，页面将不再注入。", "success");
  } finally {
    setBusy(false);
  }
}

async function updateStoreSelection() {
  const storeId = getEl("storeSelect").value;
  const response = await sendMessage({
    type: "xh:set-store",
    storeId,
  });
  if (!response?.ok) {
    throw new Error(response?.error || "切换店铺失败");
  }
  setStatus("默认店铺已更新。", "success");
}

async function updateDefaultStock() {
  const defaultStockQty = getEl("defaultStockQty").value.trim();
  const response = await sendMessage({
    type: "xh:set-default-stock",
    defaultStockQty,
  });
  if (!response?.ok) {
    throw new Error(response?.error || "更新默认直邮库存失败");
  }
  setStatus("默认直邮库存已更新。", "success");
}

getEl("loginButton").addEventListener("click", () => {
  login().catch((error) => {
    setConnection("error", "连接失败");
    setStatus(error instanceof Error ? error.message : String(error), "error");
    setBusy(false);
  });
});

getEl("refreshButton").addEventListener("click", () => {
  refreshSession().catch((error) => {
    setStatus(error instanceof Error ? error.message : String(error), "error");
    setBusy(false);
  });
});

getEl("logoutButton").addEventListener("click", () => {
  logout().catch((error) => {
    setStatus(error instanceof Error ? error.message : String(error), "error");
    setBusy(false);
  });
});

getEl("storeSelect").addEventListener("change", () => {
  updateStoreSelection().catch((error) => {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  });
});

getEl("defaultStockQty").addEventListener("change", () => {
  updateDefaultStock().catch((error) => {
    setStatus(error instanceof Error ? error.message : String(error), "error");
  });
});

loadPopup().catch((error) => {
  setConnection("error", "加载失败");
  setStatus(error instanceof Error ? error.message : String(error), "error");
  setBusy(false);
});
