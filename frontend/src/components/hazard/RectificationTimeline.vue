<script setup>
import { computed } from 'vue'

import StatusTag from '@/components/common/StatusTag.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { formatDateTime } from '@/utils/format'

const props = defineProps({
  records: { type: Array, default: () => [] },
})

// 存在重启流水时，按轮次在时间轴上分组
const maxRound = computed(() =>
  props.records.reduce((max, item) => Math.max(max, item.round_no || 1), 1),
)

const groups = computed(() => {
  if (maxRound.value <= 1) return [{ round_no: 1, records: props.records }]
  const result = []
  for (let round = 1; round <= maxRound.value; round += 1) {
    const records = props.records.filter((item) => (item.round_no || 1) === round)
    if (records.length) result.push({ round_no: round, records })
  }
  return result
})
</script>

<template>
  <EmptyState v-if="!records.length" title="暂无整改跟踪记录" />
  <template v-else>
    <div v-for="group in groups" :key="group.round_no" class="timeline-round">
      <div v-if="maxRound > 1" class="timeline-round-head">
        <span class="tag" :class="group.round_no === 1 ? 'tag-muted' : 'tag-accent'">
          {{ group.round_no === 1 ? '首轮整改（重启前）' : `第 ${group.round_no} 轮整改（重启后）` }}
        </span>
      </div>
      <ol class="timeline">
        <li
          v-for="record in group.records"
          :key="record.id"
          class="timeline-item"
          :class="{ 'timeline-item-reopen': record.action === 'reopen' }"
        >
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
    </div>
  </template>
</template>
