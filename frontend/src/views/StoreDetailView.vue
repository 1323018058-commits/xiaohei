<template>
  <div v-loading="loading">
    <div class="page-header">
      <h2>{{ store?.store_name || `Store #${storeId}` }}</h2>
      <el-button @click="$router.push('/stores')">返回列表</el-button>
    </div>

    <div class="stat-grid mb-4" v-if="store">
      <div class="stat-card">
        <div class="stat-value">{{ store.offer_count }}</div>
        <div class="stat-label">在线商品</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">
          <el-tag :type="store.api_key_status === '有效' ? 'success' : 'danger'">{{ store.api_key_status }}</el-tag>
        </div>
        <div class="stat-label">API状态</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ store.sync_freshness }}</div>
        <div class="stat-label">同步状态</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ store.health_score }}分</div>
        <div class="stat-label">健康度</div>
      </div>
    </div>

    <!-- Tabs for offers, sales, finance -->
    <el-tabs v-model="activeTab" class="page-card">
      <el-tab-pane label="商品列表" name="offers">
        <el-table :data="offers" stripe max-height="500">
          <el-table-column prop="title" label="标题" min-width="250" show-overflow-tooltip />
          <el-table-column prop="sku" label="SKU" width="120" />
          <el-table-column prop="selling_price" label="售价" width="100" align="right">
            <template #default="{ row }">R {{ row.selling_price?.toFixed(2) }}</template>
          </el-table-column>
          <el-table-column prop="stock_on_hand" label="库存" width="80" align="center" />
          <el-table-column prop="status" label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'Buyable' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="销售记录" name="sales">
        <el-table :data="sales" stripe max-height="500">
          <el-table-column prop="order_date" label="日期" width="120" />
          <el-table-column prop="product_title" label="商品" min-width="200" show-overflow-tooltip />
          <el-table-column prop="quantity" label="数量" width="80" align="center" />
          <el-table-column prop="selling_price" label="金额" width="100" align="right">
            <template #default="{ row }">R {{ row.selling_price?.toFixed(2) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="财务报表" name="finance">
        <el-table :data="finance" stripe max-height="500">
          <el-table-column prop="date" label="日期" width="120" />
          <el-table-column prop="description" label="描述" min-width="200" />
          <el-table-column prop="amount" label="金额" width="120" align="right">
            <template #default="{ row }">R {{ row.amount?.toFixed(2) }}</template>
          </el-table-column>
        </el-table>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { storeApi } from '@/api'

const route = useRoute()
const storeId = ref(Number(route.params.id))

const store = ref<any>(null)
const loading = ref(false)
const activeTab = ref('offers')
const offers = ref<any[]>([])
const sales = ref<any[]>([])
const finance = ref<any[]>([])

async function fetchDetail() {
  loading.value = true
  try {
    const { data } = await storeApi.get(storeId.value)
    store.value = data.store || data
  } finally {
    loading.value = false
  }
}

async function fetchOffers() {
  try {
    const { data } = await storeApi.offers(storeId.value)
    // Cached endpoint returns {ok, data: {offers: [...]}}
    const payload = data.data || data
    offers.value = payload.offers || payload.offer_list || []
  } catch (e: any) {
    console.error('fetchOffers error', e?.response?.data || e)
  }
}

async function fetchSales() {
  try {
    const { data } = await storeApi.sales(storeId.value)
    const payload = data.data || data
    sales.value = payload.sales || payload.order_items || []
  } catch (e: any) {
    console.error('fetchSales error', e?.response?.data || e)
  }
}

async function fetchFinance() {
  try {
    const { data } = await storeApi.finance(storeId.value)
    const payload = data.data || data
    finance.value = payload.entries || payload.statements || payload.finance || []
  } catch (e: any) {
    console.error('fetchFinance error', e?.response?.data || e)
  }
}

watch(activeTab, (tab) => {
  if (tab === 'offers' && !offers.value.length) fetchOffers()
  if (tab === 'sales' && !sales.value.length) fetchSales()
  if (tab === 'finance' && !finance.value.length) fetchFinance()
})

watch(
  () => route.params.id,
  (id) => {
    const nextId = Number(id)
    if (Number.isNaN(nextId) || nextId === storeId.value) return

    storeId.value = nextId
    store.value = null
    offers.value = []
    sales.value = []
    finance.value = []

    fetchDetail()
    if (activeTab.value === 'offers') fetchOffers()
    if (activeTab.value === 'sales') fetchSales()
    if (activeTab.value === 'finance') fetchFinance()
  }
)

onMounted(() => {
  fetchDetail()
  fetchOffers()
})
</script>
