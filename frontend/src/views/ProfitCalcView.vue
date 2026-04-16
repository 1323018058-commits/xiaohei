<template>
  <div>
    <div class="page-header">
      <h2>利润计算器</h2>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px">
      <!-- Input form -->
      <div class="page-card">
        <h3 style="margin-bottom: 16px">参数输入</h3>
        <el-form :model="form" label-width="120px">
          <el-form-item label="售价 (ZAR)">
            <el-input-number v-model="form.selling_price_zar" :min="0" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item label="成本 (CNY)">
            <el-input-number v-model="form.cost_cny" :min="0" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item label="重量 (kg)">
            <el-input-number v-model="form.weight_kg" :min="0" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item label="汇率 (ZAR/CNY)">
            <el-input-number v-model="form.fx_rate" :min="0.01" :precision="4" style="width:100%" />
          </el-form-item>
          <el-form-item label="佣金率">
            <el-input-number v-model="form.commission_rate" :min="0" :max="1" :step="0.01" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item label="VAT 税率">
            <el-input-number v-model="form.vat_rate" :min="0" :max="1" :step="0.01" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item label="运费 (CNY/kg)">
            <el-input-number v-model="form.freight_rate" :min="0" :precision="1" style="width:100%" />
          </el-form-item>
          <el-form-item label="目标利润率">
            <el-input-number v-model="form.target_margin" :min="0" :max="1" :step="0.05" :precision="2" style="width:100%" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" @click="calculate" :loading="calculating" style="width:100%">计算利润</el-button>
          </el-form-item>
        </el-form>
      </div>

      <!-- Result -->
      <div class="page-card">
        <h3 style="margin-bottom: 16px">计算结果</h3>
        <template v-if="result">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="售价 (ZAR)">R {{ result.selling_price_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="成本 (ZAR)">R {{ result.cost_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="运费 (ZAR)">R {{ result.freight_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="佣金 (ZAR)">R {{ result.commission_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="VAT (ZAR)">R {{ result.vat_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="总成本 (ZAR)">R {{ result.total_cost_zar?.toFixed(2) }}</el-descriptions-item>
            <el-descriptions-item label="利润 (ZAR)">
              <span :style="{ color: result.profit_zar >= 0 ? '#67c23a' : '#f56c6c', fontWeight: '600', fontSize: '16px' }">
                R {{ result.profit_zar?.toFixed(2) }}
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="利润率">
              <span :style="{ color: result.margin_rate >= 0 ? '#67c23a' : '#f56c6c', fontWeight: '600' }">
                {{ result.margin_rate?.toFixed(2) }}%
              </span>
            </el-descriptions-item>
            <el-descriptions-item label="建议售价 (ZAR)">
              <span style="color: #409eff; font-weight: 600">R {{ result.suggested_price_zar?.toFixed(2) }}</span>
            </el-descriptions-item>
          </el-descriptions>
        </template>
        <el-empty v-else description="点击计算按钮查看结果" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { profitApi } from '@/api'
import type { ProfitResult } from '@/types'

const form = reactive({
  selling_price_zar: 299,
  cost_cny: 35,
  weight_kg: 0.5,
  fx_rate: 0.41,
  commission_rate: 0.15,
  vat_rate: 0.15,
  freight_rate: 79,
  target_margin: 0.25,
})

const result = ref<ProfitResult | null>(null)
const calculating = ref(false)

async function calculate() {
  calculating.value = true
  try {
    const { data } = await profitApi.calculate(form)
    result.value = data
  } finally {
    calculating.value = false
  }
}
</script>
