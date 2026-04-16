<template>
  <div>
    <div class="page-header">
      <h2>AI铺货</h2>
      <el-button type="primary" @click="showCreateDialog = true">新建铺货</el-button>
    </div>

    <el-table :data="jobs" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="listing_title" label="标题" min-width="250" show-overflow-tooltip>
        <template #default="{ row }">{{ row.listing_title || row.amazon_url?.substring(0, 60) }}</template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ row.status }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="error_message" label="错误" min-width="180" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170" />
    </el-table>

    <!-- Create dialog -->
    <el-dialog v-model="showCreateDialog" title="新建AI铺货" width="520px">
      <el-form :model="createForm" label-width="100px">
        <el-form-item label="Amazon URL" required>
          <el-input v-model="createForm.amazon_url" placeholder="https://www.amazon.com/dp/..." />
        </el-form-item>
        <el-form-item label="目标店铺">
          <el-select v-model="createForm.store_id" placeholder="选择店铺" style="width:100%">
            <el-option v-for="s in storeStore.stores" :key="s.id" :label="s.store_name || `Store #${s.id}`" :value="s.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="createJob" :loading="creating">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { listingApi } from '@/api'
import { useStoreStore } from '@/stores/store'
import { ElMessage } from 'element-plus'

const storeStore = useStoreStore()
const jobs = ref<any[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)
const createForm = ref({ amazon_url: '', store_id: null as number | null })

function statusType(s: string) {
  if (s === 'completed' || s === 'submitted') return 'success'
  if (s === 'failed') return 'danger'
  if (s === 'processing') return 'warning'
  return 'info'
}

async function fetchJobs() {
  loading.value = true
  try {
    const { data } = await listingApi.list()
    jobs.value = data.jobs || []
  } finally {
    loading.value = false
  }
}

async function createJob() {
  if (!createForm.value.amazon_url) return ElMessage.warning('请输入 Amazon URL')
  creating.value = true
  try {
    await listingApi.create(createForm.value)
    ElMessage.success('铺货任务已创建')
    showCreateDialog.value = false
    createForm.value = { amazon_url: '', store_id: null }
    fetchJobs()
  } finally {
    creating.value = false
  }
}

onMounted(fetchJobs)
</script>
