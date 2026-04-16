<template>
  <div class="print-page">
    <div v-if="loading" v-loading="true" style="min-height: 300px" />

    <template v-else-if="printData">
      <div class="print-header no-print">
        <h2>三标打印 - {{ printData.shipment_name }}</h2>
        <el-button type="primary" @click="handlePrint">打印</el-button>
      </div>

      <div class="print-content">
        <div
          v-for="(item, idx) in printData.items"
          :key="item.id"
          class="label-card"
        >
          <div class="label-header">
            <span class="label-no">{{ idx + 1 }} / {{ printData.items.length }}</span>
            <span class="shipment-name">{{ printData.shipment_name }}</span>
          </div>
          <div class="label-body">
            <div class="label-row">
              <span class="label-field">SKU:</span>
              <span class="label-value">{{ item.sku }}</span>
            </div>
            <div class="label-row">
              <span class="label-field">TSIN:</span>
              <span class="label-value">{{ item.tsin_id }}</span>
            </div>
            <div class="label-row">
              <span class="label-field">商品名称:</span>
              <span class="label-value">{{ item.title }}</span>
            </div>
            <div class="label-row">
              <span class="label-field">数量:</span>
              <span class="label-value">{{ item.qty_sending }}</span>
            </div>
            <div class="label-row">
              <span class="label-field">PO:</span>
              <span class="label-value">{{ printData.po_number }}</span>
            </div>
            <div class="label-row">
              <span class="label-field">仓库:</span>
              <span class="label-value">{{ printData.facility_code }}</span>
            </div>
          </div>
          <div class="label-footer">
            <span>Line {{ item.line_no }}</span>
            <span>{{ printData.due_date }}</span>
          </div>
        </div>
      </div>
    </template>

    <el-empty v-else description="未找到打印数据" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { warehouseApi } from '@/api'

const route = useRoute()
const loading = ref(false)
const printData = ref<any>(null)

async function fetchPrintData() {
  const storeId = Number(route.params.storeId)
  const shipmentId = Number(route.params.shipmentId)
  if (!storeId || !shipmentId) return

  loading.value = true
  try {
    const { data } = await warehouseApi.printData(storeId, shipmentId)
    printData.value = data
  } finally {
    loading.value = false
  }
}

function handlePrint() {
  window.print()
}

onMounted(fetchPrintData)
</script>

<style scoped>
.print-page {
  padding: 20px;
  background: #fff;
}

.print-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.print-content {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.label-card {
  width: 320px;
  border: 2px solid #333;
  padding: 12px;
  page-break-inside: avoid;
  font-size: 13px;
}

.label-header {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid #999;
  padding-bottom: 6px;
  margin-bottom: 8px;
  font-weight: bold;
}

.label-no {
  color: #666;
}

.label-body {
  line-height: 1.8;
}

.label-row {
  display: flex;
}

.label-field {
  width: 80px;
  flex-shrink: 0;
  color: #666;
}

.label-value {
  font-weight: 500;
}

.label-footer {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid #999;
  padding-top: 6px;
  margin-top: 8px;
  color: #666;
  font-size: 12px;
}

@media print {
  .no-print {
    display: none !important;
  }

  .print-page {
    padding: 0;
  }

  .label-card {
    width: 300px;
    margin: 8px;
  }
}
</style>
