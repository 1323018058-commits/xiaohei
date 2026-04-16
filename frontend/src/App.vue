<template>
  <router-view />
</template>

<script setup lang="ts">
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

// Try to restore session on mount
authStore.tryRestoreSession()
</script>
