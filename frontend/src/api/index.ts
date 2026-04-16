/* API modules — one function per backend endpoint */
import http from './http'

// ---- Auth ----
export const authApi = {
  login: (data: { username: string; password: string }) => http.post('/auth/login', data),
  register: (data: { username: string; password: string; email: string; email_code: string }) =>
    http.post('/auth/register', data),
  sendCode: (email: string) => http.post('/auth/send-code', { email }),
  logout: () => http.post('/auth/logout'),
  me: () => http.get('/auth/me'),
  refresh: (refresh_token: string) => http.post('/auth/refresh', { refresh_token }),
  activate: (key: string) => http.post('/auth/activate', { key }),
}

// ---- Stores ----
export const storeApi = {
  list: () => http.get('/stores'),
  get: (id: number) => http.get(`/stores/${id}`),
  create: (data: any) => http.post('/stores', data),
  update: (id: number, data: any) => http.patch(`/stores/${id}`, data),
  remove: (id: number) => http.delete(`/stores/${id}`),
  sync: (id: number) => http.post(`/stores/${id}/sync`),
  offers: (id: number, params?: any) => http.get(`/stores/${id}/offers`, { params }),
  sales: (id: number, params?: any) => http.get(`/stores/${id}/sales/orders`, { params }),
  finance: (id: number, params?: any) => http.get(`/stores/${id}/financial/statements`, { params }),
  financeBalance: (id: number) => http.get(`/stores/${id}/financial/balance`),
  shipments: (id: number, params?: any) => http.get(`/stores/${id}/shipments`, { params }),
}

// ---- Dashboard ----
export const dashboardApi = {
  stats: () => http.get('/dashboard/stats'),
  activity: (limit = 20) => http.get('/dashboard/activity', { params: { limit } }),
}

// ---- Bids ----
export const bidApi = {
  status: (storeId: number) => http.get(`/bids/${storeId}/status`),
  start: (storeId: number) => http.post(`/bids/${storeId}/start`),
  stop: (storeId: number) => http.post(`/bids/${storeId}/stop`),
  products: (storeId: number, params?: any) =>
    http.get(`/bids/${storeId}/products`, { params }),
  refreshBuybox: (storeId: number, offerId: string) =>
    http.post(`/bids/${storeId}/products/${offerId}/refresh-buybox`),
  refreshAllBuybox: (storeId: number) =>
    http.post(`/bids/${storeId}/products/refresh-buybox-all`),
  syncProducts: (storeId: number) => http.post(`/bids/${storeId}/products/sync`),
  syncStatus: (storeId: number) => http.get(`/bids/${storeId}/products/sync/status`),
  upsertProducts: (storeId: number, data: any) =>
    http.post(`/bids/${storeId}/products`, data),
  patchProduct: (storeId: number, offerId: string, data: any) =>
    http.patch(`/bids/${storeId}/products/${offerId}`, data),
  exportProducts: (storeId: number) =>
    http.get(`/bids/${storeId}/products/export`, { responseType: 'blob' }),
  importProducts: (storeId: number, formData: FormData) =>
    http.post(`/bids/${storeId}/products/import`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    }),
  log: (storeId: number, params?: any) =>
    http.get(`/bids/${storeId}/log`, { params }),
  insights: (storeId: number) => http.get(`/bids/${storeId}/insights`),
}

// ---- Products ----
export const productApi = {
  list: (storeId: number, params?: any) =>
    http.get(`/products/${storeId}`, { params }),
  detail: (storeId: number, offerId: string) =>
    http.get(`/products/${storeId}/${offerId}`),
  saveSync: (storeId: number, offerId: string, data: any) =>
    http.post(`/products/${storeId}/${offerId}/save-sync`, data),
  sync: (storeId: number) => http.post(`/products/${storeId}/sync`),
  syncStatus: (storeId: number) => http.get(`/products/${storeId}/sync/status`),
}

// ---- Listings ----
export const listingApi = {
  list: (params?: any) => http.get('/listings/jobs', { params }),
  create: (data: any) => http.post('/listings/jobs', data),
  get: (id: number) => http.get(`/listings/jobs/${id}`),
  retry: (id: number) => http.post(`/listings/jobs/${id}/retry`),
  stats: () => http.get('/listings/stats'),
}

// ---- Dropship ----
export const dropshipApi = {
  list: (params?: any) => http.get('/dropship/jobs', { params }),
  keywordImport: (data: any) => http.post('/dropship/keyword-import', data),
  keywordProgress: () => http.get('/dropship/keyword-progress'),
  get: (id: number) => http.get(`/dropship/jobs/${id}`),
  retry: (id: number) => http.post(`/dropship/jobs/${id}/retry`),
  stats: () => http.get('/dropship/stats'),
}

// ---- Library ----
export const libraryApi = {
  list: (params?: any) => http.get('/library/products', { params }),
  detail: (productId: number) => http.get(`/library/products/${productId}`),
  stats: () => http.get('/library/stats'),
  filters: () => http.get('/library/filters'),
  export: (params?: any) => http.get('/library/export', { params, responseType: 'blob' }),
  scrapeStart: (data: any) => http.post('/library/scrape/start', data),
  scrapeProgress: () => http.get('/library/scrape/progress'),
  scrapeStop: () => http.post('/library/scrape/stop'),
  quarantine: (data: any) => http.post('/library/quarantine', data),
  quarantineList: (params?: any) => http.get('/library/quarantine', { params }),
  import: (data: any) => http.post('/library/import', data),
}

// ---- Stores (additional) ----
// Financial transactions endpoint
export const storeFinanceApi = {
  transactions: (storeId: number, params?: any) =>
    http.get(`/stores/${storeId}/financial/transactions`, { params }),
}

// ---- CN Express ----
export const cnexpressApi = {
  account: () => http.get('/cnexpress/account'),
  saveAccount: (data: any) => http.post('/cnexpress/account', data),
  loginAccount: (data: any) => http.post('/cnexpress/account/login', data),
  warehouses: () => http.get('/cnexpress/warehouses'),
  lines: (params?: any) => http.get('/cnexpress/lines', { params }),
  orders: (params?: any) => http.get('/cnexpress/orders', { params }),
  createOrder: (data: any) => http.post('/cnexpress/orders', data),
  getOrder: (id: number) => http.get(`/cnexpress/orders/${id}`),
  labels: (orderNo: string) => http.get(`/cnexpress/labels/${orderNo}`),
  wallet: () => http.get('/cnexpress/wallet'),
  tracking: (trackingNo: string) => http.get(`/cnexpress/tracking/${trackingNo}`),
}

// ---- Warehouse ----
export const warehouseApi = {
  jobs: (params?: any) => http.get('/warehouse/jobs', { params }),
  jobDetail: (storeId: number, shipmentId: number) =>
    http.get(`/warehouse/jobs/${storeId}/${shipmentId}`),
  saveDraft: (storeId: number, shipmentId: number, data: any) =>
    http.post(`/warehouse/jobs/${storeId}/${shipmentId}`, data),
  getDraft: (storeId: number, shipmentId: number) =>
    http.get(`/warehouse/drafts/${storeId}/${shipmentId}`),
  printData: (storeId: number, shipmentId: number) =>
    http.get(`/warehouse/print/${storeId}/${shipmentId}`),
  submitCnx: (storeId: number, shipmentId: number, data: any) =>
    http.post(`/warehouse/jobs/${storeId}/${shipmentId}/cnx-submit`, data),
  auditLog: (storeId: number, shipmentId: number) =>
    http.get(`/warehouse/audit/${storeId}/${shipmentId}`),
}

// ---- Notifications ----
export const notificationApi = {
  list: (limit = 50) => http.get('/notifications', { params: { limit } }),
  markRead: (id: number) => http.post(`/notifications/${id}/read`),
  markAllRead: () => http.post('/notifications/read_all'),
  unreadCount: () => http.get('/notifications/unread_count'),
}

// ---- Profit Calculator ----
export const profitApi = {
  calculate: (data: any) => http.post('/profit/calculate', data),
}

// ---- Admin ----
export const adminApi = {
  stats: () => http.get('/admin/stats'),
  systemHealth: () => http.get('/admin/system-health'),
  users: (params?: any) => http.get('/admin/users', { params }),
  updateUser: (id: number, data: any) => http.patch(`/admin/users/${id}`, data),
  generateLicense: (data: any) => http.post('/admin/licenses/generate', data),
  exportLicenses: () => http.get('/admin/licenses/export', { responseType: 'blob' }),
}
