<template>
  <div>
    <div class="page-header">
      <h2>CN Express 物流</h2>
    </div>

    <el-tabs v-model="activeTab">
      <!-- Account Settings Tab -->
      <el-tab-pane label="账号设置" name="account">
        <el-card shadow="never">
          <template #header><span style="font-weight:600">嘉鸿物流账号绑定</span></template>

          <!-- Bound state -->
          <div v-if="accountInfo" class="mb-4">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="绑定状态">
                <el-tag :type="accountBound ? 'success' : 'danger'" size="small">
                  {{ accountBound ? '已绑定' : '未绑定' }}
                </el-tag>
              </el-descriptions-item>
              <el-descriptions-item label="账号">{{ accountInfo.account_username || '-' }}</el-descriptions-item>
              <el-descriptions-item label="客户ID">{{ accountInfo.customer_id || '-' }}</el-descriptions-item>
              <el-descriptions-item label="登录名">{{ accountInfo.login_name || '-' }}</el-descriptions-item>
              <el-descriptions-item label="Token" :span="2">
                <span style="font-family:monospace">{{ accountInfo.token_masked || '-' }}</span>
              </el-descriptions-item>
            </el-descriptions>
          </div>

          <el-divider>{{ accountBound ? '重新登录 / 更换账号' : '登录嘉鸿账号' }}</el-divider>

          <!-- Login form -->
          <el-form :model="loginForm" label-width="100px" style="max-width:450px">
            <el-form-item label="账号">
              <el-input v-model="loginForm.username" placeholder="嘉鸿客户编号，如 CG000379" clearable />
            </el-form-item>
            <el-form-item label="密码">
              <el-input v-model="loginForm.password" type="password" placeholder="嘉鸿登录密码" show-password clearable />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="doLogin" :loading="logging">登录并绑定</el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </el-tab-pane>

      <!-- Orders Tab -->
      <el-tab-pane label="运单管理" name="orders">
        <el-table :data="orders" v-loading="loadingOrders" stripe>
          <el-table-column prop="order_no" label="运单号" width="180" />
          <el-table-column prop="sn" label="追踪号" width="160" />
          <el-table-column prop="line_name" label="线路" width="200" show-overflow-tooltip />
          <el-table-column prop="warehouse_name" label="目的仓" width="180" show-overflow-tooltip />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="row.status === 'end' ? 'success' : row.status === 'cancel' ? 'danger' : 'warning'" size="small">
                {{ statusMap[row.status] || row.status }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="重量(kg)" width="100" align="right">
            <template #default="{ row }">{{ row.weight || row.yu_weight || '-' }}</template>
          </el-table-column>
          <el-table-column prop="take_time" label="揽收时间" width="170" />
          <el-table-column label="操作" width="100">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="viewTracking(row.order_no)">追踪</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="仓库" name="warehouses">
        <el-table :data="warehouses" stripe>
          <el-table-column prop="name" label="仓库名称" min-width="250" show-overflow-tooltip />
          <el-table-column prop="sn" label="代码" width="120" />
          <el-table-column prop="destination_cn_name" label="国家" width="100" />
          <el-table-column prop="city" label="城市" width="140" />
          <el-table-column prop="address" label="地址" min-width="300" show-overflow-tooltip />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="线路" name="lines">
        <el-table :data="lines" stripe>
          <el-table-column prop="name" label="线路名称" min-width="250" show-overflow-tooltip />
          <el-table-column prop="sn" label="代码" width="140" />
          <el-table-column prop="package_type" label="货物类型" width="120" />
          <el-table-column prop="forecast_enum_text" label="预报方式" width="120" />
          <el-table-column prop="status_text" label="状态" width="100" />
        </el-table>
      </el-tab-pane>

      <el-tab-pane label="钱包" name="wallet">
        <div v-if="wallet">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="客户名称">{{ wallet.customer_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="币种">{{ wallet.currency_name || '-' }}</el-descriptions-item>
            <el-descriptions-item label="余额">{{ wallet.balance }}</el-descriptions-item>
            <el-descriptions-item label="信用额度">{{ wallet.credit_number }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <el-empty v-else description="暂无钱包信息" />
      </el-tab-pane>
    </el-tabs>

    <!-- Tracking dialog -->
    <el-dialog v-model="showTracking" title="物流追踪" width="500px">
      <el-timeline v-if="trackingInfo?.events?.length">
        <el-timeline-item v-for="(e, i) in trackingInfo.events" :key="i" :timestamp="e.time">
          {{ e.description }}
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无物流信息" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { cnexpressApi } from '@/api'
import { ElMessage } from 'element-plus'

const activeTab = ref('account')
const orders = ref<any[]>([])
const warehouses = ref<any[]>([])
const lines = ref<any[]>([])
const wallet = ref<any>(null)
const loadingOrders = ref(false)
const showTracking = ref(false)
const trackingInfo = ref<any>(null)

// Account binding
const accountInfo = ref<any>(null)
const accountBound = ref(false)
const logging = ref(false)
const loginForm = reactive({ username: '', password: '' })

const statusMap: Record<string, string> = {
  'wait': '待处理', 'process': '处理中', 'sending': '运输中',
  'end': '已签收', 'cancel': '已取消', 'exception': '异常',
}

async function fetchAccount() {
  try {
    const { data } = await cnexpressApi.account()
    accountInfo.value = data.account
    accountBound.value = data.bound
  } catch {
    accountInfo.value = null
    accountBound.value = false
  }
}

async function doLogin() {
  if (!loginForm.username || !loginForm.password) {
    ElMessage.warning('请输入账号和密码')
    return
  }
  logging.value = true
  try {
    const { data } = await cnexpressApi.loginAccount({
      account_username: loginForm.username,
      account_password: loginForm.password,
    })
    if (data.ok) {
      ElMessage.success('嘉鸿账号绑定成功')
      accountInfo.value = data.account
      accountBound.value = true
      loginForm.username = ''
      loginForm.password = ''
    }
  } catch (e: any) {
    ElMessage.error(e?.response?.data?.detail || '登录失败')
  } finally {
    logging.value = false
  }
}

// Helper: extract rows from CNExpress nested response {ok, data: {code, data: [...]}}
function extractRows(resp: any): any[] {
  const d = resp?.data
  if (!d) return []
  // data.data could be array (warehouses/lines) or {data: [...]} (orders paginated)
  const inner = d.data
  if (Array.isArray(inner)) return inner
  if (inner?.data && Array.isArray(inner.data)) return inner.data
  return []
}

async function fetchOrders() {
  if (!accountBound.value) return
  loadingOrders.value = true
  try {
    const { data } = await cnexpressApi.orders()
    orders.value = extractRows(data)
  } catch { /* not bound */ }
  finally { loadingOrders.value = false }
}

async function fetchWarehouses() {
  if (!accountBound.value) return
  try {
    const { data } = await cnexpressApi.warehouses()
    warehouses.value = extractRows(data)
  } catch { /* ignore */ }
}

async function fetchLines() {
  if (!accountBound.value) return
  try {
    const { data } = await cnexpressApi.lines()
    lines.value = extractRows(data)
  } catch { /* ignore */ }
}

async function fetchWallet() {
  if (!accountBound.value) return
  try {
    const { data } = await cnexpressApi.wallet()
    const rows = extractRows(data)
    wallet.value = rows.length > 0 ? rows[0] : null
  } catch { /* ignore */ }
}

async function viewTracking(trackingNo: string) {
  if (!trackingNo) return
  const { data } = await cnexpressApi.tracking(trackingNo)
  trackingInfo.value = data
  showTracking.value = true
}

watch(activeTab, (tab) => {
  if (tab === 'orders' && !orders.value.length) fetchOrders()
  if (tab === 'warehouses' && !warehouses.value.length) fetchWarehouses()
  if (tab === 'lines' && !lines.value.length) fetchLines()
  if (tab === 'wallet' && !wallet.value) fetchWallet()
})

onMounted(fetchAccount)
</script>

<style scoped>
.mb-4 { margin-bottom: 16px; }
</style>
