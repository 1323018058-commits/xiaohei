import axios from 'axios'
import type { AuthTokens } from '@/types'
import { ElMessage } from 'element-plus'

const http = axios.create({
  baseURL: '/api',
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
})

// Request interceptor: attach JWT + CSRF token
http.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  const csrf = localStorage.getItem('csrf_token')
  if (csrf) {
    config.headers['X-CSRF-Token'] = csrf
  }
  return config
})

// Response interceptor: handle 401 → refresh token
let isRefreshing = false
let pendingRequests: Array<(token: string) => void> = []

http.interceptors.response.use(
  (response) => {
    // Extract CSRF from response header if present
    const csrf = response.headers['x-csrf-token']
    if (csrf) {
      localStorage.setItem('csrf_token', csrf)
    }
    return response
  },
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      const refreshToken = localStorage.getItem('refresh_token')
      if (!refreshToken) {
        clearAuth()
        window.location.href = '/login'
        return Promise.reject(error)
      }

      if (isRefreshing) {
        return new Promise((resolve) => {
          pendingRequests.push((newToken: string) => {
            originalRequest.headers.Authorization = `Bearer ${newToken}`
            resolve(http(originalRequest))
          })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      try {
        const { data } = await axios.post<AuthTokens>('/api/auth/refresh', {
          refresh_token: refreshToken,
        })
        localStorage.setItem('access_token', data.access_token)
        localStorage.setItem('refresh_token', data.refresh_token)

        pendingRequests.forEach((cb) => cb(data.access_token))
        pendingRequests = []

        originalRequest.headers.Authorization = `Bearer ${data.access_token}`
        return http(originalRequest)
      } catch {
        clearAuth()
        window.location.href = '/login'
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }

    // Show error message for non-401 errors
    const msg = error.response?.data?.detail || error.response?.data?.error || error.message
    if (msg) {
      ElMessage.error(msg)
    }

    return Promise.reject(error)
  },
)

function clearAuth() {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('csrf_token')
}

export default http
