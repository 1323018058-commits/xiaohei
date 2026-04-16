import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { StoreItem } from '@/types'
import { storeApi } from '@/api'

export const useStoreStore = defineStore('store', () => {
  const stores = ref<StoreItem[]>([])
  const activeStoreId = ref<number>(0) // 0 = 全部店铺
  const loading = ref(false)

  const activeStore = computed(() =>
    activeStoreId.value === 0 ? null : stores.value.find((s) => s.id === activeStoreId.value) || null,
  )

  async function fetchStores() {
    loading.value = true
    try {
      const { data } = await storeApi.list()
      stores.value = data.stores || []
    } finally {
      loading.value = false
    }
  }

  function setActiveStore(id: number) {
    activeStoreId.value = id ?? 0
  }

  return { stores, activeStoreId, activeStore, loading, fetchStores, setActiveStore }
})
