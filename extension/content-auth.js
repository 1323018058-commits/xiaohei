/**
 * 小黑ERP Takealot 助手 — Content-Auth Script (ERP 授权页)
 *
 * 功能:
 *   监听 ERP 授权页 DOM，当 #extension-auth 元素出现时，
 *   读取 data-auth-code 属性，
 *   发送 AUTH_CODE 消息给 Service Worker。
 */

(function () {
    'use strict';

    console.log('[小黑ERP] content-auth.js 已加载，URL:', window.location.href);

    let sent = false;

    function readAndSendAuthCode() {
        if (sent) return true;

        const authElement = document.querySelector('#extension-auth');
        if (!authElement) return false;

        const authCode = authElement.getAttribute('data-auth-code');
        if (!authCode) return false;

        sent = true;

        console.log('[小黑ERP] 检测到授权码，正在传递到扩展...');

        chrome.runtime.sendMessage(
            {
                type: 'AUTH_CODE',
                authCode: authCode,
                sourceUrl: window.location.href,
            },
            (response) => {
                if (chrome.runtime.lastError) {
                    console.error('[小黑ERP] 发送失败:', chrome.runtime.lastError.message);
                    sent = false;
                    return;
                }
                if (response && response.ok) {
                    console.log('[小黑ERP] 授权码已成功传递到插件');
                } else {
                    console.error('[小黑ERP] 授权码传递失败:', response);
                    sent = false;
                }
            }
        );
        return true;
    }

    // Try immediately
    if (readAndSendAuthCode()) return;

    // Watch for DOM changes (Vue SPA renders #extension-auth after API call)
    const observer = new MutationObserver(() => {
        if (readAndSendAuthCode()) {
            observer.disconnect();
        }
    });

    // Wait for body to be ready
    function startObserving() {
        if (!document.body) {
            document.addEventListener('DOMContentLoaded', startObserving);
            return;
        }
        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: true,
            attributeFilter: ['data-auth-code'],
        });
    }

    startObserving();

    // Also poll every 500ms as fallback (MutationObserver can miss Vue SPA updates)
    const pollInterval = setInterval(() => {
        if (readAndSendAuthCode()) {
            clearInterval(pollInterval);
            observer.disconnect();
        }
    }, 500);

    // Timeout after 2 minutes
    setTimeout(() => {
        observer.disconnect();
        clearInterval(pollInterval);
    }, 120000);
})();
