<script setup>
import { onMounted, ref } from 'vue'

import BaseCard from '@/components/common/BaseCard.vue'
import { fetchMonthlyRectification } from '@/api/overview'
import { useToastStore } from '@/stores/toast'

const props = defineProps({
  stats: { type: Object, required: true },
})

const toast = useToastStore()

function percent(value) {
  return `${Math.round((value ?? 0) * 100)}%`
}

function days(value) {
  return value === null || value === undefined ? '—' : `${value} 天`
}

const now = new Date()
const monthInput = ref(`${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`)
const monthly = ref(null)

async function loadMonthly() {
  const [year, month] = monthInput.value.split('-').map(Number)
  if (!year || !month) return
  try {
    monthly.value = await fetchMonthlyRectification(year, month)
  } catch (error) {
    toast.error(error.message)
  }
}

onMounted(loadMonthly)
</script>

<template>
  <BaseCard
    title="整改闭环统计"
    subtitle="办理时长与闭环率按整改轮次分别统计；重启不改写历史月报"
  >
    <div class="cohort-table">
      <div class="cohort-row cohort-head">
        <span>轮次</span>
        <span>任务数</span>
        <span>已闭环</span>
        <span>在办</span>
        <span>闭环率</span>
        <span>平均办理时长</span>
      </div>
      <div class="cohort-row">
        <span>首轮整改（重启前）</span>
        <span>{{ stats.first.total }}</span>
        <span>{{ stats.first.closed }}</span>
        <span>{{ stats.first.open }}</span>
        <span>{{ percent(stats.first.closure_rate) }}</span>
        <span>{{ days(stats.first.avg_handling_days) }}</span>
      </div>
      <div class="cohort-row reopen">
        <span>重启后的整改</span>
        <span>{{ stats.reopened.total }}</span>
        <span>{{ stats.reopened.closed }}</span>
        <span>{{ stats.reopened.open }}</span>
        <span>{{ percent(stats.reopened.closure_rate) }}</span>
        <span>{{ days(stats.reopened.avg_handling_days) }}</span>
      </div>
    </div>
    <p class="muted" style="margin: 10px 0 0">曾被重启的隐患：{{ stats.reopen_hazard_count }} 条</p>

    <div class="monthly">
      <div class="monthly-head">
        <strong>整改月报</strong>
        <div class="row-gap">
          <input v-model="monthInput" type="month" class="input" @change="loadMonthly" />
          <button class="btn btn-sm" type="button" @click="loadMonthly">查询</button>
        </div>
      </div>
      <p class="muted" style="margin: 6px 0 10px">
        月报按截至所选月末的快照统计，后续重启不会改写已出月报。
      </p>
      <div v-if="monthly" class="cohort-table">
        <div class="cohort-row cohort-head">
          <span>轮次</span>
          <span>月末任务数</span>
          <span>已闭环</span>
          <span>当月新开</span>
          <span>当月销号</span>
          <span>闭环率</span>
        </div>
        <div class="cohort-row">
          <span>首轮整改</span>
          <span>{{ monthly.first.total }}</span>
          <span>{{ monthly.first.closed }}</span>
          <span>{{ monthly.first.started_in_period }}</span>
          <span>{{ monthly.first.closed_in_period }}</span>
          <span>{{ percent(monthly.first.closure_rate) }}</span>
        </div>
        <div class="cohort-row reopen">
          <span>重启后的整改</span>
          <span>{{ monthly.reopened.total }}</span>
          <span>{{ monthly.reopened.closed }}</span>
          <span>{{ monthly.reopened.started_in_period }}</span>
          <span>{{ monthly.reopened.closed_in_period }}</span>
          <span>{{ percent(monthly.reopened.closure_rate) }}</span>
        </div>
      </div>
    </div>
  </BaseCard>
</template>

<style scoped>
.cohort-table {
  display: flex;
  flex-direction: column;
}

.cohort-row {
  display: grid;
  grid-template-columns: 1.6fr repeat(5, 1fr);
  gap: 8px;
  padding: 8px 4px;
  align-items: center;
  border-bottom: 1px solid var(--border-color, #e2e6ee);
  font-size: 14px;
}

.cohort-row:last-child {
  border-bottom: none;
}

.cohort-head {
  font-weight: 600;
  color: var(--text-secondary, #6b7280);
  font-size: 13px;
}

.cohort-row.reopen {
  color: var(--warning, #c07c1d);
}

.monthly {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px dashed var(--border-color, #e2e6ee);
}

.monthly-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.monthly-head .input {
  max-width: 150px;
}
</style>
