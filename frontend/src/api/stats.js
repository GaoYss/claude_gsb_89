import { http } from './http'

/** 重启前后分开的整改轮次统计（办理时长 / 闭环率） */
export function fetchRectificationStats() {
  return http.get('/stats/rectification')
}

/** 已生成的月报列表（快照） */
export function fetchMonthlyReports() {
  return http.get('/stats/monthly-reports')
}

export function fetchMonthlyReport(period) {
  return http.get(`/stats/monthly-reports/${period}`)
}

/** 生成月报快照；overwrite=true 时显式覆盖同期月报 */
export function generateMonthlyReport(payload) {
  return http.post('/stats/monthly-reports', payload)
}
