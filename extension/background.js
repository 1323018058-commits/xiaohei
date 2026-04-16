/**
 * 小黑ERP Takealot 助手 — Background Service Worker
 *
 * 负责：
 * 1. 维护扩展授权 token
 * 2. 调用 ERP 扩展接口
 * 3. 返回连接状态 / 店铺列表 / 今日操作统计
 * 4. 转发利润测算与一键上架请求
 */

const ERP_BASE_URLS = [
    'http://localhost',
    'https://43.156.151.68',
];
const AUTH_REDEEM_PATH = '/api/extension/redeem-code';
const PREFERRED_STORE_KEY = 'talerpPreferredStoreId';

let erpBaseUrl = ERP_BASE_URLS[0];

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (!message || !message.type) {
        sendResponse({ ok: false, error: '无效消息' });
        return true;
    }

    switch (message.type) {
        case 'AUTH_CODE':
            handleAuthCode(message).then(sendResponse);
            return true;
        case 'GET_STATUS':
            handleGetStatus().then(sendResponse);
            return true;
        case 'GET_PRICING_CONFIG':
            handleGetPricingConfig(message).then(sendResponse);
            return true;
        case 'GET_LIST_HISTORY':
            handleGetListHistory(message).then(sendResponse);
            return true;
        case 'CALCULATE_PROFIT':
            handleCalculateProfit(message).then(sendResponse);
            return true;
        case 'LIST_NOW':
            handleListNow(message).then(sendResponse);
            return true;
        default:
            sendResponse({ ok: false, error: `未知消息类型: ${message.type}` });
            return true;
    }
});

async function getStoredAuth() {
    const data = await chrome.storage.local.get(['token', 'userName', 'expiresAt', 'erpBaseUrl']);
    if (data.erpBaseUrl) erpBaseUrl = data.erpBaseUrl;
    return data;
}

async function clearStoredAuth() {
    await chrome.storage.local.remove(['token', 'userName', 'expiresAt', 'erpBaseUrl']);
}

function normalizeApiPayload(payload) {
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
        return payload;
    }

    const detail = payload.detail;
    if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
        return {
            ...payload,
            error_code: payload.error_code || detail.error_code || '',
            message: payload.message || detail.message || '',
            error: payload.error || detail.message || '',
        };
    }

    if (Array.isArray(detail)) {
        const validationMessage = detail
            .map((item) => item?.msg)
            .filter(Boolean)
            .join('; ');
        return {
            ...payload,
            error: payload.error || validationMessage || '',
        };
    }

    if (typeof detail === 'string') {
        return {
            ...payload,
            error: payload.error || detail,
        };
    }

    return payload;
}

async function authedJsonFetch(path, options = {}) {
    const auth = await getStoredAuth();
    const token = auth.token || '';
    if (!token) {
        return {
            ok: false,
            error: '未连接 ERP，请先授权',
            error_code: 'EXTENSION_TOKEN_MISSING',
            status: 401,
            http_status: 401,
        };
    }

    try {
        const headers = new Headers(options.headers || {});
        headers.set('Authorization', `Bearer ${token}`);
        if (options.body && !headers.has('Content-Type')) {
            headers.set('Content-Type', 'application/json');
        }
        const response = await fetch(`${erpBaseUrl}${path}`, {
            ...options,
            headers,
        });
        const payload = normalizeApiPayload(await response.json().catch(() => ({})));
        if (response.status === 401) {
            await clearStoredAuth();
        }
        return {
            ...payload,
            status: payload?.status ?? response.status,
            http_status: response.status,
            ok: response.ok && payload.ok !== false,
        };
    } catch (err) {
        return {
            ok: false,
            error: `网络错误: ${err.message}`,
            error_code: 'NETWORK_ERROR',
            status: 0,
            http_status: 0,
        };
    }
}

function extractRedeemToken(payload) {
    return (
        payload?.token ||
        payload?.access_token ||
        payload?.accessToken ||
        payload?.data?.token ||
        payload?.data?.access_token ||
        payload?.data?.accessToken ||
        ''
    );
}

function extractRedeemUserName(payload) {
    return (
        payload?.user?.name ||
        payload?.user_name ||
        payload?.username ||
        payload?.data?.user?.name ||
        payload?.data?.user_name ||
        payload?.data?.username ||
        '用户'
    );
}

function extractRedeemExpiresAt(payload) {
    return (
        payload?.expires_at ||
        payload?.expiresAt ||
        payload?.data?.expires_at ||
        payload?.data?.expiresAt ||
        ''
    );
}

async function handleAuthCode(message) {
    const authCode = message?.authCode || '';
    if (!authCode) {
        return { ok: false, error: '缺少 auth_code' };
    }

    if (message.sourceUrl) {
        for (const baseUrl of ERP_BASE_URLS) {
            if (message.sourceUrl.startsWith(baseUrl)) {
                erpBaseUrl = baseUrl;
                break;
            }
        }
    }

    try {
        const response = await fetch(`${erpBaseUrl}${AUTH_REDEEM_PATH}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ auth_code: authCode }),
        });

        const payload = normalizeApiPayload(await response.json().catch(() => ({})));
        const token = extractRedeemToken(payload);

        if (!response.ok || payload.ok === false) {
            return {
                ok: false,
                error: payload.error || payload.message || `兑换失败（HTTP ${response.status}）`,
                error_code: payload.error_code || payload.errorCode || '',
                status: payload?.status ?? response.status,
                http_status: response.status,
            };
        }

        if (!token) {
            return {
                ok: false,
                error: '兑换成功但未返回 token',
                status: payload?.status ?? response.status,
                http_status: response.status,
            };
        }

        await chrome.storage.local.set({
            token,
            userName: extractRedeemUserName(payload),
            expiresAt: extractRedeemExpiresAt(payload),
            erpBaseUrl,
        });

        return {
            ok: true,
            user: { name: extractRedeemUserName(payload) },
            expiresAt: extractRedeemExpiresAt(payload),
        };
    } catch (err) {
        return {
            ok: false,
            error: `网络错误: ${err.message}`,
            error_code: 'NETWORK_ERROR',
            status: 0,
            http_status: 0,
        };
    }
}

async function handleGetStatus() {
    const auth = await getStoredAuth();
    if (!auth.token) {
        return { connected: false };
    }

    if (auth.expiresAt) {
        const expiresDate = new Date(auth.expiresAt);
        if (expiresDate < new Date()) {
            await clearStoredAuth();
            return { connected: false, error: 'Token 已过期' };
        }
    }

    const payload = await authedJsonFetch('/api/extension/status', { method: 'GET' });
    if (!payload.ok) {
        return {
            connected: false,
            error: payload.error || '无法连接 ERP',
        };
    }

    return {
        connected: true,
        user: payload.user?.name || auth.userName || '用户',
        userId: payload.user?.id || null,
        store: payload.store || null,
        stores: payload.stores || [],
        todayActions: payload.today_actions || 0,
        todayListNow: payload.today_list_now || 0,
    };
}

async function handleCalculateProfit(message) {
    return authedJsonFetch('/api/extension/calculate-profit', {
        method: 'POST',
        body: JSON.stringify(message.payload || {}),
    });
}

async function handleGetPricingConfig(message) {
    let storeId = message?.payload?.storeId;
    if (!storeId) {
        const stored = await chrome.storage.local.get([PREFERRED_STORE_KEY]);
        storeId = stored?.[PREFERRED_STORE_KEY];
    }

    if (!storeId) {
        const status = await authedJsonFetch('/api/extension/status', { method: 'GET' });
        storeId = status?.store?.id;
    }

    const resolvedStoreId = parseInt(storeId || '0', 10);
    if (!resolvedStoreId) {
        return { ok: false, error: '缺少 store_id', status: 400 };
    }

    return authedJsonFetch(`/api/extension/pricing-config?store_id=${resolvedStoreId}`, {
        method: 'GET',
    });
}

async function handleGetListHistory(message) {
    const rawLimit = Number.parseInt(message?.payload?.limit || '5', 10);
    const limit = Number.isFinite(rawLimit) ? Math.min(Math.max(rawLimit, 1), 20) : 5;

    return authedJsonFetch(`/api/extension/list-history?limit=${limit}`, {
        method: 'GET',
    });
}

async function handleListNow(message) {
    return authedJsonFetch('/api/extension/list-now', {
        method: 'POST',
        body: JSON.stringify(message.payload || {}),
    });
}
