/* Common TypeScript types shared across the frontend */

export interface ApiResponse<_T = any> {
  ok: boolean
  error?: string
  [key: string]: any
}

export interface PaginatedMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
}

// Auth
export interface UserInfo {
  id: number
  username: string
  role: string
  license_type: string
  license_expires_at: string | null
  created_at: string
}

export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  license_key?: string
}

export interface AuthTokens {
  access_token: string
  refresh_token: string
  token_type: string
}

// Store
export interface StoreItem {
  id: number
  store_name: string
  store_alias: string
  offer_count: number
  api_key_status: string
  last_synced_at: string | null
  health_score: number
  health_level: string
  sync_freshness: string
}

// Bid
export interface BidProductItem {
  id: number
  store_binding_id: number
  offer_id: string
  title: string
  sku: string
  current_price_zar: number
  buybox_price_zar: number
  floor_price_zar: number
  target_price_zar: number
  auto_bid_enabled: number
  is_active: number
  last_bid_at: string | null
  last_error: string
}

export interface BidEngineStatus {
  store_id: number
  running: boolean
  cycle_count: number
  last_cycle_at: string | null
  products_total: number
  products_active: number
  last_error: string
}

// Listing
export interface ListingJobItem {
  id: number
  store_id: number
  amazon_url: string
  listing_title: string | null
  status: string
  error_message: string
  created_at: string
  updated_at: string | null
}

// Dropship
export interface DropshipJobItem {
  id: number
  store_id: number
  source_keyword: string
  amazon_url: string
  status: string
  error_message: string
  submission_id: string
  created_at: string
  updated_at: string | null
}

// Library
export interface LibraryProductItem {
  product_id: number
  tsin: number | null
  title: string
  brand: string
  slug: string
  url: string
  image: string
  category_main: string
  category_l1: string | null
  price_min: number | null
  price_max: number | null
  pretty_price: string
  saving: string
  star_rating: number | null
  reviews_total: number
  reviews_5: number
  reviews_4: number
  reviews_3: number
  reviews_2: number
  reviews_1: number
  latest_review_at: string | null
  in_stock: string
  is_preorder: number
  offer_count: number
  updated_at: string | null
}

export interface ScrapeProgress {
  running: boolean
  total_scraped: number
  round: number
  current_cat: string
  total_cats: number
  done_cats: number
  mode: string
  error: string | null
  elapsed_sec: number
  last_event: string
}

export interface LibraryStats {
  auto_scrape: {
    running: boolean
    status: string
    last_started_at: string | null
    last_finished_at: string | null
    last_task_id: string | null
    last_total_scraped: number
    last_new_products: number
    last_error: string | null
  }
  total_products: number
  quarantined: number
  categories: number
  brands: number
  last_updated: string | null
}

// Dashboard
export interface DashboardStats {
  store_count: number
  total_offers: number
  total_bid_products: number
  active_bid_products: number
  dropship_submitted: number
  fulfillment_failed: number
  total_sales_zar: number
  total_orders: number
  daily_data: DailyData[]
  snapshot_fallback: boolean
  snapshot_stale: boolean
  refreshing: boolean
  alerts: any[]
}

export interface DailyData {
  date: string
  sales: number
  orders: number
}

export interface ActivityItem {
  module: string
  level: string
  title: string
  detail: string
  created_at: string
}

// Notification
export interface NotificationItem {
  id: number
  level: string
  title: string
  detail: string
  module: string
  is_read: number
  created_at: string | null
}

// CN Express
export interface CnExpressOrder {
  id: number
  order_no: string
  tracking_number: string
  status: string
  weight_kg: number
  created_at: string
}

// Profit Calculator
export interface ProfitResult {
  ok: boolean
  selling_price_zar: number
  cost_cny: number
  cost_zar: number
  freight_cny: number
  freight_zar: number
  commission_zar: number
  vat_zar: number
  total_cost_zar: number
  profit_zar: number
  margin_rate: number
  suggested_price_zar: number
  fx_rate: number
  weight_kg: number
}

// --- 履约中心类型 ---
export type WorkflowStatus =
  | '待用户预报快递'
  | '待到仓'
  | '待贴三标'
  | '待送嘉鸿'
  | '待用户预报嘉鸿'
  | '嘉鸿已预报'

export interface FulfillmentDraftItem {
  id: number
  shipment_item_id: string
  line_no: number
  sku: string
  title: string
  takealot_url: string
  tsin_id: string
  qty_required: number
  qty_sending: number
  arrived_qty: number
  domestic_tracking_no: string
  domestic_carrier: string
  declared_en_name: string
  declared_cn_name: string
  hs_code: string
  origin_country: string
  unit_price_usd: number
  unit_weight_kg: number
  note: string
}

export interface FulfillmentDraft {
  id: number
  store_binding_id: number
  user_id: number
  shipment_id: number
  shipment_name: string
  po_number: string
  due_date: string
  facility_code: string
  warehouse_name: string
  package_count: number
  total_weight_kg: number
  decl_currency: string
  sender_country: string
  delivery_address: string
  selected_cnx_warehouse_id: number | null
  selected_cnx_line_id: number | null
  cnx_order_no: string
  cnx_forecasted_at: string | null
  workflow_status: WorkflowStatus
  warehouse_received_complete: number
  labels_done: number
  labels_done_at: string | null
  sent_to_cnx: number
  sent_to_cnx_at: string | null
  notify_user_cnx_at: string | null
  warehouse_note: string
  updated_by_username: string
  updated_by_role: string
  version: number
  created_at: string | null
  updated_at: string | null
  items: FulfillmentDraftItem[]
}

export interface WarehouseJobSummary {
  store_id: number
  store_alias: string
  shipment_id: number
  shipment_name: string
  po_number: string
  due_date: string
  workflow_status: WorkflowStatus
  ready_count: number
  total_items: number
  updated_at: string | null
  updated_by_username: string
}

export interface AuditLogEntry {
  id: number
  action: string
  old_status: string
  new_status: string
  changes_json: string
  username: string
  role: string
  created_at: string | null
}
