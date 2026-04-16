<template>
  <div>
    <div class="page-header">
      <h2>消息通知</h2>
      <el-button @click="markAllRead" :disabled="notifStore.unreadCount === 0">全部已读</el-button>
    </div>

    <el-table :data="notifications" v-loading="loading" stripe>
      <el-table-column prop="level" label="级别" width="80" align="center">
        <template #default="{ row }">
          <el-tag :type="row.level === 'error' ? 'danger' : row.level === 'warning' ? 'warning' : 'info'" size="small">
            {{ row.level }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="title" label="标题" min-width="250">
        <template #default="{ row }">
          <span :style="{ fontWeight: row.is_read ? 'normal' : '600' }">{{ row.title }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
      <el-table-column prop="module" label="模块" width="100" />
      <el-table-column prop="created_at" label="时间" width="170" />
      <el-table-column label="操作" width="80" align="center">
        <template #default="{ row }">
          <el-button v-if="!row.is_read" size="small" link type="primary" @click="markRead(row.id)">已读</el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { notificationApi } from '@/api'
import { useNotificationStore } from '@/stores/notification'
import type { NotificationItem } from '@/types'

const notifStore = useNotificationStore()
const notifications = ref<NotificationItem[]>([])
const loading = ref(false)

async function fetchNotifications() {
  loading.value = true
  try {
    const { data } = await notificationApi.list()
    notifications.value = data.notifications || []
  } finally {
    loading.value = false
  }
}

async function markRead(id: number) {
  await notificationApi.markRead(id)
  fetchNotifications()
  notifStore.fetchUnreadCount()
}

async function markAllRead() {
  await notificationApi.markAllRead()
  fetchNotifications()
  notifStore.fetchUnreadCount()
}

onMounted(fetchNotifications)
</script>
