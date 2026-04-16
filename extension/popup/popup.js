const statusCard = document.getElementById('status-card');
const statusDot = document.getElementById('status-dot');
const statusLabel = document.getElementById('status-label');
const statusDetail = document.getElementById('status-detail');
const storeDetail = document.getElementById('store-detail');
const statsSection = document.getElementById('stats-section');
const countValue = document.getElementById('count-value');
const listCountValue = document.getElementById('list-count-value');
const errorSection = document.getElementById('error-section');
const historySection = document.getElementById('history-section');
const historyCount = document.getElementById('history-count');
const historyList = document.getElementById('history-list');
const connectBtn = document.getElementById('connect-btn');
const openErpBtn = document.getElementById('open-erp-btn');
const disconnectBtn = document.getElementById('disconnect-btn');

const ERP_AUTH_URLS = [
    'http://localhost/extension/authorize',
    'https://43.156.151.68/extension/authorize',
];

function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function formatCreatedAt(value) {
    if (!value) {
        return '时间未知';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
        return String(value);
    }
    return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    }).format(date);
}

function getHistoryDisplayStatus(item) {
    const rawStatus = String(item?.status || '').trim();
    const status = rawStatus.toLowerCase();
    if (status === 'failed' || item?.error_code || item?.error_msg) {
        return { label: rawStatus || '失败', tone: 'failed' };
    }
    if (['queued', 'dispatching', 'processing', 'running'].includes(status)) {
        return { label: rawStatus || '处理中', tone: status === 'queued' ? 'queued' : 'processing' };
    }
    if (['submitted', 'success', 'succeeded', 'completed', 'done'].includes(status)) {
        return { label: rawStatus || '已提交', tone: 'success' };
    }
    return { label: rawStatus || '未知', tone: 'success' };
}

function getActionTypeLabel(actionType) {
    const value = String(actionType || '').trim();
    switch (value) {
        case 'list_now':
            return '一键上架';
        default:
            return value || '动作';
    }
}

function buildHistoryItem(item) {
    const displayStatus = getHistoryDisplayStatus(item);
    const actionTypeLabel = getActionTypeLabel(item?.action_type);
    const actionId = item?.id ? String(item.id) : '';
    const offerId = item?.offer_id ? String(item.offer_id) : '';
    const taskId = item?.task_id ? String(item.task_id) : '';
    const statusText = displayStatus.label;
    const metaParts = [
        `类型：${escapeHtml(actionTypeLabel)}`,
        actionId ? `动作 #${escapeHtml(actionId)}` : '',
        offerId ? `Offer ${escapeHtml(offerId)}` : '',
        taskId ? `任务 ${escapeHtml(taskId)}` : '',
        item?.created_at ? escapeHtml(formatCreatedAt(item.created_at)) : '',
    ].filter(Boolean);
    const reasonParts = [];
    if (item?.error_code) {
        reasonParts.push(`错误码：${escapeHtml(item.error_code)}`);
    }
    if (item?.error_msg) {
        reasonParts.push(`原因：${escapeHtml(item.error_msg)}`);
    }

    const title = escapeHtml(item?.title || item?.plid || '未命名动作');

    return `
        <div class="history-item ${displayStatus.tone}">
            <div class="history-topline">
                <div class="history-main">${escapeHtml(actionTypeLabel)} · ${title}</div>
                <div class="history-badge ${displayStatus.tone}">${escapeHtml(statusText)}</div>
            </div>
            <div class="history-meta">
                ${metaParts.map((part) => `<span>${part}</span>`).join('')}
            </div>
            ${reasonParts.length ? `<div class="history-note">${reasonParts.join(' · ')}</div>` : ''}
        </div>
    `;
}

async function loadRecentHistory() {
    historySection.style.display = 'block';
    historyCount.textContent = '加载中...';
    historyList.innerHTML = '<div class="history-empty">正在加载最近记录...</div>';

    try {
        const response = await chrome.runtime.sendMessage({
            type: 'GET_LIST_HISTORY',
            payload: { limit: 5 },
        });

        if (!response || !response.ok) {
            const message = response?.error || '暂无最近记录';
            historyCount.textContent = '';
            historyList.innerHTML = `<div class="history-empty">${escapeHtml(message)}</div>`;
            return;
        }

        const actions = Array.isArray(response.actions) ? response.actions : [];
        historyCount.textContent = actions.length ? `最近 ${actions.length} 条` : '';
        if (!actions.length) {
            historyList.innerHTML = '<div class="history-empty">暂无上架记录</div>';
            return;
        }

        historyList.innerHTML = actions.map((item) => buildHistoryItem(item)).join('');
    } catch (err) {
        historyCount.textContent = '';
        historyList.innerHTML = `<div class="history-empty">${escapeHtml(err?.message || '加载失败')}</div>`;
    }
}

async function refreshStatus() {
    try {
        const response = await chrome.runtime.sendMessage({ type: 'GET_STATUS' });

        if (response && response.connected) {
            statusCard.className = 'status-card connected';
            statusDot.className = 'status-dot green';
            statusLabel.textContent = '已连接';
            statusDetail.textContent = response.user ? `用户：${response.user}` : '小黑ERP';
            const storeCount = Array.isArray(response.stores) ? response.stores.length : 0;
            if (response.store && response.store.name) {
                storeDetail.style.display = 'block';
                storeDetail.textContent = storeCount > 1
                    ? `当前店铺：${response.store.name} · 共 ${storeCount} 个店铺`
                    : `当前店铺：${response.store.name}`;
            } else if (storeCount > 0) {
                storeDetail.style.display = 'block';
                storeDetail.textContent = `已绑定 ${storeCount} 个店铺`;
            } else {
                storeDetail.style.display = 'none';
                storeDetail.textContent = '';
            }

            statsSection.style.display = 'grid';
            countValue.textContent = response.todayActions || '0';
            listCountValue.textContent = response.todayListNow || '0';

            connectBtn.style.display = 'none';
            openErpBtn.style.display = 'block';
            disconnectBtn.style.display = 'block';
            errorSection.style.display = 'none';
            await loadRecentHistory();
        } else {
            statusCard.className = 'status-card disconnected';
            statusDot.className = 'status-dot red';
            statusLabel.textContent = '未连接';
            statusDetail.textContent = '请先连接小黑ERP';
            storeDetail.style.display = 'none';
            storeDetail.textContent = '';
            statsSection.style.display = 'none';
            historySection.style.display = 'none';
            connectBtn.style.display = 'block';
            openErpBtn.style.display = 'none';
            disconnectBtn.style.display = 'none';

            if (response && response.error) {
                errorSection.textContent = response.error;
                errorSection.style.display = 'block';
            } else {
                errorSection.style.display = 'none';
            }
        }
    } catch (err) {
        statusLabel.textContent = '错误';
        statusDetail.textContent = err.message;
        storeDetail.style.display = 'none';
        historySection.style.display = 'none';
        errorSection.textContent = err.message;
        errorSection.style.display = 'block';
    }
}

connectBtn.addEventListener('click', async () => {
    const url = ERP_AUTH_URLS[0];
    await chrome.tabs.create({ url });
    window.close();
});

openErpBtn.addEventListener('click', async () => {
    const data = await chrome.storage.local.get(['erpBaseUrl']);
    const erpBaseUrl = data.erpBaseUrl || ERP_AUTH_URLS[0].replace('/extension/authorize', '/');
    await chrome.tabs.create({ url: erpBaseUrl });
    window.close();
});

disconnectBtn.addEventListener('click', async () => {
    await chrome.storage.local.remove(['token', 'userName', 'expiresAt', 'erpBaseUrl']);
    refreshStatus();
});

document.addEventListener('DOMContentLoaded', () => {
    refreshStatus();
});
