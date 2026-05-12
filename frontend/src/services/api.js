import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || '/api'

const api = axios.create({ baseURL: BASE, timeout: 30000 })

// Chat
export const sendMessage = (data) => api.post('/chat/message', data)
export const getConversation = (id) => api.get(`/chat/conversation/${id}`)

// SOPs
export const listSops = (params) => api.get('/sops/', { params })
export const getSop = (id) => api.get(`/sops/${id}`)
export const getParsedSop = (id) => api.get(`/sops/${id}/parsed`)
export const uploadSop = (file, autoPublish = false) => {
  const fd = new FormData()
  fd.append('file', file)
  return api.post(`/sops/upload?auto_publish=${autoPublish}`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const publishSop = (id) => api.post(`/sops/${id}/publish`)
export const unpublishSop = (id) => api.post(`/sops/${id}/unpublish`)
export const deleteSop = (id) => api.delete(`/sops/${id}`)
export const searchSops = (data) => api.post('/sops/search', data)

// Escalations
export const listEscalations = (params) => api.get('/escalations/', { params })
export const getEscalation = (id) => api.get(`/escalations/${id}`)
export const updateEscalationStatus = (id, status) =>
  api.patch(`/escalations/${id}/status?status=${status}`)

// Analytics
export const getAnalytics = () => api.get('/analytics/summary')

// Admin
export const listConversations = (params) => api.get('/admin/conversations', { params })
export const getConversationEvents = (id) => api.get(`/admin/conversations/${id}/events`)
export const listProducts = () => api.get('/admin/products')
