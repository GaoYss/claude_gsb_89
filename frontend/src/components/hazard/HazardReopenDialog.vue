<script setup>
import { reactive, ref, watch } from 'vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  hazardCode: { type: String, default: '' },
  hazardTitle: { type: String, default: '' },
  assignee: { type: String, default: '' },
  submitting: { type: Boolean, default: false },
})

const emit = defineEmits(['close', 'submit'])

const form = reactive({
  reason: '',
  basis: '',
  operator: '',
  deadline: '',
  confirmed: false,
})
const error = ref('')

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      form.reason = ''
      form.basis = ''
      form.operator = props.assignee || ''
      form.deadline = ''
      form.confirmed = false
      error.value = ''
    }
  },
)

function cancel() {
  emit('close')
}

function submit() {
  if (form.reason.trim().length < 2) {
    error.value = '请填写重启原因（同类问题再次出现的情况说明）'
    return
  }
  if (form.basis.trim().length < 2) {
    error.value = '请填写重启依据（如巡查记录、现场复核、上级要求等）'
    return
  }
  if (!form.confirmed) {
    error.value = '请勾选确认后再提交重启申请'
    return
  }
  error.value = ''
  emit('submit', {
    reason: form.reason.trim(),
    basis: form.basis.trim(),
    operator: form.operator.trim() || null,
    deadline: form.deadline || null,
    confirmed: true,
  })
}
</script>

<template>
  <div v-if="visible" class="modal-mask" @click.self="cancel">
    <div class="modal modal-wide" role="dialog" aria-modal="true">
      <div class="modal-header">申请重启已销号隐患</div>
      <div class="modal-body">
        <p class="muted" style="margin-top: 0">
          隐患「<strong>{{ hazardTitle }}</strong
          >」（{{ hazardCode }}）已销号。重启后将基于原隐患单进入新一轮整改流程，
          原有整改流水全部保留，该隐患在统计中不再计入已销号。
        </p>
        <div class="form-grid">
          <div class="field span-2">
            <label>重启原因 <span class="required">*</span></label>
            <textarea
              v-model="form.reason"
              class="textarea"
              rows="3"
              placeholder="说明同类问题再次出现的位置、现象、范围等"
            />
          </div>
          <div class="field span-2">
            <label>重启依据 <span class="required">*</span></label>
            <textarea
              v-model="form.basis"
              class="textarea"
              rows="3"
              placeholder="如：巡查记录编号、现场复核照片、上级检查通报等"
            />
          </div>
          <div class="field">
            <label>申请人</label>
            <input v-model="form.operator" class="input" placeholder="例如 王海涛" />
          </div>
          <div class="field">
            <label>本轮整改期限</label>
            <input v-model="form.deadline" type="date" class="input" />
          </div>
          <div class="field span-2">
            <label class="checkbox-label">
              <input v-model="form.confirmed" type="checkbox" />
              <span>
                我已确认同类问题确实再次出现，重启依据真实有效，同意重新进入整改流程
              </span>
            </label>
          </div>
        </div>
        <p v-if="error" class="muted" style="color: var(--danger); margin: 8px 0 0">
          {{ error }}
        </p>
      </div>
      <div class="modal-footer">
        <button class="btn" :disabled="submitting" @click="cancel">取消</button>
        <button class="btn btn-primary" :disabled="submitting" @click="submit">
          {{ submitting ? '提交中…' : '确认重启' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.modal-wide {
  max-width: 640px;
}

.checkbox-label {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-weight: normal;
  cursor: pointer;
}

.checkbox-label input[type='checkbox'] {
  margin-top: 4px;
}
</style>
