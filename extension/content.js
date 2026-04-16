/**
 * 小黑ERP Takealot 助手 — Content Script
 *
 * V1 聚焦两件事：
 * 1. 详情页利润测算
 * 2. 详情页一键上架
 */

(() => {
    'use strict';

    const PLID_URL_REGEX = /PLID(\d+)/i;
    const STYLE_ID = 'talerp-styles';
    const PANEL_ID = 'talerp-inline-section';
    const PREFERRED_STORE_KEY = 'talerpPreferredStoreId';
    const DEFAULT_RATE_HINT = 'JHB:20 / CPT / DBN:30';
    const DEFAULT_SIZE_RULE = '体积重 = 长 × 宽 × 高 / 6000';

    let latestProfitResult = null;
    let extensionStatusCache = null;
    let extensionStatusAt = 0;
    let pricingConfigCache = null;
    let pricingConfigAt = 0;
    let pricingConfigStoreId = '';
    let lastUrl = window.location.href;
    let lastPlid = extractPlidFromUrl();

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function formatZar(value) {
        const num = Number(value);
        return Number.isFinite(num) && num > 0 ? `R ${num.toFixed(2)}` : '未识别';
    }

    function extractPlidFromUrl() {
        const match = window.location.href.match(PLID_URL_REGEX);
        return match ? match[1] : null;
    }

    function parsePriceFromText(text) {
        const cleaned = String(text || '').replace(/[R\s,]/g, '').trim();
        const num = parseFloat(cleaned);
        return Number.isFinite(num) ? num : 0;
    }

    function extractDetailTitle() {
        const titleEl =
            document.querySelector('[data-ref="product-title"]') ||
            document.querySelector('h1.product-title') ||
            document.querySelector('h1');
        const text = titleEl?.textContent?.trim();
        if (text && text.length < 500) {
            return text;
        }
        return '';
    }

    function extractDetailImageUrl() {
        const imageEl =
            document.querySelector('[data-ref="product-gallery"] img') ||
            document.querySelector('.pdp-gallery img') ||
            document.querySelector('.product-gallery img');
        const directSrc = imageEl?.getAttribute('src') || imageEl?.getAttribute('data-src');
        if (directSrc && directSrc.startsWith('http')) {
            return directSrc;
        }
        const ogImage = document.querySelector('meta[property="og:image"]');
        const ogSrc = ogImage?.getAttribute('content');
        return ogSrc && ogSrc.startsWith('http') ? ogSrc : '';
    }

    function extractDetailBarcode() {
        const labels = document.querySelectorAll('span, div, td, dt');
        for (const label of labels) {
            if (label.textContent?.trim() !== 'Barcode') {
                continue;
            }
            const sibling = label.nextElementSibling;
            const directValue = sibling?.textContent?.trim();
            if (directValue && directValue.length < 100) {
                return directValue;
            }
            const parent = label.parentElement;
            if (!parent) {
                continue;
            }
            const children = Array.from(parent.children);
            const index = children.indexOf(label);
            if (index >= 0 && index + 1 < children.length) {
                const fallbackValue = children[index + 1]?.textContent?.trim();
                if (fallbackValue && fallbackValue.length < 100) {
                    return fallbackValue;
                }
            }
        }
        return '';
    }

    function detectBrandInScope(scope) {
        const brandLink = scope?.querySelector?.('a[href*="filter=Brand:"]');
        const brandName = brandLink?.textContent?.trim();
        return brandName || '';
    }

    function extractSellingPriceZAR() {
        const reliableSelectors = [
            '[data-testid="price"]',
            '[data-ref="buybox-price"]',
            '[data-ref="product-price"]',
            '.buybox-module-price',
            '.pdp-price',
            '.product-price',
        ];

        for (const selector of reliableSelectors) {
            const el = document.querySelector(selector);
            const num = parsePriceFromText(el?.textContent || '');
            if (num > 0) {
                return num;
            }
        }

        const buybox = document.querySelector('[class*="buybox"]');
        if (buybox) {
            const spans = buybox.querySelectorAll('span');
            for (const span of spans) {
                const text = span.textContent?.trim() || '';
                if (!/^R\s?[\d,.\s]+$/.test(text)) {
                    continue;
                }
                const num = parsePriceFromText(text);
                if (num > 0) {
                    return num;
                }
            }
        }

        const metaPrice = document.querySelector('meta[property="product:price:amount"]');
        const metaValue = parseFloat(metaPrice?.getAttribute('content') || '');
        return Number.isFinite(metaValue) && metaValue > 0 ? metaValue : 0;
    }

    async function sendRuntimeMessage(type, payload = undefined) {
        try {
            return await chrome.runtime.sendMessage(payload ? { type, payload } : { type });
        } catch (err) {
            return {
                ok: false,
                connected: false,
                error: err?.message || '插件通信失败',
            };
        }
    }

    async function getExtensionStatus(force = false) {
        const cacheMs = 60 * 1000;
        if (!force && extensionStatusCache && Date.now() - extensionStatusAt < cacheMs) {
            return extensionStatusCache;
        }
        const response = await sendRuntimeMessage('GET_STATUS');
        extensionStatusCache = response || { connected: false };
        extensionStatusAt = Date.now();
        return extensionStatusCache;
    }

    async function getPricingConfig(force = false, storeId) {
        const cacheMs = 5 * 60 * 1000;
        const activeStoreId = String(storeId || '');
        if (!activeStoreId) {
            return { ok: false, error: '缺少 store_id' };
        }

        if (
            !force &&
            pricingConfigCache &&
            pricingConfigStoreId === activeStoreId &&
            Date.now() - pricingConfigAt < cacheMs
        ) {
            return pricingConfigCache;
        }

        const response = await sendRuntimeMessage('GET_PRICING_CONFIG', { storeId: activeStoreId });
        pricingConfigCache = response || { ok: false };
        pricingConfigAt = Date.now();
        pricingConfigStoreId = activeStoreId;
        return pricingConfigCache;
    }

    async function getPreferredStoreId() {
        try {
            const data = await chrome.storage.local.get([PREFERRED_STORE_KEY]);
            return data?.[PREFERRED_STORE_KEY] ? String(data[PREFERRED_STORE_KEY]) : '';
        } catch (_err) {
            return '';
        }
    }

    async function setPreferredStoreId(storeId) {
        if (!storeId) {
            return;
        }
        try {
            await chrome.storage.local.set({ [PREFERRED_STORE_KEY]: String(storeId) });
        } catch (_err) {
            // 忽略本地存储异常，不影响主流程
        }
    }

    function getListNowStatusCopy(response) {
        const status = String(response?.status || response?.action_status || '').trim().toLowerCase();
        const actionId = response?.action_id ? String(response.action_id) : '';
        const details = [];

        if (actionId) {
            details.push(`动作 ID ${actionId}`);
        }

        switch (status) {
            case 'queued':
                return {
                    buttonText: '排队中',
                    tone: 'warning',
                    message: `请求已进入队列，正在等待处理${details.length ? `（${details.join('，')}）` : ''}。`,
                };
            case 'processing':
                return {
                    buttonText: '处理中',
                    tone: 'warning',
                    message: `请求已提交，当前正在处理中${details.length ? `（${details.join('，')}）` : ''}。`,
                };
            case 'submitted':
                return {
                    buttonText: '已提交',
                    tone: 'success',
                    message: `请求已提交，后端已确认受理${details.length ? `（${details.join('，')}）` : ''}。`,
                };
            case 'recorded':
                return {
                    buttonText: '已记录',
                    tone: 'warning',
                    message: `请求已记录到 ERP，后续会继续处理上架任务${details.length ? `（${details.join('，')}）` : ''}。`,
                };
            default:
                return {
                    buttonText: '已提交',
                    tone: 'success',
                    message: `请求已提交${details.length ? `（${details.join('，')}）` : ''}。`,
                };
        }
    }

    function injectStyles() {
        if (document.getElementById(STYLE_ID)) {
            return;
        }

        const style = document.createElement('style');
        style.id = STYLE_ID;
        style.textContent = `
            .talerp-panel {
                --talerp-blue: #2b67f6;
                --talerp-blue-deep: #1f4fd8;
                --talerp-text: #13233d;
                --talerp-muted: #6d7f9e;
                --talerp-border: #dce7fb;
                --talerp-soft: #f7faff;
                --talerp-success: #16a34a;
                --talerp-warning: #d97706;
                --talerp-danger: #dc2626;
                border: 1px solid var(--talerp-border);
                border-radius: 20px;
                background: linear-gradient(180deg, rgba(255,255,255,.97), rgba(244,248,255,.93));
                color: var(--talerp-text);
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
                box-shadow: 0 16px 34px rgba(91, 121, 182, .15);
                padding: 10px;
                margin-top: 8px;
                line-height: 1.3;
            }

            .talerp-panel * {
                box-sizing: border-box;
            }

            .talerp-panel-header {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                margin-bottom: 6px;
            }

            .talerp-panel-badge {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                min-height: 26px;
                padding: 0 9px;
                border-radius: 999px;
                background: rgba(43,103,246,.08);
                border: 1px solid rgba(43,103,246,.12);
                color: var(--talerp-blue);
                font-size: 10px;
                font-weight: 800;
            }

            .talerp-panel-tools {
                display: flex;
                align-items: center;
                gap: 6px;
            }

            .talerp-detail-toggle,
            .talerp-param-toggle,
            .talerp-panel-toggle {
                border: 1px solid var(--talerp-border);
                background: #fff;
                color: var(--talerp-muted);
                border-radius: 11px;
                min-height: 28px;
                padding: 0 9px;
                font-size: 10px;
                font-weight: 800;
                cursor: pointer;
                flex-shrink: 0;
            }

            .talerp-panel-body.collapsed {
                display: none;
            }

            .talerp-summary-card {
                border: 1px solid var(--talerp-border);
                border-radius: 16px;
                background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(241,246,255,.94));
                padding: 10px;
            }

            .talerp-summary-title {
                font-size: 12px;
                font-weight: 800;
                color: var(--talerp-text);
                line-height: 1.45;
                display: -webkit-box;
                -webkit-box-orient: vertical;
                -webkit-line-clamp: 1;
                overflow: hidden;
            }

            .talerp-summary-meta {
                margin-top: 4px;
                font-size: 10px;
                color: var(--talerp-muted);
                line-height: 1.6;
            }

            .talerp-summary-grid {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 6px;
                margin-top: 6px;
            }

            .talerp-summary-metric {
                padding: 8px;
                border-radius: 12px;
                background: #fff;
                border: 1px solid rgba(220,231,251,.85);
            }

            .talerp-summary-metric span {
                display: block;
                font-size: 10px;
                color: var(--talerp-muted);
                margin-bottom: 3px;
            }

            .talerp-summary-metric strong {
                font-size: 12px;
                font-weight: 800;
                color: var(--talerp-text);
            }

            .talerp-status-row {
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                flex-wrap: wrap;
                margin-top: 6px;
            }

            .talerp-status-pill {
                display: inline-flex;
                align-items: center;
                gap: 6px;
                min-height: 28px;
                padding: 0 10px;
                border-radius: 999px;
                border: 1px solid rgba(43,103,246,.12);
                background: rgba(43,103,246,.08);
                color: var(--talerp-blue);
                font-size: 10px;
                font-weight: 800;
            }

            .talerp-status-pill.connected {
                background: rgba(22,163,74,.10);
                border-color: rgba(22,163,74,.18);
                color: var(--talerp-success);
            }

            .talerp-status-pill.warning {
                background: rgba(217,119,6,.10);
                border-color: rgba(217,119,6,.16);
                color: var(--talerp-warning);
            }

            .talerp-status-text {
                font-size: 10px;
                color: var(--talerp-muted);
                line-height: 1.6;
                text-align: left;
                flex: 1;
            }

            .talerp-grid,
            .talerp-grid-3 {
                display: grid;
                gap: 6px;
                margin-top: 6px;
            }

            .talerp-grid {
                grid-template-columns: 1fr 1fr;
            }

            .talerp-grid-3 {
                grid-template-columns: repeat(3, 1fr);
            }

            .talerp-field {
                min-width: 0;
            }

            .talerp-field label {
                display: block;
                margin-bottom: 3px;
                font-size: 10px;
                font-weight: 700;
                color: #4b5f84;
            }

            .talerp-field input,
            .talerp-field select {
                width: 100%;
                min-width: 0;
                height: 34px;
                padding: 0 9px;
                border-radius: 11px;
                border: 1px solid #d8e3f8;
                background: var(--talerp-soft);
                color: var(--talerp-text);
                font-size: 11px;
                outline: none;
                transition: border-color .2s ease, box-shadow .2s ease, background .2s ease;
            }

            .talerp-field input:focus,
            .talerp-field select:focus {
                border-color: var(--talerp-blue);
                background: #fff;
                box-shadow: 0 0 0 4px rgba(43,103,246,.12);
            }

            .talerp-field-hint {
                margin-top: 6px;
                padding: 7px 9px;
                border-radius: 11px;
                background: rgba(43,103,246,.06);
                border: 1px solid rgba(43,103,246,.10);
                color: #4b5f84;
                font-size: 10px;
                line-height: 1.6;
            }

            .talerp-param-body {
                display: none;
            }

            .talerp-param-body.expanded {
                display: block;
            }

            .talerp-results {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 6px;
                margin-top: 6px;
            }

            .talerp-result-item {
                padding: 8px;
                border-radius: 12px;
                border: 1px solid var(--talerp-border);
                background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(247,250,255,.94));
            }

            .talerp-result-item span {
                display: block;
                font-size: 10px;
                color: var(--talerp-muted);
                margin-bottom: 3px;
            }

            .talerp-result-item strong {
                font-size: 13px;
                font-weight: 800;
                color: var(--talerp-text);
            }

            .talerp-result-item strong.positive {
                color: var(--talerp-success);
            }

            .talerp-result-item strong.negative {
                color: var(--talerp-danger);
            }

            .talerp-result-item strong.warning {
                color: var(--talerp-warning);
            }

            .talerp-detail-body {
                display: none;
            }

            .talerp-detail-body.expanded {
                display: block;
            }

            .talerp-rule-inline {
                display: grid;
                gap: 3px;
                margin-top: 6px;
                padding-top: 6px;
                border-top: 1px dashed var(--talerp-border);
                font-size: 10px;
                color: var(--talerp-muted);
                line-height: 1.6;
            }

            .talerp-action-row {
                display: flex;
                gap: 8px;
                margin-top: 8px;
            }

            .talerp-btn {
                flex: 1;
                min-height: 36px;
                border-radius: 12px;
                border: 1px solid transparent;
                cursor: pointer;
                font-size: 11px;
                font-weight: 800;
                transition: transform .2s ease, box-shadow .2s ease, opacity .2s ease;
            }

            .talerp-btn:hover {
                transform: translateY(-1px);
            }

            .talerp-btn:disabled {
                opacity: .72;
                cursor: not-allowed;
                transform: none;
            }

            .talerp-btn-primary {
                background: linear-gradient(135deg, var(--talerp-blue), var(--talerp-blue-deep));
                color: #fff;
                box-shadow: 0 12px 24px rgba(43,103,246,.22);
            }

            .talerp-btn-secondary {
                background: #fff;
                color: var(--talerp-blue);
                border-color: #d8e3f8;
            }

            .talerp-message {
                margin-top: 6px;
                min-height: 16px;
                font-size: 10px;
                line-height: 1.6;
                color: var(--talerp-muted);
            }

            .talerp-confirm-mask {
                position: fixed;
                inset: 0;
                z-index: 10020;
                display: flex;
                align-items: center;
                justify-content: center;
                padding: 24px;
                background: rgba(15,23,42,.42);
                backdrop-filter: blur(6px);
            }

            .talerp-confirm-card {
                width: min(420px, calc(100vw - 48px));
                border-radius: 24px;
                border: 1px solid var(--talerp-border);
                background: linear-gradient(180deg, rgba(255,255,255,.98), rgba(247,250,255,.94));
                box-shadow: 0 20px 48px rgba(91,121,182,.18);
                padding: 22px;
                color: var(--talerp-text);
            }

            .talerp-confirm-title {
                font-size: 20px;
                font-weight: 800;
                margin-bottom: 10px;
            }

            .talerp-confirm-body {
                font-size: 13px;
                line-height: 1.8;
                color: #4b5f84;
                white-space: pre-wrap;
            }

            .talerp-confirm-actions {
                display: flex;
                gap: 10px;
                margin-top: 18px;
            }

            .talerp-confirm-secondary,
            .talerp-confirm-primary {
                flex: 1;
                min-height: 42px;
                border-radius: 16px;
                cursor: pointer;
                font-size: 13px;
                font-weight: 800;
                border: 1px solid transparent;
            }

            .talerp-confirm-secondary {
                background: #fff;
                color: var(--talerp-muted);
                border-color: #d8e3f8;
            }

            .talerp-confirm-primary {
                background: linear-gradient(135deg, var(--talerp-blue), var(--talerp-blue-deep));
                color: #fff;
            }

            @media (max-width: 480px) {
                .talerp-grid,
                .talerp-grid-3,
                .talerp-results,
                .talerp-summary-grid {
                    grid-template-columns: 1fr;
                }

                .talerp-action-row {
                    flex-direction: column;
                }
            }
        `;
        document.head.appendChild(style);
    }

    function createInlinePricingPanel(plid) {
        const pagePrice = extractSellingPriceZAR();
        const targetPrice = pagePrice > 1 ? Number((pagePrice - 1).toFixed(2)) : 0;
        const title = extractDetailTitle() || '当前商品';

        const section = document.createElement('div');
        section.id = PANEL_ID;
        section.className = 'talerp-panel';
        section.innerHTML = `
            <div class="talerp-panel-header">
                <div class="talerp-panel-badge">小黑ERP</div>
                <div class="talerp-panel-tools">
                    <button type="button" class="talerp-param-toggle" id="talerp-param-toggle">参数</button>
                    <button type="button" class="talerp-detail-toggle" id="talerp-detail-toggle">明细</button>
                    <button type="button" class="talerp-panel-toggle" id="talerp-toggle-btn">折叠</button>
                </div>
            </div>
            <div class="talerp-panel-body" id="talerp-panel-body">
                <div class="talerp-summary-card">
                    <div class="talerp-summary-title" id="talerp-summary-title">${escapeHtml(title)}</div>
                    <div class="talerp-summary-meta" id="talerp-summary-meta">PLID：${escapeHtml(plid)}</div>
                    <div class="talerp-summary-grid">
                        <div class="talerp-summary-metric">
                            <span>当前 BuyBox</span>
                            <strong id="talerp-buybox-price">${formatZar(pagePrice)}</strong>
                        </div>
                        <div class="talerp-summary-metric">
                            <span>默认上架价</span>
                            <strong id="talerp-target-price">${targetPrice > 0 ? formatZar(targetPrice) : '未识别'}</strong>
                        </div>
                    </div>
                    <div class="talerp-status-row">
                        <div class="talerp-status-pill warning" id="talerp-connection-pill">正在连接 ERP</div>
                        <div class="talerp-status-text" id="talerp-store-summary">正在读取店铺与默认参数...</div>
                    </div>
                </div>

                <div class="talerp-grid-3">
                    <div class="talerp-field">
                        <label for="talerp-length">长(cm)</label>
                        <input type="number" id="talerp-length" step="0.1" min="0" placeholder="请输入">
                    </div>
                    <div class="talerp-field">
                        <label for="talerp-width">宽(cm)</label>
                        <input type="number" id="talerp-width" step="0.1" min="0" placeholder="请输入">
                    </div>
                    <div class="talerp-field">
                        <label for="talerp-height">高(cm)</label>
                        <input type="number" id="talerp-height" step="0.1" min="0" placeholder="请输入">
                    </div>
                </div>

                <div class="talerp-grid">
                    <div class="talerp-field">
                        <label for="talerp-weight">重量(kg)</label>
                        <input type="number" id="talerp-weight" step="0.01" min="0" placeholder="请输入">
                    </div>
                    <div class="talerp-field">
                        <label for="talerp-purchase-price">采购价(CNY)</label>
                        <input type="number" id="talerp-purchase-price" step="0.01" min="0" placeholder="请输入">
                    </div>
                </div>

                <div class="talerp-grid">
                    <div class="talerp-field">
                        <label for="talerp-selling-price">测算售价(ZAR)</label>
                        <input type="number" id="talerp-selling-price" step="0.01" min="0" placeholder="自动带入" value="${pagePrice || ''}">
                    </div>
                    <div class="talerp-field">
                        <label for="talerp-store-select">上架店铺</label>
                        <select id="talerp-store-select">
                            <option value="">正在读取店铺...</option>
                        </select>
                    </div>
                </div>

                <div class="talerp-param-body" id="talerp-param-body">
                    <div class="talerp-grid">
                        <div class="talerp-field">
                            <label for="talerp-freight-rate">空运单价</label>
                            <input type="number" id="talerp-freight-rate" step="1" min="0" value="">
                        </div>
                        <div class="talerp-field">
                            <label for="talerp-po-fee">操作费</label>
                            <input type="number" id="talerp-po-fee" step="1" min="0" value="">
                        </div>
                    </div>
                    <div class="talerp-field-hint" id="talerp-field-hint">
                        测算售价只用于利润计算，一键上架默认按 BuyBox - 1 ZAR 提交。
                    </div>
                    <div class="talerp-rule-inline">
                        <div id="talerp-rule-rate">操作费参考：${escapeHtml(DEFAULT_RATE_HINT)}</div>
                        <div id="talerp-rule-size">${escapeHtml(DEFAULT_SIZE_RULE)}</div>
                    </div>
                </div>

                <div class="talerp-results">
                    <div class="talerp-result-item"><span>计费重(kg)</span><strong id="talerp-r-weight">—</strong></div>
                    <div class="talerp-result-item"><span>空运利润率</span><strong id="talerp-r-profit-rate">—</strong></div>
                    <div class="talerp-result-item"><span>空运利润(CNY)</span><strong id="talerp-r-profit">—</strong></div>
                    <div class="talerp-result-item"><span>推荐售价(10%)</span><strong id="talerp-r-reco10">—</strong></div>
                </div>

                <div class="talerp-detail-body" id="talerp-detail-body">
                    <div class="talerp-results">
                        <div class="talerp-result-item"><span>空运运费(ZAR)</span><strong id="talerp-r-freight">—</strong></div>
                        <div class="talerp-result-item"><span>提现+汇损(ZAR)</span><strong id="talerp-r-withdraw">—</strong></div>
                        <div class="talerp-result-item"><span>推荐售价(30%)</span><strong id="talerp-r-reco30">—</strong></div>
                        <div class="talerp-result-item"><span>尾程费 + VAT(ZAR)</span><strong id="talerp-r-lastmile-total">—</strong></div>
                    </div>
                </div>

                <div class="talerp-action-row">
                    <button type="button" class="talerp-btn talerp-btn-secondary" id="talerp-reset-btn">重置参数</button>
                    <button type="button" class="talerp-btn talerp-btn-primary" id="talerp-calc-btn">计算利润</button>
                </div>
                <div class="talerp-action-row">
                    <button type="button" class="talerp-btn talerp-btn-primary" id="talerp-list-btn" data-plid="${escapeHtml(plid)}">一键上架</button>
                </div>

                <div class="talerp-message" id="talerp-panel-msg">补全长宽高、重量、采购价后，系统会自动更新利润。</div>
            </div>
        `;

        const toggleBtn = section.querySelector('#talerp-toggle-btn');
        const body = section.querySelector('#talerp-panel-body');
        const paramToggleBtn = section.querySelector('#talerp-param-toggle');
        const paramBody = section.querySelector('#talerp-param-body');
        const detailToggleBtn = section.querySelector('#talerp-detail-toggle');
        const detailBody = section.querySelector('#talerp-detail-body');
        toggleBtn?.addEventListener('click', () => {
            body?.classList.toggle('collapsed');
            toggleBtn.textContent = body?.classList.contains('collapsed') ? '展开' : '折叠';
        });
        paramToggleBtn?.addEventListener('click', () => {
            paramBody?.classList.toggle('expanded');
            paramToggleBtn.textContent = paramBody?.classList.contains('expanded') ? '收起参数' : '参数';
        });
        detailToggleBtn?.addEventListener('click', () => {
            detailBody?.classList.toggle('expanded');
            detailToggleBtn.textContent = detailBody?.classList.contains('expanded') ? '收起明细' : '明细';
        });

        return section;
    }

    function setPanelMsg(panel, text, tone = 'muted') {
        const el = panel.querySelector('#talerp-panel-msg');
        if (!el) {
            return;
        }
        el.textContent = text || '';
        el.style.color = tone === 'error'
            ? '#dc2626'
            : tone === 'success'
                ? '#16a34a'
                : tone === 'warning'
                    ? '#d97706'
                    : '#6d7f9e';
    }

    function setConnectionState(panel, { connected, label, detail, warning = false }) {
        const pill = panel.querySelector('#talerp-connection-pill');
        const summary = panel.querySelector('#talerp-store-summary');
        if (pill) {
            pill.textContent = label;
            pill.classList.toggle('connected', Boolean(connected));
            pill.classList.toggle('warning', !connected || warning);
        }
        if (summary) {
            summary.textContent = detail || '';
        }
    }

    function updateSummaryCard(panel) {
        const title = extractDetailTitle() || '当前商品';
        const plid = extractPlidFromUrl() || panel.querySelector('#talerp-list-btn')?.dataset.plid || '';
        const pagePrice = extractSellingPriceZAR();
        const targetPrice = pagePrice > 1 ? Number((pagePrice - 1).toFixed(2)) : 0;

        const titleEl = panel.querySelector('#talerp-summary-title');
        const metaEl = panel.querySelector('#talerp-summary-meta');
        const buyboxEl = panel.querySelector('#talerp-buybox-price');
        const targetEl = panel.querySelector('#talerp-target-price');
        if (titleEl) {
            titleEl.textContent = title;
        }
        if (metaEl) {
            metaEl.textContent = `PLID：${plid}`;
        }
        if (buyboxEl) {
            buyboxEl.textContent = formatZar(pagePrice);
        }
        if (targetEl) {
            targetEl.textContent = targetPrice > 0 ? formatZar(targetPrice) : '未识别';
        }

        const priceInput = panel.querySelector('#talerp-selling-price');
        if (priceInput && !priceInput.dataset.userEdited && pagePrice > 0) {
            priceInput.value = String(pagePrice);
        }
    }

    function resetResultFields(panel) {
        const resultIds = [
            'talerp-r-weight',
            'talerp-r-profit-rate',
            'talerp-r-profit',
            'talerp-r-freight',
            'talerp-r-withdraw',
            'talerp-r-reco10',
            'talerp-r-reco30',
            'talerp-r-lastmile-total',
        ];
        resultIds.forEach((id) => {
            const el = panel.querySelector(`#${id}`);
            if (el) {
                el.textContent = '—';
                el.classList.remove('positive', 'negative', 'warning');
            }
        });
    }

    function resetPanel(panel) {
        const numericDefaults = {
            'talerp-length': '',
            'talerp-width': '',
            'talerp-height': '',
            'talerp-weight': '',
            'talerp-purchase-price': '',
        };

        Object.entries(numericDefaults).forEach(([id, value]) => {
            const input = panel.querySelector(`#${id}`);
            if (input) {
                input.value = value;
            }
        });

        const pagePrice = extractSellingPriceZAR();
        const sellingPriceInput = panel.querySelector('#talerp-selling-price');
        if (sellingPriceInput) {
            sellingPriceInput.value = pagePrice > 0 ? String(pagePrice) : '';
            delete sellingPriceInput.dataset.userEdited;
        }

        latestProfitResult = null;
        resetResultFields(panel);
        updateSummaryCard(panel);
        setPanelMsg(panel, '已重置参数，请重新填写并计算。');
    }

    function readPanelNumber(panel, id, fallback = 0) {
        const raw = panel.querySelector(`#${id}`)?.value;
        const num = parseFloat(raw || '');
        return Number.isFinite(num) ? num : fallback;
    }

    function buildProfitPayload(panel) {
        return {
            plid: extractPlidFromUrl(),
            title: extractDetailTitle() || '',
            length_cm: readPanelNumber(panel, 'talerp-length'),
            width_cm: readPanelNumber(panel, 'talerp-width'),
            height_cm: readPanelNumber(panel, 'talerp-height'),
            weight_kg: readPanelNumber(panel, 'talerp-weight'),
            purchase_price_cny: readPanelNumber(panel, 'talerp-purchase-price'),
            selling_price_zar: readPanelNumber(panel, 'talerp-selling-price'),
            air_freight_cny_per_kg: readPanelNumber(panel, 'talerp-freight-rate'),
            operation_fee_cny: readPanelNumber(panel, 'talerp-po-fee'),
        };
    }

    function isProfitPayloadComplete(payload) {
        return [
            payload.length_cm,
            payload.width_cm,
            payload.height_cm,
            payload.weight_kg,
            payload.purchase_price_cny,
            payload.selling_price_zar,
        ].every((item) => Number(item) > 0);
    }

    function setResultText(panel, id, text, tone = '') {
        const el = panel.querySelector(`#${id}`);
        if (!el) {
            return;
        }
        el.textContent = text;
        el.classList.remove('positive', 'negative', 'warning');
        if (tone) {
            el.classList.add(tone);
        }
    }

    async function runCalculation(panel, explicit = false) {
        const payload = buildProfitPayload(panel);
        if (!isProfitPayloadComplete(payload)) {
            if (explicit) {
                setPanelMsg(panel, '请先补全长宽高、重量、采购价和测算售价。', 'warning');
            }
            latestProfitResult = null;
            resetResultFields(panel);
            return;
        }

        const response = await sendRuntimeMessage('CALCULATE_PROFIT', payload);
        if (!response?.ok) {
            latestProfitResult = null;
            if (explicit) {
                setPanelMsg(panel, response?.error || '利润计算失败，请稍后再试。', 'error');
            }
            return;
        }

        latestProfitResult = response.result || null;
        const result = response.result || {};
        const profit = Number(result.air_profit_cny || 0);
        const profitTone = profit >= 0 ? 'positive' : 'negative';
        const lastMileTotal = Number(result.last_mile_fee_zar || 0) + Number(result.last_mile_vat_zar || 0);

        setResultText(panel, 'talerp-r-weight', result.chargeable_weight_kg != null ? String(result.chargeable_weight_kg) : '—');
        setResultText(
            panel,
            'talerp-r-profit-rate',
            result.air_profit_rate_pct != null ? `${result.air_profit_rate_pct}%` : '—',
            profitTone
        );
        setResultText(
            panel,
            'talerp-r-profit',
            result.air_profit_cny != null ? `¥ ${result.air_profit_cny}` : '—',
            profitTone
        );
        setResultText(panel, 'talerp-r-freight', result.air_freight_zar != null ? `R ${result.air_freight_zar}` : '—');
        setResultText(panel, 'talerp-r-withdraw', result.withdrawal_fx_loss_zar != null ? `R ${result.withdrawal_fx_loss_zar}` : '—');
        setResultText(panel, 'talerp-r-reco10', result.recommended_price_10pct != null ? `R ${result.recommended_price_10pct}` : '—', 'positive');
        setResultText(panel, 'talerp-r-reco30', result.recommended_price_30pct != null ? `R ${result.recommended_price_30pct}` : '—', 'positive');
        setResultText(panel, 'talerp-r-lastmile-total', Number.isFinite(lastMileTotal) ? `R ${lastMileTotal.toFixed(2)}` : '—');

        setPanelMsg(
            panel,
            profit >= 0 ? '利润测算已更新，可直接选择店铺后一键上架。' : '当前测算利润为负，建议先调参数再决定是否上架。',
            profit >= 0 ? 'success' : 'warning'
        );
    }

    async function showErpConfirm(title, body, confirmText = '确认', cancelText = '取消') {
        return new Promise((resolve) => {
            const mask = document.createElement('div');
            mask.className = 'talerp-confirm-mask';
            mask.innerHTML = `
                <div class="talerp-confirm-card">
                    <div class="talerp-confirm-title">${escapeHtml(title)}</div>
                    <div class="talerp-confirm-body">${escapeHtml(body)}</div>
                    <div class="talerp-confirm-actions">
                        <button type="button" class="talerp-confirm-secondary">${escapeHtml(cancelText)}</button>
                        <button type="button" class="talerp-confirm-primary">${escapeHtml(confirmText)}</button>
                    </div>
                </div>
            `;

            const cleanup = (result) => {
                mask.remove();
                resolve(result);
            };

            mask.querySelector('.talerp-confirm-secondary')?.addEventListener('click', () => cleanup(false));
            mask.querySelector('.talerp-confirm-primary')?.addEventListener('click', () => cleanup(true));
            mask.addEventListener('click', (event) => {
                if (event.target === mask) {
                    cleanup(false);
                }
            });
            document.body.appendChild(mask);
        });
    }

    async function hydrateStores(panel, status) {
        const select = panel.querySelector('#talerp-store-select');
        if (!select) {
            return;
        }

        if (!status?.connected) {
            select.innerHTML = '<option value="">请先连接 ERP</option>';
            setConnectionState(panel, {
                connected: false,
                label: '未连接 ERP',
                detail: status?.error || '请先在插件弹窗中完成授权。',
                warning: true,
            });
            setPanelMsg(panel, status?.error || '请先连接小黑ERP，再使用一键上架。', 'warning');
            return;
        }

        const stores = Array.isArray(status.stores) ? status.stores : [];
        if (!stores.length) {
            select.innerHTML = '<option value="">暂无可用店铺</option>';
            setConnectionState(panel, {
                connected: true,
                label: 'ERP 已连接',
                detail: '当前账号暂无可上架店铺，请先去 ERP 绑定店铺。',
                warning: true,
            });
            setPanelMsg(panel, '当前账号下没有可用店铺。', 'warning');
            return;
        }

        select.innerHTML = stores
            .map((store) => `<option value="${escapeHtml(store.id)}">${escapeHtml(store.name)}</option>`)
            .join('');

        const preferredStoreId = await getPreferredStoreId();
        const defaultStoreId = status.store?.id ? String(status.store.id) : '';
        const selectedStoreId = stores.some((store) => String(store.id) === preferredStoreId)
            ? preferredStoreId
            : defaultStoreId || String(stores[0].id);
        select.value = selectedStoreId;

        const selectedStore = stores.find((store) => String(store.id) === String(select.value)) || stores[0];
        setConnectionState(panel, {
            connected: true,
            label: 'ERP 已连接',
            detail: `当前店铺：${selectedStore.name} · 共 ${stores.length} 个店铺可选`,
        });
    }

    function hydratePricingConfig(panel, pricingResponse) {
        const cfg = pricingResponse?.ok ? (pricingResponse.config || {}) : {};
        const defaults = {
            'talerp-freight-rate': cfg.default_air_freight_cny_per_kg || 79,
            'talerp-po-fee': cfg.default_operation_fee_cny || 20,
        };

        Object.entries(defaults).forEach(([id, value]) => {
            const input = panel.querySelector(`#${id}`);
            if (input && !input.value) {
                input.value = String(value);
            }
        });

        const hint = panel.querySelector('#talerp-field-hint');
        if (hint) {
            const fx = cfg.exchange_rate_zar_to_cny ? Number(cfg.exchange_rate_zar_to_cny).toFixed(4) : '';
            hint.textContent = fx
                ? `测算售价只用于利润计算。一键上架仍默认按 BuyBox - 1 ZAR 提交。当前汇率参考：1 ZAR ≈ ${fx} CNY`
                : '测算售价只用于利润计算。一键上架仍默认按 BuyBox - 1 ZAR 提交。';
        }

        const ruleRate = panel.querySelector('#talerp-rule-rate');
        const ruleSize = panel.querySelector('#talerp-rule-size');
        if (ruleRate) {
            ruleRate.textContent = `操作费参考：${cfg.notes?.operation_fee_hint || DEFAULT_RATE_HINT}`;
        }
        if (ruleSize) {
            ruleSize.textContent = cfg.notes?.size_weight_rule || DEFAULT_SIZE_RULE;
        }
    }

    async function bootstrapPanel(panel) {
        const status = await getExtensionStatus();
        await hydrateStores(panel, status);

        const select = panel.querySelector('#talerp-store-select');
        const preferredId = select?.value || status.store?.id || '';
        const pricing = await getPricingConfig(false, preferredId);

        hydratePricingConfig(panel, pricing);
        updateSummaryCard(panel);
        await runCalculation(panel);
    }

    async function listNow(panel) {
        const btn = panel.querySelector('#talerp-list-btn');
        if (!btn || btn.disabled) {
            return;
        }

        const storeSelect = panel.querySelector('#talerp-store-select');
        const storeId = parseInt(storeSelect?.value || '0', 10);
        if (!storeId) {
            setPanelMsg(panel, '请先选择要上架的店铺。', 'warning');
            return;
        }

        const pagePrice = extractSellingPriceZAR();
        if (!(pagePrice > 1)) {
            setPanelMsg(panel, '当前页面没有识别到有效 BuyBox 价格，暂时无法一键上架。', 'warning');
            return;
        }

        if (!latestProfitResult) {
            const proceedWithoutCalc = await showErpConfirm(
                '还没完成利润测算',
                '你还没有完成当前商品的利润测算。\n系统仍会按 BuyBox - 1 ZAR 继续上架，是否继续？',
                '继续上架',
                '先去计算'
            );
            if (!proceedWithoutCalc) {
                setPanelMsg(panel, '已取消，请先完成利润测算。', 'warning');
                return;
            }
        }

        const targetPrice = Number((pagePrice - 1).toFixed(2));
        const storeName = storeSelect?.selectedOptions?.[0]?.textContent || `店铺 ${storeId}`;
        const title = extractDetailTitle() || '当前商品';
        const confirmed = await showErpConfirm(
            '确认一键上架',
            `商品：${title}\n店铺：${storeName}\n默认上架价：${formatZar(targetPrice)}`,
            '确认上架',
            '取消'
        );
        if (!confirmed) {
            return;
        }

        let allowNegativeProfit = false;
        const currentProfit = Number(latestProfitResult?.air_profit_cny || 0);
        if (latestProfitResult && currentProfit < 0) {
            const proceed = await showErpConfirm(
                '当前默认价格可能亏损',
                `当前测算利润为 ¥ ${currentProfit.toFixed(2)}。\n如果继续，系统仍会按 BuyBox - 1 ZAR 上架。`,
                '仍然继续',
                '返回修改'
            );
            if (!proceed) {
                setPanelMsg(panel, '已取消上架，请先调整参数。', 'warning');
                return;
            }
            allowNegativeProfit = true;
        }

        const payload = {
            store_id: storeId,
            plid: extractPlidFromUrl(),
            page_url: window.location.href,
            title,
            image_url: extractDetailImageUrl() || '',
            barcode: extractDetailBarcode() || '',
            buybox_price_zar: pagePrice,
            page_price_zar: pagePrice,
            target_price_zar: targetPrice,
            brand_name: detectBrandInScope(document) || '',
            allow_negative_profit: allowNegativeProfit,
            pricing_snapshot: latestProfitResult
                ? {
                    air_profit_cny: latestProfitResult.air_profit_cny,
                    air_profit_rate_pct: latestProfitResult.air_profit_rate_pct,
                    recommended_price_10pct: latestProfitResult.recommended_price_10pct,
                    recommended_price_30pct: latestProfitResult.recommended_price_30pct,
                }
                : {},
        };

        btn.disabled = true;
        const originalText = btn.textContent;
        btn.textContent = '上架中...';
        setPanelMsg(panel, '正在提交上架请求，请稍候...', 'muted');

        try {
            const response = await sendRuntimeMessage('LIST_NOW', payload);
            if (response?.ok) {
                const copy = getListNowStatusCopy(response);
                btn.textContent = copy.buttonText;
                await setPreferredStoreId(storeId);
                extensionStatusCache = null;
                setPanelMsg(
                    panel,
                    copy.message,
                    copy.tone
                );
                return;
            }

            if (response?.error_code === 'ALREADY_PENDING') {
                btn.disabled = true;
                btn.textContent = '处理中';
                setPanelMsg(panel, '该商品已有上架动作在处理中，请稍后去 ERP 查看结果。', 'warning');
                return;
            }

            if (response?.error_code === 'ALREADY_LISTED') {
                btn.disabled = true;
                btn.textContent = '已上架过';
                setPanelMsg(panel, '该商品已存在上架记录，无需重复提交。', 'warning');
                return;
            }

            btn.disabled = false;
            btn.textContent = originalText;
            setPanelMsg(panel, response?.error || '上架失败，请稍后重试。', 'error');
        } catch (err) {
            btn.disabled = false;
            btn.textContent = originalText;
            setPanelMsg(panel, err?.message || '网络错误，请稍后重试。', 'error');
        }
    }

    function bindPanelEvents(panel) {
        const watchedInputs = [
            'talerp-length',
            'talerp-width',
            'talerp-height',
            'talerp-weight',
            'talerp-purchase-price',
            'talerp-selling-price',
            'talerp-freight-rate',
            'talerp-po-fee',
        ];

        let calcTimer = null;
        watchedInputs.forEach((id) => {
            const input = panel.querySelector(`#${id}`);
            if (!input) {
                return;
            }
            input.addEventListener('input', () => {
                if (id === 'talerp-selling-price') {
                    input.dataset.userEdited = '1';
                }
                if (calcTimer) {
                    clearTimeout(calcTimer);
                }
                calcTimer = setTimeout(() => {
                    runCalculation(panel).catch(() => {});
                }, 350);
            });
        });

        panel.querySelector('#talerp-store-select')?.addEventListener('change', async (event) => {
            const storeId = event.target?.value || '';
            await setPreferredStoreId(storeId);
            const storeName = event.target?.selectedOptions?.[0]?.textContent || '';
            const status = await getExtensionStatus();
            const storeCount = Array.isArray(status?.stores) ? status.stores.length : 0;
            setConnectionState(panel, {
                connected: Boolean(status?.connected),
                label: status?.connected ? 'ERP 已连接' : '未连接 ERP',
                detail: storeName ? `当前店铺：${storeName}${storeCount ? ` · 共 ${storeCount} 个店铺可选` : ''}` : '请选择店铺',
                warning: !status?.connected,
            });
            pricingConfigCache = null;
            pricingConfigStoreId = '';
            const pricing = await getPricingConfig(true, storeId);
            hydratePricingConfig(panel, pricing);
            await runCalculation(panel);
        });

        panel.querySelector('#talerp-reset-btn')?.addEventListener('click', () => resetPanel(panel));
        panel.querySelector('#talerp-calc-btn')?.addEventListener('click', () => {
            runCalculation(panel, true).catch(() => {});
        });
        panel.querySelector('#talerp-list-btn')?.addEventListener('click', () => {
            listNow(panel).catch(() => {});
        });
    }

    function findDetailAnchor() {
        const candidates = Array.from(document.querySelectorAll('button, span, a, div'));
        for (const element of candidates) {
            if (element.offsetParent === null) {
                continue;
            }
            const text = element.textContent || '';
            const hasBuyboxText =
                text.includes('Add to Cart') ||
                text.includes('Add to List') ||
                text.includes('Select an option') ||
                text.includes('Notify Me');
            if (!hasBuyboxText) {
                continue;
            }
            const rect = element.getBoundingClientRect();
            if (rect.left < window.innerWidth * 0.4 || rect.top > 1400) {
                continue;
            }
            const cardAncestor = element.closest('[class*="carousel"], [class*="slider"], [class*="product-card"], [data-ref="product-card"]');
            if (cardAncestor) {
                continue;
            }
            return element;
        }

        const buyboxArea = document.querySelector('[class*="buybox"], [class*="buy-box"], [data-ref="buybox"], [class*="product-action"], [class*="add-to-cart"]');
        if (buyboxArea && buyboxArea.offsetParent !== null) {
            return buyboxArea;
        }
        return null;
    }

    function findBuyboxContainer(anchor) {
        let node = anchor;
        let depth = 0;
        while (node && node !== document.body && depth < 15) {
            const style = window.getComputedStyle(node);
            const bgColor = style.backgroundColor;
            const looksWhite =
                bgColor === 'rgb(255, 255, 255)' ||
                bgColor === 'rgba(255, 255, 255, 1)' ||
                bgColor === '#ffffff';
            if (looksWhite && node.offsetWidth > 220 && node.offsetWidth < 640) {
                return node;
            }
            node = node.parentElement;
            depth += 1;
        }
        return null;
    }

    function clearRetryTimers() {
        if (injectDetailPanel.retryInterval) {
            clearInterval(injectDetailPanel.retryInterval);
            injectDetailPanel.retryInterval = null;
        }
        injectDetailPanel.retryCount = 0;
    }

    function applyFixedStyle(panel) {
        panel.style.position = 'fixed';
        panel.style.right = '16px';
        panel.style.bottom = '16px';
        panel.style.width = '308px';
        panel.style.maxWidth = 'calc(100vw - 16px)';
        panel.style.zIndex = '10001';
    }

    function injectFallbackPanel(plid) {
        if (document.getElementById(PANEL_ID)) {
            return;
        }
        const panel = createInlinePricingPanel(plid);
        bindPanelEvents(panel);
        applyFixedStyle(panel);
        document.body.appendChild(panel);
        bootstrapPanel(panel).catch(() => {});
    }

    function injectDetailPanel() {
        const plid = extractPlidFromUrl();
        if (!plid) {
            return;
        }

        const existingPanel = document.getElementById(PANEL_ID);
        if (existingPanel) {
            updateSummaryCard(existingPanel);
            return;
        }

        const anchor = findDetailAnchor();
        if (!anchor) {
            if (!injectDetailPanel.retryInterval) {
                injectDetailPanel.retryCount = 0;
                injectDetailPanel.retryInterval = setInterval(() => {
                    injectDetailPanel.retryCount += 1;
                    if (document.getElementById(PANEL_ID)) {
                        clearRetryTimers();
                        return;
                    }
                    if (injectDetailPanel.retryCount >= 20) {
                        clearRetryTimers();
                        injectFallbackPanel(plid);
                        return;
                    }
                    injectDetailPanel();
                }, 1000);
            }
            return;
        }

        clearRetryTimers();

        const panel = createInlinePricingPanel(plid);
        bindPanelEvents(panel);
        const buybox = findBuyboxContainer(anchor);
        if (buybox?.parentElement) {
            panel.style.position = 'relative';
            panel.style.width = '308px';
            panel.style.maxWidth = '100%';
            panel.style.marginLeft = 'auto';
            panel.style.zIndex = '1';
            panel.style.boxShadow = '0 18px 40px rgba(91, 121, 182, .16)';
            buybox.parentElement.insertBefore(panel, buybox.nextSibling);
        } else {
            applyFixedStyle(panel);
            document.body.appendChild(panel);
        }

        bootstrapPanel(panel).catch(() => {});
    }
    injectDetailPanel.retryInterval = null;
    injectDetailPanel.retryCount = 0;

    function cleanupInjectedElements() {
        document.getElementById(PANEL_ID)?.remove();
        clearRetryTimers();
        latestProfitResult = null;
    }

    function handleUrlChange() {
        const currentUrl = window.location.href;
        const currentPlid = extractPlidFromUrl();
        if (currentUrl === lastUrl && currentPlid === lastPlid) {
            const panel = document.getElementById(PANEL_ID);
            if (panel) {
                updateSummaryCard(panel);
            }
            return;
        }

        lastUrl = currentUrl;
        lastPlid = currentPlid;
        cleanupInjectedElements();

        if (currentPlid) {
            setTimeout(() => {
                injectDetailPanel();
            }, 300);
        }
    }

    function init() {
        injectStyles();
        if (extractPlidFromUrl()) {
            injectDetailPanel();
        }

        if (!init.urlPollTimer) {
            init.urlPollTimer = setInterval(handleUrlChange, 350);
        }

        if (!init.popstateBound) {
            window.addEventListener('popstate', handleUrlChange);
            init.popstateBound = true;
        }

        if (!init.observerBound) {
            const observer = new MutationObserver((mutations) => {
                const hasNewNodes = mutations.some((mutation) => mutation.addedNodes.length > 0);
                if (!hasNewNodes) {
                    return;
                }
                if (init.debounceTimer) {
                    clearTimeout(init.debounceTimer);
                }
                init.debounceTimer = setTimeout(() => {
                    if (extractPlidFromUrl()) {
                        injectDetailPanel();
                    }
                }, 450);
            });

            observer.observe(document.body, {
                childList: true,
                subtree: true,
            });
            init.observerBound = true;
        }
    }

    init.urlPollTimer = null;
    init.debounceTimer = null;
    init.popstateBound = false;
    init.observerBound = false;

    init();
})();
