<template>
  <div>
    <div class="page-header">
      <h2>管理后台</h2>
    </div>

    <!-- Stats -->
    <div class="stat-grid mb-4" v-if="stats">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_users ?? 0 }}</div>
        <div class="stat-label">总用户数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.active_users ?? 0 }}</div>
        <div class="stat-label">活跃用户</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_stores ?? 0 }}</div>
        <div class="stat-label">总店铺数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value">{{ stats.active_licenses ?? 0 }}</div>
        <div class="stat-label">活跃许可证</div>
      </div>
    </div>

    <el-tabs v-model="activeTab">
      <!-- Users tab -->
      <el-tab-pane label="用户管理" name="users">
        <el-table :data="users" v-loading="loadingUsers" stripe>
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="username" label="用户名" width="150" />
          <el-table-column prop="role" label="角色" width="100" />
          <el-table-column prop="license_type" label="许可证" width="120" />
          <el-table-column prop="license_expires_at" label="过期时间" width="170" />
          <el-table-column prop="store_count" label="店铺数" width="80" align="center" />
          <el-table-column prop="created_at" label="注册时间" width="170" />
        </el-table>
      </el-tab-pane>

      <!-- License tab -->
      <el-tab-pane label="许可证管理" name="licenses">
        <div style="margin-bottom: 16px">
          <el-form :model="licenseForm" inline>
            <el-form-item label="类型">
              <el-select v-model="licenseForm.license_type" style="width:120px">
                <el-option label="基础版" value="basic" />
                <el-option label="专业版" value="pro" />
                <el-option label="企业版" value="enterprise" />
              </el-select>
            </el-form-item>
            <el-form-item label="天数">
              <el-input-number v-model="licenseForm.days" :min="1" :max="3650" />
            </el-form-item>
            <el-form-item label="数量">
              <el-input-number v-model="licenseForm.count" :min="1" :max="100" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" @click="generateLicenses" :loading="generating">生成</el-button>
            </el-form-item>
            <el-form-item>
              <el-button @click="exportLicenses">导出 CSV</el-button>
            </el-form-item>
          </el-form>
        </div>

        <div v-if="generatedKeys.length" class="page-card">
          <h4>已生成的密钥:</h4>
          <el-input type="textarea" :model-value="generatedKeys.join('\n')" :rows="Math.min(generatedKeys.length, 10)" readonly />
        </div>
      </el-tab-pane>

      <!-- System health -->
      <el-tab-pane label="系统状态" name="health">
        <div class="page-card" v-if="health">
          <el-descriptions :column="2" border>
            <el-descriptions-item label="Redis">
              <el-tag :type="health.redis_ok ? 'success' : 'danger'">{{ health.redis_ok ? '正常' : '异常' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="数据库">
              <el-tag :type="health.db_ok ? 'success' : 'danger'">{{ health.db_ok ? '正常' : '异常' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="Celery">
              <el-tag :type="health.celery_ok ? 'success' : 'danger'">{{ health.celery_ok ? '正常' : '异常' }}</el-tag>
            </el-descriptions-item>
            <el-descriptions-item label="版本">{{ health.version || '-' }}</el-descriptions-item>
          </el-descriptions>
        </div>
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, watch } from 'vue'
import { adminApi } from '@/api'
import { ElMessage } from 'element-plus'

const activeTab = ref('users')
const stats = ref<any>(null)
const users = ref<any[]>([])
const loadingUsers = ref(false)
const health = ref<any>(null)
const generating = ref(false)
const generatedKeys = ref<string[]>([])
const licenseForm = reactive({ license_type: 'pro', days: 365, count: 1 })

async function fetchStats() {
  const { data } = await adminApi.stats()
  stats.value = data
}

async function fetchUsers() {
  loadingUsers.value = true
  try {
    const { data } = await adminApi.users()
    users.value = data.users || []
  } finally {
    loadingUsers.value = false
  }
}

async function fetchHealth() {
  const { data } = await adminApi.systemHealth()
  health.value = data
}

async function generateLicenses() {
  generating.value = true
  try {
    const { data } = await adminApi.generateLicense(licenseForm)
    generatedKeys.value = data.keys || []
    ElMessage.success(`已生成 ${generatedKeys.value.length} 个密钥`)
  } finally {
    generating.value = false
  }
}

async function exportLicenses() {
  const { data } = await adminApi.exportLicenses()
  const url = window.URL.createObjectURL(data)
  const a = document.createElement('a')
  a.href = url
  a.download = 'licenses.csv'
  a.click()
  window.URL.revokeObjectURL(url)
}

watch(activeTab, (tab) => {
  if (tab === 'health' && !health.value) fetchHealth()
})

onMounted(() => {
  fetchStats()
  fetchUsers()
})
</script>
