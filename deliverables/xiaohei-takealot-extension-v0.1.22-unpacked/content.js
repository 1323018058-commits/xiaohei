(() => {
if (globalThis.__xhErpTakealotContent?.boot) {
  void globalThis.__xhErpTakealotContent.boot(true);
  return;
}

const PANEL_ID = "xh-erp-panel";
const LIST_CARD_BOX_CLASS = "xh-list-card-facts";
const LIST_CARD_HOST_CLASS = "xh-list-card-host";
const LIST_CARD_VERTICAL_HOST_CLASS = "xh-list-card-host-vertical";
const LIST_CARD_BOUND_ATTR = "data-xh-list-card-bound";
const LIST_CARD_PLID_ATTR = "data-xh-list-card-plid";
const PANEL_CSS_LINK_ID = "xh-erp-panel-css";
const PANEL_EMERGENCY_STYLE_ID = "xh-erp-panel-emergency-style";
const PLID_REGEX = /PLID(\d+)/i;
const LISTING_SCAN_RETRY_DELAYS = [250, 800, 1500, 3000, 6000, 10000, 16000, 24000];
const LISTING_SCAN_INTERVAL_MS = 2500;
const PANEL_EMERGENCY_CSS = `
#xh-erp-panel{box-sizing:border-box;width:100%;max-width:318px;margin:12px 0;padding:0;color:#111;font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;font-size:12px;line-height:1.35;background:#fff;border:1px solid #e5e5e5;border-radius:0;box-shadow:none;overflow:visible}
#xh-erp-panel *{box-sizing:border-box}
#xh-erp-panel[data-placement=sidebar]{max-width:none}
#xh-erp-panel[data-placement=inline]{position:static;width:min(318px,100%);max-width:318px;z-index:auto}
#xh-erp-panel[data-placement=floating]{position:fixed;right:16px;bottom:16px;width:min(338px,calc(100vw - 32px));max-width:338px;max-height:min(720px,calc(100vh - 32px));margin:0;overflow:auto;z-index:2147483600;box-shadow:0 18px 50px rgba(0,0,0,.18)}
#xh-erp-panel[data-loading=true]{opacity:.82}
.xh-panel-header{display:flex;align-items:center;justify-content:space-between;gap:10px;min-height:42px;padding:10px 12px;background:#fff;border-bottom:1px solid #ebebeb}
.xh-header-actions{display:flex;align-items:center;gap:6px}.xh-kicker{margin-bottom:2px;color:#737373;font-size:9px;font-weight:800;letter-spacing:0;text-transform:uppercase}.xh-title{color:#111;font-size:14px;font-weight:900}.xh-title-sm{color:#111;font-size:15px;font-weight:900}.xh-modal-subtitle{margin-top:3px;color:#737373;font-size:11px}
.xh-refresh,.xh-primary,.xh-secondary,.xh-ghost{border-radius:0;cursor:pointer;font-family:inherit}.xh-refresh{width:26px;height:26px;padding:0;color:#111;background:#fff;border:1px solid #d4d4d4;font-size:13px}.xh-primary{min-height:34px;padding:8px 11px;color:#fff;background:#111;border:1px solid #111;font-size:12px;font-weight:900}.xh-secondary{min-height:31px;padding:7px 10px;color:#111;background:#fff;border:1px solid #111;font-size:12px;font-weight:850}.xh-ghost{min-height:26px;padding:5px 7px;color:#525252;background:#fff;border:1px solid transparent;font-size:11px;font-weight:750}.xh-primary:hover{background:#2a2a2a}.xh-secondary:hover,.xh-refresh:hover,.xh-ghost:hover{background:#f5f5f5}
.xh-dimensions{padding:9px 12px 0;color:#525252;font-size:11px}.xh-fee-row{display:grid;grid-template-columns:minmax(0,1fr) 72px;gap:6px;padding:8px 12px 0}.xh-fee-row>div{min-width:0;padding:7px 8px;background:#fafafa;border:1px solid #ebebeb}.xh-fee-row span,.xh-readonly-box span{display:block;color:#737373;font-size:10px;font-weight:800}.xh-fee-row strong{display:block;margin-top:2px;color:#111;font-size:11px;font-weight:900;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.xh-block{margin-top:10px;padding:10px 12px 0;border-top:1px solid #ebebeb}.xh-block-compact{padding-bottom:12px}.xh-subtitle{margin-bottom:8px;color:#111;font-size:11px;font-weight:900}.xh-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.xh-field{display:grid;gap:4px;min-width:0}.xh-field+.xh-field{margin-top:9px}.xh-grid .xh-field+.xh-field{margin-top:0}.xh-field-label{display:block;color:#737373;font-size:10px;font-weight:850}
.xh-input,.xh-select{width:100%;min-width:0;min-height:29px;padding:6px 7px;color:#111;background:#fff;border:1px solid #d4d4d4;border-radius:0;outline:none;font-family:inherit;font-size:12px}.xh-input:focus,.xh-select:focus{border-color:#111;box-shadow:inset 0 -1px 0 #111}.xh-readonly-fee{min-height:58px}.xh-readonly-box{min-height:29px;padding:6px 7px;color:#111;background:#fafafa;border:1px solid #d4d4d4}.xh-readonly-box strong{display:block;color:#111;font-size:11px;font-weight:900;overflow-wrap:anywhere}.xh-input-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px}
.xh-result-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px}.xh-stat{min-height:42px;padding:7px 8px;background:#fff;border:1px solid #ebebeb}.xh-stat span{display:block;color:#737373;font-size:10px;font-weight:850}.xh-stat strong{display:block;margin-top:3px;color:#111;font-size:12px;font-weight:900;overflow-wrap:anywhere}.xh-full{width:100%}.hidden{display:none!important}.xh-meta-line{padding:8px 9px;color:#525252;background:#fafafa;border:1px solid #ebebeb;font-size:11px;line-height:1.45}.xh-hint{margin-top:8px;color:#737373;font-size:11px;line-height:1.45}.xh-hint[data-mode=success]{color:#047857}.xh-hint[data-mode=error]{color:#b91c1c}
.xh-modal{position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;padding:18px;background:rgba(17,17,17,.46)}.xh-modal-card{width:min(380px,calc(100vw - 36px));max-height:calc(100vh - 36px);overflow:auto;padding:14px;background:#fff;border:1px solid #111;border-radius:0;box-shadow:none}.xh-modal-header{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:12px;padding-bottom:11px;border-bottom:1px solid #ebebeb}
.xh-list-card-facts{box-sizing:border-box;display:block;flex:0 0 auto;align-self:stretch;clear:both;width:100%;min-width:0;margin:8px 0 0;padding:7px;color:#111;background:#fff;border:1px solid #111;border-radius:0;font-family:"Microsoft YaHei","PingFang SC","Segoe UI",sans-serif;font-size:11px;line-height:1.25}.xh-list-card-host-vertical{display:flex!important;flex-direction:column!important;align-items:stretch!important}.xh-list-card-grid{display:grid;grid-template-columns:minmax(0,1fr) 54px;gap:6px 8px}.xh-list-card-facts[data-density=mini]{padding:6px;font-size:10px}.xh-list-card-facts[data-density=mini] .xh-list-card-grid{grid-template-columns:minmax(0,1fr) 38px;gap:5px}.xh-list-card-grid>div{min-width:0}.xh-list-card-grid span,.xh-list-card-row span{display:block;color:#737373;font-size:9px;font-weight:850}.xh-list-card-grid strong,.xh-list-card-row strong{display:block;margin-top:2px;color:#111;font-size:11px;font-weight:900;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.xh-list-card-spinner{display:inline-block;width:9px;height:9px;margin-right:4px;vertical-align:-1px;border:1px solid #d4d4d4;border-top-color:#111;border-radius:999px;animation:xh-list-card-spin .72s linear infinite}@keyframes xh-list-card-spin{to{transform:rotate(360deg)}}.xh-list-card-row-muted strong{color:#525252}.xh-list-card-row-error strong{color:#b91c1c}
#xh-erp-panel[data-view=login]{color:#151515;background:#fffaf0;border:2px solid #151515;box-shadow:5px 5px 0 #151515}#xh-erp-panel[data-view=login] .xh-panel-header{background:#ffdf57;border-bottom:2px solid #151515}#xh-erp-panel[data-view=login] .xh-refresh,#xh-erp-panel[data-view=login] .xh-primary,#xh-erp-panel[data-view=login] .xh-secondary,#xh-erp-panel[data-view=login] .xh-ghost,#xh-erp-panel[data-view=login] .xh-input,#xh-erp-panel[data-view=login] .xh-select{border:2px solid #151515}#xh-erp-panel[data-view=login] .xh-primary,#xh-erp-panel[data-view=login] .xh-secondary,#xh-erp-panel[data-view=login] .xh-refresh{box-shadow:3px 3px 0 #151515}
`;

function ensurePanelStylesheet() {
  if (!document.getElementById(PANEL_EMERGENCY_STYLE_ID)) {
    const style = document.createElement("style");
    style.id = PANEL_EMERGENCY_STYLE_ID;
    style.textContent = PANEL_EMERGENCY_CSS;
    (document.head || document.documentElement).appendChild(style);
  }
  if (document.getElementById(PANEL_CSS_LINK_ID)) {
    return;
  }
  const link = document.createElement("link");
  link.id = PANEL_CSS_LINK_ID;
  link.rel = "stylesheet";
  link.href = chrome.runtime.getURL("styles/panel.css");
  (document.head || document.documentElement).appendChild(link);
}

function createEmptyPricingDraft() {
  return {
    airFreightUnitCnyPerKg: "",
    purchasePriceCny: "",
    salePriceZar: "",
    actualWeightKg: "",
    lengthCm: "",
    widthCm: "",
    heightCm: "",
  };
}

const state = {
  plid: null,
  title: "",
  categoryPath: [],
  settings: null,
  preview: null,
  loading: false,
  categoryRetryPlid: null,
  factRetryPlid: null,
  factRetryCount: 0,
  factRetryTimer: null,
  listingScanTimer: null,
  listingMutationObserver: null,
  listingIntersectionObserver: null,
  listingScrollHandler: null,
  listingResizeHandler: null,
  listingScanInterval: null,
  listingRetryTimers: [],
  listingPendingBoxes: new Map(),
  listingFactRefreshPlids: new Set(),
  listingFactRefreshAttemptedPlids: new Set(),
  listingActiveRequests: 0,
  listingQueue: [],
  pricingDraft: createEmptyPricingDraft(),
};

function findOwnTextElement(pattern) {
  const elements = Array.from(document.querySelectorAll("button,a,h2,h3,h4,strong,span,p,div"));
  return elements.find((element) => {
    if (!(element instanceof HTMLElement) || element.closest(`#${PANEL_ID}`)) {
      return false;
    }
    const text = (element.textContent || "").trim();
    return text.length > 0 && text.length < 120 && pattern.test(text);
  });
}

function getNearestCardLikeBlock(element) {
  let current = element;
  let best = element;
  for (let depth = 0; current && depth < 9; depth += 1) {
    const rect = current.getBoundingClientRect();
    if (rect.width >= 220 && rect.height >= 40) {
      best = current;
    }
    if (rect.width >= 260 && rect.height >= 86) {
      break;
    }
    current = current.parentElement;
  }
  return best;
}

function isVisibleElement(element) {
  if (!(element instanceof HTMLElement) || element.closest(`#${PANEL_ID}`)) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function isRightRailElement(element) {
  if (!isVisibleElement(element)) {
    return false;
  }
  const rect = element.getBoundingClientRect();
  const minLeft = Math.min(window.innerWidth * 0.55, 980);
  return rect.left >= minLeft && rect.width <= 520;
}

function getElementDescriptor(element) {
  if (!(element instanceof HTMLElement)) {
    return "";
  }
  return [
    element.id,
    element.className,
    element.getAttribute("data-ref"),
    element.getAttribute("data-testid"),
    element.getAttribute("aria-label"),
  ].join(" ");
}

function parseZarPricesFromText(text) {
  const prices = [];
  const pattern = /(?:^|[^\w])R\s*([0-9]+(?:[\s,][0-9]{3})*(?:\.[0-9]{1,2})?)/gi;
  let match = pattern.exec(String(text || ""));
  while (match) {
    const amount = Number(match[1].replace(/\s/g, "").replace(/,/g, ""));
    if (Number.isFinite(amount) && amount > 0 && amount < 500000) {
      prices.push(amount);
    }
    match = pattern.exec(String(text || ""));
  }
  return prices;
}

function isStruckThroughElement(element) {
  let current = element;
  for (let depth = 0; current instanceof HTMLElement && depth < 5; depth += 1) {
    const style = window.getComputedStyle(current);
    const decoration = `${style.textDecoration || ""} ${style.textDecorationLine || ""}`.toLowerCase();
    if (decoration.includes("line-through")) {
      return true;
    }
    current = current.parentElement;
  }
  return false;
}

function scoreProductPriceElement(element, text, priceCount) {
  if (!isVisibleElement(element) || isStruckThroughElement(element)) {
    return -Infinity;
  }
  const normalizedText = String(text || "").replace(/\s+/g, " ").trim();
  const descriptor = getElementDescriptor(element).toLowerCase();
  const rect = element.getBoundingClientRect();
  const style = window.getComputedStyle(element);
  const fontSize = Number.parseFloat(style.fontSize || "0") || 0;
  const fontWeight = Number.parseInt(style.fontWeight || "400", 10) || 400;
  const exactPrice = /^R\s*[0-9]+(?:[\s,][0-9]{3})*(?:\.[0-9]{1,2})?$/i.test(normalizedText);
  const secondaryContext =
    /\b(was|rrp|save|saving|discount|voucher|coupon|monthly|month|credit|ebucks|delivery|shipping|fee)\b/i.test(normalizedText) ||
    /\b(old|strike|before|was|rrp|saving|discount|voucher|coupon|delivery|shipping)\b/i.test(descriptor);

  let score = 0;
  if (isRightRailElement(element)) score += 120;
  if (/\b(price|buybox|purchase|pdp|checkout|amount)\b/i.test(descriptor)) score += 42;
  if (exactPrice) score += 45;
  if (fontSize >= 18) score += Math.min(fontSize, 38);
  if (fontWeight >= 600) score += 10;
  if (rect.top >= 0 && rect.top <= Math.max(window.innerHeight, 900)) score += 18;
  if (priceCount === 1) score += 12;
  if (secondaryContext) score -= 85;
  if (normalizedText.length > 80) score -= 35;
  if (priceCount > 2) score -= 45;
  return score;
}

function getCurrentPagePriceZar() {
  const selector = [
    "[data-ref]",
    "[data-testid]",
    "[class]",
    "strong",
    "span",
    "div",
    "p",
    "h2",
    "h3",
  ].join(",");
  const candidates = [];
  for (const element of Array.from(document.querySelectorAll(selector))) {
    if (!(element instanceof HTMLElement) || element.closest(`#${PANEL_ID}`) || element.closest(`.${LIST_CARD_BOX_CLASS}`)) {
      continue;
    }
    const text = (element.textContent || "").replace(/\s+/g, " ").trim();
    if (!text || text.length > 140 || !/R\s*\d/i.test(text)) {
      continue;
    }
    const prices = parseZarPricesFromText(text);
    if (!prices.length) {
      continue;
    }
    const score = scoreProductPriceElement(element, text, prices.length);
    if (score === -Infinity) {
      continue;
    }
    candidates.push({ price: prices[0], score });
  }
  candidates.sort((left, right) => right.score - left.score);
  return candidates[0]?.price ?? null;
}

function getAutoSalePriceZar() {
  const pagePrice = getCurrentPagePriceZar();
  if (pagePrice == null || pagePrice <= 1) {
    return null;
  }
  return Number((pagePrice - 1).toFixed(2));
}

function findRightRailTextElement(pattern) {
  const elements = Array.from(document.querySelectorAll("button,a,h2,h3,h4,strong,span,p,div"));
  return elements.find((element) => {
    if (!isRightRailElement(element)) {
      return false;
    }
    const text = (element.textContent || "").replace(/\s+/g, " ").trim();
    return text.length > 0 && text.length < 220 && pattern.test(text);
  });
}

function getRightRailCard(element) {
  let current = element;
  let best = element;
  for (let depth = 0; current && depth < 10; depth += 1) {
    if (!(current instanceof HTMLElement) || current.closest(`#${PANEL_ID}`)) {
      break;
    }
    const rect = current.getBoundingClientRect();
    if (rect.left < window.innerWidth * 0.45 || rect.width > 520) {
      break;
    }
    if (rect.width >= 180 && rect.width <= 420 && rect.height >= 45) {
      best = current;
    }
    if (rect.width >= 210 && rect.width <= 360 && rect.height >= 80 && rect.height <= 360) {
      best = current;
    }
    current = current.parentElement;
  }
  return best;
}

function getSidebarMountTarget() {
  const sellerNode =
    findRightRailTextElement(/^Sold by\b/i) ||
    findRightRailTextElement(/^Seller Score\b/i);
  if (sellerNode) {
    return { reference: getRightRailCard(sellerNode), mode: "before" };
  }

  const creditNode = findRightRailTextElement(/takealot\.credit|eBucks|Discovery\s*MILES/i);
  if (creditNode) {
    return { reference: getRightRailCard(creditNode), mode: "before" };
  }

  const actionNode =
    findRightRailTextElement(/^(Add to Cart|Add to cart|Buy Now|Pre-order)$/i) ||
    findRightRailTextElement(/FREE NEXT DAY/i);
  if (actionNode) {
    return { reference: getRightRailCard(actionNode), mode: "after" };
  }

  return null;
}

function getInlineMountReference() {
  const titleNode =
    document.querySelector("h1") ||
    document.querySelector('[data-testid="product-title"]') ||
    document.querySelector('[class*="product-title"]');
  if (!titleNode || titleNode.closest(`#${PANEL_ID}`)) {
    return null;
  }
  return getNearestCardLikeBlock(titleNode);
}

function getSidebarMountReference() {
  const otherOffersNode = findOwnTextElement(/^Other Offers$/i);
  if (otherOffersNode) {
    return otherOffersNode;
  }

  return null;
}

function mountPanel(panel) {
  panel.dataset.placement = "floating";
  if (panel.parentElement !== document.body || panel !== document.body.lastElementChild) {
    document.body.appendChild(panel);
  }
}

function schedulePanelRemount() {
  if (!state.plid) {
    return;
  }
  window.setTimeout(() => {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      mountPanel(panel);
    }
  }, 500);
  window.setTimeout(() => {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      mountPanel(panel);
    }
  }, 1500);
  window.setTimeout(() => {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      mountPanel(panel);
    }
  }, 3000);
  window.setTimeout(() => {
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      mountPanel(panel);
    }
  }, 5000);
}

function extractPlid() {
  const match = window.location.href.match(PLID_REGEX);
  return match ? match[1] : null;
}

function extractPlidFromValue(value) {
  const match = String(value || "").match(PLID_REGEX);
  return match ? match[1] : null;
}

function extractNumericPlidFromValue(value) {
  const text = String(value || "").trim();
  const prefixed = extractPlidFromValue(text);
  if (prefixed) {
    return prefixed;
  }
  const numeric = text.match(/^\d{5,}$/);
  return numeric ? numeric[0] : null;
}

function isPlidAttributeName(name) {
  const normalized = String(name || "").toLowerCase().replace(/[^a-z0-9]+/g, "");
  return [
    "plid",
    "productlineid",
    "productid",
    "productline",
    "externalproductid",
  ].some((key) => normalized.includes(key));
}

function extractPlidFromElement(element) {
  if (!(element instanceof HTMLElement)) {
    return null;
  }
  if (element instanceof HTMLAnchorElement) {
    const hrefPlid = extractPlidFromValue(element.href);
    if (hrefPlid) {
      return hrefPlid;
    }
  }
  for (const attribute of Array.from(element.attributes)) {
    const plid = isPlidAttributeName(attribute.name)
      ? extractNumericPlidFromValue(attribute.value)
      : extractPlidFromValue(attribute.value);
    if (plid) {
      return plid;
    }
  }
  return null;
}

function findPlidInElementTree(container) {
  if (!(container instanceof HTMLElement)) {
    return null;
  }
  const direct = extractPlidFromElement(container);
  if (direct) {
    return direct;
  }
  const candidates = Array.from(container.querySelectorAll("a[href],img[src],[href*='PLID'],[src*='PLID'],[data-ref],[data-id],[data-url],[data-href],[data-product-id],[data-productline-id],[data-product-line-id],[data-plid]"));
  for (const candidate of candidates.slice(0, 80)) {
    const plid = extractPlidFromElement(candidate);
    if (plid) {
      return plid;
    }
  }
  return null;
}

function countUniquePlidsInElement(container) {
  if (!(container instanceof HTMLElement)) {
    return 0;
  }
  const plids = new Set();
  const direct = extractPlidFromElement(container);
  if (direct) {
    plids.add(direct);
  }
  const candidates = Array.from(container.querySelectorAll("a[href],img[src],[href*='PLID'],[src*='PLID'],[data-ref],[data-id],[data-url],[data-href],[data-product-id],[data-productline-id],[data-product-line-id],[data-plid]"));
  for (const candidate of candidates.slice(0, 120)) {
    const plid = extractPlidFromElement(candidate);
    if (plid) {
      plids.add(plid);
      if (plids.size > 1) {
        return plids.size;
      }
    }
  }
  return plids.size;
}

function hasVisibleSeedBounds(node) {
  if (!(node instanceof HTMLElement)) {
    return false;
  }
  const rect = node.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) {
    return true;
  }
  const descendants = Array.from(node.querySelectorAll("img,span,strong,p,div,h3,h4")).slice(0, 16);
  return descendants.some((child) => {
    if (!(child instanceof HTMLElement)) {
      return false;
    }
    const childRect = child.getBoundingClientRect();
    return childRect.width > 0 && childRect.height > 0;
  });
}

function getListingSeedElements() {
  const directSelector = [
    "a[href]",
    "button",
    "img[src]",
    "[data-ref]",
    "[data-id]",
    "[data-url]",
    "[data-href]",
    "[data-product-id]",
    "[data-productline-id]",
    "[data-product-line-id]",
    "[data-plid]",
  ].join(",");
  const cardSelector = [
    "article",
    "li",
    '[data-testid*="product"]',
    '[data-ref*="product"]',
    '[class*="product-card"]',
    '[class*="productCard"]',
    '[class*="product_"]',
  ].join(",");
  const seeds = [];
  const seenNodes = new WeakSet();
  const pushSeed = (node, plid) => {
    if (!(node instanceof HTMLElement) || !plid) {
      return;
    }
    if (node.closest(`#${PANEL_ID}`) || node.closest(`.${LIST_CARD_BOX_CLASS}`)) {
      return;
    }
    const rect = node.getBoundingClientRect();
    if (!hasVisibleSeedBounds(node) || rect.width >= 1600 || rect.height >= 2000) {
      return;
    }
    if (seenNodes.has(node)) {
      return;
    }
    seenNodes.add(node);
    seeds.push({ node, plid });
  };

  for (const node of Array.from(document.links || [])) {
    pushSeed(node, extractPlidFromElement(node));
  }
  for (const node of Array.from(document.querySelectorAll(directSelector))) {
    pushSeed(node, extractPlidFromElement(node));
  }
  for (const node of Array.from(document.querySelectorAll(cardSelector))) {
    pushSeed(node, findPlidInElementTree(node));
  }
  return seeds;
}

function getProductTitle() {
  const titleNode =
    document.querySelector("h1") ||
    document.querySelector('[data-testid="product-title"]') ||
    document.querySelector("title");
  return titleNode ? (titleNode.textContent || "").trim() : "";
}

function cleanCategoryPart(value) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return "";
  const lowered = text.toLowerCase();
  if (
    ["takealot", "home", "daily deals", "cart", "account", "login", "register"].includes(lowered) ||
    ["share", "report this product", "help centre", "sell on takealot", "orders", "my account"].includes(lowered) ||
    /^all\s+(pets|dogs|cats|birds|fish|small pets)$/i.test(text) ||
    lowered.includes("shop by department") ||
    lowered.includes("customer service") ||
    /^plid\d+/i.test(text)
  ) {
    return "";
  }
  if (state.title && text === state.title) {
    return "";
  }
  return text;
}

function normalizeCategoryPath(parts) {
  const path = [];
  for (const part of parts) {
    const cleaned = cleanCategoryPart(part);
    if (cleaned && !path.includes(cleaned)) {
      path.push(cleaned);
    }
  }
  return path.slice(-6);
}

function collectCategoryParts(container) {
  if (!container) return [];
  const nodes = Array.from(container.querySelectorAll("a,span,li"));
  const parts = nodes
    .map((node) => cleanCategoryPart(node.textContent || ""))
    .filter((text) => text && text.length <= 80);
  return normalizeCategoryPath(parts);
}

function getProductCategoryPath() {
  const selectors = [
    '[data-testid*="breadcrumb"]',
    '[data-ref*="breadcrumb"]',
    '[class*="breadcrumb"]',
    'nav[aria-label*="Breadcrumb"]',
    'nav[aria-label*="breadcrumb"]',
  ];
  for (const selector of selectors) {
    const containers = Array.from(document.querySelectorAll(selector));
    for (const container of containers) {
      if (container.closest(`#${PANEL_ID}`)) continue;
      const path = collectCategoryParts(container);
      if (path.length >= 2) {
        return path;
      }
    }
  }

  const titleNode = document.querySelector("h1");
  const titleTop = titleNode?.getBoundingClientRect?.().top ?? 360;
  const candidates = Array.from(document.querySelectorAll("a[href]"))
    .filter((node) => node instanceof HTMLElement && !node.closest(`#${PANEL_ID}`))
    .filter((node) => {
      const rect = node.getBoundingClientRect();
      return rect.top >= 0 && rect.top <= titleTop + 48 && rect.width > 0 && rect.height > 0;
    })
    .map((node) => cleanCategoryPart(node.textContent || ""))
    .filter((text) => text && text.length <= 80);
  return normalizeCategoryPath(candidates);
}

function getListingPageCategoryPath() {
  const selectors = [
    '[data-testid*="breadcrumb"]',
    '[data-ref*="breadcrumb"]',
    '[class*="breadcrumb"]',
    'nav[aria-label*="Breadcrumb"]',
    'nav[aria-label*="breadcrumb"]',
  ];
  for (const selector of selectors) {
    const containers = Array.from(document.querySelectorAll(selector));
    for (const container of containers) {
      if (container.closest(`#${PANEL_ID}`)) continue;
      const path = collectCategoryParts(container);
      if (path.length >= 2) {
        return path;
      }
    }
  }
  return [];
}

function findListingProductCard(anchor) {
  let current = anchor;
  let best = null;
  let bestScore = -Infinity;
  for (let depth = 0; current && depth < 12; depth += 1) {
    if (!(current instanceof HTMLElement) || current.closest(`#${PANEL_ID}`)) {
      break;
    }
    const rect = current.getBoundingClientRect();
    const uniquePlidCount = countUniquePlidsInElement(current);
    const hasPrice = /from\s*r|r\s*\d+/i.test(current.textContent || "");
    const hasProductAction = /shop all options|add to cart|buy now/i.test(current.textContent || "");
    const hasImage = Boolean(current.querySelector("img"));
    const hasTitleHint = Boolean(current.querySelector("h3,h4,[data-testid*='product-title'],[class*='product-title']"));
    const descriptor = getElementDescriptor(current).toLowerCase();
    const hasProductHint =
      current.tagName === "ARTICLE" ||
      current.tagName === "LI" ||
      /\b(product|product-card|productcard|grid-item|search-result|catalogue|cell)\b/i.test(descriptor);
    if (uniquePlidCount > 1) {
      break;
    }
    if (
      rect.width >= 72 &&
      rect.width <= 1100 &&
      rect.height >= 70 &&
      (hasPrice || hasProductAction || hasImage || hasTitleHint || hasProductHint)
    ) {
      let score = rect.width * 0.02 + rect.height * 0.03;
      if (hasProductAction) score += 28;
      if (hasPrice) score += 22;
      if (hasImage) score += 18;
      if (hasTitleHint) score += 16;
      if (hasProductHint) score += 34;
      if (rect.width > 760 || rect.height > 720) score -= 40;
      if (score > bestScore) {
        bestScore = score;
        best = current;
      }
    }
    if (
      rect.width >= 96 &&
      rect.width <= 620 &&
      rect.height >= 130 &&
      (hasPrice || hasProductAction) &&
      (hasImage || hasTitleHint || hasProductHint)
    ) {
      best = current;
    }
    current = current.parentElement;
  }
  return best;
}

function promoteListingCardHost(card) {
  if (!(card instanceof HTMLElement) || !card.parentElement) {
    return card;
  }
  if (card.tagName !== "A") {
    return card;
  }
  const parent = card.parentElement;
  const parentRect = parent.getBoundingClientRect();
  const cardRect = card.getBoundingClientRect();
  if (
    countUniquePlidsInElement(parent) === 1 &&
    parentRect.width >= Math.max(cardRect.width, 72) &&
    parentRect.width <= 1100 &&
    parentRect.height >= cardRect.height &&
    parentRect.height <= 900
  ) {
    return parent;
  }
  return card;
}

function getListingCardTitle(card, anchor) {
  const titleSelectors = [
    '[data-testid*="product-title"]',
    '[class*="product-title"]',
    'h3',
    'h4',
  ];
  for (const selector of titleSelectors) {
    const node = card.querySelector(selector);
    const text = cleanCategoryPart(node?.textContent || "");
    if (text && text.length > 8) {
      return text;
    }
  }
  const anchorText = cleanCategoryPart(anchor?.textContent || "");
  if (anchorText && anchorText.length > 8 && !/^from\s*r/i.test(anchorText)) {
    return anchorText;
  }
  const lines = String(card.textContent || "")
    .split("\n")
    .map((line) => cleanCategoryPart(line))
    .filter((line) => line && line.length > 8 && !/^from\s*r/i.test(line) && !/shop all options/i.test(line));
  return lines[0] || "";
}

function findListingCardInsertReference(card) {
  const buttons = Array.from(card.querySelectorAll("button,a,div,span"))
    .filter((node) => node instanceof HTMLElement && /shop all options|add to cart|buy now/i.test(node.textContent || ""));
  if (buttons.length) {
    let reference = buttons[0];
    for (let depth = 0; reference.parentElement && depth < 3; depth += 1) {
      const parent = reference.parentElement;
      const rect = parent.getBoundingClientRect();
      if (rect.width >= 120 && rect.height <= 80) {
        reference = parent;
      }
    }
    return reference;
  }
  return null;
}

function prepareListingCardHost(card) {
  card.classList.add(LIST_CARD_HOST_CLASS);
  const style = window.getComputedStyle(card);
  if (style.display.includes("flex") && /^row/i.test(style.flexDirection)) {
    card.classList.add(LIST_CARD_VERTICAL_HOST_CLASS);
  }
}

function mountListingCardBox(card, box) {
  prepareListingCardHost(card);
  const reference = findListingCardInsertReference(card);
  const cardRect = card.getBoundingClientRect();
  box.dataset.density = cardRect.width < 170 ? "mini" : "standard";
  if (reference?.parentElement && card.contains(reference)) {
    reference.insertAdjacentElement("afterend", box);
    return;
  }
  card.appendChild(box);
}

function createListingCardBox(plid) {
  ensurePanelStylesheet();
  const box = document.createElement("div");
  box.className = LIST_CARD_BOX_CLASS;
  box.setAttribute(LIST_CARD_PLID_ATTR, plid);
  box.innerHTML = buildListingCardBoxMarkup({ status: "loading" });
  return box;
}

function listingPreviewHasDimensions(preview) {
  const product = preview?.product || {};
  const pricing = preview?.pricing || {};
  return (
    (hasFiniteNumber(product.length_cm) && hasFiniteNumber(product.width_cm) && hasFiniteNumber(product.height_cm)) ||
    (hasFiniteNumber(pricing.length_cm) && hasFiniteNumber(pricing.width_cm) && hasFiniteNumber(pricing.height_cm)) ||
    Boolean(product.merchant_packaged_dimensions_raw || product.cbs_package_dimensions_raw || product.consolidated_packaged_dimensions_raw)
  );
}

function listingPreviewHasWeight(preview) {
  const product = preview?.product || {};
  const pricing = preview?.pricing || {};
  return (
    hasFiniteNumber(product.actual_weight_kg) ||
    hasFiniteNumber(pricing.actual_weight_kg) ||
    Boolean(product.merchant_packaged_weight_raw || product.cbs_package_weight_raw)
  );
}

function listingPreviewNeedsFactRefresh(preview) {
  return Boolean(preview && (!listingPreviewHasDimensions(preview) || !listingPreviewHasWeight(preview)));
}

function getListingRequestKey(plid, forceRefreshFacts = false) {
  return `${plid}:${forceRefreshFacts ? "refresh" : "preview"}`;
}

function buildListingCardBoxMarkup({ status, preview, error } = {}) {
  if (status === "loading") {
    if (preview) {
      const product = preview.product || {};
      const pricing = preview.pricing || {};
      const category = product.category_label || pricing.success_fee_category || "未识别";
      const commission = pricing.success_fee_rate != null ? formatPercent(pricing.success_fee_rate) : "待测算";
      const dimensionsPending = !listingPreviewHasDimensions(preview);
      const weightPending = !listingPreviewHasWeight(preview);
      const dimensions = dimensionsPending ? "查询中" : formatCompactDimensions(product, pricing);
      const weight = weightPending ? "查询中" : formatCompactWeight(product, pricing);
      return `
        <div class="xh-list-card-grid xh-list-card-grid-loading">
          <div><span>类目</span><strong title="${escapeHtml(category)}">${escapeHtml(category)}</strong></div>
          <div><span>佣金</span><strong>${escapeHtml(commission)}</strong></div>
          <div><span>长x宽x高</span><strong>${dimensionsPending ? '<i class="xh-list-card-spinner" aria-hidden="true"></i>' : ""}${escapeHtml(dimensions)}</strong></div>
          <div><span>重量</span><strong>${weightPending ? '<i class="xh-list-card-spinner" aria-hidden="true"></i>' : ""}${escapeHtml(weight)}</strong></div>
        </div>
      `;
    }
    return `
      <div class="xh-list-card-row xh-list-card-row-muted">
        <span>小黑</span><strong><i class="xh-list-card-spinner" aria-hidden="true"></i>正在查询商品信息</strong>
      </div>
    `;
  }
  if (status === "error") {
    return `
      <div class="xh-list-card-row xh-list-card-row-error">
        <span>小黑</span><strong>${escapeHtml(error || "同步失败")}</strong>
      </div>
    `;
  }

  const product = preview?.product || {};
  const pricing = preview?.pricing || {};
  const category = product.category_label || pricing.success_fee_category || "未识别";
  const commission = pricing.success_fee_rate != null ? formatPercent(pricing.success_fee_rate) : "待测算";
  const dimensions = listingPreviewHasDimensions(preview)
    ? formatCompactDimensions(product, pricing)
    : "接口未返回";
  const weight = listingPreviewHasWeight(preview)
    ? formatCompactWeight(product, pricing)
    : "接口未返回";
  return `
    <div class="xh-list-card-grid">
      <div><span>类目</span><strong title="${escapeHtml(category)}">${escapeHtml(category)}</strong></div>
      <div><span>佣金</span><strong>${escapeHtml(commission)}</strong></div>
      <div><span>长x宽x高</span><strong>${escapeHtml(dimensions)}</strong></div>
      <div><span>重量</span><strong>${escapeHtml(weight)}</strong></div>
    </div>
  `;
}

function getPanel() {
  ensurePanelStylesheet();
  let panel = document.getElementById(PANEL_ID);
  if (!panel) {
    panel = document.createElement("section");
    panel.id = PANEL_ID;
  }
  mountPanel(panel);
  return panel;
}

function setLoading(loading) {
  state.loading = loading;
  const panel = getPanel();
  panel.dataset.loading = loading ? "true" : "false";
}

function buildDisconnectedView() {
  return `
    <div class="xh-panel-header">
      <div>
        <div class="xh-kicker">Xiaohei ERP</div>
        <div class="xh-title">连接 ERP</div>
      </div>
      <button class="xh-refresh" type="button" data-action="refresh">↻</button>
    </div>
    <div class="xh-block xh-block-compact">
      <div class="xh-subtitle">先连接，再自动显示商品护栏与上架入口</div>
      <div class="xh-field">
        <label class="xh-field-label">账号</label>
        <input class="xh-input" data-field="erp-username" placeholder="输入 ERP 账号" />
      </div>
      <div class="xh-field">
        <label class="xh-field-label">密码</label>
        <input class="xh-input" data-field="erp-password" type="password" placeholder="输入 ERP 密码" />
      </div>
      <button class="xh-primary xh-full" data-action="login" type="button">登录 ERP</button>
      <div class="xh-hint" data-field="global-hint">登录成功后，扩展会自动保存连接。</div>
    </div>
  `;
}

function buildConnectedView() {
  const user = state.settings?.extensionUser;
  const stores = Array.isArray(state.settings?.extensionStores) ? state.settings.extensionStores : [];
  const selectedStoreId = state.settings?.defaultStoreId || "";
  const storeOptions = stores.map((store) => {
    const selected = store.store_id === selectedStoreId ? "selected" : "";
    return `<option value="${escapeHtml(store.store_id)}" ${selected}>${escapeHtml(store.name)}</option>`;
  }).join("");

  const guardrailStatus =
    state.preview?.guardrail?.status ||
    state.preview?.product?.fact_status ||
    "waiting";
  const product = state.preview?.product || {};
  const pricing = state.preview?.pricing || null;
  const weight = state.preview
    ? (listingPreviewHasWeight(state.preview) ? formatCompactWeight(product, pricing || {}) : "正在补全重量")
    : "查询中";
  const dimensions = state.preview
    ? (listingPreviewHasDimensions(state.preview) ? formatCompactDimensions(product, pricing || {}) : "正在补全尺寸")
    : "查询中";
  const protectedFloor = state.preview?.guardrail?.protected_floor_price || "";
  const productCategoryLabel = state.preview?.product?.category_label || formatCategoryPath(state.categoryPath) || "未识别";
  const successFeeMatched = Boolean(pricing?.success_fee_category);
  const successFeeCategory = successFeeMatched ? pricing.success_fee_category : "未匹配类目，默认费率";
  const successFeeRate = pricing?.success_fee_rate != null ? formatPercent(pricing.success_fee_rate) : "待测算";
  const successFeeAmount = pricing?.success_fee_amount_zar ?? "待测算";
  const tailShippingFee = pricing?.tail_shipping_fee_zar;
  const tailVatFee = pricing?.tail_vat_fee_zar;
  const hasCompleteFacts = Boolean(
    state.preview &&
      listingPreviewHasWeight(state.preview) &&
      listingPreviewHasDimensions(state.preview),
  );
  const panelNote = !state.preview
    ? "正在从 ERP 接口查询商品信息。"
    : hasCompleteFacts
      ? (pricing?.note || "输入试算参数后显示推荐售价。")
      : "正在补全商品重量和尺寸，完成后会自动刷新试算。";
  const displayTailFee = tailShippingFee != null
    ? `${formatZar(tailShippingFee)} + VAT ${formatZar(tailVatFee || 0)}`
    : "待测算";
  const displayFulfillmentTier = formatFulfillmentTier(
    pricing?.fulfillment_size_tier,
    pricing?.fulfillment_weight_tier,
  );
  const draftAirFreight = firstPositiveText(
    state.pricingDraft.airFreightUnitCnyPerKg,
    pricing?.air_freight_unit_cny_per_kg,
    79,
  );
  const draftPurchasePrice = stringifyPositiveNumber(state.pricingDraft.purchasePriceCny);
  const draftSalePrice = firstPositiveText(state.pricingDraft.salePriceZar, getAutoSalePriceZar(), pricing?.sale_price_zar);
  const draftActualWeight = firstPositiveText(
    state.pricingDraft.actualWeightKg,
    product.actual_weight_kg,
    pricing?.actual_weight_kg,
  );
  const draftLength = firstPositiveText(state.pricingDraft.lengthCm, product.length_cm, pricing?.length_cm);
  const draftWidth = firstPositiveText(state.pricingDraft.widthCm, product.width_cm, pricing?.width_cm);
  const draftHeight = firstPositiveText(state.pricingDraft.heightCm, product.height_cm, pricing?.height_cm);
  const recommendedPrice10 = pricing?.recommended_price_10_zar ?? "待测算";
  const recommendedPrice30 = pricing?.recommended_price_30_zar ?? "待测算";
  const suggestedProtectedFloor = pricing?.recommended_protected_floor_price_zar ?? "待测算";
  const estimatedProfit = pricing?.profit_zar ?? "待测算";
  const estimatedMargin = pricing?.margin_rate != null
    ? `${(Number(pricing.margin_rate) * 100).toFixed(2)}%`
    : "待测算";
  const breakEvenPrice = pricing?.break_even_price_zar ?? "待测算";
  const chargeableWeight = pricing?.chargeable_weight_kg ?? "待测算";
  const displayChargeableWeight = typeof chargeableWeight === "number" ? `${formatNumber(chargeableWeight, 2)} kg` : chargeableWeight;
  const displayProfit = typeof estimatedProfit === "number" ? formatZar(estimatedProfit) : estimatedProfit;
  const displaySuccessFeeAmount = typeof successFeeAmount === "number" ? formatZar(successFeeAmount) : successFeeAmount;
  const displayRecommendedPrice10 = typeof recommendedPrice10 === "number" ? formatZar(recommendedPrice10) : recommendedPrice10;
  const displayRecommendedPrice30 = typeof recommendedPrice30 === "number" ? formatZar(recommendedPrice30) : recommendedPrice30;
  const displaySuggestedProtectedFloor =
    typeof suggestedProtectedFloor === "number" ? formatZar(suggestedProtectedFloor) : suggestedProtectedFloor;
  const modalProtectedFloor =
    protectedFloor ||
    (pricing?.recommended_protected_floor_price_zar != null
      ? String(pricing.recommended_protected_floor_price_zar)
      : "");

  return `
    <div class="xh-panel-header">
      <div>
        <div class="xh-kicker">Xiaohei ERP</div>
        <div class="xh-title">上架试算</div>
      </div>
      <div class="xh-header-actions">
        <button class="xh-refresh" type="button" data-action="refresh" title="刷新">↻</button>
        <button class="xh-ghost" type="button" data-action="logout">退出</button>
      </div>
    </div>

    <div class="xh-dimensions">${escapeHtml(weight)} · ${escapeHtml(dimensions)}</div>
    <div class="xh-fee-row">
      <div><span>类目</span><strong title="${escapeHtml(productCategoryLabel)}">${escapeHtml(productCategoryLabel)}</strong></div>
      <div><span>佣金</span><strong title="${escapeHtml(successFeeCategory || "")}">${escapeHtml(successFeeRate)}</strong></div>
    </div>

    <div class="xh-block">
      <div class="xh-grid">
        <div class="xh-field">
          <label class="xh-field-label">空运单价 (CNY/kg)</label>
          <input class="xh-input" data-field="air-freight-unit" inputmode="decimal" placeholder="79" value="${escapeHtml(draftAirFreight)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">采购价 (CNY)</label>
          <input class="xh-input" data-field="purchase-price" inputmode="decimal" placeholder="0" value="${escapeHtml(draftPurchasePrice)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">销售价 (ZAR)</label>
          <input class="xh-input" data-field="sale-price" inputmode="decimal" placeholder="0" value="${escapeHtml(draftSalePrice)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">重量 (kg)</label>
          <input class="xh-input" data-field="actual-weight" inputmode="decimal" placeholder="0" value="${escapeHtml(draftActualWeight)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">长 (cm)</label>
          <input class="xh-input" data-field="length-cm" inputmode="decimal" placeholder="0" value="${escapeHtml(draftLength)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">宽 (cm)</label>
          <input class="xh-input" data-field="width-cm" inputmode="decimal" placeholder="0" value="${escapeHtml(draftWidth)}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">高 (cm)</label>
          <input class="xh-input" data-field="height-cm" inputmode="decimal" placeholder="0" value="${escapeHtml(draftHeight)}" />
        </div>
        <div class="xh-field xh-readonly-fee">
          <label class="xh-field-label">尾程配送费</label>
          <div class="xh-readonly-box">
            <strong>${escapeHtml(displayTailFee)}</strong>
            <span>${escapeHtml(displayFulfillmentTier)}</span>
          </div>
        </div>
      </div>
      <button class="xh-secondary xh-full" data-action="recalculate" type="button">重新试算</button>
    </div>

    <div class="xh-block">
      <div class="xh-subtitle">结果</div>
      <div class="xh-result-grid">
        <div class="xh-stat"><span>计费重</span><strong>${escapeHtml(String(displayChargeableWeight))}</strong></div>
        <div class="xh-stat"><span>利润</span><strong>${escapeHtml(String(displayProfit))}</strong></div>
        <div class="xh-stat"><span>佣金费用</span><strong>${escapeHtml(String(displaySuccessFeeAmount))}</strong></div>
        <div class="xh-stat"><span>利润率</span><strong>${escapeHtml(String(estimatedMargin))}</strong></div>
        <div class="xh-stat"><span>10% 利润售价</span><strong>${escapeHtml(String(displayRecommendedPrice10))}</strong></div>
        <div class="xh-stat"><span>30% 利润售价</span><strong>${escapeHtml(String(displayRecommendedPrice30))}</strong></div>
        <div class="xh-stat"><span>建议保护价</span><strong>${escapeHtml(String(displaySuggestedProtectedFloor))}</strong></div>
      </div>
      <div class="xh-hint" data-field="global-hint" ${hasCompleteFacts ? "" : 'data-mode="error"'}>${escapeHtml(panelNote)}</div>
    </div>

    <div class="xh-block xh-block-compact">
      <button class="xh-primary xh-full" data-action="open-list-now" type="button">一键上架</button>
    </div>

    <div class="xh-modal hidden" data-modal="list-now">
      <div class="xh-modal-card">
        <div class="xh-modal-header">
          <div>
            <div class="xh-title-sm">一键上架</div>
            <div class="xh-modal-subtitle">${escapeHtml(user?.username || "已连接")} · ${escapeHtml(state.plid || "-")}</div>
          </div>
          <button class="xh-ghost" type="button" data-action="close-list-now">关闭</button>
        </div>
        <div class="xh-field">
          <label class="xh-field-label">上架店铺</label>
          <select class="xh-select" data-field="modal-store-select">
            ${storeOptions}
          </select>
        </div>
        <div class="xh-field">
          <label class="xh-field-label">保护价 (ZAR)</label>
          <div class="xh-input-row">
            <input class="xh-input" data-field="modal-protected-floor" inputmode="decimal" placeholder="输入保护价" value="${escapeHtml(String(modalProtectedFloor))}" />
            <button class="xh-secondary" data-action="fill-suggested-floor" type="button">建议</button>
          </div>
        </div>
        <div class="xh-field">
          <label class="xh-field-label">库存数量</label>
          <input class="xh-input" data-field="modal-quantity" inputmode="numeric" placeholder="默认库存" value="${escapeHtml(String(state.settings?.defaultStockQty || ""))}" />
        </div>
        <div class="xh-field">
          <label class="xh-field-label">任务说明</label>
          <div class="xh-meta-line">确认后会先保存保护价，再创建上架任务。失败时只保留记录，不会误写价格。</div>
        </div>
        <button class="xh-primary xh-full" data-action="confirm-list-now" type="button">保存保护价并创建任务</button>
      </div>
    </div>
  `;
}

function renderPanel() {
  if (!state.plid) {
    const existing = document.getElementById(PANEL_ID);
    if (existing) {
      existing.remove();
    }
    return;
  }
  const panel = getPanel();
  panel.dataset.view = state.settings?.extensionToken ? "connected" : "login";
  panel.innerHTML = state.settings?.extensionToken ? buildConnectedView() : buildDisconnectedView();
  schedulePanelRemount();
}

function setHint(message, mode = "default") {
  const node = document.querySelector('[data-field="global-hint"]');
  if (!node) return;
  node.textContent = message;
  node.dataset.mode = mode;
}

async function sendMessage(payload) {
  return chrome.runtime.sendMessage(payload);
}

function parseNullableNumber(value) {
  const text = String(value ?? "").trim();
  if (!text) {
    return null;
  }
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function parsePositiveNumber(value) {
  const number = parseNullableNumber(value);
  return number != null && number > 0 ? number : null;
}

function stringifyPositiveNumber(value) {
  const number = parsePositiveNumber(value);
  return number != null ? String(number) : "";
}

function firstPositiveText(...values) {
  for (const value of values) {
    const text = stringifyPositiveNumber(value);
    if (text) {
      return text;
    }
  }
  return "";
}

function getEffectiveSalePriceZar() {
  const inputValue = document.querySelector(`#${PANEL_ID} [data-field="sale-price"]`)?.value;
  return (
    parsePositiveNumber(inputValue) ??
    parsePositiveNumber(state.pricingDraft.salePriceZar) ??
    getAutoSalePriceZar() ??
    parsePositiveNumber(state.preview?.pricing?.sale_price_zar)
  );
}

function isBenignExtensionInjectionError(error) {
  const message = String(error?.message || error || "");
  return /duplicate|already exists|overlap|stylesheet|style sheet|重复|重叠|样式表/i.test(message);
}

function scanListingProductCards() {
  if (!state.settings?.extensionToken || !state.settings?.defaultStoreId) {
    return;
  }
  const seeds = getListingSeedElements();
  const seenCards = new Set();
  for (const seed of seeds) {
    const plid = seed.plid;
    if (!plid) {
      continue;
    }
    const card = promoteListingCardHost(findListingProductCard(seed.node));
    if (!card || seenCards.has(card)) {
      continue;
    }
    const existingPlid = card.getAttribute(LIST_CARD_PLID_ATTR);
    const existingBox = card.querySelector(`.${LIST_CARD_BOX_CLASS}`);
    if (card.hasAttribute(LIST_CARD_BOUND_ATTR) && existingPlid === plid && existingBox) {
      continue;
    }
    if (card.hasAttribute(LIST_CARD_BOUND_ATTR)) {
      existingBox?.remove();
      card.removeAttribute(LIST_CARD_BOUND_ATTR);
      card.removeAttribute(LIST_CARD_PLID_ATTR);
    }
    seenCards.add(card);
    const title = getListingCardTitle(card, seed.node);
    const box = createListingCardBox(plid);
    box.dataset.title = title;
    mountListingCardBox(card, box);
    card.setAttribute(LIST_CARD_BOUND_ATTR, "true");
    card.setAttribute(LIST_CARD_PLID_ATTR, plid);
    observeListingCard(card, box, { plid, title });
  }
}

function observeListingCard(card, box, meta) {
  if (!state.listingIntersectionObserver) {
    state.listingIntersectionObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) {
          continue;
        }
        const target = entry.target;
        const plid = target.getAttribute(LIST_CARD_PLID_ATTR);
        const currentBox = target.querySelector(`.${LIST_CARD_BOX_CLASS}`);
        if (!plid || !currentBox) {
          continue;
        }
        state.listingIntersectionObserver.unobserve(target);
        enqueueListingPreview({
          plid,
          title: currentBox.dataset.title || "",
          box: currentBox,
          forceRefreshFacts: true,
        });
      }
    }, { rootMargin: "2200px 0px" });
  }
  state.listingIntersectionObserver.observe(card);

  const rect = card.getBoundingClientRect();
  if (rect.top < window.innerHeight + 2200 && rect.bottom > -2200) {
    enqueueListingPreview({ ...meta, box, forceRefreshFacts: true });
  }
}

function enqueueListingPreview(item) {
  const forceRefreshFacts = item.forceRefreshFacts !== false;
  if (forceRefreshFacts) {
    state.listingFactRefreshPlids.add(item.plid);
    state.listingFactRefreshAttemptedPlids.add(item.plid);
    if (item.previewForLoading) {
      item.box.innerHTML = buildListingCardBoxMarkup({ status: "loading", preview: item.previewForLoading });
    }
  }
  const requestKey = getListingRequestKey(item.plid, forceRefreshFacts);
  const pendingBoxes = state.listingPendingBoxes.get(requestKey);
  if (pendingBoxes) {
    pendingBoxes.push(item.box);
    return;
  }
  state.listingPendingBoxes.set(requestKey, [item.box]);
  state.listingQueue.push({
    plid: item.plid,
    title: item.title,
    forceRefreshFacts,
  });
  void pumpListingPreviewQueue();
}

async function pumpListingPreviewQueue() {
  while (state.listingActiveRequests < 4 && state.listingQueue.length) {
    const item = state.listingQueue.shift();
    state.listingActiveRequests += 1;
    void fetchListingPreview(item)
      .catch(() => {})
      .finally(() => {
        state.listingActiveRequests -= 1;
        void pumpListingPreviewQueue();
      });
  }
}

async function fetchListingPreview({ plid, title, forceRefreshFacts = false }) {
  const requestKey = getListingRequestKey(plid, forceRefreshFacts);
  try {
    const categoryPath = getListingPageCategoryPath();
    const response = await sendMessage({
      type: "xh:profit-preview",
      plid,
      title,
      categoryPath,
      storeId: state.settings.defaultStoreId,
      forceRefreshFacts,
    });
    if (!response?.ok) {
      throw new Error(response?.error || "同步失败");
    }
    const boxes = state.listingPendingBoxes.get(requestKey) || [];
    const preview = response.data;
    if (
      !forceRefreshFacts &&
      listingPreviewNeedsFactRefresh(preview) &&
      !state.listingFactRefreshAttemptedPlids.has(plid)
    ) {
      for (const box of boxes) {
        box.innerHTML = buildListingCardBoxMarkup({ status: "loading", preview });
      }
      const refreshKey = getListingRequestKey(plid, true);
      const refreshPendingBoxes = state.listingPendingBoxes.get(refreshKey);
      state.listingFactRefreshPlids.add(plid);
      state.listingFactRefreshAttemptedPlids.add(plid);
      if (refreshPendingBoxes) {
        refreshPendingBoxes.push(...boxes);
      } else {
        state.listingPendingBoxes.set(refreshKey, boxes);
        state.listingQueue.push({ plid, title, forceRefreshFacts: true });
        void pumpListingPreviewQueue();
      }
      return;
    }
    state.listingFactRefreshPlids.delete(plid);
    for (const box of boxes) {
      renderListingPreviewBox(box, preview);
    }
  } catch (error) {
    if (forceRefreshFacts) {
      state.listingFactRefreshPlids.delete(plid);
    }
    for (const box of state.listingPendingBoxes.get(requestKey) || []) {
      box.innerHTML = buildListingCardBoxMarkup({
        status: "error",
        error: error instanceof Error ? error.message : String(error),
      });
    }
  } finally {
    state.listingPendingBoxes.delete(requestKey);
  }
}

function renderListingPreviewBox(box, preview) {
  if (!box || !box.isConnected) {
    return;
  }
  box.innerHTML = buildListingCardBoxMarkup({ preview });
}

function scheduleListingCardScan() {
  if (!state.settings?.extensionToken || state.plid) {
    return;
  }
  if (state.listingScanTimer) {
    window.clearTimeout(state.listingScanTimer);
  }
  state.listingScanTimer = window.setTimeout(() => {
    state.listingScanTimer = null;
    scanListingProductCards();
  }, 180);
}

function initListingPageInjection() {
  if (!state.settings?.extensionToken || state.plid) {
    return;
  }
  scanListingProductCards();
  for (const delay of LISTING_SCAN_RETRY_DELAYS) {
    const timer = window.setTimeout(() => {
      state.listingRetryTimers = state.listingRetryTimers.filter((item) => item !== timer);
      scanListingProductCards();
    }, delay);
    state.listingRetryTimers.push(timer);
  }
  if (!state.listingScanInterval) {
    state.listingScanInterval = window.setInterval(() => {
      if (state.plid || !state.settings?.extensionToken) {
        return;
      }
      scanListingProductCards();
    }, LISTING_SCAN_INTERVAL_MS);
  }
  if (!state.listingMutationObserver) {
    state.listingMutationObserver = new MutationObserver(() => scheduleListingCardScan());
    state.listingMutationObserver.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: [
        "href",
        "src",
        "data-ref",
        "data-id",
        "data-url",
        "data-href",
        "data-product-id",
        "data-productline-id",
        "data-product-line-id",
        "data-plid",
      ],
    });
  }
  if (!state.listingScrollHandler) {
    state.listingScrollHandler = () => scheduleListingCardScan();
    window.addEventListener("scroll", state.listingScrollHandler, { passive: true, capture: true });
  }
  if (!state.listingResizeHandler) {
    state.listingResizeHandler = () => scheduleListingCardScan();
    window.addEventListener("resize", state.listingResizeHandler, { passive: true });
  }
}

function clearListingPageInjection() {
  if (state.listingScanTimer) {
    window.clearTimeout(state.listingScanTimer);
    state.listingScanTimer = null;
  }
  if (state.listingScanInterval) {
    window.clearInterval(state.listingScanInterval);
    state.listingScanInterval = null;
  }
  for (const timer of state.listingRetryTimers) {
    window.clearTimeout(timer);
  }
  state.listingRetryTimers = [];
  if (state.listingMutationObserver) {
    state.listingMutationObserver.disconnect();
    state.listingMutationObserver = null;
  }
  if (state.listingScrollHandler) {
    window.removeEventListener("scroll", state.listingScrollHandler, true);
    state.listingScrollHandler = null;
  }
  if (state.listingResizeHandler) {
    window.removeEventListener("resize", state.listingResizeHandler);
    state.listingResizeHandler = null;
  }
  for (const box of document.querySelectorAll(`.${LIST_CARD_BOX_CLASS}`)) {
    box.remove();
  }
  for (const card of document.querySelectorAll(`[${LIST_CARD_BOUND_ATTR}]`)) {
    card.removeAttribute(LIST_CARD_BOUND_ATTR);
    card.removeAttribute(LIST_CARD_PLID_ATTR);
    card.classList.remove(LIST_CARD_HOST_CLASS, LIST_CARD_VERTICAL_HOST_CLASS);
  }
  state.listingQueue = [];
  state.listingPendingBoxes.clear();
  state.listingFactRefreshPlids.clear();
  state.listingFactRefreshAttemptedPlids.clear();
  if (state.listingIntersectionObserver) {
    state.listingIntersectionObserver.disconnect();
    state.listingIntersectionObserver = null;
  }
}

async function createListNowTask(plid, title, storeId, salePriceZar, quantity) {
  return chrome.runtime.sendMessage({
    type: "xh:list-now",
    plid,
    title,
    storeId,
    salePriceZar,
    quantity,
  });
}

async function loadSession() {
  const response = await sendMessage({ type: "xh:get-session" });
  if (!response?.ok) {
    throw new Error(response?.error || "读取扩展会话失败");
  }
  return response.data;
}

async function loadPricingDraft() {
  if (!state.plid) return;
  const response = await sendMessage({
    type: "xh:get-pricing-draft",
    plid: state.plid,
    storeId: state.settings?.defaultStoreId || "",
  });
  if (response?.ok && response.data) {
    state.pricingDraft = {
      airFreightUnitCnyPerKg: stringifyPositiveNumber(response.data.airFreightUnitCnyPerKg),
      purchasePriceCny: stringifyPositiveNumber(response.data.purchasePriceCny),
      salePriceZar: stringifyPositiveNumber(response.data.salePriceZar),
      actualWeightKg: stringifyPositiveNumber(response.data.actualWeightKg),
      lengthCm: stringifyPositiveNumber(response.data.lengthCm),
      widthCm: stringifyPositiveNumber(response.data.widthCm),
      heightCm: stringifyPositiveNumber(response.data.heightCm),
    };
  } else {
    state.pricingDraft = createEmptyPricingDraft();
  }
}

async function savePricingDraft() {
  if (!state.plid) return;
  await sendMessage({
    type: "xh:set-pricing-draft",
    plid: state.plid,
    storeId: state.settings?.defaultStoreId || "",
    airFreightUnitCnyPerKg: parsePositiveNumber(state.pricingDraft.airFreightUnitCnyPerKg),
    purchasePriceCny: parsePositiveNumber(state.pricingDraft.purchasePriceCny),
    salePriceZar: parsePositiveNumber(state.pricingDraft.salePriceZar),
    actualWeightKg: parsePositiveNumber(state.pricingDraft.actualWeightKg),
    lengthCm: parsePositiveNumber(state.pricingDraft.lengthCm),
    widthCm: parsePositiveNumber(state.pricingDraft.widthCm),
    heightCm: parsePositiveNumber(state.pricingDraft.heightCm),
  });
}

async function loadSettings() {
  const response = await sendMessage({ type: "xh:get-settings" });
  if (!response?.ok) {
    throw new Error(response?.error || "读取扩展配置失败");
  }
  state.settings = response.data;
  renderPanel();
}

async function requestPreview() {
  if (!state.settings?.extensionToken || !state.settings?.defaultStoreId || !state.plid) {
    return;
  }
  const previewPlid = state.plid;
  const salePriceZar = getEffectiveSalePriceZar();
  state.categoryPath = getProductCategoryPath();
  setLoading(true);
  setHint("正在同步商品事实…");
  try {
    const response = await sendMessage({
      type: "xh:profit-preview",
      plid: previewPlid,
      title: state.title,
      categoryPath: state.categoryPath,
      storeId: state.settings.defaultStoreId,
      forceRefreshFacts: true,
      airFreightUnitCnyPerKg: parsePositiveNumber(state.pricingDraft.airFreightUnitCnyPerKg),
      purchasePriceCny: parsePositiveNumber(state.pricingDraft.purchasePriceCny),
      salePriceZar,
      actualWeightKg: parsePositiveNumber(state.pricingDraft.actualWeightKg),
      lengthCm: parsePositiveNumber(state.pricingDraft.lengthCm),
      widthCm: parsePositiveNumber(state.pricingDraft.widthCm),
      heightCm: parsePositiveNumber(state.pricingDraft.heightCm),
    });
    if (!response?.ok) {
      throw new Error(response?.error || "预览失败");
    }
    if (state.plid !== previewPlid) {
      return;
    }
    state.preview = response.data;
    if (
      !state.preview?.guardrail?.protected_floor_price &&
      state.preview?.pricing?.recommended_protected_floor_price_zar
    ) {
      const suggestedFloor = String(state.preview.pricing.recommended_protected_floor_price_zar);
      state.pricingDraft.suggestedProtectedFloor = suggestedFloor;
    }
    renderPanel();
    if (listingPreviewHasWeight(state.preview) && listingPreviewHasDimensions(state.preview)) {
      clearFactRetry();
      setHint("已实时获取重量尺寸，点一键上架后再选择店铺和保护价。", "success");
    } else {
      setHint("正在补全商品重量和尺寸，完成后会自动刷新试算。");
      scheduleFactRetry(previewPlid);
    }
    scheduleCategoryRetry(previewPlid);
  } catch (error) {
    if (String(error).includes("Invalid or expired extension token")) {
      await sendMessage({ type: "xh:logout" });
      state.settings = null;
      state.preview = null;
      const panel = document.getElementById(PANEL_ID);
      if (panel) {
        panel.remove();
      }
      return;
    }
    renderPanel();
    setHint(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setLoading(false);
  }
}

function clearFactRetry() {
  if (state.factRetryTimer) {
    window.clearTimeout(state.factRetryTimer);
    state.factRetryTimer = null;
  }
  state.factRetryPlid = null;
  state.factRetryCount = 0;
}

function scheduleFactRetry(plid) {
  if (!plid || state.plid !== plid) {
    return;
  }
  if (state.factRetryPlid !== plid) {
    state.factRetryPlid = plid;
    state.factRetryCount = 0;
  }
  if (state.factRetryTimer || state.factRetryCount >= 5) {
    return;
  }
  const delays = [1500, 3000, 6000, 10000, 15000];
  const delay = delays[Math.min(state.factRetryCount, delays.length - 1)];
  state.factRetryCount += 1;
  state.factRetryTimer = window.setTimeout(() => {
    state.factRetryTimer = null;
    if (state.plid === plid && state.settings?.extensionToken) {
      void requestPreview();
    }
  }, delay);
}

function scheduleCategoryRetry(plid) {
  if (state.categoryPath.length || state.categoryRetryPlid === plid) {
    return;
  }
  state.categoryRetryPlid = plid;
  setTimeout(() => {
    if (state.plid !== plid) {
      return;
    }
    const categoryPath = getProductCategoryPath();
    if (categoryPath.length) {
      state.categoryPath = categoryPath;
      void requestPreview();
    }
  }, 1000);
}

async function handleLogin() {
  const username = document.querySelector('[data-field="erp-username"]')?.value?.trim() || "";
  const password = document.querySelector('[data-field="erp-password"]')?.value?.trim() || "";
  if (!username || !password) {
    setHint("账号、密码都要填。", "error");
    return;
  }
  setLoading(true);
  setHint("正在登录 ERP…");
  try {
    const response = await sendMessage({
      type: "xh:login",
      username,
      password,
    });
    if (!response?.ok) {
      throw new Error(response?.error || "登录失败");
    }
    state.settings = await (await sendMessage({ type: "xh:get-settings" })).data;
    renderPanel();
    setHint("ERP 已连接。", "success");
    await requestPreview();
  } catch (error) {
    if (isBenignExtensionInjectionError(error)) {
      const settingsResponse = await sendMessage({ type: "xh:get-settings" });
      if (settingsResponse?.ok && settingsResponse.data?.extensionToken) {
        state.settings = settingsResponse.data;
        renderPanel();
        setHint("ERP 已连接。", "success");
        if (state.plid) {
          await requestPreview();
        }
        return;
      }
    }
    setHint(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setLoading(false);
  }
}

async function handleStoreChange(storeId) {
  const response = await sendMessage({
    type: "xh:set-store",
    storeId,
  });
  if (!response?.ok) {
    setHint(response?.error || "切换店铺失败", "error");
    return;
  }
  state.settings.defaultStoreId = storeId;
  await loadPricingDraft();
  await requestPreview();
}

async function handleRecalculate() {
  await savePricingDraft();
  await requestPreview();
}

async function saveProtectedFloorValue(protectedFloorPrice, storeId) {
  if (!state.plid) {
    throw new Error("没有识别到当前商品 PLID。");
  }
  if (!storeId) {
    throw new Error("请先选择店铺。");
  }

  const response = await sendMessage({
    type: "xh:protected-floor",
    plid: state.plid,
    title: state.title,
    protectedFloorPrice,
    storeId,
  });
  if (!response?.ok) {
    throw new Error(response?.error || "保存保护价失败");
  }
  state.preview = {
    ...(state.preview || {}),
    guardrail: response.data,
    product: state.preview?.product,
  };
  return response.data;
}

async function handleSaveFloor() {
  const input = document.querySelector('[data-field="modal-protected-floor"]');
  if (!input || !state.plid) {
    return;
  }
  const rawValue = String(input.value || "").trim();
  const fallbackSuggested = state.preview?.pricing?.recommended_protected_floor_price_zar;
  const effectiveRawValue = rawValue || (fallbackSuggested != null ? String(fallbackSuggested) : "");
  if (!effectiveRawValue) {
    setHint("请先输入保护价。", "error");
    return;
  }
  if (!rawValue && fallbackSuggested != null) {
    input.value = String(fallbackSuggested);
  }
  const numericValue = Number(effectiveRawValue);
  if (!Number.isFinite(numericValue) || numericValue <= 0) {
    setHint("保护价必须大于 0。", "error");
    return;
  }
  if (!state.settings?.defaultStoreId) {
    setHint("请先选择店铺。", "error");
    return;
  }

  setLoading(true);
  setHint("正在保存保护价…");
  try {
    await saveProtectedFloorValue(numericValue, state.settings.defaultStoreId);
    renderPanel();
    setHint("保护价已保存，后续 listing 同步后会自动挂到 AutoBid。", "success");
  } catch (error) {
    setHint(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setLoading(false);
  }
}

async function handleApplySuggestedFloor() {
  if (!isPricingComplete(state.preview?.pricing)) {
    setHint("计费信息还没完整加载，等重量、尺寸、空运费和尾程费都算出来后再采用建议保护价。", "error");
    return;
  }
  const suggested = state.preview?.pricing?.recommended_protected_floor_price_zar;
  if (suggested == null) {
    setHint("请先完成试算后再采用建议保护价。", "error");
    return;
  }
  const input = document.querySelector('[data-field="modal-protected-floor"]');
  if (input) {
    input.value = String(suggested);
  }
}

async function handleLogout() {
  await sendMessage({ type: "xh:logout" });
  state.settings = await (await sendMessage({ type: "xh:get-settings" })).data;
  state.preview = null;
  renderPanel();
  setHint("已退出扩展连接。");
}

function setModalOpen(open) {
  const modal = document.querySelector('[data-modal="list-now"]');
  if (!modal) return;
  modal.classList.toggle("hidden", !open);
}

async function handleListNow() {
  const select = document.querySelector('[data-field="modal-store-select"]');
  const storeId = select?.value || state.settings?.defaultStoreId;
  if (!storeId) {
    setHint("请先选择店铺。", "error");
    return;
  }

  const protectedFloorInput = document.querySelector('[data-field="modal-protected-floor"]');
  const suggestedProtectedFloor = state.preview?.pricing?.recommended_protected_floor_price_zar;
  const protectedFloorRaw =
    String(protectedFloorInput?.value || "").trim() ||
    (suggestedProtectedFloor != null ? String(suggestedProtectedFloor) : "");
  const protectedFloorPrice = Number(protectedFloorRaw);
  if (!Number.isFinite(protectedFloorPrice) || protectedFloorPrice <= 0) {
    setHint("请先填写有效保护价。", "error");
    return;
  }

  const salePriceZar = getEffectiveSalePriceZar();
  const quantityInput = document.querySelector('[data-field="modal-quantity"]');
  const quantity = parsePositiveNumber(quantityInput?.value) ?? parsePositiveNumber(state.settings?.defaultStockQty) ?? 1;
  if (salePriceZar == null) {
    setHint("请先确认销售价后再发起一键上架。", "error");
    return;
  }
  if (!isPricingComplete(state.preview?.pricing)) {
    setHint("计费信息还没完整加载，已阻止上架：请等计费重、空运费、尾程费和建议保护价全部显示后再提交。", "error");
    return;
  }

  setLoading(true);
  setHint("正在保存保护价并提交上架…");
  try {
    await saveProtectedFloorValue(protectedFloorPrice, storeId);
    const response = await createListNowTask(state.plid, state.title, storeId, salePriceZar, quantity);
    if (!response?.ok) {
      throw new Error(response?.error || "创建任务失败");
    }
    setModalOpen(false);
    const automation = response.data?.automation;
    const openedListingCenter = Boolean(automation?.openedListingCenter);
    if (automation?.outcome === "buyable") {
      setHint(
        openedListingCenter ? "已上架，已为你打开上架记录" : "已上架",
        "success",
      );
      return;
    }
    if (automation?.outcome === "failed") {
      setHint(
        openedListingCenter ? "上架失败，已为你打开上架记录" : "上架失败",
        "error",
      );
      return;
    }
    if (automation?.message) {
      setHint("正在处理，结果出来后会显示到上架记录", "success");
      return;
    }
    setHint("正在处理，结果出来后会显示到上架记录", "success");
  } catch (error) {
    setHint(error instanceof Error ? error.message : String(error), "error");
  } finally {
    setLoading(false);
  }
}

function bindEvents() {
  document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) {
      return;
    }

    if (target.matches('[data-action="refresh"]')) {
      void requestPreview();
    }
    if (target.matches('[data-action="login"]')) {
      void handleLogin();
    }
    if (target.matches('[data-action="fill-suggested-floor"]')) {
      void handleApplySuggestedFloor();
    }
    if (target.matches('[data-action="recalculate"]')) {
      void handleRecalculate();
    }
    if (target.matches('[data-action="logout"]')) {
      void handleLogout();
    }
    if (target.matches('[data-action="open-list-now"]')) {
      setModalOpen(true);
    }
    if (target.matches('[data-action="close-list-now"]')) {
      setModalOpen(false);
    }
    if (target.matches('[data-action="confirm-list-now"]')) {
      void handleListNow();
    }
  });

  document.addEventListener("change", (event) => {
    const target = event.target;
    if (target instanceof HTMLSelectElement) {
      if (target.matches('[data-field="modal-store-select"]')) {
        return;
      }
      return;
    }
    if (target instanceof HTMLInputElement) {
      if (target.matches('[data-field="air-freight-unit"]')) {
        state.pricingDraft.airFreightUnitCnyPerKg = target.value;
      }
      if (target.matches('[data-field="purchase-price"]')) {
        state.pricingDraft.purchasePriceCny = target.value;
      }
      if (target.matches('[data-field="sale-price"]')) {
        state.pricingDraft.salePriceZar = target.value;
      }
      if (target.matches('[data-field="actual-weight"]')) {
        state.pricingDraft.actualWeightKg = target.value;
      }
      if (target.matches('[data-field="length-cm"]')) {
        state.pricingDraft.lengthCm = target.value;
      }
      if (target.matches('[data-field="width-cm"]')) {
        state.pricingDraft.widthCm = target.value;
      }
      if (target.matches('[data-field="height-cm"]')) {
        state.pricingDraft.heightCm = target.value;
      }
    }
  });
}

function installNavigationWatcher() {
  let lastUrl = window.location.href;
  const rerenderIfChanged = () => {
    if (window.location.href === lastUrl) {
      return;
    }
    lastUrl = window.location.href;
    const nextPlid = extractPlid();
    const plidChanged = nextPlid !== state.plid;
    state.plid = nextPlid;
    state.title = getProductTitle();
    state.categoryPath = getProductCategoryPath();
    state.categoryRetryPlid = null;
    clearFactRetry();
    if (plidChanged) {
      state.preview = null;
      state.pricingDraft = createEmptyPricingDraft();
      renderPanel();
    }
    setTimeout(() => {
      void (async () => {
        if (!state.settings?.extensionToken) {
          return;
        }
        if (!state.plid) {
          initListingPageInjection();
          return;
        }
        clearListingPageInjection();
        await loadPricingDraft();
        renderPanel();
        await requestPreview();
      })();
    }, 300);
  };

  const originalPushState = history.pushState;
  history.pushState = function (...args) {
    const result = originalPushState.apply(this, args);
    rerenderIfChanged();
    return result;
  };
  window.addEventListener("popstate", rerenderIfChanged);

  const observer = new MutationObserver(() => rerenderIfChanged());
  observer.observe(document.documentElement, { childList: true, subtree: true });
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "xh:session-updated") {
    void boot(true);
    sendResponse({ ok: true });
  }
});

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function formatNumber(value, digits = 2) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) {
    return "待测算";
  }
  return Number(value).toLocaleString("en-ZA", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) {
    return "待测算";
  }
  return `${(Number(value) * 100).toFixed(1).replace(/\.0$/, "")}%`;
}

function formatZar(value) {
  if (value == null || value === "" || !Number.isFinite(Number(value))) {
    return "待测算";
  }
  return `R ${formatNumber(value, 2)}`;
}

function formatCompactNumber(value) {
  if (!hasFiniteNumber(value)) {
    return "";
  }
  return Number(value).toLocaleString("en-ZA", {
    maximumFractionDigits: 2,
    minimumFractionDigits: 0,
  });
}

function hasFiniteNumber(value) {
  return value != null && value !== "" && Number.isFinite(Number(value));
}

function isPricingComplete(pricing) {
  return Boolean(
    pricing &&
      hasFiniteNumber(pricing.chargeable_weight_kg) &&
      hasFiniteNumber(pricing.airfreight_cost_zar) &&
      hasFiniteNumber(pricing.tail_shipping_fee_zar) &&
      hasFiniteNumber(pricing.tail_vat_fee_zar) &&
      hasFiniteNumber(pricing.recommended_protected_floor_price_zar),
  );
}

function formatCategoryPath(path) {
  return Array.isArray(path) && path.length ? path.join(" > ") : "";
}

function formatCompactDimensions(product = {}, pricing = {}) {
  const length = product.length_cm ?? pricing.length_cm;
  const width = product.width_cm ?? pricing.width_cm;
  const height = product.height_cm ?? pricing.height_cm;
  if (hasFiniteNumber(length) && hasFiniteNumber(width) && hasFiniteNumber(height)) {
    return `${formatCompactNumber(length)}x${formatCompactNumber(width)}x${formatCompactNumber(height)} cm`;
  }
  const raw = product.merchant_packaged_dimensions_raw || product.cbs_package_dimensions_raw || product.consolidated_packaged_dimensions_raw;
  return raw || "未补全";
}

function formatCompactWeight(product = {}, pricing = {}) {
  const weight = product.actual_weight_kg ?? pricing.actual_weight_kg;
  if (hasFiniteNumber(weight)) {
    return `${formatCompactNumber(weight)} kg`;
  }
  return product.merchant_packaged_weight_raw || product.cbs_package_weight_raw || "未补全";
}

function formatFulfillmentTier(sizeTier, weightTier) {
  const sizeLabels = {
    low_standard: "低费标准件",
    mid_standard: "中费标准件",
    other_standard: "标准件",
    electronics_standard: "电子标准件",
    large: "Large",
    oversize: "Oversize",
    bulky: "Bulky",
    extra_bulky: "Extra Bulky",
  };
  const weightLabels = {
    light: "<=7kg",
    heavy: "7-25kg",
    heavy_plus: "25-40kg",
    very_heavy: "40kg+",
  };
  if (!sizeTier && !weightTier) {
    return "按尺寸/重量自动测算";
  }
  return `${sizeLabels[sizeTier] || sizeTier || "-"} · ${weightLabels[weightTier] || weightTier || "-"}`;
}

async function boot(forceRefresh = false) {
  ensurePanelStylesheet();
  state.plid = extractPlid();
  state.title = getProductTitle();
  state.categoryPath = getProductCategoryPath();
  const session = await loadSession();
  if (!session?.connected) {
    clearListingPageInjection();
    clearFactRetry();
    const panel = document.getElementById(PANEL_ID);
    if (panel) {
      panel.remove();
    }
    state.settings = null;
    state.preview = null;
    return;
  }
  await loadSettings();
  if (state.settings?.extensionToken) {
    if (!state.plid) {
      clearFactRetry();
      initListingPageInjection();
      return;
    }
    clearListingPageInjection();
    if (forceRefresh) {
      state.preview = null;
    }
    await loadPricingDraft();
    renderPanel();
    if (state.settings?.defaultStoreId) {
      await requestPreview();
    } else {
      setHint("请选择一个默认店铺后再加载商品护栏。");
    }
  }
}

globalThis.__xhErpTakealotContent = {
  boot,
  scanListingProductCards,
  initListingPageInjection,
};

bindEvents();
installNavigationWatcher();
void boot();
})();
