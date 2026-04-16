<template>
  <div>
    <div class="page-header">
      <h2>个人设置</h2>
    </div>

    <div class="page-card" style="max-width: 600px">
      <el-descriptions :column="1" border v-if="authStore.user">
        <el-descriptions-item label="用户名">{{ authStore.user.username }}</el-descriptions-item>
        <el-descriptions-item label="角色">{{ authStore.user.role }}</el-descriptions-item>
        <el-descriptions-item label="许可证类型">{{ authStore.user.license_type || '无' }}</el-descriptions-item>
        <el-descriptions-item label="许可证到期">{{ authStore.user.license_expires_at || '未激活' }}</el-descriptions-item>
        <el-descriptions-item label="注册时间">{{ authStore.user.created_at }}</el-descriptions-item>
      </el-descriptions>

      <el-divider />

      <h3 style="margin-bottom: 16px">激活许可证</h3>
      <el-form @submit.prevent="activateLicense" inline>
        <el-form-item>
          <el-input v-model="licenseKey" placeholder="输入许可证密钥" style="width: 300px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="activateLicense" :loading="activating">激活</el-button>
        </el-form-item>
      </el-form>

      <el-divider />

      <h3 style="margin-bottom: 16px">Chrome 扩展</h3>
      <el-button type="primary" @click="$router.push('/extension/authorize')">授权扩展</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'
import { ElMessage } from 'element-plus'

const authStore = useAuthStore()
const licenseKey = ref('')
const activating = ref(false)

async function activateLicense() {
  if (!licenseKey.value) return ElMessage.warning('请输入许可证密钥')
  activating.value = true
  try {
    await authApi.activate(licenseKey.value)
    ElMessage.success('许可证已激活')
    licenseKey.value = ''
    authStore.fetchUser()
  } finally {
    activating.value = false
  }
}
</script>
