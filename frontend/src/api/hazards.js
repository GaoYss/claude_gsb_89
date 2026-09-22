import { compact, http } from './http'

export function fetchHazards(params) {
  return http.get('/hazards', { params: compact(params) })
}

export function fetchHazard(id) {
  return http.get(`/hazards/${id}`)
}

export function createHazard(payload) {
  return http.post('/hazards', payload)
}

export function updateHazard(id, payload) {
  return http.put(`/hazards/${id}`, payload)
}

export function deleteHazard(id) {
  return http.delete(`/hazards/${id}`)
}

export function addRectification(id, payload) {
  return http.post(`/hazards/${id}/rectifications`, payload)
}

export function transitionHazard(id, payload) {
  return http.post(`/hazards/${id}/transition`, payload)
}

export function applyReopen(id, payload) {
  return http.post(`/hazards/${id}/reopen`, payload)
}

export function reviewReopen(reopenId, payload) {
  return http.post(`/hazards/reopens/${reopenId}/review`, payload)
}

export function fetchReopens(params) {
  return http.get('/hazards/reopens', { params: compact(params) })
}
