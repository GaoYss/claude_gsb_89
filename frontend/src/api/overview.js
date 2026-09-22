import { http } from './http'

export function fetchSummary() {
  return http.get('/overview/summary')
}

export function fetchMonthlyRectification(year, month) {
  return http.get('/overview/rectification-monthly', { params: { year, month } })
}

