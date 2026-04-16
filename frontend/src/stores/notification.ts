import { defineStore } from 'pinia'
import { ref } from 'vue'
import { notificationApi } from '@/api'

export const useNotificationStore = defineStore('notification', () => {
  const unreadCount = ref(0)
  let timer: ReturnType<typeof setInterval> | null = null

  async function fetchUnreadCount() {
    try {
      const { data } = await notificationApi.unreadCount()
      unreadCount.value = data.count || 0
    } catch {
      // ignore
    }
  }

  function startPolling(intervalMs = 60000) {
    fetchUnreadCount()
    if (timer) clearInterval(timer)
    timer = setInterval(fetchUnreadCount, intervalMs)
  }

  function stopPolling() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  return { unreadCount, fetchUnreadCount, startPolling, stopPolling }
})
