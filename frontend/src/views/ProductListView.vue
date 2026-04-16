<template>
  <div>
    <div class="page-header">
      <h2>商品管理</h2>
      <div style="display: flex; align-items: center; gap: 12px">
        <el-radio-group v-model="statusFilter" size="small">
          <el-radio-button label="">全部 ({{ totalCount }})</el-radio-button>
          <el-radio-button label="Buyable">在售 ({{ buyableCount }})</el-radio-button>
          <el-radio-button label="Not Buyable">不可购买 ({{ notBuyableCount }})</el-radio-button>
          <el-radio-button label="OffShelf">已下架 ({{ offShelfCount }})</el-radio-button>
        </el-radio-group>
        <el-button type="primary" @click="syncProducts" :loading="syncing">同步商品</el-button>
      </div>
    </div>

    <el-alert
      v-if="syncProgress.running"
      class="sync-progress-banner"
      type="info"
      :closable="false"
      show-icon
    >
      <template #title>商品同步进行中 · {{ syncStageLabel }}</template>
      <div class="sync-progress-text">{{ syncProgressDetail }}</div>
      <el-progress
        v-if="syncProgress.total"
        :percentage="syncPercentage"
        :stroke-width="8"
        :show-text="syncPercentage > 0"
      />
    </el-alert>

    <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 16px">
      <el-input
        v-model="searchQuery"
        placeholder="搜索 SKU / 商品名"
        style="width: 260px"
        clearable
        @keyup.enter="handleSearch"
        @clear="handleSearch"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <el-button type="primary" plain @click="handleSearch">搜索</el-button>
      <el-button @click="handleReset">重置</el-button>
    </div>

    <el-table :data="products" v-loading="loading">
      <el-table-column label="图片" width="84" align="center">
        <template #default="{ row }">
          <img
            v-if="row.image_url"
            :src="row.image_url"
            class="product-thumbnail"
            alt="商品图片"
            @error="handleImageError(row)"
          />
          <div v-else class="product-thumbnail placeholder">暂无</div>
        </template>
      </el-table-column>
      <el-table-column label="商品标题" min-width="300" show-overflow-tooltip>
        <template #default="{ row }">
          <a
            v-if="getTakealotLink(row)"
            :href="getTakealotLink(row)"
            class="product-title-link"
            target="_blank"
            rel="noopener noreferrer"
          >
            {{ row.title }}
          </a>
          <span v-else>{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="sku" label="SKU" width="140" />
      <el-table-column label="售价" width="120" align="right">
        <template #default="{ row }">
          <div style="font-weight: 600; color: #1d1d1f">R {{ row.selling_price?.toFixed(2) || '-' }}</div>
        </template>
      </el-table-column>
      <el-table-column label="划线价(RRP)" width="120" align="right">
        <template #default="{ row }">
          <span v-if="row.rrp && row.rrp > 0 && row.rrp !== row.selling_price" style="color: #aeaeb2; text-decoration: line-through; font-size: 12px">
            R {{ row.rrp.toFixed(2) }}
          </span>
          <span v-else style="color: #d1d1d6; font-size: 12px">未设置</span>
        </template>
      </el-table-column>
      <el-table-column prop="stock_on_hand" label="库存" width="80" align="center" />
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="getStatusTagType(row)" size="small">
            {{ getStatusLabel(row) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button size="small" link type="primary" @click="viewDetail(row)">详情</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div style="display: flex; justify-content: flex-end; margin-top: 16px">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="pageSize"
        :total="totalProducts"
        layout="total, prev, pager, next"
        @current-change="handlePageChange"
      />
    </div>

    <!-- Detail dialog -->
    <el-dialog
      v-model="showDetail"
      :title="detailForm.title || selectedProduct?.title || '商品详情'"
      width="720px"
      @closed="handleDetailClosed"
    >
      <div v-loading="detailLoading">
        <div v-if="selectedProduct" class="detail-header">
          <img
            v-if="detailForm.image_url || selectedProduct.image_url"
            :src="detailForm.image_url || selectedProduct.image_url"
            class="detail-thumbnail"
            alt="商品图片"
          />
          <div v-else class="detail-thumbnail placeholder">暂无</div>
          <div class="detail-meta">
            <a
              v-if="detailForm.takealot_url || getTakealotLink(selectedProduct)"
              :href="detailForm.takealot_url || getTakealotLink(selectedProduct)"
              class="product-title-link"
              target="_blank"
              rel="noopener noreferrer"
            >
              {{ detailForm.title || selectedProduct.title }}
            </a>
            <div v-else class="detail-title">{{ detailForm.title || selectedProduct.title }}</div>
            <div class="detail-subline">Offer ID：{{ detailForm.offer_id || selectedProduct.offer_id }}</div>
            <div class="detail-subline">SKU：{{ detailForm.sku || selectedProduct.sku }}</div>
          </div>
        </div>

        <el-alert
          v-if="detailForm.offer_status === 'Disabled by Takealot'"
          type="warning"
          :closable="false"
          show-icon
          title="该商品当前为平台下架状态；如切换到其它状态，最终是否生效以 Takealot 返回结果为准。"
          style="margin-bottom: 16px"
        />

        <el-form label-width="88px">
          <el-row :gutter="16">
            <el-col :span="12">
              <el-form-item label="售价">
                <el-input-number
                  v-model="detailForm.current_price_zar"
                  :min="1"
                  :precision="0"
                  :step="1"
                  controls-position="right"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="RRP">
                <el-input-number
                  v-model="detailForm.rrp_zar"
                  :min="1"
                  :precision="0"
                  :step="1"
                  controls-position="right"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="库存">
                <el-input-number
                  v-model="detailForm.dropship_stock"
                  :disabled="detailForm.leadtime_days !== 14"
                  :min="0"
                  :precision="0"
                  :step="1"
                  controls-position="right"
                  style="width: 100%"
                />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="当前状态">
                <el-tag :type="getStatusTagType({ status_group: getOfferStatusGroup(detailForm.offer_status) })">
                  {{ getOfferStatusLabel(detailForm.offer_status) }}
                </el-tag>
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="Leadtime">
                <el-select v-model="detailForm.leadtime_days" style="width: 100%" :disabled="detailForm.offer_status === 'Disabled by Seller' || detailForm.offer_status === 'Disabled by Takealot'">
                  <el-option
                    v-for="option in leadtimeOptions"
                    :key="String(option.value)"
                    :label="option.label"
                    :value="option.value"
                  />
                </el-select>
              </el-form-item>
            </el-col>
            <el-col :span="24">
              <div class="detail-helper-text">
                状态以卖家后台实际返回为准；变为在售需要 `Leadtime = 14 days` 且 `库存 > 0`。
              </div>
            </el-col>
          </el-row>
        </el-form>
      </div>

      <template #footer>
        <span>
          <el-button @click="showDetail = false" :disabled="savingDetail">取消</el-button>
          <el-button type="primary" @click="saveDetailAndSync" :loading="savingDetail">
            保存并同步 Takealot
          </el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { productApi } from '@/api'
import { useStoreStore } from '@/stores/store'
import { ElMessage } from 'element-plus'
import { Search } from '@element-plus/icons-vue'

type SyncProgressState = {
  running: boolean
  stage?: string
  message?: string
  total?: number
  processed?: number
  updated?: number
  failed?: number
  result?: string
}

const storeStore = useStoreStore()
const products = ref<any[]>([])
const loading = ref(false)
const syncing = ref(false)
const showDetail = ref(false)
const selectedProduct = ref<any>(null)
const detailLoading = ref(false)
const savingDetail = ref(false)
const detailOriginal = ref<any>(null)
const detailForm = ref({
  offer_id: '',
  sku: '',
  title: '',
  current_price_zar: 1,
  rrp_zar: 1,
  dropship_stock: 0,
  offer_status: 'Not Buyable',
  leadtime_days: 'none' as number | 'none',
  takealot_url: '',
  image_url: '',
})
const statusFilter = ref('')
const searchQuery = ref('')
const currentPage = ref(1)
const pageSize = 50
const totalProducts = ref(0)
const counts = ref({
  all: 0,
  buyable: 0,
  not_buyable: 0,
  off_shelf: 0,
})
const syncProgress = ref<SyncProgressState>({ running: false, stage: 'idle' })
const leadtimeOptions = [
  { value: 'none', label: 'None' },
  { value: 14, label: '14 days' },
]

let syncPollTimer: ReturnType<typeof setTimeout> | null = null

const totalCount = computed(() => counts.value.all || 0)
const buyableCount = computed(() => counts.value.buyable || 0)
const notBuyableCount = computed(() => counts.value.not_buyable || 0)
const offShelfCount = computed(() => counts.value.off_shelf || 0)
const syncStageLabel = computed(() => {
  switch (syncProgress.value.stage) {
    case 'queued':
      return '等待开始'
    case 'syncing':
      return '同步商品'
    case 'enriching_images':
      return '补充图片'
    case 'error':
      return '同步失败'
    case 'done':
      return '同步完成'
    default:
      return '处理中'
  }
})
const syncPercentage = computed(() => {
  const total = Number(syncProgress.value.total || 0)
  const processed = Number(syncProgress.value.processed || 0)
  if (!total) return 0
  return Math.max(0, Math.min(100, Math.round((processed / total) * 100)))
})
const syncProgressDetail = computed(() => {
  const details: string[] = []

  if (syncProgress.value.message) details.push(syncProgress.value.message)
  if (syncProgress.value.total) {
    details.push(`${Math.min(syncProgress.value.processed || 0, syncProgress.value.total)}/${syncProgress.value.total}`)
  }
  if (syncProgress.value.updated) details.push(`已更新 ${syncProgress.value.updated}`)
  if (syncProgress.value.failed) details.push(`失败 ${syncProgress.value.failed}`)

  return details.join(' · ') || '正在处理，请稍候...'
})

async function fetchProducts() {
  const storeId = storeStore.activeStoreId
  if (!storeId) {
    products.value = []
    totalProducts.value = 0
    counts.value = { all: 0, buyable: 0, not_buyable: 0, off_shelf: 0 }
    return
  }
  loading.value = true
  try {
    const { data } = await productApi.list(storeId, {
      page: currentPage.value,
      page_size: pageSize,
      q: searchQuery.value || undefined,
      status: statusFilter.value || undefined,
    })
    if (storeId !== storeStore.activeStoreId) return
    products.value = data.products || data.offers || []
    totalProducts.value = Number(data.total || 0)
    counts.value = {
      all: Number(data.counts?.all || 0),
      buyable: Number(data.counts?.buyable || 0),
      not_buyable: Number(data.counts?.not_buyable || 0),
      off_shelf: Number(data.counts?.off_shelf || 0),
    }
  } finally {
    loading.value = false
  }
}

function stopSyncPolling() {
  if (syncPollTimer) {
    clearTimeout(syncPollTimer)
    syncPollTimer = null
  }
}

function scheduleSyncPolling() {
  stopSyncPolling()
  if (!syncProgress.value.running || !storeStore.activeStoreId) return
  syncPollTimer = setTimeout(() => {
    void fetchSyncStatus()
  }, 2000)
}

function resetSyncProgress() {
  stopSyncPolling()
  syncProgress.value = { running: false, stage: 'idle' }
  syncing.value = false
}

function normalizeSyncProgress(data: any): SyncProgressState {
  return {
    running: !!data?.running,
    stage: data?.stage || (data?.running ? 'syncing' : 'idle'),
    message: data?.message || '',
    total: Number(data?.total || 0),
    processed: Number(data?.processed || 0),
    updated: Number(data?.updated || 0),
    failed: Number(data?.failed || 0),
    result: data?.result || '',
  }
}

function getTakealotLink(row: any) {
  if (row?.takealot_url) return row.takealot_url
  if (row?.plid) return `https://www.takealot.com/x/${row.plid}`
  return ''
}

function getStatusGroup(row: any) {
  return row?.status_group || row?.status || ''
}

function getStatusLabel(row: any) {
  const statusGroup = getStatusGroup(row)
  if (statusGroup === 'Buyable') return '在售'
  if (statusGroup === 'OffShelf') {
    const offerStatus = String(row?.offer_status || '').trim()
    if (offerStatus === 'Disabled by Seller' || offerStatus === 'Disabled by Takealot') {
      return getOfferStatusLabel(offerStatus)
    }
    return '已下架'
  }
  return '不可购买'
}

function getStatusTagType(row: any) {
  const statusGroup = getStatusGroup(row)
  if (statusGroup === 'Buyable') return 'success'
  if (statusGroup === 'OffShelf') return 'danger'
  return 'warning'
}

function getOfferStatusGroup(offerStatus: string) {
  if (offerStatus === 'Buyable') return 'Buyable'
  if (offerStatus === 'Disabled by Seller' || offerStatus === 'Disabled by Takealot') return 'OffShelf'
  return 'Not Buyable'
}

function getOfferStatusLabel(offerStatus: string) {
  if (offerStatus === 'Buyable') return '在售'
  if (offerStatus === 'Disabled by Seller') return '卖家下架'
  if (offerStatus === 'Disabled by Takealot') return '平台下架'
  return '不可购买'
}

function toInteger(value: unknown, fallback: number) {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return fallback
  return Math.round(parsed)
}

function normalizeDetailProduct(product: any) {
  const currentPrice = toInteger(product?.current_price_zar ?? product?.selling_price, 1)
  const rrp = toInteger(product?.rrp_zar ?? product?.rrp, currentPrice)
  const stock = toInteger(product?.dropship_stock ?? product?.stock_on_hand, 0)
  const leadtimeDays: number | 'none' = product?.leadtime_days == null ? 'none' : toInteger(product?.leadtime_days, 14)

  return {
    offer_id: product?.offer_id || '',
    sku: product?.sku || '',
    title: product?.title || '',
    current_price_zar: Math.max(1, currentPrice),
    rrp_zar: Math.max(1, rrp),
    dropship_stock: Math.max(0, stock),
    offer_status: product?.offer_status || 'Not Buyable',
    leadtime_days: leadtimeDays,
    takealot_url: product?.takealot_url || getTakealotLink(product),
    image_url: product?.image_url || '',
    status_group: product?.status_group || product?.status || '',
    status_label: product?.status_label || '',
  }
}

function applyDetailProduct(product: any) {
  const normalized = normalizeDetailProduct(product)
  detailForm.value = {
    offer_id: normalized.offer_id,
    sku: normalized.sku,
    title: normalized.title,
    current_price_zar: normalized.current_price_zar,
    rrp_zar: normalized.rrp_zar,
    dropship_stock: normalized.dropship_stock,
    offer_status: normalized.offer_status,
    leadtime_days: normalized.leadtime_days,
    takealot_url: normalized.takealot_url,
    image_url: normalized.image_url,
  }
  detailOriginal.value = { ...normalized }
  selectedProduct.value = {
    ...(selectedProduct.value || {}),
    ...product,
    offer_id: normalized.offer_id,
    sku: normalized.sku,
    title: normalized.title,
    selling_price: normalized.current_price_zar,
    current_price_zar: normalized.current_price_zar,
    rrp: normalized.rrp_zar,
    rrp_zar: normalized.rrp_zar,
    stock_on_hand: normalized.dropship_stock,
    dropship_stock: normalized.dropship_stock,
    offer_status: normalized.offer_status,
    leadtime_days: normalized.leadtime_days,
    status_group: product?.status_group || normalized.status_group || selectedProduct.value?.status_group || '',
    status_label: product?.status_label || normalized.status_label || selectedProduct.value?.status_label || '',
    takealot_url: normalized.takealot_url,
    image_url: normalized.image_url,
  }
}

async function fetchSyncStatus(options?: { notifyOnFinish?: boolean }) {
  const notifyOnFinish = options?.notifyOnFinish ?? true
  const storeId = storeStore.activeStoreId
  if (!storeId) {
    resetSyncProgress()
    return
  }

  try {
    const { data } = await productApi.syncStatus(storeId)
    if (storeId !== storeStore.activeStoreId) return

    const previousRunning = syncProgress.value.running
    syncProgress.value = normalizeSyncProgress(data)
    syncing.value = syncProgress.value.running

    if (syncProgress.value.running) {
      scheduleSyncPolling()
      return
    }

    stopSyncPolling()

    if (previousRunning) {
      await fetchProducts()
      if (!notifyOnFinish) return

      if (syncProgress.value.result === 'error' || syncProgress.value.stage === 'error') {
        ElMessage.error(syncProgress.value.message || '同步失败')
      } else {
        ElMessage.success(syncProgress.value.message || '同步完成')
      }
    }
  } catch {
    if (syncProgress.value.running) {
      syncing.value = true
      syncProgress.value = {
        ...syncProgress.value,
        message: syncProgress.value.message || '同步状态获取失败，正在重试...',
      }
      scheduleSyncPolling()
    } else {
      stopSyncPolling()
      syncing.value = false
      syncProgress.value = { running: false, stage: 'idle' }
    }
  }
}

async function syncProducts() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  syncing.value = true
  try {
    const { data } = await productApi.sync(storeId)
    const isActiveSync = !!data?.running || ['queued', 'syncing', 'enriching_images'].includes(data?.stage || '')
    const message = data?.message || (data?.ok === false ? '另一同步任务正在运行，请稍后再试' : '商品管理同步任务已提交')
    if (isActiveSync || data?.ok !== false) {
      syncProgress.value = normalizeSyncProgress({
        ...syncProgress.value,
        running: true,
        stage: data?.stage || 'queued',
        message,
      })
      scheduleSyncPolling()
    } else {
      resetSyncProgress()
    }
    if (data?.ok === false) {
      ElMessage.info(message)
    } else {
      ElMessage.success(message)
    }
    if (isActiveSync || data?.ok !== false) {
      await fetchSyncStatus({ notifyOnFinish: true })
    }
  } finally {
    if (!syncProgress.value.running) {
      syncing.value = false
    }
  }
}

async function viewDetail(row: any) {
  selectedProduct.value = row
  applyDetailProduct(row)
  showDetail.value = true
  const storeId = storeStore.activeStoreId
  if (!storeId) return

  detailLoading.value = true
  try {
    const { data } = await productApi.detail(storeId, row.offer_id)
    if (storeId !== storeStore.activeStoreId) return
    applyDetailProduct(data?.product || row)
  } catch {
    ElMessage.error('加载商品详情失败')
  } finally {
    detailLoading.value = false
  }
}

function handleDetailClosed() {
  detailLoading.value = false
  savingDetail.value = false
  selectedProduct.value = null
  detailOriginal.value = null
  detailForm.value = {
    offer_id: '',
    sku: '',
    title: '',
    current_price_zar: 1,
    rrp_zar: 1,
    dropship_stock: 0,
    offer_status: 'Not Buyable',
    leadtime_days: 'none',
    takealot_url: '',
    image_url: '',
  }
}

function buildSavePayload() {
  if (!detailOriginal.value) return {}

  const payload: Record<string, number | string | null> = {}
  if (toInteger(detailForm.value.current_price_zar, 1) !== toInteger(detailOriginal.value.current_price_zar, 1)) {
    payload.selling_price_zar = Math.max(1, toInteger(detailForm.value.current_price_zar, 1))
  }
  if (toInteger(detailForm.value.rrp_zar, 1) !== toInteger(detailOriginal.value.rrp_zar, 1)) {
    payload.rrp_zar = Math.max(1, toInteger(detailForm.value.rrp_zar, 1))
  }
  if (toInteger(detailForm.value.dropship_stock, 0) !== toInteger(detailOriginal.value.dropship_stock, 0)) {
    payload.dropship_stock = Math.max(0, toInteger(detailForm.value.dropship_stock, 0))
  }
  if ((detailForm.value.leadtime_days || 'none') !== (detailOriginal.value.leadtime_days || 'none')) {
    payload.leadtime_days = detailForm.value.leadtime_days === 'none' ? null : detailForm.value.leadtime_days
  }
  return payload
}

async function saveDetailAndSync() {
  const storeId = storeStore.activeStoreId
  const offerId = selectedProduct.value?.offer_id || detailForm.value.offer_id
  if (!storeId || !offerId) return

  const payload = buildSavePayload()
  if (!Object.keys(payload).length) {
    ElMessage.info('没有需要同步的变更')
    return
  }

  const finalLeadtimeDays = detailForm.value.leadtime_days === 14 ? 14 : null
  const finalStock = Math.max(0, toInteger(detailForm.value.dropship_stock, 0))
  if (finalLeadtimeDays === 14 && finalStock <= 0) {
    ElMessage.error('要变成在售，Leadtime 必须是 14 days 且库存必须大于 0')
    return
  }

  savingDetail.value = true
  try {
    const { data } = await productApi.saveSync(storeId, offerId, payload)
    applyDetailProduct(data?.product || selectedProduct.value)
    await fetchProducts()
    ElMessage.success(data?.sync_result === 'local_only' ? '已保存' : '已保存并同步到 Takealot')
  } catch (error: any) {
    const message = error?.response?.data?.detail || '保存并同步失败'
    ElMessage.error(message)
  } finally {
    savingDetail.value = false
  }
}

function handleImageError(row: any) {
  row.image_url = ''
}

function handlePageChange(page: number) {
  currentPage.value = page
  void fetchProducts()
}

function handleSearch() {
  currentPage.value = 1
  void fetchProducts()
}

function handleReset() {
  const shouldRefetchByStatusWatch = statusFilter.value !== ''
  searchQuery.value = ''
  currentPage.value = 1
  statusFilter.value = ''
  if (!shouldRefetchByStatusWatch) {
    void fetchProducts()
  }
}

watch(
  () => storeStore.activeStoreId,
  async () => {
    resetSyncProgress()
    currentPage.value = 1
    await fetchProducts()
    await fetchSyncStatus({ notifyOnFinish: false })
  },
)

watch(statusFilter, async () => {
  currentPage.value = 1
  await fetchProducts()
})

watch(
  () => detailForm.value.leadtime_days,
  (value) => {
    if (value !== 14) {
      detailForm.value.dropship_stock = 0
      return
    }
  },
)

onMounted(async () => {
  await fetchProducts()
  await fetchSyncStatus({ notifyOnFinish: false })
})

onUnmounted(() => {
  stopSyncPolling()
})
</script>

<style scoped>
.sync-progress-banner {
  margin-bottom: 16px;
}

.sync-progress-text {
  margin-bottom: 8px;
  color: #606266;
  font-size: 13px;
}

.product-thumbnail {
  width: 44px;
  height: 44px;
  border-radius: 6px;
  object-fit: cover;
  display: block;
  margin: 0 auto;
  background: #f5f7fa;
}

.product-thumbnail.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  border: 1px dashed #dcdfe6;
}

.product-title-link {
  color: #409eff;
  text-decoration: none;
}

.product-title-link:hover {
  text-decoration: underline;
}

.detail-header {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.detail-thumbnail {
  width: 72px;
  height: 72px;
  border-radius: 10px;
  object-fit: cover;
  background: #f5f7fa;
  flex-shrink: 0;
}

.detail-thumbnail.placeholder {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 12px;
  border: 1px dashed #dcdfe6;
}

.detail-meta {
  min-width: 0;
}

.detail-title {
  font-size: 16px;
  font-weight: 600;
  color: #1d1d1f;
  margin-bottom: 8px;
}

.detail-subline {
  color: #606266;
  font-size: 13px;
  line-height: 1.8;
}

.detail-helper-text {
  color: #909399;
  font-size: 12px;
  margin-top: -4px;
}
</style>
