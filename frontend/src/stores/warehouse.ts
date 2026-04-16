import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { warehouseApi } from '@/api'
import type { WarehouseJobSummary, FulfillmentDraft, AuditLogEntry } from '@/types'

export const useWarehouseStore = defineStore('warehouse', () => {
  const jobs = ref<WarehouseJobSummary[]>([])
  const currentDraft = ref<FulfillmentDraft | null>(null)
  const auditLogs = ref<AuditLogEntry[]>([])
  const loading = ref(false)
  const saving = ref(false)
  const searchQuery = ref('')
  const statusFilter = ref('')
  const storeFilter = ref('')  // '' = 全部店铺

  // 可用的店铺选项（从 jobs 中提取去重）
  const storeOptions = computed(() => {
    const map = new Map<number, string>()
    for (const job of jobs.value) {
      if (!map.has(job.store_id)) {
        map.set(job.store_id, job.store_alias)
      }
    }
    return Array.from(map.entries()).map(([id, alias]) => ({
      value: String(id),
      label: alias || `Store #${id}`,
    }))
  })

  // 按筛选后的 jobs 计算状态数量
  const statusCounts = computed(() => {
    const counts: Record<string, number> = {}
    const base = storeFilter.value
      ? jobs.value.filter(j => String(j.store_id) === storeFilter.value)
      : jobs.value
    for (const job of base) {
      counts[job.workflow_status] = (counts[job.workflow_status] || 0) + 1
    }
    return counts
  })

  const filteredJobs = computed(() => {
    let result = jobs.value

    // 店铺筛选
    if (storeFilter.value) {
      result = result.filter(j => String(j.store_id) === storeFilter.value)
    }

    // 状态筛选
    if (statusFilter.value) {
      result = result.filter(j => j.workflow_status === statusFilter.value)
    }

    // 搜索
    if (searchQuery.value) {
      const q = searchQuery.value.toLowerCase()
      result = result.filter(j =>
        j.shipment_name.toLowerCase().includes(q) ||
        j.po_number.toLowerCase().includes(q) ||
        j.store_alias.toLowerCase().includes(q) ||
        String(j.shipment_id).includes(q)
      )
    }
    return result
  })

  async function fetchJobs() {
    loading.value = true
    try {
      const { data } = await warehouseApi.jobs()
      jobs.value = data.items || []
    } finally {
      loading.value = false
    }
  }

  async function loadDraft(storeId: number, shipmentId: number) {
    loading.value = true
    try {
      const { data } = await warehouseApi.jobDetail(storeId, shipmentId)
      currentDraft.value = data.draft || null
    } finally {
      loading.value = false
    }
  }

  async function saveDraft(storeId: number, shipmentId: number, draftData: any) {
    saving.value = true
    try {
      const { data } = await warehouseApi.saveDraft(storeId, shipmentId, draftData)
      if (data.ok && currentDraft.value) {
        currentDraft.value.version = data.version
        currentDraft.value.workflow_status = data.workflow_status
      }
      return data
    } finally {
      saving.value = false
    }
  }

  async function loadAuditLog(storeId: number, shipmentId: number) {
    try {
      const { data } = await warehouseApi.auditLog(storeId, shipmentId)
      auditLogs.value = data.items || []
    } catch {
      auditLogs.value = []
    }
  }

  function clearDraft() {
    currentDraft.value = null
    auditLogs.value = []
  }

  return {
    jobs, currentDraft, auditLogs, loading, saving,
    searchQuery, statusFilter, storeFilter,
    storeOptions, statusCounts, filteredJobs,
    fetchJobs, loadDraft, saveDraft, loadAuditLog, clearDraft,
  }
})
