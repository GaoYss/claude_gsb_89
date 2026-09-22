<script setup>
import { onMounted, ref } from 'vue'

import {
  fetchMonthlyReports,
  fetchRectificationStats,
  generateMonthlyReport,
} from '@/api/stats'
import { fetchReopens as fetchReopenList } from '@/api/hazards'
import BaseCard from '@/components/common/BaseCard.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import StatCard from '@/components/common/StatCard.vue'
import StatusTag from '@/components/common/StatusTag.vue'
import { useToastStore } from '@/stores/toast'
import { formatDateTime, todayString } from '@/utils/format'

const toast = useToastStore()

const stats = ref(null)
const reports = ref([])
const pendingReopens = ref([])
const loading = ref(true)
const generating = ref(false)

const selectedPeriod = ref(todayString().slice(0, 7))
const generatedBy = ref('')
const overwrite = ref(false)
const viewing = ref(null)

function percent(value) {
  const number = Number(value || 0) * 100
  return `${number.toFixed(1)}%`
}

function daysText(value) {
  if (value === null || value === undefined) return '—'
  return `${Number(value).toFixed(1)} 天`
}

async function load() {
  loading.value = true
  try {
    const [statsData, reportsData, reopensData] = await Promise.all([
      fetchRectificationStats(),
      fetchMonthlyReports(),
      fetchReopenList({ status: 'pending', page_size: 50 }),
    ])
    stats.value = statsData
    reports.value = reportsData
    pendingReopens.value = reopensData.items || []
  } catch (error) {
    toast.error(error.message)
  } finally {
    loading.value = false
  }
}

onMounted(load)

async function generate() {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(selectedPeriod.value)) {
    toast.error('月份格式应为 YYYY-MM')
    return
  }
  generating.value = true
  try {
    const report = await generateMonthlyReport({
      period: selectedPeriod.value,
      generated_by: generatedBy.value.trim() || null,
      overwrite: overwrite.value,
    })
    viewing.value = report
    overwrite.value = false
    toast.success(`${selectedPeriod.value} 月报已生成（快照已固化）`)
    await load()
    viewing.value = reports.value.find((item) => item.period === selectedPeriod.value) || report
  } catch (error) {
    toast.error(error.message)
  } finally {
    generating.value = false
  }
}

function viewReport(report) {
  viewing.value = report
}
</script>

<template>
  <div v-if="loading" class="muted">加载中…</div>
  <div v-else>
    <PageHeader
      title="整改统计与月报"
      description="办理时长与闭环率按整改轮次分开统计；月报为生成时刻的固化快照，隐患重启不会改写已出月报。"
    />

    <!-- 重启待办 -->
    <BaseCard title="重启申请待办" :subtitle="`${pendingReopens.length} 条待确认`">
      <div v-if="pendingReopens.length" class="row-gap" style="flex-direction: column; gap: 10px">
        <div
          v-for="item in pendingReopens"
          :key="item.id"
          class="row-gap"
          style="justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--border, #eee)"
        >
          <div>
            <RouterLink class="btn-link" :to="`/hazards/${item.hazard_id}`">
              {{ item.hazard?.title || `隐患 #${item.hazard_id}` }}
            </RouterLink>
            <div class="muted" style="font-size: 13px">{{ item.reason }}</div>
          </div>
          <div class="row-gap" style="align-items: center; gap: 8px">
            <StatusTag kind="reopen_status" :value="item.status" />
            <span class="muted">{{ formatDateTime(item.applied_at) }}</span>
          </div>
        </div>
      </div>
      <EmptyState v-else title="暂无待确认的重启申请" />
    </BaseCard>

    <!-- 轮次统计 -->
    <div v-if="stats" class="stat-grid" style="margin-top: 16px">
      <StatCard
        label="首轮闭环率（重启前）"
        :value="percent(stats.first_round.closure_rate)"
        :hint="`${stats.first_round.closed_current}/${stats.first_round.entered} 仍闭环，平均办理 ${daysText(stats.first_round.avg_handling_days)}`"
        tone="ok"
      />
      <StatCard
        label="首轮销号后重启"
        :value="stats.first_round.reopened_after_close"
        :hint="`共 ${stats.first_round.closed_cycles} 次首轮销号`"
        tone="warn"
      />
      <StatCard
        label="重启后闭环率"
        :value="percent(stats.reopened_round.closure_rate)"
        :hint="`${stats.reopened_round.closed_current}/${stats.reopened_round.entered} 已再次销号，平均办理 ${daysText(stats.reopened_round.avg_handling_days)}`"
        tone="accent"
      />
      <StatCard
        label="重启后整改中"
        :value="stats.reopened_round.in_progress"
        hint="基于原隐患重新发起的整改任务"
      />
    </div>

    <BaseCard v-if="stats" title="分轮次明细" subtitle="重启前后的办理时长与闭环率分别计算" style="margin-top: 16px">
      <div class="table-wrap">
        <table class="data-table">
          <thead>
            <tr>
              <th>轮次</th>
              <th>进入整改</th>
              <th>整改中</th>
              <th>当前闭环</th>
              <th>曾销号</th>
              <th>销号后重启</th>
              <th>闭环率</th>
              <th>平均办理时长</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in stats.round_detail" :key="item.scope + item.label">
              <td>{{ item.label }}</td>
              <td>{{ item.entered }}</td>
              <td>{{ item.in_progress }}</td>
              <td>{{ item.closed_current }}</td>
              <td>{{ item.closed_cycles }}</td>
              <td>{{ item.reopened_after_close }}</td>
              <td>{{ percent(item.closure_rate) }}</td>
              <td>{{ daysText(item.avg_handling_days) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </BaseCard>

    <div class="split-2" style="margin-top: 16px">
      <!-- 月报生成 -->
      <BaseCard title="生成月报" subtitle="统计口径以生成时刻为准并固化保存">
        <div class="field">
          <label>所属月份</label>
          <input v-model="selectedPeriod" type="month" class="input" style="max-width: 200px" />
        </div>
        <div class="field" style="margin-top: 10px">
          <label>生成人</label>
          <input v-model="generatedBy" class="input" style="max-width: 200px" placeholder="可选" />
        </div>
        <div class="field row-gap" style="margin-top: 10px; gap: 6px">
          <input v-model="overwrite" type="checkbox" id="overwrite" />
          <label for="overwrite" class="muted">同期月报已存在时覆盖重算（历史月报默认不允许改写）</label>
        </div>
        <div class="form-actions" style="margin-top: 12px">
          <button class="btn btn-primary" type="button" :disabled="generating" @click="generate">
            {{ generating ? '生成中…' : '生成月报快照' }}
          </button>
        </div>
      </BaseCard>

      <!-- 月报列表 -->
      <BaseCard title="已生成月报" subtitle="点击查看固化快照内容">
        <div v-if="reports.length" style="display: flex; flex-direction: column; gap: 8px">
          <button
            v-for="report in reports"
            :key="report.period"
            class="btn"
            type="button"
            style="justify-content: space-between; display: flex"
            @click="viewReport(report)"
          >
            <span>{{ report.period }} 月报</span>
            <span class="muted" style="font-size: 12px">{{ formatDateTime(report.generated_at) }}</span>
          </button>
        </div>
        <EmptyState v-else title="暂无月报" description="选择月份后生成第一期月报快照" />
      </BaseCard>
    </div>

    <!-- 月报快照详情 -->
    <BaseCard
      v-if="viewing"
      :title="`${viewing.period} 月报（固化快照）`"
      :subtitle="`生成于 ${formatDateTime(viewing.generated_at)}${viewing.generated_by ? ' · ' + viewing.generated_by : ''}`"
      style="margin-top: 16px"
    >
      <template #actions>
        <button class="btn btn-sm" type="button" @click="viewing = null">关闭</button>
      </template>
      <div class="stat-grid">
        <StatCard label="隐患总数" :value="viewing.data.hazard_total" />
        <StatCard label="未销号" :value="viewing.data.hazard_open" :hint="`其中重启后整改 ${viewing.data.hazard_reopened} 条`" />
        <StatCard label="已销号" :value="viewing.data.hazard_closed" hint="重启后的隐患不计入" />
        <StatCard label="逾期未整改" :value="viewing.data.hazard_overdue" />
        <StatCard label="本月新登记" :value="viewing.data.registered_this_month" />
        <StatCard label="本月销号（轮次）" :value="viewing.data.closed_this_month" />
        <StatCard label="本月确认重启" :value="viewing.data.reopened_this_month" />
      </div>
      <p v-if="viewing.remark" class="muted" style="margin-top: 12px">备注：{{ viewing.remark }}</p>
      <p class="muted" style="margin-top: 12px; font-size: 12px">
        本快照生成后不再随隐患状态变化；如需按当前口径重算，请在左侧勾选「覆盖重算」。
      </p>
    </BaseCard>
  </div>
</template>
