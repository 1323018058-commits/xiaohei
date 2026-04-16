<template>
  <div class="library-page">
    <!-- Header -->
    <div class="page-header">
      <div>
        <div class="page-subtitle">HISTORICAL INTELLIGENCE</div>
        <h2>选品情报中心</h2>
        <p class="page-desc">基于 Takealot 实时爬虫数据的全链路商品库。数千个分类、百万级商品，帮助您找到最佳的铺货商品机会。</p>
      </div>
      <el-button type="primary" @click="showScrapeDialog = true">
        <el-icon class="mr-1"><Search /></el-icon>启动爬取
      </el-button>
    </div>

    <!-- Stats -->
    <div class="stat-grid mb-4">
      <div class="stat-card">
        <div class="stat-value">{{ formatNum(stats?.total_products ?? 0) }}</div>
        <div class="stat-label">商品总量</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats?.categories ?? 0 }}</div>
        <div class="stat-label">主类目</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ formatNum(stats?.brands ?? 0) }}</div>
        <div class="stat-label">品牌数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats?.last_updated?.slice(0, 10) ?? '--' }}</div>
        <div class="stat-label">最近更新</div>
      </div>
      <div class="stat-card">
        <div class="stat-value stat-value--compact">{{ autoScrapeTime }}</div>
        <div class="stat-label">最近自动补采（北京时间）</div>
        <div class="stat-subtext">{{ autoScrapeSummary }}</div>
      </div>
      <div class="stat-card">
        <el-tooltip
          v-if="autoScrapeErrorHint"
          :content="autoScrapeErrorHint"
          placement="top"
          effect="dark"
        >
          <div class="stat-value stat-value--compact stat-value--tooltip" :class="autoScrapeStatusClass">
            {{ autoScrapeStatusLabel }}
          </div>
        </el-tooltip>
        <div v-else class="stat-value stat-value--compact" :class="autoScrapeStatusClass">
          {{ autoScrapeStatusLabel }}
        </div>
        <div class="stat-label">自动补采状态</div>
        <div class="stat-subtext">{{ autoScrapeStatusHint }}</div>
      </div>
      <div class="stat-card" v-if="stats?.quarantined">
        <div class="stat-value" style="color:#e6a23c">{{ stats.quarantined }}</div>
        <div class="stat-label">隔离区</div>
      </div>
    </div>

    <!-- Scrape Progress Bar -->
    <el-alert
      v-if="scrapeProgress?.running"
      type="info"
      :closable="false"
      class="mb-4"
    >
      <template #title>
        <div class="flex-between">
          <span>
            正在爬取: {{ scrapeProgress.current_cat }}
            ({{ scrapeProgress.done_cats }}/{{ scrapeProgress.total_cats }} 类目)
            — 已采集 {{ formatNum(scrapeProgress.total_scraped) }} 条
            — {{ Math.round(scrapeProgress.elapsed_sec) }}秒
          </span>
          <el-button size="small" type="danger" @click="stopScrape">停止</el-button>
        </div>
      </template>
      <el-progress
        :percentage="scrapeProgress.total_cats > 0 ? Math.round(scrapeProgress.done_cats / scrapeProgress.total_cats * 100) : 0"
        :stroke-width="8"
        class="mt-2"
      />
    </el-alert>

    <!-- Filter panel -->
    <el-card shadow="never" class="mb-4">
      <template #header>
        <span class="filter-title">高级筛选中心</span>
      </template>
      <el-form :inline="true" class="filter-form" @submit.prevent="doSearch(1)">
        <el-form-item label="关键词">
          <el-input
            v-model="filters.keyword"
            placeholder="输入产品标题、PLID 或关键词"
            clearable
            style="width: 260px"
            @keyup.enter="doSearch(1)"
          />
        </el-form-item>
        <el-form-item label="类目">
          <el-select
            v-model="filters.category"
            placeholder="全部类目"
            clearable
            filterable
            style="width: 200px"
          >
            <el-option
              v-for="c in filterOptions.categories"
              :key="c" :label="c" :value="c"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="品牌">
          <el-input
            v-model="filters.brand"
            placeholder="搜索品牌或留空"
            clearable
            style="width: 160px"
          />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number
            v-model="filters.minPrice"
            :min="0" :controls="false"
            placeholder="Min"
            style="width: 90px"
          />
          <span class="mx-1">-</span>
          <el-input-number
            v-model="filters.maxPrice"
            :min="0" :controls="false"
            placeholder="Max"
            style="width: 90px"
          />
        </el-form-item>
        <el-form-item label="评分">
          <el-select v-model="filters.minRating" placeholder="不限" clearable style="width: 100px">
            <el-option label="4.5+" :value="4.5" />
            <el-option label="4.0+" :value="4.0" />
            <el-option label="3.5+" :value="3.5" />
            <el-option label="3.0+" :value="3.0" />
          </el-select>
        </el-form-item>
        <el-form-item label="最低评论">
          <el-input-number
            v-model="filters.minReviews"
            :min="0" :controls="false"
            placeholder="50+"
            style="width: 80px"
          />
        </el-form-item>
        <el-form-item label="库存状态">
          <el-select v-model="filters.stockType" placeholder="全部" clearable style="width: 120px">
            <el-option label="有货" value="in_stock" />
            <el-option label="备货中" value="ships" />
            <el-option label="预售" value="preorder" />
            <el-option label="缺货" value="out" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="doSearch(1)">搜索</el-button>
          <el-button @click="handleResetAndSearch">重置</el-button>
        </el-form-item>
      </el-form>

      <!-- Quick filters -->
      <div class="quick-chips">
        <el-tag effect="plain" class="quick-chip" @click="quickFilter('high_rating')">高评分 (4.5+)</el-tag>
        <el-tag effect="plain" class="quick-chip" @click="quickFilter('popular')">高评论 (100+)</el-tag>
        <el-tag effect="plain" class="quick-chip" @click="quickFilter('ships')">备货中 / Lead Time</el-tag>
        <el-tag effect="plain" class="quick-chip" @click="quickFilter('no_brand')">无品牌商品</el-tag>
        <el-tag effect="plain" class="quick-chip" @click="quickFilter('cheap')">低价 (R0-R200)</el-tag>
      </div>
    </el-card>

    <!-- Products table -->
    <el-card shadow="never">
      <template #header>
        <div class="flex-between table-header-row">
          <span class="filter-title">情报商品池 ({{ formatNum(total) }} 条)</span>
          <div class="table-header-tools">
            <span class="table-header-hint">列表自动刷新（30秒）</span>
            <el-switch
              v-model="listAutoRefreshEnabled"
              @change="handleListAutoRefreshToggle"
            />
          </div>
        </div>
      </template>

      <el-table
        :data="products"
        v-loading="loading"
        stripe
        style="width: 100%"
        :row-class-name="rowClassName"
      >
        <el-table-column label="图片" width="70" align="center">
          <template #default="{ row }">
            <el-image
              :src="row.image"
              style="width: 50px; height: 50px"
              fit="contain"
              :preview-src-list="row.image ? [row.image] : []"
              lazy
            >
              <template #error><div class="img-placeholder">N/A</div></template>
            </el-image>
          </template>
        </el-table-column>

        <el-table-column label="PLID" width="110">
          <template #default="{ row }">
            <a
              v-if="row.url"
              :href="row.url"
              target="_blank"
              class="plid-link"
            >PLID{{ row.product_id }}</a>
            <span v-else>{{ row.product_id }}</span>
          </template>
        </el-table-column>

        <el-table-column label="产品标题 / 类目" min-width="300" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="product-title">{{ row.title }}</div>
            <div class="product-meta">{{ row.category_main }}</div>
          </template>
        </el-table-column>

        <el-table-column label="品牌" width="120" show-overflow-tooltip>
          <template #default="{ row }">
            <span>{{ row.brand || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="销售价" width="110" align="right">
          <template #default="{ row }">
            <div class="price-main">R {{ row.price_min?.toFixed(0) ?? '-' }}</div>
            <div class="price-original" v-if="row.price_max && row.price_max > row.price_min">
              R {{ row.price_max?.toFixed(0) }}
            </div>
          </template>
        </el-table-column>

        <el-table-column label="评分 / 评论" width="130" align="center">
          <template #default="{ row }">
            <div v-if="row.star_rating" class="rating-row">
              <el-rate :model-value="row.star_rating" disabled show-score text-color="#ff9900" />
            </div>
            <div class="review-count">{{ row.reviews_total ?? 0 }} 条评论</div>
          </template>
        </el-table-column>

        <el-table-column label="最新评论" width="110" align="center">
          <template #default="{ row }">
            <span class="text-muted">{{ row.latest_review_at || '-' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              :type="stockTagType(row.in_stock)"
              size="small"
            >{{ stockLabel(row.in_stock) }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="80" align="center" fixed="right">
          <template #default="{ row }">
            <el-dropdown trigger="click">
              <el-button link type="primary" size="small">操作</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item @click="openUrl(row.url)">查看详情</el-dropdown-item>
                  <el-dropdown-item @click="doQuarantine(row.product_id)">隔离</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </template>
        </el-table-column>
      </el-table>

      <!-- Pagination -->
      <div class="pagination-row">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :page-sizes="[30, 50, 100]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="doSearch"
          @size-change="() => doSearch(1)"
        />
      </div>
    </el-card>

    <!-- Scrape config dialog -->
    <el-dialog v-model="showScrapeDialog" title="启动选品爬取" width="560px">
      <el-form :model="scrapeForm" label-width="120px">
        <el-form-item label="Lead Time">
          <el-input-number v-model="scrapeForm.lead_min" :min="0" :max="365" style="width: 100px" />
          <span class="mx-2">至</span>
          <el-input-number v-model="scrapeForm.lead_max" :min="0" :max="365" style="width: 100px" />
          <span class="ml-2 text-muted">工作日</span>
        </el-form-item>
        <el-form-item label="价格范围 (ZAR)">
          <el-input-number v-model="scrapeForm.price_min" :min="0" :controls="false" style="width: 120px" />
          <span class="mx-2">-</span>
          <el-input-number v-model="scrapeForm.price_max" :min="0" :controls="false" style="width: 120px" />
        </el-form-item>
        <el-form-item label="每分类上限">
          <el-input-number v-model="scrapeForm.max_per_cat" :min="0" :max="10000" style="width: 120px" />
          <span class="ml-2 text-muted">0 = 不限</span>
        </el-form-item>
        <el-form-item label="选择类目">
          <el-select
            v-model="scrapeForm.categories"
            multiple
            collapse-tags
            collapse-tags-tooltip
            placeholder="全部类目 (留空=全选)"
            style="width: 100%"
            filterable
          >
            <el-option v-for="c in filterOptions.categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showScrapeDialog = false">取消</el-button>
        <el-button type="primary" @click="startScrape" :loading="scraping">保存配置并开始</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, reactive, onMounted, onUnmounted } from 'vue'
import { libraryApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import type { LibraryProductItem, ScrapeProgress, LibraryStats } from '@/types'

// State
const products = ref<LibraryProductItem[]>([])
const stats = ref<LibraryStats | null>(null)
const total = ref(0)
const page = ref(1)
const pageSize = ref(50)
const loading = ref(false)
const showScrapeDialog = ref(false)
const scraping = ref(false)
const scrapeProgress = ref<ScrapeProgress | null>(null)
const listAutoRefreshEnabled = ref(true)
let progressTimer: any = null
let statsTimer: ReturnType<typeof setInterval> | null = null
let listRefreshTimer: ReturnType<typeof setInterval> | null = null
let statsRefreshInFlight = false
let listRefreshInFlight = false

const LIST_AUTO_REFRESH_KEY = 'library:list-auto-refresh-enabled'

const filterOptions = ref<{ categories: string[]; brands: string[] }>({
  categories: [],
  brands: [],
})

const filters = reactive({
  keyword: '',
  category: '',
  brand: '',
  minPrice: undefined as number | undefined,
  maxPrice: undefined as number | undefined,
  minRating: undefined as number | undefined,
  minReviews: undefined as number | undefined,
  stockType: '',
})

const scrapeForm = reactive({
  lead_min: 7,
  lead_max: 21,
  price_min: 0,
  price_max: 100000,
  max_per_cat: 500,
  categories: [] as string[],
})

// Helpers
function formatNum(n: number) {
  return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : String(n)
}

function stockTagType(status: string) {
  if (!status) return 'info'
  const s = status.toLowerCase()
  if (s.includes('in stock') || s === 'available now') return 'success'
  if (s.includes('ships in')) return 'warning'
  if (s.includes('pre-order')) return 'primary'
  if (s.includes('out of stock')) return 'danger'
  return 'info'
}

function stockLabel(status: string) {
  if (!status) return '未知'
  const s = status.toLowerCase()
  if (s.includes('in stock') || s === 'available now') return '有货'
  if (s.includes('ships in')) return '备货中'
  if (s.includes('pre-order')) return '预售'
  if (s.includes('out of stock')) return '缺货'
  return status.slice(0, 8)
}

function rowClassName({ row }: { row: LibraryProductItem }) {
  if (row.is_preorder) return 'row-preorder'
  return ''
}

function openUrl(url: string) {
  if (url) window.open(url, '_blank')
}

function formatChinaDateTime(value: string | null | undefined) {
  if (!value) return '--'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return '--'
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(parsed)
}

const autoScrapeTime = computed(() => {
  const auto = stats.value?.auto_scrape
  return formatChinaDateTime(auto?.last_finished_at || auto?.last_started_at)
})

const autoScrapeSummary = computed(() => {
  const auto = stats.value?.auto_scrape
  if (!auto) return '尚无补采记录'
  if (auto.running) return '本轮补采正在执行'
  if (auto.status === 'queued') return '已进入补采队列'
  if (auto.last_finished_at) {
    return `采集/更新 ${auto.last_total_scraped || 0} 条，净新增 ${auto.last_new_products || 0} 个`
  }
  return '尚无完成记录'
})

const autoScrapeStatusLabel = computed(() => {
  const auto = stats.value?.auto_scrape
  if (!auto) return '空闲'
  if (auto.running) return '运行中'
  if (auto.status === 'queued') return '待执行'
  if (auto.status === 'success') return '正常'
  if (auto.status === 'error') return '异常'
  if (auto.status === 'skipped') return '已跳过'
  return '空闲'
})

const autoScrapeStatusClass = computed(() => {
  const auto = stats.value?.auto_scrape
  if (auto?.running) return 'stat-value--warning'
  if (auto?.status === 'success') return 'stat-value--success'
  if (auto?.status === 'error') return 'stat-value--danger'
  return ''
})

const autoScrapeErrorHint = computed(() => {
  const auto = stats.value?.auto_scrape
  if (auto?.status !== 'error' || !auto.last_error) return ''
  return auto.last_error
})

const autoScrapeStatusHint = computed(() => {
  const auto = stats.value?.auto_scrape
  if (!auto) return '等待下一轮自动补采'
  if (auto.running) return '补采中，页面会自动刷新'
  if (auto.status === 'queued') return '等待后台 worker 执行'
  if (auto.status === 'success') return `上次净新增 ${auto.last_new_products || 0} 个`
  if (auto.status === 'error') return auto.last_error ? '悬浮可查看失败原因' : '本轮补采失败'
  if (auto.status === 'skipped') return '本轮因已有任务被跳过'
  return '等待下一轮自动补采'
})

// Data loading
async function loadFilters() {
  try {
    const res = await libraryApi.filters()
    filterOptions.value = res.data
  } catch (e) {
    console.error('Failed to load filters', e)
  }
}

async function loadStats() {
  try {
    const res = await libraryApi.stats()
    stats.value = res.data
  } catch (e) {
    console.error('Failed to load stats', e)
  }
}

async function refreshStatsIfNeeded() {
  if (document.hidden || statsRefreshInFlight) return
  statsRefreshInFlight = true
  try {
    await loadStats()
  } finally {
    statsRefreshInFlight = false
  }
}

async function refreshListIfNeeded() {
  if (document.hidden || !listAutoRefreshEnabled.value || loading.value || listRefreshInFlight) return
  listRefreshInFlight = true
  try {
    await doSearch(undefined, { silent: true, background: true })
  } finally {
    listRefreshInFlight = false
  }
}

function buildSearchParams() {
  const params: any = {
    page: page.value,
    page_size: pageSize.value,
  }
  if (filters.keyword) params.q = filters.keyword
  if (filters.category) params.category = filters.category
  if (filters.brand) params.brand = filters.brand
  if (filters.minPrice !== undefined && filters.minPrice !== null) params.min_price = filters.minPrice
  if (filters.maxPrice !== undefined && filters.maxPrice !== null) params.max_price = filters.maxPrice
  if (filters.minRating) params.min_rating = filters.minRating
  if (filters.minReviews) params.min_reviews = filters.minReviews
  if (filters.stockType) params.stock_type = filters.stockType
  return params
}

async function doSearch(p?: number, options: { silent?: boolean; background?: boolean } = {}) {
  if (p !== undefined) page.value = p
  if (!options.background) {
    loading.value = true
  }
  try {
    const res = await libraryApi.list(buildSearchParams())
    if (options.background && loading.value) {
      return
    }
    products.value = res.data.items || []
    total.value = res.data.total || 0
  } catch (e: any) {
    console.error('Search failed', e)
    if (!options.silent) {
      ElMessage.error(e?.response?.data?.detail || '查询失败')
    }
  } finally {
    if (!options.background) {
      loading.value = false
    }
  }
}

function resetFilters() {
  filters.keyword = ''
  filters.category = ''
  filters.brand = ''
  filters.minPrice = undefined
  filters.maxPrice = undefined
  filters.minRating = undefined
  filters.minReviews = undefined
  filters.stockType = ''
}

function handleResetAndSearch() {
  resetFilters()
  doSearch(1)
}

function quickFilter(type: string) {
  resetFilters()
  if (type === 'high_rating') {
    filters.minRating = 4.5
  } else if (type === 'popular') {
    filters.minReviews = 100
  } else if (type === 'ships') {
    filters.stockType = 'ships'
  } else if (type === 'no_brand') {
    filters.brand = 'no_brand'
  } else if (type === 'cheap') {
    filters.minPrice = 0
    filters.maxPrice = 200
  }
  doSearch(1)
}

// Scrape
async function startScrape() {
  scraping.value = true
  try {
    const res = await libraryApi.scrapeStart(scrapeForm)
    if (res.data.ok) {
      ElMessage.success('爬取任务已启动')
      showScrapeDialog.value = false
      startProgressPolling()
    } else {
      ElMessage.warning(res.data.error || '启动失败')
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.error || '启动失败')
  } finally {
    scraping.value = false
  }
}

async function stopScrape() {
  try {
    await libraryApi.scrapeStop()
    ElMessage.info('已发送停止信号')
  } catch {
    ElMessage.error('停止失败')
  }
}

async function pollProgress() {
  try {
    const res = await libraryApi.scrapeProgress()
    scrapeProgress.value = res.data

    if (res.data && !res.data.running && res.data.mode !== 'idle') {
      // Scrape finished — but only show toast if it just completed (within 30s)
      stopProgressPolling()
      const elapsed = res.data.elapsed_sec || 0
      if (elapsed > 0 && elapsed < 3600) {
        if (res.data.error) {
          ElMessage.warning(`爬取结束: ${res.data.error}`)
        } else if (res.data.total_scraped > 0) {
          ElMessage.success(`爬取完成! 共采集 ${res.data.total_scraped} 条`)
        }
      }
      // Refresh data
      await Promise.all([doSearch(1), loadStats()])
    }
  } catch {
    // Ignore poll errors
  }
}

function startProgressPolling() {
  stopProgressPolling()
  pollProgress()
  progressTimer = setInterval(pollProgress, 3000)
}

function stopProgressPolling() {
  if (progressTimer) {
    clearInterval(progressTimer)
    progressTimer = null
  }
}

function startStatsPolling() {
  stopStatsPolling()
  if (document.hidden) return
  statsTimer = setInterval(refreshStatsIfNeeded, 30000)
}

function stopStatsPolling() {
  if (statsTimer) {
    clearInterval(statsTimer)
    statsTimer = null
  }
}

function startListPolling() {
  stopListPolling()
  if (document.hidden || !listAutoRefreshEnabled.value) return
  listRefreshTimer = setInterval(refreshListIfNeeded, 30000)
}

function stopListPolling() {
  if (listRefreshTimer) {
    clearInterval(listRefreshTimer)
    listRefreshTimer = null
  }
}

function handleListAutoRefreshToggle(value: string | number | boolean) {
  const enabled = Boolean(value)
  listAutoRefreshEnabled.value = enabled
  localStorage.setItem(LIST_AUTO_REFRESH_KEY, enabled ? '1' : '0')
  if (enabled) {
    refreshListIfNeeded()
    startListPolling()
    return
  }
  stopListPolling()
}

function handleVisibilityChange() {
  if (document.hidden) {
    stopStatsPolling()
    stopListPolling()
    return
  }
  refreshStatsIfNeeded()
  startStatsPolling()
  if (listAutoRefreshEnabled.value) {
    refreshListIfNeeded()
    startListPolling()
  }
}

// Quarantine
async function doQuarantine(productId: number) {
  try {
    await ElMessageBox.confirm('确认将该商品移入隔离区？', '隔离确认', {
      type: 'warning',
    })
    await libraryApi.quarantine({ product_ids: [productId], reason: 'manual' })
    ElMessage.success('已隔离')
    doSearch()
    loadStats()
  } catch {
    // cancelled or error
  }
}

// Init
onMounted(async () => {
  listAutoRefreshEnabled.value = localStorage.getItem(LIST_AUTO_REFRESH_KEY) !== '0'
  await Promise.all([loadFilters(), loadStats()])
  doSearch(1)
  document.addEventListener('visibilitychange', handleVisibilityChange)
  startStatsPolling()
  startListPolling()
  // Check if scrape is already running — must await to get result
  await pollProgress()
  if (scrapeProgress.value?.running) {
    startProgressPolling()
  }
})

onUnmounted(() => {
  stopProgressPolling()
  stopStatsPolling()
  stopListPolling()
  document.removeEventListener('visibilitychange', handleVisibilityChange)
})
</script>

<style scoped>
.library-page { padding: 0 }
.page-header {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 20px;
}
.page-subtitle {
  font-size: 12px; color: #409eff; font-weight: 600;
  letter-spacing: 2px; margin-bottom: 4px;
}
.page-desc {
  font-size: 13px; color: #909399; margin-top: 4px; max-width: 600px;
}
.stat-grid {
  display: flex; gap: 16px; flex-wrap: wrap;
}
.stat-card {
  background: #fff; border: 1px solid #ebeef5; border-radius: 8px;
  padding: 16px 24px; min-width: 140px; text-align: center;
}
.stat-value { font-size: 24px; font-weight: 700; color: #303133; }
.stat-value--compact { font-size: 20px; }
.stat-value--success { color: #67c23a; }
.stat-value--warning { color: #e6a23c; }
.stat-value--danger { color: #f56c6c; }
.stat-value--tooltip {
  cursor: help;
  text-decoration: underline dotted;
  text-underline-offset: 4px;
}
.stat-label { font-size: 12px; color: #909399; margin-top: 4px; }
.stat-subtext {
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
}

.filter-title { font-weight: 600; font-size: 15px; }
.filter-form { display: flex; flex-wrap: wrap; gap: 0; }
.quick-chips { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.quick-chip { cursor: pointer; }
.quick-chip:hover { color: #409eff; border-color: #409eff; }

.flex-between { display: flex; justify-content: space-between; align-items: center; width: 100%; }
.table-header-row { gap: 12px; flex-wrap: wrap; }
.table-header-tools { display: flex; align-items: center; gap: 10px; }
.table-header-hint { font-size: 12px; color: #606266; }
.mr-1 { margin-right: 4px; }
.mx-1 { margin: 0 4px; }
.mx-2 { margin: 0 8px; }
.ml-2 { margin-left: 8px; }
.mb-4 { margin-bottom: 16px; }
.mt-2 { margin-top: 8px; }
.text-muted { color: #909399; font-size: 12px; }

.product-title { font-size: 13px; line-height: 1.4; }
.product-meta { font-size: 11px; color: #909399; margin-top: 2px; }
.price-main { font-weight: 600; color: #303133; }
.price-original { font-size: 11px; color: #c0c4cc; text-decoration: line-through; }
.rating-row { transform: scale(0.8); transform-origin: center; }
.review-count { font-size: 11px; color: #909399; }
.plid-link { color: #409eff; text-decoration: none; font-size: 12px; }
.plid-link:hover { text-decoration: underline; }
.img-placeholder {
  width: 50px; height: 50px; background: #f5f7fa;
  display: flex; align-items: center; justify-content: center;
  font-size: 11px; color: #c0c4cc;
}

.pagination-row {
  display: flex; justify-content: flex-end; margin-top: 16px;
}

:deep(.row-preorder) {
  background-color: #fdf6ec !important;
}
</style>
