import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { UserInfo } from '@/types'
import { authApi } from '@/api'
import router from '@/router'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserInfo | null>(null)
  const loading = ref(false)

  const isLoggedIn = computed(() => !!user.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  const username = computed(() => user.value?.username || '')

  async function login(username: string, password: string) {
    loading.value = true
    try {
      const { data } = await authApi.login({ username, password })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      await fetchUser()
      router.push('/')
    } finally {
      loading.value = false
    }
  }

  async function register(username: string, password: string, email: string, emailCode: string) {
    loading.value = true
    try {
      const { data } = await authApi.register({ username, password, email, email_code: emailCode })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      await fetchUser()
      router.push('/')
    } finally {
      loading.value = false
    }
  }

  async function fetchUser() {
    try {
      const { data } = await authApi.me()
      user.value = data as UserInfo
    } catch {
      user.value = null
    }
  }

  async function logout() {
    try {
      await authApi.logout()
    } catch {
      // ignore
    }
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
    localStorage.removeItem('csrf_token')
    router.push('/login')
  }

  function tryRestoreSession() {
    const token = localStorage.getItem('access_token')
    if (token) {
      fetchUser()
    }
  }

  return { user, loading, isLoggedIn, isAdmin, username, login, register, fetchUser, logout, tryRestoreSession }
})
