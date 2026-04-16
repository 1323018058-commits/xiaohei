<template>
  <div class="ext-auth-page">
    <div class="page-card" style="max-width: 500px; margin: 60px auto; text-align: center">
      <div v-if="loading" style="padding: 40px 0">
        <el-icon :size="40" class="is-loading" style="color: #2b67f6"><Loading /></el-icon>
        <p style="color: #909399; margin-top: 16px; font-size: 14px">正在连接扩展，请稍候...</p>
      </div>

      <div v-else-if="error">
        <h2 style="margin-bottom: 16px">连接失败</h2>
        <el-alert :title="error" type="error" :closable="false" style="margin-bottom: 16px" />
        <el-button type="primary" @click="authorize">重试</el-button>
      </div>

      <div v-else-if="authCode">
        <el-icon :size="48" style="color: #67c23a"><CircleCheck /></el-icon>
        <h2 style="margin: 12px 0 8px">扩展连接成功！</h2>
        <p style="color: #909399; font-size: 13px">正在跳转到 ERP 首页...</p>
      </div>

      <!-- Hidden element for Chrome extension content-auth.js to read -->
      <div v-if="authCode" id="extension-auth" :data-auth-code="authCode" style="display:none"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Loading, CircleCheck } from '@element-plus/icons-vue'
import http from '@/api/http'

const router = useRouter()
const authCode = ref('')
const loading = ref(true)
const error = ref('')

async function authorize() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await http.post('/extension/authorize-api')
    authCode.value = data.auth_code || data.code || ''

    if (authCode.value) {
      await nextTick()
      // Give content-auth.js 2 seconds to read the auth code, then redirect
      setTimeout(() => {
        router.push('/')
        ElMessage.success('扩展已连接成功')
      }, 2000)
    } else {
      error.value = '未获取到授权码，请重试'
    }
  } catch {
    error.value = '生成失败，请重试'
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  authorize()
})
</script>
