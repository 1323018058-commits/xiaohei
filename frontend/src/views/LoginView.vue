<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="brand">ProfitLens ERP</h1>
      <p class="subtitle">Takealot 跨境电商 ERP 系统</p>

      <el-tabs v-model="activeTab" stretch>
        <el-tab-pane label="登录" name="login">
          <el-form ref="loginFormRef" :model="loginForm" :rules="loginRules" @submit.prevent="handleLogin">
            <el-form-item prop="username">
              <el-input v-model="loginForm.username" placeholder="用户名" prefix-icon="User" size="large" />
            </el-form-item>
            <el-form-item prop="password">
              <el-input v-model="loginForm.password" placeholder="密码" prefix-icon="Lock" type="password" size="large" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="authStore.loading" size="large" style="width:100%">登 录</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>

        <el-tab-pane label="注册" name="register">
          <el-form ref="regFormRef" :model="regForm" :rules="regRules" @submit.prevent="handleRegister">
            <el-form-item prop="username">
              <el-input v-model="regForm.username" placeholder="用户名" prefix-icon="User" size="large" />
            </el-form-item>
            <el-form-item prop="email">
              <el-input v-model="regForm.email" placeholder="邮箱地址" prefix-icon="Message" size="large" />
            </el-form-item>
            <el-form-item prop="email_code">
              <div style="display:flex;gap:10px;width:100%">
                <el-input v-model="regForm.email_code" placeholder="邮箱验证码" prefix-icon="Key" size="large" style="flex:1" />
                <el-button size="large" :disabled="codeCooldown > 0 || !regForm.email" :loading="sendingCode" @click="handleSendCode">
                  {{ codeCooldown > 0 ? `${codeCooldown}s` : '获取验证码' }}
                </el-button>
              </div>
            </el-form-item>
            <el-form-item prop="password">
              <el-input v-model="regForm.password" placeholder="密码（至少6位）" prefix-icon="Lock" type="password" size="large" show-password />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" native-type="submit" :loading="authStore.loading" size="large" style="width:100%">注 册</el-button>
            </el-form-item>
          </el-form>
        </el-tab-pane>
      </el-tabs>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { authApi } from '@/api'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'

const authStore = useAuthStore()
const activeTab = ref('login')

// Login form
const loginFormRef = ref<FormInstance>()
const loginForm = reactive({ username: '', password: '' })
const loginRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

// Register form
const regFormRef = ref<FormInstance>()
const regForm = reactive({ username: '', email: '', email_code: '', password: '' })
const regRules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }, { min: 3, message: '至少3个字符', trigger: 'blur' }],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '邮箱格式不正确', trigger: 'blur' },
  ],
  email_code: [{ required: true, message: '请输入验证码', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }, { min: 6, message: '至少6个字符', trigger: 'blur' }],
}

// Send code
const sendingCode = ref(false)
const codeCooldown = ref(0)
let cooldownTimer: ReturnType<typeof setInterval> | null = null

async function handleSendCode() {
  if (!regForm.email) return
  sendingCode.value = true
  try {
    await authApi.sendCode(regForm.email)
    ElMessage.success('验证码已发送，请查看邮箱')
    codeCooldown.value = 60
    cooldownTimer = setInterval(() => {
      codeCooldown.value--
      if (codeCooldown.value <= 0 && cooldownTimer) {
        clearInterval(cooldownTimer)
        cooldownTimer = null
      }
    }, 1000)
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.detail || '发送失败')
  } finally {
    sendingCode.value = false
  }
}

onUnmounted(() => {
  if (cooldownTimer) clearInterval(cooldownTimer)
})

async function handleLogin() {
  const valid = await loginFormRef.value?.validate().catch(() => false)
  if (!valid) return
  await authStore.login(loginForm.username, loginForm.password)
}

async function handleRegister() {
  const valid = await regFormRef.value?.validate().catch(() => false)
  if (!valid) return
  await authStore.register(regForm.username, regForm.password, regForm.email, regForm.email_code)
}
</script>

<style scoped lang="scss">
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1d1e2c 0%, #2d3a4b 100%);
}
.login-card {
  width: 420px;
  background: #fff;
  border-radius: 12px;
  padding: 40px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.15);
}
.brand {
  text-align: center;
  font-size: 28px;
  font-weight: 700;
  color: #409eff;
  margin-bottom: 4px;
}
.subtitle {
  text-align: center;
  color: #909399;
  font-size: 13px;
  margin-bottom: 24px;
}
</style>
