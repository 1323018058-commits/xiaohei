<template>
  <div>
    <div class="page-header">
      <h2>发货中心</h2>
    </div>

    <!-- 状态看板 -->
    <el-row :gutter="16" class="status-board">
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="待用户预报快递" :value="store.statusCounts['待用户预报快递'] || 0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="待贴三标" :value="store.statusCounts['待贴三标'] || 0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="待送嘉鸿" :value="store.statusCounts['待送嘉鸿'] || 0" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="待用户预报嘉鸿" :value="store.statusCounts['待用户预报嘉鸿'] || 0" />
        </el-card>
      </el-col>
    </el-row>

    <!-- 工具栏 -->
    <el-row :gutter="12" class="toolbar" align="middle">
      <el-col :span="8">
        <el-input
          v-model="store.searchQuery"
          placeholder="搜索PO/SKU..."
          clearable
          prefix-icon="Search"
        />
      </el-col>
      <el-col :span="6">
        <el-select v-model="store.statusFilter" placeholder="全部状态" clearable style="width: 100%">
          <el-option label="全部状态" value="" />
          <el-option v-for="s in allStatuses" :key="s" :label="s" :value="s" />
        </el-select>
      </el-col>
      <el-col :span="2">
        <el-button :icon="Refresh" @click="store.fetchJobs()" :loading="store.loading">
          刷新
        </el-button>
      </el-col>
    </el-row>

    <!-- 作业列表 -->
    <el-table :data="store.filteredJobs" v-loading="store.loading" stripe style="width: 100%">
      <el-table-column prop="store_alias" label="店铺" width="130" show-overflow-tooltip />
      <el-table-column label="Shipment / PO" min-width="220">
        <template #default="{ row }">
          <div>{{ row.shipment_name }}</div>
          <div style="color: #909399; font-size: 12px">{{ row.po_number }}</div>
        </template>
      </el-table-column>
      <el-table-column prop="due_date" label="截止日期" width="120" />
      <el-table-column label="状态" width="140" align="center">
        <template #default="{ row }">
          <el-tag :type="getTagType(row.workflow_status)" size="small">
            {{ row.workflow_status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="SKU到齐" width="100" align="center">
        <template #default="{ row }">
          {{ row.ready_count }} / {{ row.total_items }}
        </template>
      </el-table-column>
      <el-table-column prop="updated_at" label="最后更新" width="170">
        <template #default="{ row }">
          <div>{{ row.updated_at || '-' }}</div>
          <div v-if="row.updated_by_username" style="color: #909399; font-size: 12px">
            {{ row.updated_by_username }}
          </div>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <template #default="{ row }">
          <el-button size="small" type="primary" link @click="openDetail(row)">
            打开
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 作业详情弹窗 -->
    <el-dialog v-model="dialogVisible" title="作业详情" width="900px" destroy-on-close>
      <template v-if="store.currentDraft">
        <!-- 顶部 Shipment 信息摘要 -->
        <el-descriptions :column="3" border size="small" class="draft-summary">
          <el-descriptions-item label="Shipment">
            {{ store.currentDraft.shipment_name }}
          </el-descriptions-item>
          <el-descriptions-item label="PO">
            {{ store.currentDraft.po_number }}
          </el-descriptions-item>
          <el-descriptions-item label="截止日期">
            {{ store.currentDraft.due_date }}
          </el-descriptions-item>
          <el-descriptions-item label="仓库">
            {{ store.currentDraft.warehouse_name }}
          </el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag
              :type="getTagType(store.currentDraft.workflow_status)"
              size="small"
            >
              {{ store.currentDraft.workflow_status }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="版本">
            v{{ store.currentDraft.version }}
          </el-descriptions-item>
        </el-descriptions>

        <!-- SKU 明细表格 -->
        <el-table
          :data="store.currentDraft.items"
          stripe
          size="small"
          style="width: 100%; margin-top: 16px"
          max-height="360"
        >
          <el-table-column prop="line_no" label="#" width="50" />
          <el-table-column prop="sku" label="SKU" width="130" show-overflow-tooltip />
          <el-table-column prop="title" label="商品名称" min-width="180" show-overflow-tooltip />
          <el-table-column prop="qty_required" label="需求数" width="80" align="center" />
          <el-table-column prop="qty_sending" label="发货数" width="80" align="center" />
          <el-table-column label="到仓数" width="100" align="center">
            <template #default="{ row }">
              <el-input-number
                v-model="row.arrived_qty"
                :min="0"
                :max="row.qty_sending"
                size="small"
                controls-position="right"
                style="width: 80px"
              />
            </template>
          </el-table-column>
          <el-table-column label="快递单号" width="180">
            <template #default="{ row }">
              <el-input
                v-model="row.domestic_tracking_no"
                size="small"
                placeholder="快递单号"
              />
            </template>
          </el-table-column>
        </el-table>

        <!-- 底部操作区 -->
        <div class="draft-actions" style="margin-top: 20px">
          <!-- 仓库动作按钮组 -->
          <el-space wrap>
            <el-popconfirm title="确认标记三标已完成?" @confirm="markLabels">
              <template #reference>
                <el-button type="success" size="small" :disabled="store.currentDraft.labels_done === 1">
                  标记三标完成
                </el-button>
              </template>
            </el-popconfirm>
            <el-popconfirm title="确认标记已送嘉鸿?" @confirm="markSentToCnx">
              <template #reference>
                <el-button type="warning" size="small" :disabled="store.currentDraft.sent_to_cnx === 1">
                  标记已送嘉鸿
                </el-button>
              </template>
            </el-popconfirm>
            <el-popconfirm title="确认通知用户预报嘉鸿?" @confirm="notifyUserCnx">
              <template #reference>
                <el-button type="danger" size="small" :disabled="!!store.currentDraft.notify_user_cnx_at">
                  通知用户预报嘉鸿
                </el-button>
              </template>
            </el-popconfirm>
          </el-space>

          <!-- 仓库备注 -->
          <el-input
            v-model="store.currentDraft.warehouse_note"
            type="textarea"
            :rows="2"
            placeholder="仓库备注..."
            style="margin-top: 12px"
          />

          <!-- 保存按钮 -->
          <div style="margin-top: 12px; text-align: right">
            <el-button
              type="primary"
              :loading="store.saving"
              @click="handleSave"
            >
              保存
            </el-button>
          </div>
        </div>
      </template>

      <el-empty v-else-if="!store.loading" description="无数据" />
      <div v-else v-loading="true" style="min-height: 200px" />
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useWarehouseStore } from '@/stores/warehouse'
import { useStoreStore } from '@/stores/store'
import type { WarehouseJobSummary, WorkflowStatus } from '@/types'
import { watch } from 'vue'

const store = useWarehouseStore()
const storeStore = useStoreStore()

// 全局店铺选择器变化时，同步到发货中心筛选
watch(() => storeStore.activeStoreId, (newId) => {
  store.storeFilter = newId > 0 ? String(newId) : ''
}, { immediate: true })

const dialogVisible = ref(false)
const currentStoreId = ref(0)
const currentShipmentId = ref(0)

const allStatuses: WorkflowStatus[] = [
  '待用户预报快递',
  '待到仓',
  '待贴三标',
  '待送嘉鸿',
  '待用户预报嘉鸿',
  '嘉鸿已预报',
]

type TagType = 'primary' | 'success' | 'warning' | 'info' | 'danger'
const statusTagType: Record<string, TagType> = {
  '待用户预报快递': 'info',
  '待到仓': 'warning',
  '待贴三标': 'primary',
  '待送嘉鸿': 'warning',
  '待用户预报嘉鸿': 'danger',
  '嘉鸿已预报': 'success',
}
function getTagType(status: string): TagType {
  return statusTagType[status] ?? 'info'
}

async function openDetail(row: WarehouseJobSummary) {
  currentStoreId.value = row.store_id
  currentShipmentId.value = row.shipment_id
  dialogVisible.value = true
  await store.loadDraft(row.store_id, row.shipment_id)
  store.loadAuditLog(row.store_id, row.shipment_id)
}

async function handleSave() {
  if (!store.currentDraft) return
  const draft = store.currentDraft
  try {
    const result = await store.saveDraft(currentStoreId.value, currentShipmentId.value, {
      items: draft.items.map(item => ({
        id: item.id,
        arrived_qty: item.arrived_qty,
        domestic_tracking_no: item.domestic_tracking_no,
      })),
      warehouse_note: draft.warehouse_note,
      version: draft.version,
    })
    if (result.ok) {
      ElMessage.success('保存成功')
      store.fetchJobs()
    }
  } catch (err: any) {
    if (err?.response?.status === 409) {
      ElMessageBox.alert(
        '数据已被其他用户修改，请刷新后重试。',
        '版本冲突',
        { confirmButtonText: '刷新', type: 'warning' },
      ).then(() => {
        store.loadDraft(currentStoreId.value, currentShipmentId.value)
      })
    } else {
      ElMessage.error(err?.response?.data?.error || '保存失败')
    }
  }
}

async function markLabels() {
  if (!store.currentDraft) return
  try {
    await store.saveDraft(currentStoreId.value, currentShipmentId.value, {
      action: 'mark_labels_done',
      version: store.currentDraft.version,
    })
    ElMessage.success('已标记三标完成')
    store.loadDraft(currentStoreId.value, currentShipmentId.value)
    store.fetchJobs()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '操作失败')
  }
}

async function markSentToCnx() {
  if (!store.currentDraft) return
  try {
    await store.saveDraft(currentStoreId.value, currentShipmentId.value, {
      action: 'mark_sent_to_cnx',
      version: store.currentDraft.version,
    })
    ElMessage.success('已标记送嘉鸿')
    store.loadDraft(currentStoreId.value, currentShipmentId.value)
    store.fetchJobs()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '操作失败')
  }
}

async function notifyUserCnx() {
  if (!store.currentDraft) return
  try {
    await store.saveDraft(currentStoreId.value, currentShipmentId.value, {
      action: 'notify_user_cnx',
      version: store.currentDraft.version,
    })
    ElMessage.success('已通知用户预报嘉鸿')
    store.loadDraft(currentStoreId.value, currentShipmentId.value)
    store.fetchJobs()
  } catch (err: any) {
    ElMessage.error(err?.response?.data?.error || '操作失败')
  }
}

onMounted(() => store.fetchJobs())
</script>

<style scoped>
.status-board {
  margin-bottom: 20px;
}
.toolbar {
  margin-bottom: 16px;
}
.draft-summary {
  margin-bottom: 8px;
}
</style>
