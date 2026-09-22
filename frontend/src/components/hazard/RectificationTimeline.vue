<script setup>
import { computed } from 'vue'

import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { formatDate, formatDateTime } from '@/utils/format'

const props = defineProps({
  records: { type: Array, default: () => [] },
  cycles: { type: Array, default: () => [] },
})

const cycleMap = computed(() => {
  const map = new Map()
  for (const cycle of props.cycles) {
    map.set(cycle.seq, cycle)
  }
  return map
})

// 按轮次分组（倒序：最新一轮在最上），轮次内按时间正序
const groups = computed(() => {
  const seqs = [...new Set(props.records.map((record) => record.cycle_seq || 1))]
  return seqs
    .slice()
    .sort((a, b) => b - a)
    .map((seq) => ({
      seq,
      cycle: cycleMap.value.get(seq),
      records: props.records
        .filter((record) => (record.cycle_seq || 1) === seq)
        .slice()
        .sort((a, b) => new Date(a.recorded_at) - new Date(b.recorded_at)),
    }))
})
</script>

<template>
  <EmptyState v-if="!records.length" title="暂无整改跟踪记录" />
  <div v-else class="cycle-list">
    <section v-for="group in groups" :key="group.seq" class="cycle-group">
      <header class="cycle-head">
        <span class="cycle-title" :class="{ reopen: group.seq > 1 }">
          {{ group.seq === 1 ? '首轮整改' : `第 ${group.seq} 轮整改（重启）` }}
        </span>
        <span v-if="group.cycle" class="timeline-meta">
          {{ formatDate(group.cycle.started_on) }}
          <template v-if="group.cycle.closed_on">
            → {{ formatDate(group.cycle.closed_on) }}
          </template>
          <template v-else>起 · 在办中</template>
        </span>
        <StatusTag
          v-if="group.cycle && group.cycle.closed_on"
          kind="hazard_status"
          value="closed"
        />
        <span v-else-if="group.cycle" class="tag tag-warn">在办</span>
      </header>
      <div v-if="group.cycle && group.cycle.is_reopen" class="cycle-reopen">
        <div><span class="muted">重启原因：</span>{{ group.cycle.reopen_reason }}</div>
        <div><span class="muted">重启依据：</span>{{ group.cycle.reopen_basis }}</div>
      </div>
      <ol class="timeline">
        <li v-for="record in group.records" :key="record.id" class="timeline-item">
          <div class="timeline-head">
            <StatusTag kind="rectification_action" :value="record.action" />
            <span class="timeline-meta">{{ formatDateTime(record.recorded_at) }}</span>
            <span v-if="record.operator" class="timeline-meta">· {{ record.operator }}</span>
            <span v-if="record.status_from || record.status_to" class="row-gap">
              <StatusTag v-if="record.status_from" kind="hazard_status" :value="record.status_from" />
              <span class="timeline-meta">→</span>
              <StatusTag v-if="record.status_to" kind="hazard_status" :value="record.status_to" />
            </span>
          </div>
          <div class="timeline-body">{{ record.content }}</div>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.cycle-group + .cycle-group {
  margin-top: 18px;
  padding-top: 14px;
  border-top: 1px dashed var(--border-color, #e2e6ee);
}

.cycle-head {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}

.cycle-title {
  font-weight: 600;
  color: var(--text-regular, #4a5568);
}

.cycle-title.reopen {
  color: var(--warning, #c07c1d);
}

.cycle-reopen {
  background: var(--warning-bg, #fdf6ec);
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 10px;
  font-size: 13px;
  line-height: 1.7;
}
</style>
