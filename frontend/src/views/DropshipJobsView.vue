<template>
  <div>
    <div class="page-header">
      <h2>关键词铺货</h2>
      <el-button type="primary" @click="showImportDialog = true">导入关键词</el-button>
    </div>

    <!-- Progress bar -->
    <el-card v-if="progress.running" shadow="never" style="margin-bottom: 16px">
      <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 8px">
        <el-icon class="is-loading" :size="18" style="color: #409eff"><Loading /></el-icon>
        <span style="font-weight: 600">{{ progress.keyword ? `正在搜索: ${progress.keyword}` : '正在处理...' }}</span>
      </div>
      <el-progress
        :percentage="progressPct"
        :stroke-width="18"
        :text-inside="true"
        striped
        striped-flow
      />
      <div style="margin-top: 8px; font-size: 12px; color: #909399">
        {{ progress.stage || progress.step || '' }}
        <span v-if="progress.found != null"> · 已找到 {{ progress.found }} 条商品</span>
        <span v-if="progress.scraped != null"> · 已抓取 {{ progress.scraped }} 条</span>
        <span v-if="progress.created_jobs"> · 已创建 {{ progress.created_jobs }} 个任务</span>
        <span v-if="progress.processed != null && progress.total"> · 已处理 {{ progress.processed }}/{{ progress.total }}</span>
      </div>
    </el-card>

    <!-- Completed result -->
    <el-alert
      v-if="lastResult"
      :title="lastResult"
      type="info"
      :closable="true"
      @close="lastResult = ''"
      style="margin-bottom: 16px"
      show-icon
    />

    <el-table :data="jobs" v-loading="loading" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column label="商品" min-width="220">
        <template #default="{ row }">
          <div style="display: flex; align-items: center; gap: 8px">
            <img v-if="row.image_url" :src="row.image_url" style="width: 40px; height: 40px; object-fit: cover; border-radius: 4px; flex-shrink: 0" />
            <div style="min-width: 0">
              <div style="font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap">
                {{ row.orig_title || row.listing_title || row.asin || '—' }}
              </div>
              <div style="font-size: 11px; color: #909399">
                <a v-if="row.amazon_url" :href="row.amazon_url" target="_blank" style="color: #409eff">{{ row.asin || 'Amazon' }}</a>
                <span v-if="row.source_keyword"> · {{ row.source_keyword.split('|')[0] }}</span>
              </div>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="matched_similarity" label="相似度" width="80" align="center">
        <template #default="{ row }">
          <span v-if="row.matched_similarity">{{ row.matched_similarity }}%</span>
          <span v-else style="color: #c0c4cc">—</span>
        </template>
      </el-table-column>
      <el-table-column prop="submission_id" label="提交ID" width="120" />
      <el-table-column prop="error_message" label="错误" min-width="160" show-overflow-tooltip />
      <el-table-column prop="created_at" label="创建时间" width="170" />
    </el-table>

    <!-- Import dialog -->
    <el-dialog v-model="showImportDialog" title="关键词铺货 — 搜索 Amazon" width="520px">
      <el-form :model="importForm" label-width="100px">
        <el-form-item label="关键词" required>
          <el-input v-model="importForm.keyword" placeholder="英文搜索关键词 (搜索 Amazon US)" />
        </el-form-item>
        <el-form-item label="目标店铺">
          <el-select v-model="importForm.store_id" placeholder="选择店铺" style="width:100%">
            <el-option v-for="s in storeStore.stores" :key="s.id" :label="s.store_name || `Store #${s.id}`" :value="s.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="最大数量">
          <el-input-number v-model="importForm.max_items" :min="1" :max="50" />
        </el-form-item>
        <el-form-item label="搜索页数">
          <el-input-number v-model="importForm.pages" :min="1" :max="10" />
        </el-form-item>
        <el-form-item label="相似度阈值">
          <el-input-number v-model="importForm.threshold" :min="0" :max="100" :step="5" />
          <span style="margin-left: 8px; font-size: 12px; color: #909399">%</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" @click="startImport" :loading="importing">开始搜索</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { dropshipApi } from '@/api'
import { useStoreStore } from '@/stores/store'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const storeStore = useStoreStore()
const jobs = ref<any[]>([])
const loading = ref(false)
const showImportDialog = ref(false)
const importing = ref(false)
const importForm = ref({ keyword: '', store_id: null as number | null, max_items: 10, pages: 5, threshold: 65 })
const progress = ref<any>({ running: false })
const lastResult = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const progressPct = computed(() => {
  if (!progress.value.running) return 0
  if (progress.value.total && progress.value.processed) {
    return Math.min(Math.round((progress.value.processed / progress.value.total) * 100), 99)
  }
  return 0
})

function statusType(s: string) {
  if (s === 'completed' || s === 'submitted' || s === 'success') return 'success'
  if (s === 'failed') return 'danger'
  if (['processing', 'running', 'scraping', 'matching', 'ai_rewriting', 'filling', 'submitting', 'dispatching'].includes(s)) return 'warning'
  if (s === 'pending' || s === 'queued') return 'info'
  return 'info'
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: '等待中', queued: '排队中', processing: '处理中', running: '运行中',
    dispatching: '分发中', scraping: '抓取中', matching: '匹配中',
    ai_rewriting: 'AI改写', filling: '填表中', submitting: '提交中',
    completed: '完成', submitted: '已提交', success: '成功', failed: '失败',
  }
  return map[s] || s
}

async function fetchJobs() {
  loading.value = true
  try {
    const { data } = await dropshipApi.list()
    jobs.value = data.jobs || []
  } finally {
    loading.value = false
  }
}

async function fetchProgress() {
  try {
    const { data } = await dropshipApi.keywordProgress()
    const wasRunning = progress.value.running
    progress.value = data || { running: false }
    // When task finishes, show result and refresh job list
    if (wasRunning && !progress.value.running) {
      fetchJobs()
      if (progress.value.error) {
        lastResult.value = `任务完成，但有错误: ${progress.value.error}`
      } else if (progress.value.created_jobs) {
        lastResult.value = `关键词搜索完成，创建了 ${progress.value.created_jobs} 个铺货任务`
      } else {
        lastResult.value = `关键词搜索完成 (${progress.value.step || 'done'})`
      }
    }
  } catch {
    // ignore
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(() => {
    fetchProgress()
    if (progress.value.running) {
      fetchJobs()
    }
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function startImport() {
  if (!importForm.value.keyword) return ElMessage.warning('请输入关键词')
  importing.value = true
  const kw = importForm.value.keyword
  try {
    await dropshipApi.keywordImport(importForm.value)
    ElMessage.success('导入任务已启动')
    showImportDialog.value = false
    importForm.value = { keyword: '', store_id: null, max_items: 10, pages: 5, threshold: 65 }
    // Immediately show progress
    progress.value = { running: true, keyword: kw, stage: '任务已提交，等待开始...' }
    // Poll quickly to catch fast-finishing tasks
    setTimeout(() => { fetchProgress(); fetchJobs() }, 1000)
    setTimeout(() => { fetchProgress(); fetchJobs() }, 3000)
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  fetchJobs()
  fetchProgress()
  startPolling()
})

onUnmounted(() => {
  stopPolling()
})
</script>
