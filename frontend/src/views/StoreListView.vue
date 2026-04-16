<template>
  <div>
    <div class="page-header">
      <h2>店铺管理</h2>
      <div style="display: flex; align-items: center; gap: 12px">
        <span style="font-size: 13px; color: #86868b">{{ stores.length }} / {{ maxStores }} 家</span>
        <el-button type="primary" @click="handleAddStore">添加店铺</el-button>
      </div>
    </div>

    <el-table :data="stores" v-loading="loading" stripe>
      <el-table-column prop="store_name" label="店铺名称" min-width="140">
        <template #default="{ row }">
          <router-link :to="`/stores/${row.id}`" style="color: #409eff; text-decoration: none">
            {{ row.store_name || row.store_alias || `Store #${row.id}` }}
          </router-link>
        </template>
      </el-table-column>
      <el-table-column prop="takealot_store_id" label="店铺 ID" width="120" align="center" />
      <el-table-column prop="offer_count" label="商品数" width="80" align="center" />
      <el-table-column label="API Key" min-width="180">
        <template #default="{ row }">
          <div style="display: flex; align-items: center; gap: 6px">
            <span style="font-family: monospace; font-size: 12px; color: #909399">
              {{ row.api_key_display || '—' }}
            </span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="api_key_status" label="API状态" width="90" align="center">
        <template #default="{ row }">
          <el-tag :type="row.api_key_status === '有效' ? 'success' : 'danger'" size="small">
            {{ row.api_key_status || '未知' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_synced_at" label="最近同步" width="140" align="center">
        <template #default="{ row }">
          <span style="font-size: 12px; color: #86868b">{{ row.last_synced_at || '未同步' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="syncStore(row.id)" :loading="syncingId === row.id">同步</el-button>
          <el-button size="small" type="danger" @click="removeStore(row.id)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Add store dialog -->
    <el-dialog v-model="showAddDialog" title="添加店铺" width="480px">
      <el-form :model="addForm" label-width="80px">
        <el-form-item label="API Key" required>
          <el-input
            v-model="addForm.api_key"
            type="password"
            show-password
            autocomplete="new-password"
            placeholder="Takealot Seller API Key"
          />
        </el-form-item>
        <el-form-item label="店铺名称" required>
          <el-input v-model="addForm.store_name" placeholder="输入店铺名称" />
        </el-form-item>
        <el-form-item label="店铺 ID" required>
          <el-input v-model="addForm.takealot_store_id" placeholder="Takealot 店铺 ID" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAddDialog = false">取消</el-button>
        <el-button type="primary" @click="addStore" :loading="adding">添加</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { storeApi } from '@/api'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStoreStore } from '@/stores/store'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()
const storeStore = useStoreStore()
const stores = ref<any[]>([])
const loading = ref(false)
const syncingId = ref<number | null>(null)
const showAddDialog = ref(false)
const adding = ref(false)
const addForm = ref({ api_key: '', store_name: '', takealot_store_id: '' })

const maxStores = computed(() => authStore.isAdmin ? 20 : 5)

function handleAddStore() {
  if (stores.value.length >= maxStores.value) {
    ElMessage.warning(`已达店铺上限（${maxStores.value}家）`)
    return
  }
  showAddDialog.value = true
}

async function fetchStores() {
  loading.value = true
  try {
    const { data } = await storeApi.list()
    stores.value = data.stores || []
  } finally {
    loading.value = false
  }
}

async function syncStore(id: number) {
  syncingId.value = id
  try {
    await storeApi.sync(id)
    ElMessage.success('同步完成')
    fetchStores()
  } finally {
    syncingId.value = null
  }
}

async function addStore() {
  if (!addForm.value.api_key) return ElMessage.warning('请输入 API Key')
  if (!addForm.value.store_name) return ElMessage.warning('请输入店铺名称')
  if (!addForm.value.takealot_store_id) return ElMessage.warning('请输入店铺 ID')
  adding.value = true
  try {
    await storeApi.create(addForm.value)
    ElMessage.success('店铺已添加')
    showAddDialog.value = false
    addForm.value = { api_key: '', store_name: '', takealot_store_id: '' }
    fetchStores()
    storeStore.fetchStores()
  } finally {
    adding.value = false
  }
}

async function removeStore(id: number) {
  await ElMessageBox.confirm('确定删除此店铺?', '确认')
  await storeApi.remove(id)
  ElMessage.success('已删除')
  fetchStores()
  storeStore.fetchStores()
}

onMounted(fetchStores)
</script>
