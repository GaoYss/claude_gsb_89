<script setup>
import { computed, reactive, ref, watch } from 'vue'

import StatusTag from '@/components/common/StatusTag.vue'
import { formatDate, formatDateTime } from '@/utils/format'

const props = defineProps({
  hazard: { type: Object, required: true },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['applied', 'reviewed'])

const applying = ref(false)
const applyForm = reactive({ reason: '', applicant: props.hazard.discoverer || '' })
const applyError = ref('')

watch(
  () => props.hazard?.id,
  () => {
    applying.value = false
    applyForm.reason = ''
    applyForm.applicant = props.hazard?.discoverer || ''
  },
)

const pendingRequest = computed(
  () => (props.hazard.reopen_requests || []).find((item) => item.status === 'pending') || null,
)
const history = computed(() =>
  [...(props.hazard.reopen_requests || [])].sort((a, b) => b.id - a.id),
)

const reviewForm = reactive({
  decision: 'confirmed',
  evidence: '',
  confirmer: '',
  review_comment: '',
  deadline: '',
})
const reviewError = ref('')

function startApply() {
  applying.value = true
  applyError.value = ''
}

function cancelApply() {
  applying.value = false
  applyError.value = ''
}

function submitApply() {
  if (applyForm.reason.trim().length < 5) {
    applyError.value = '请填写重启原因（不少于 5 个字），说明同类问题再次出现的情况'
    return
  }
  emit('applied', {
    reason: applyForm.reason.trim(),
    applicant: applyForm.applicant.trim() || null,
  })
}

function submitReview() {
  reviewError.value = ''
  if (reviewForm.decision === 'confirmed' && reviewForm.evidence.trim().length < 5) {
    reviewError.value = '确认重启必须填写重启依据（现场复核情况 / 佐证材料）'
    return
  }
  emit('reviewed', {
    reopen_id: pendingRequest.value.id,
    payload: {
      decision: reviewForm.decision,
      evidence: reviewForm.decision === 'confirmed' ? reviewForm.evidence.trim() : null,
      confirmer: reviewForm.confirmer.trim() || null,
      review_comment: reviewForm.review_comment.trim() || null,
      deadline: reviewForm.decision || null,
    },
  })
}
</script>

<template>
  <section class="card">
    <header class="card-header">
      <div>
        <div class="card-title">销号重启</div>
        <div class="card-subtitle">
          同类问题再次出现时，可基于原隐患重新进入整改流程，原整改流水保留
        </div>
      </div>
    </header>
    <div class="card-body">
      <!-- 已销号且无待确认申请：发起申请 -->
      <template v-if="hazard.status === 'closed' && !pendingRequest">
        <form v-if="applying" @submit.prevent="submitApply">
          <div class="field">
            <label>申请人</label>
            <input v-model="applyForm.applicant" class="input" placeholder="例如 张三" />
          </div>
          <div class="field" style="margin-top: 10px">
            <label>重启原因 <span class="required">*</span></label>
            <textarea
              v-model="applyForm.reason"
              class="textarea"
              placeholder="说明同类问题再次出现的部位、现象、发现时间等"
            />
          </div>
          <p v-if="applyError" class="muted" style="color: var(--danger); margin: 8px 0 0">
            {{ applyError }}
          </p>
          <div class="form-actions">
            <button class="btn btn-primary" type="submit" :disabled="submitting">
              {{ submitting ? '提交中…' : '提交重启申请' }}
            </button>
            <button class="btn" type="button" :disabled="submitting" @click="cancelApply">取消</button>
            <span class="muted" style="align-self: center">提交后需主管确认并填写依据才会生效</span>
          </div>
        </form>
        <div v-else class="row-gap">
          <p class="muted" style="margin: 0 0 10px">
            该隐患已销号。如原位置同类问题再次出现，可申请重启，进入新一轮整改。
          </p>
          <button class="btn" type="button" @click="startApply">申请重启</button>
        </div>
      </template>

      <!-- 待确认：确认 / 驳回 -->
      <form v-else-if="pendingRequest" @submit.prevent="submitReview">
        <div class="row-gap" style="margin-bottom: 10px">
          <StatusTag kind="reopen_status" value="pending" />
          <span class="muted">{{ formatDateTime(pendingRequest.applied_at) }} 发起</span>
        </div>
        <dl class="def-list">
          <div class="def-item full">
            <dt>重启原因</dt>
            <dd>{{ pendingRequest.reason }}</dd>
          </div>
          <div class="def-item">
            <dt>申请人</dt>
            <dd>{{ pendingRequest.applicant || '—' }}</dd>
          </div>
          <div class="def-item">
            <dt>原销号日期</dt>
            <dd>{{ formatDate(pendingRequest.previous_closed_on) }}</dd>
          </div>
        </dl>

        <div class="field" style="margin-top: 8px">
          <label>确认意见</label>
          <div class="row-gap">
            <label class="row-gap" style="gap: 6px">
              <input v-model="reviewForm.decision" type="radio" value="confirmed" />
              确认重启
            </label>
            <label class="row-gap" style="gap: 6px">
              <input v-model="reviewForm.decision" type="radio" value="rejected" />
              驳回申请
            </label>
          </div>
        </div>
        <div v-if="reviewForm.decision === 'confirmed'" class="field" style="margin-top: 10px">
          <label>重启依据 <span class="required">*</span></label>
          <textarea
            v-model="reviewForm.evidence"
            class="textarea"
            placeholder="现场复核情况、佐证材料（照片 / 检测记录等）"
          />
          <div class="field" style="margin-top: 10px">
            <label>新一轮整改期限（可选）</label>
            <input v-model="reviewForm.deadline" type="date" class="input" style="max-width: 200px" />
          </div>
        </div>
        <div class="field" style="margin-top: 10px">
          <label>确认人</label>
          <input v-model="reviewForm.confirmer" class="input" style="max-width: 200px" placeholder="例如 王科长" />
        </div>
        <div class="field" style="margin-top: 10px">
          <label>备注意见</label>
          <textarea
            v-model="reviewForm.review_comment"
            class="textarea"
            :placeholder="reviewForm.decision === 'confirmed' ? '同意重启的补充意见' : '驳回原因（如非原问题复发）'"
          />
        </div>
        <p v-if="reviewError" class="muted" style="color: var(--danger); margin: 8px 0 0">
          {{ reviewError }}
        </p>
        <div class="form-actions">
          <button class="btn btn-primary" type="submit" :disabled="submitting">
            {{ submitting ? '处理中…' : '提交确认' }}
          </button>
        </div>
      </form>

      <!-- 非已销号（重启后整改中）且无待处理申请 -->
      <p v-else class="muted" style="margin: 0">
        该隐患已重启，当前正在第 {{ (hazard.reopen_count || 0) + 1 }} 轮整改中。
      </p>

      <!-- 历史申请 -->
      <div v-if="history.length" style="margin-top: 14px">
        <div class="card-subtitle" style="margin-bottom: 8px">重启记录</div>
        <ul class="timeline" style="margin: 0">
          <li v-for="item in history" :key="item.id" class="timeline-item">
            <div class="timeline-head">
              <StatusTag kind="reopen_status" :value="item.status" />
              <span class="timeline-meta">第 {{ item.round_no }} 轮</span>
              <span class="timeline-meta">{{ formatDateTime(item.confirmed_at || item.applied_at) }}</span>
            </div>
            <div class="timeline-body">
              <div>重启原因：{{ item.reason }}</div>
              <div v-if="item.evidence">重启依据：{{ item.evidence }}</div>
              <div v-if="item.review_comment">意见：{{ item.review_comment }}</div>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>
