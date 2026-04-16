<template>
  <div class="dashboard">
    <!-- Welcome -->
    <div class="welcome-section mb-6">
      <div>
        <h1 class="welcome-title">{{ greeting }}，{{ username }}</h1>
        <p class="welcome-sub">{{ todayStr }} — 这是你的业务概览</p>
      </div>
      <el-tag v-if="stats?.snapshot_stale" type="warning" size="small" round>数据刷新中...</el-tag>
    </div>

    <!-- Stat Cards -->
    <div class="stat-grid mb-6">
      <div class="stat-card" v-for="s in statItems" :key="s.label">
        <div class="stat-value">{{ s.value }}</div>
        <div class="stat-label">{{ s.label }}</div>
      </div>
    </div>

    <!-- Chart + Quick Actions row -->
    <div class="two-col mb-6">
      <!-- Sales Chart -->
      <div class="page-card chart-card">
        <h3>近14天销售趋势</h3>
        <v-chart :option="chartOption" style="height: 280px" autoresize />
      </div>

      <!-- Quick Actions -->
      <div class="quick-actions">
        <router-link v-for="a in actions" :key="a.path" :to="a.path" class="action-card">
          <el-icon :size="24" :style="{ color: a.color }"><component :is="a.icon" /></el-icon>
          <span class="action-label">{{ a.label }}</span>
        </router-link>
      </div>
    </div>

    <!-- Activity -->
    <div class="page-card">
      <h3>最近动态</h3>
      <div v-if="activities.length" class="activity-list">
        <div v-for="(item, i) in activities" :key="i" class="activity-item">
          <div :class="['activity-dot', item.level === 'error' ? 'dot-danger' : 'dot-primary']" />
          <div class="activity-content">
            <span class="activity-title">{{ item.title }}</span>
            <span class="activity-detail">{{ item.detail }}</span>
          </div>
          <span class="activity-time">{{ item.created_at?.slice(11, 16) || '' }}</span>
        </div>
      </div>
      <el-empty v-else description="暂无动态" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { dashboardApi } from '@/api'
import { useAuthStore } from '@/stores/auth'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart, BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import {
  Shop, Timer, Upload, Connection, Search, Van,
} from '@element-plus/icons-vue'
import type { DashboardStats, ActivityItem } from '@/types'

use([CanvasRenderer, LineChart, BarChart, GridComponent, TooltipComponent, LegendComponent])

const authStore = useAuthStore()
const stats = ref<DashboardStats | null>(null)
const activities = ref<ActivityItem[]>([])

const username = computed(() => authStore.username || 'User')
const todayStr = computed(() => {
  const d = new Date()
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
})
const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 12) return '早上好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const statItems = computed(() => [
  { label: '活跃店铺', value: stats.value?.store_count ?? '-' },
  { label: '在线商品', value: stats.value?.total_offers ?? '-' },
  { label: '自动出价', value: stats.value?.active_bid_products ?? '-' },
  { label: '14天销售额', value: `R ${fmtNum(stats.value?.total_sales_zar)}` },
  { label: '14天订单', value: stats.value?.total_orders ?? '-' },
  { label: '已提交铺货', value: stats.value?.dropship_submitted ?? '-' },
])

const actions = [
  { path: '/stores', icon: Shop, label: '店铺管理', color: '#0071e3' },
  { path: '/bids', icon: Timer, label: '自动出价', color: '#ff9f0a' },
  { path: '/listings', icon: Upload, label: 'AI铺货', color: '#34c759' },
  { path: '/dropship', icon: Connection, label: '关键词铺货', color: '#af52de' },
  { path: '/library', icon: Search, label: '选品库', color: '#ff3b30' },
  { path: '/cnexpress', icon: Van, label: 'CN Express', color: '#5ac8fa' },
]

const chartOption = computed(() => {
  const data = stats.value?.daily_data || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { data: ['销售额 (ZAR)', '订单数'], textStyle: { color: '#86868b', fontSize: 12 } },
    grid: { left: 50, right: 30, top: 40, bottom: 30 },
    xAxis: { type: 'category', data: data.map(d => d.date.slice(5)), axisLine: { lineStyle: { color: '#e5e5ea' } }, axisLabel: { color: '#86868b' } },
    yAxis: [
      { type: 'value', name: 'ZAR', splitLine: { lineStyle: { color: '#f0f0f0' } }, axisLabel: { color: '#86868b' } },
      { type: 'value', name: '订单', splitLine: { show: false }, axisLabel: { color: '#86868b' } },
    ],
    series: [
      { name: '销售额 (ZAR)', type: 'bar', data: data.map(d => d.sales), itemStyle: { color: '#0071e3', borderRadius: [4, 4, 0, 0] }, barMaxWidth: 24 },
      { name: '订单数', type: 'line', yAxisIndex: 1, data: data.map(d => d.orders), itemStyle: { color: '#34c759' }, lineStyle: { width: 2 }, smooth: true, symbol: 'circle', symbolSize: 6 },
    ],
  }
})

function fmtNum(v?: number) {
  if (v == null) return '-'
  return v.toLocaleString('en-ZA', { minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

onMounted(async () => {
  const [statsRes, actRes] = await Promise.all([dashboardApi.stats(), dashboardApi.activity()])
  stats.value = statsRes.data
  activities.value = actRes.data.activities || []
})
</script>

<style scoped>
.welcome-section { display: flex; align-items: center; justify-content: space-between; }
.welcome-title { font-size: 28px; font-weight: 700; color: #1d1d1f; letter-spacing: -0.02em; }
.welcome-sub { font-size: 15px; color: #86868b; margin-top: 4px; }

.two-col { display: grid; grid-template-columns: 1fr 320px; gap: 16px; }
.chart-card { min-height: 340px; }

.quick-actions { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; align-content: start; }
.action-card {
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 8px; padding: 20px 12px; background: #fff; border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04); text-decoration: none;
  transition: all 0.25s cubic-bezier(0.25,0.1,0.25,1); cursor: pointer;
}
.action-card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.08); transform: translateY(-2px); }
.action-label { font-size: 13px; font-weight: 500; color: #1d1d1f; }

.activity-list { display: flex; flex-direction: column; gap: 0; }
.activity-item {
  display: flex; align-items: center; gap: 12px; padding: 12px 0;
  border-bottom: 1px solid rgba(0,0,0,0.04);
}
.activity-item:last-child { border-bottom: none; }
.activity-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
.dot-primary { background: #0071e3; }
.dot-danger { background: #ff3b30; }
.activity-content { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.activity-title { font-size: 14px; font-weight: 500; color: #1d1d1f; }
.activity-detail { font-size: 12px; color: #86868b; }
.activity-time { font-size: 12px; color: #aeaeb2; white-space: nowrap; }

.mb-6 { margin-bottom: 24px; }

@media (max-width: 900px) {
  .two-col { grid-template-columns: 1fr; }
  .quick-actions { grid-template-columns: repeat(3, 1fr); }
}
</style>
