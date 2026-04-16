<template>
  <div>
    <div class="page-header">
      <h2>自动出价</h2>
      <div class="flex gap-2">
        <el-button :type="engineRunning ? 'danger' : 'success'" @click="toggleEngine" :loading="toggling">
          {{ engineRunning ? '停止引擎' : '启动引擎' }}
        </el-button>
        <el-button @click="syncBidProducts" :loading="syncing">同步商品</el-button>
        <el-button @click="refreshAllBuybox" :loading="refreshingAllBuybox">全部刷新 BuyBox</el-button>
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

    <!-- Engine status -->
    <div class="stat-grid mb-4">
      <div class="stat-card">
        <div class="stat-value" :style="{ color: engineRunning ? '#67c23a' : '#909399' }">
          {{ engineRunning ? '运行中' : '已停止' }}
        </div>
        <div class="stat-label">引擎状态</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ engineState.total_products ?? 0 }}</div>
        <div class="stat-label">总商品数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ engineState.active_products ?? 0 }}</div>
        <div class="stat-label">活跃出价</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ engineState.total_checked ?? 0 }}</div>
        <div class="stat-label">累计检查</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="font-size: 12px;">
          {{ engineState.last_product_sync_at || '-' }}
        </div>
        <div class="stat-label">上次商品同步（北京时间）</div>
      </div>
      <div class="stat-card">
        <div class="stat-value" style="font-size: 12px;">
          {{ engineState.next_product_sync_at || '-' }}
        </div>
        <div class="stat-label">下次自动同步（北京时间）</div>
      </div>
    </div>

    <!-- Last cycle stats -->
    <div v-if="engineState.last_run" class="stat-grid mb-4" style="grid-template-columns: repeat(6, 1fr);">
      <div class="stat-card mini">
        <div class="stat-value" style="color: #67c23a;">{{ engineState.last_raised ?? 0 }}</div>
        <div class="stat-label">上次涨价</div>
      </div>
      <div class="stat-card mini">
        <div class="stat-value" style="color: #e6a23c;">{{ engineState.last_lowered ?? 0 }}</div>
        <div class="stat-label">上次降价</div>
      </div>
      <div class="stat-card mini">
        <div class="stat-value" style="color: #f56c6c;">{{ engineState.last_floored ?? 0 }}</div>
        <div class="stat-label">触底</div>
      </div>
      <div class="stat-card mini">
        <div class="stat-value">{{ engineState.last_unchanged ?? 0 }}</div>
        <div class="stat-label">不变</div>
      </div>
      <div class="stat-card mini">
        <div class="stat-value" style="color: #f56c6c;">{{ engineState.last_errors ?? 0 }}</div>
        <div class="stat-label">错误</div>
      </div>
      <div class="stat-card mini">
        <div class="stat-value" style="font-size: 12px;">{{ engineState.last_run || '-' }}</div>
        <div class="stat-label">上次运行（北京时间）</div>
      </div>
    </div>

    <!-- Tabs: Products / Log -->
    <el-tabs v-model="activeTab" class="mb-4">
      <el-tab-pane label="出价商品" name="products">
        <!-- Search & Filter bar -->
        <div class="flex gap-2 mb-3" style="flex-wrap: wrap; align-items: center;">
          <el-input v-model="searchSku" placeholder="搜索 SKU / 商品名" style="width: 240px" clearable
            @keyup.enter="fetchProducts" @clear="fetchProducts">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-select v-model="filterEnabled" placeholder="全部状态" style="width: 130px" clearable @change="fetchProducts">
            <el-option label="已启用" value="1" />
            <el-option label="未启用" value="0" />
          </el-select>
          <el-select v-model="filterStatus" placeholder="全部动作" style="width: 130px" clearable @change="fetchProducts">
            <el-option label="涨价" value="raised" />
            <el-option label="降价" value="lowered" />
            <el-option label="触底" value="floor" />
            <el-option label="不变" value="unchanged" />
            <el-option label="API错误" value="failed" />
          </el-select>
        </div>

        <!-- Bid products table -->
        <div class="page-card">
          <el-table :data="products" v-loading="loading" stripe style="width: 100%"
            :row-class-name="rowClassName">
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
            <el-table-column prop="sku" label="SKU" width="130" show-overflow-tooltip />
            <el-table-column label="商品名称" min-width="240" show-overflow-tooltip>
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
            <el-table-column label="当前价" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.current_price_zar">R {{ row.current_price_zar.toFixed(0) }}</span>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column label="BuyBox" width="100" align="right">
              <template #default="{ row }">
                <span v-if="row.buybox_price_zar" :style="buyboxColor(row)">
                  R {{ row.buybox_price_zar.toFixed(0) }}
                </span>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column label="底价" width="120" align="right">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.floor_price_zar"
                  :min="0" :step="10" :precision="0" :controls="false"
                  size="small" style="width: 100px"
                  @change="updateFloor(row)" />
              </template>
            </el-table-column>
            <el-table-column label="顶价" width="120" align="right">
              <template #default="{ row }">
                <el-input-number
                  v-model="row.target_price_zar"
                  :min="0" :step="10" :precision="0" :controls="false"
                  size="small" style="width: 100px"
                  @change="updateTarget(row)" />
              </template>
            </el-table-column>
            <el-table-column label="自动出价" width="90" align="center">
              <template #default="{ row }">
                <el-switch :model-value="!!row.auto_bid_enabled" @change="toggleBid(row)" size="small" />
              </template>
            </el-table-column>
            <el-table-column label="上次动作" width="90" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.last_action === 'raised'" type="success" size="small">涨价</el-tag>
                <el-tag v-else-if="row.last_action === 'lowered'" type="warning" size="small">降价</el-tag>
                <el-tag v-else-if="row.last_action === 'floor'" type="danger" size="small">触底</el-tag>
                <el-tag v-else-if="row.last_action === 'api_error'" type="danger" size="small">失败</el-tag>
                <el-tag v-else-if="row.last_action === 'unchanged'" type="info" size="small">不变</el-tag>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
            <el-table-column label="检查时间" width="140">
              <template #default="{ row }">
                <span v-if="row.last_checked_at" style="font-size: 12px; color: #909399;">
                  {{ row.last_checked_at }}
                </span>
                <span v-else style="color: #c0c4cc">-</span>
              </template>
            </el-table-column>
          </el-table>

          <!-- Pagination -->
          <div class="flex justify-end mt-3">
            <el-pagination
              v-model:current-page="currentPage"
              :page-size="pageSize"
              :total="totalProducts"
              layout="total, prev, pager, next"
              @current-change="fetchProducts"
            />
          </div>
        </div>
      </el-tab-pane>

      <el-tab-pane label="出价日志" name="log">
        <div class="page-card">
          <el-table :data="bidLogs" v-loading="logLoading" stripe>
            <el-table-column label="时间" width="160">
              <template #default="{ row }">
                <span style="font-size: 12px;">{{ row.created_at }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="sku" label="SKU" width="130" show-overflow-tooltip />
            <el-table-column label="动作" width="80" align="center">
              <template #default="{ row }">
                <el-tag v-if="row.action === 'raised'" type="success" size="small">涨价</el-tag>
                <el-tag v-else-if="row.action === 'lowered'" type="warning" size="small">降价</el-tag>
                <el-tag v-else-if="row.action === 'floor'" type="danger" size="small">触底</el-tag>
                <el-tag v-else-if="row.action === 'api_error'" type="danger" size="small">失败</el-tag>
                <el-tag v-else type="info" size="small">{{ row.action }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="旧价格" width="100" align="right">
              <template #default="{ row }">R {{ row.old_price?.toFixed(0) ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="新价格" width="100" align="right">
              <template #default="{ row }">R {{ row.new_price?.toFixed(0) ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="BuyBox" width="100" align="right">
              <template #default="{ row }">R {{ row.buybox_price?.toFixed(0) ?? '-' }}</template>
            </el-table-column>
            <el-table-column prop="reason" label="原因" min-width="200" show-overflow-tooltip />
          </el-table>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { bidApi } from '@/api'
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

// Engine state
const engineState = reactive<Record<string, any>>({})
const engineRunning = ref(false)

// Products
const products = ref<any[]>([])
const loading = ref(false)
const toggling = ref(false)
const syncing = ref(false)
const refreshingAllBuybox = ref(false)
const currentPage = ref(1)
const pageSize = 50
const totalProducts = ref(0)
const syncProgress = ref<SyncProgressState>({ running: false, stage: 'idle' })

// Filters
const searchSku = ref('')
const filterEnabled = ref('')
const filterStatus = ref('')

// Tabs
const activeTab = ref('products')

// Log
const bidLogs = ref<any[]>([])
const logLoading = ref(false)

// Auto-refresh
let refreshTimer: ReturnType<typeof setInterval> | null = null
let syncPollTimer: ReturnType<typeof setTimeout> | null = null
let forceSyncPolling = false
let viewActive = true
let statusRequestId = 0
let productsRequestId = 0
let logRequestId = 0
let syncStatusRequestId = 0
const floorTimers = new Map<string, ReturnType<typeof setTimeout>>()
const targetTimers = new Map<string, ReturnType<typeof setTimeout>>()

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

function getTakealotLink(row: any) {
  if (row?.takealot_url) return row.takealot_url
  if (row?.plid) return `https://www.takealot.com/x/${row.plid}`
  return ''
}

async function fetchStatus() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  const requestId = ++statusRequestId
  try {
    const { data } = await bidApi.status(storeId)
    if (!viewActive || requestId !== statusRequestId || storeId !== storeStore.activeStoreId) return
    if (data.ok && data.state) {
      Object.assign(engineState, data.state)
      engineRunning.value = !!data.state.running
    }
  } catch { /* ignore */ }
}

async function fetchProducts() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  const requestId = ++productsRequestId
  const page = currentPage.value
  const sku = searchSku.value || undefined
  const enabled = filterEnabled.value || undefined
  const status = filterStatus.value || undefined
  loading.value = true
  try {
    const { data } = await bidApi.products(storeId, {
      page,
      page_size: pageSize,
      sku,
      enabled,
      status,
    })
    if (
      !viewActive
      || requestId !== productsRequestId
      || storeId !== storeStore.activeStoreId
      || page !== currentPage.value
      || sku !== (searchSku.value || undefined)
      || enabled !== (filterEnabled.value || undefined)
      || status !== (filterStatus.value || undefined)
    ) {
      return
    }
    products.value = data.products || []
    totalProducts.value = data.total || 0
  } finally {
    if (viewActive && requestId === productsRequestId) {
      loading.value = false
    }
  }
}

function stopSyncPolling() {
  if (syncPollTimer) {
    clearTimeout(syncPollTimer)
    syncPollTimer = null
  }
}

function scheduleSyncPolling(force = false) {
  stopSyncPolling()
  forceSyncPolling = forceSyncPolling || force
  if (!viewActive || !storeStore.activeStoreId) return
  if (!forceSyncPolling && !syncProgress.value.running) return
  syncPollTimer = setTimeout(() => {
    if (!viewActive) return
    void fetchSyncStatus({ forcePolling: forceSyncPolling })
  }, 2000)
}

function resetSyncProgress() {
  stopSyncPolling()
  forceSyncPolling = false
  syncProgress.value = { running: false, stage: 'idle' }
  syncing.value = false
}

function normalizeSyncProgress(data: any): SyncProgressState {
  const stage = data?.stage || (data?.running ? 'syncing' : 'idle')
  const isActiveStage = ['queued', 'syncing', 'enriching_images'].includes(stage)
  return {
    running: !!data?.running || isActiveStage,
    stage,
    message: data?.message || '',
    total: Number(data?.total || 0),
    processed: Number(data?.processed || 0),
    updated: Number(data?.updated || 0),
    failed: Number(data?.failed || 0),
    result: data?.result || '',
  }
}

async function fetchSyncStatus(options?: { notifyOnFinish?: boolean; forcePolling?: boolean }) {
  const notifyOnFinish = options?.notifyOnFinish ?? true
  const forcePolling = options?.forcePolling ?? false
  const storeId = storeStore.activeStoreId
  if (!storeId) {
    resetSyncProgress()
    return
  }
  const requestId = ++syncStatusRequestId

  try {
    const { data } = await bidApi.syncStatus(storeId)
    if (!viewActive || requestId !== syncStatusRequestId || storeId !== storeStore.activeStoreId) return

    const previousRunning = syncProgress.value.running
    syncProgress.value = normalizeSyncProgress(data)
    syncing.value = syncProgress.value.running

    if (syncProgress.value.running) {
      forceSyncPolling = false
      scheduleSyncPolling()
      return
    }

    stopSyncPolling()

    if (previousRunning) {
      forceSyncPolling = false
      try {
        await Promise.all([fetchProducts(), fetchStatus()])
      } catch {
        // Completion notification should still surface even if follow-up refresh fails.
      }
      if (!viewActive || storeId !== storeStore.activeStoreId || requestId !== syncStatusRequestId) return
      if (!notifyOnFinish) return

      if (syncProgress.value.result === 'error' || syncProgress.value.stage === 'error') {
        ElMessage.error(syncProgress.value.message || '同步失败')
      } else {
        ElMessage.success(syncProgress.value.message || '同步完成')
      }
    } else if (forcePolling) {
      forceSyncPolling = true
      scheduleSyncPolling(true)
    }
  } catch {
    if (!viewActive || requestId !== syncStatusRequestId) return
    if (syncProgress.value.running) {
      syncing.value = true
      syncProgress.value = {
        ...syncProgress.value,
        message: syncProgress.value.message || '同步状态获取失败，正在重试...',
      }
      scheduleSyncPolling()
    } else if (forcePolling) {
      forceSyncPolling = true
      scheduleSyncPolling(true)
    } else {
      stopSyncPolling()
      forceSyncPolling = false
      syncing.value = false
      syncProgress.value = { running: false, stage: 'idle' }
    }
  }
}

async function fetchLog() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  const requestId = ++logRequestId
  logLoading.value = true
  try {
    const { data } = await bidApi.log(storeId, { limit: 200 })
    if (!viewActive || requestId !== logRequestId || storeId !== storeStore.activeStoreId) return
    bidLogs.value = data.log || []
  } finally {
    if (viewActive && requestId === logRequestId) {
      logLoading.value = false
    }
  }
}

async function toggleEngine() {
  if (!storeStore.activeStoreId) return
  toggling.value = true
  try {
    if (engineRunning.value) {
      await bidApi.stop(storeStore.activeStoreId)
      ElMessage.success('出价引擎已停止')
    } else {
      await bidApi.start(storeStore.activeStoreId)
      ElMessage.success('出价引擎已启动，每5分钟自动出价')
    }
    await fetchStatus()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    toggling.value = false
  }
}

async function syncBidProducts() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  syncing.value = true
  try {
    const { data } = await bidApi.syncProducts(storeId)
    const isActiveSync = !!data?.running || ['queued', 'syncing', 'enriching_images'].includes(data?.stage || '')
    const message = data?.message || (data?.ok === false ? '另一同步任务正在运行，请稍后再试' : '自动出价商品同步任务已提交')
    if (data?.ok === false) {
      ElMessage.warning(message)
    } else {
      ElMessage.success(message)
    }
    if (isActiveSync || data?.ok !== false) {
      scheduleSyncPolling(true)
      await fetchSyncStatus({ notifyOnFinish: true, forcePolling: true })
    } else {
      resetSyncProgress()
    }
  } catch (e: any) {
    syncing.value = false
    ElMessage.error(e.response?.data?.detail || '同步失败')
  }
}

async function toggleBid(row: any) {
  if (!storeStore.activeStoreId) return
  try {
    await bidApi.patchProduct(storeStore.activeStoreId, row.offer_id, {
      auto_bid_enabled: row.auto_bid_enabled ? 0 : 1,
    })
    row.auto_bid_enabled = row.auto_bid_enabled ? 0 : 1
  } catch {
    ElMessage.error('更新失败')
  }
}

async function refreshAllBuybox() {
  const storeId = storeStore.activeStoreId
  if (!storeId) return
  refreshingAllBuybox.value = true
  try {
    const { data } = await bidApi.refreshAllBuybox(storeId)
    await fetchProducts()
    ElMessage.success(
      `BuyBox 刷新完成：成功 ${data?.refreshed ?? 0}，失败 ${data?.failed ?? 0}，跳过 ${data?.skipped ?? 0}`,
    )
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '全部 BuyBox 刷新失败')
  } finally {
    refreshingAllBuybox.value = false
  }
}

function clearInputTimers(timerMap: Map<string, ReturnType<typeof setTimeout>>) {
  for (const timer of timerMap.values()) {
    clearTimeout(timer)
  }
  timerMap.clear()
}

function updateFloor(row: any) {
  const storeId = storeStore.activeStoreId
  if (!storeId || !row?.offer_id) return
  const timerKey = String(row.offer_id)
  const currentValue = row.floor_price_zar
  const existingTimer = floorTimers.get(timerKey)
  if (existingTimer) clearTimeout(existingTimer)
  const timer = setTimeout(async () => {
    if (!viewActive || storeId !== storeStore.activeStoreId) return
    try {
      await bidApi.patchProduct(storeId, row.offer_id, {
        floor_price_zar: currentValue,
      })
    } catch {
      ElMessage.error('底价更新失败')
    } finally {
      floorTimers.delete(timerKey)
    }
  }, 600)
  floorTimers.set(timerKey, timer)
}

function updateTarget(row: any) {
  const storeId = storeStore.activeStoreId
  if (!storeId || !row?.offer_id) return
  const timerKey = String(row.offer_id)
  const currentValue = row.target_price_zar
  const existingTimer = targetTimers.get(timerKey)
  if (existingTimer) clearTimeout(existingTimer)
  const timer = setTimeout(async () => {
    if (!viewActive || storeId !== storeStore.activeStoreId) return
    try {
      await bidApi.patchProduct(storeId, row.offer_id, {
        target_price_zar: currentValue,
      })
    } catch {
      ElMessage.error('顶价更新失败')
    } finally {
      targetTimers.delete(timerKey)
    }
  }, 600)
  targetTimers.set(timerKey, timer)
}

function buyboxColor(row: any): Record<string, string> {
  if (!row.buybox_price_zar || !row.current_price_zar) return {}
  if (row.buybox_price_zar < row.current_price_zar) return { color: '#f56c6c', fontWeight: 'bold' }
  if (row.buybox_price_zar > row.current_price_zar) return { color: '#67c23a', fontWeight: 'bold' }
  return { color: '#e6a23c' }
}

function rowClassName({ row }: { row: any }) {
  if (row.last_action === 'api_error') return 'row-error'
  if (row.last_action === 'floor') return 'row-floor'
  return ''
}

function handleImageError(row: any) {
  row.image_url = ''
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = setInterval(() => {
    fetchStatus()
    if (activeTab.value === 'log') fetchLog()
  }, 30000)  // Refresh every 30s
}

function stopAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer)
    refreshTimer = null
  }
}

watch(() => storeStore.activeStoreId, async () => {
  resetSyncProgress()
  clearInputTimers(floorTimers)
  clearInputTimers(targetTimers)
  currentPage.value = 1
  await fetchSyncStatus({ notifyOnFinish: false })
  fetchStatus()
  fetchProducts()
  if (activeTab.value === 'log') fetchLog()
})

watch(activeTab, (tab) => {
  if (tab === 'log') fetchLog()
})

onMounted(async () => {
  viewActive = true
  await fetchSyncStatus({ notifyOnFinish: false })
  fetchStatus()
  fetchProducts()
  startAutoRefresh()
})

onUnmounted(() => {
  viewActive = false
  stopAutoRefresh()
  stopSyncPolling()
  forceSyncPolling = false
  clearInputTimers(floorTimers)
  clearInputTimers(targetTimers)
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

.stat-card.mini .stat-value {
  font-size: 18px;
}
.stat-card.mini .stat-label {
  font-size: 11px;
}
:deep(.row-error) {
  background-color: #fef0f0 !important;
}
:deep(.row-floor) {
  background-color: #fdf6ec !important;
}
</style>
