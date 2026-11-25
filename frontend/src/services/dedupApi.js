/**
 * Bridge tipis antara UI dan endpoint FastAPI (api/app.py).
 * Semua request lewat proxy Vite; VITE_API_BASE_URL kosong = pakai proxy.
 */
const API_BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
  })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(body || `HTTP ${res.status}`)
  }
  if (res.status === 204) return null
  return res.json()
}

// GET wrappers
export const getHealth = () => request('/health')
export const getStats = () => request('/api/stats')
export const getPairs = (page = 1, perPage = 50, status = 'REVIEW') =>
  request(`/api/pairs?page=${page}&per_page=${perPage}&status=${status}`)
export const getModelInfo = () => request('/api/model/info')

// POST wrappers
export const runDedup = (selectedColumns = [], scope = 'sample') => {
  const params = new URLSearchParams({ scope })
  selectedColumns.forEach(c => params.append('selected_columns', c))
  return request(`/api/run-dedup?${params}`, { method: 'POST' })
}
export const reload = () => request('/api/reload', { method: 'POST' })

// Download
export const downloadCsv = () => {
  const url = `${API_BASE}/api/download`
  const link = document.createElement('a')
  link.href = url
  link.download = 'splink_predictions.csv'
  link.click()
}

/**
 * Ubah satu baris dari /api/pairs jadi bentuk yang dikenali oleh review UI.
 * Atribut sumber (email/city/phone) tidak tersedia di backend → '—'
 */
export function toReviewRow(p, index = 0) {
  const id = `PAIR-${p.record_id_l}-${p.record_id_r}`
  const score = Number(p.match_probability ?? 0)
  const reason = [
    score >= 0.90 ? 'High probability' : score >= 0.75 ? 'Moderate probability' : 'Low probability',
    p.decision === 'MATCH' ? 'Auto-match' : p.decision === 'REVIEW' ? 'Needs review' : '',
  ].filter(Boolean).join(' · ')
  return {
    id,
    left: p.record_id_l,
    right: p.record_id_r,
    email: '—',
    rightEmail: '—',
    city: '—',
    rightCity: '—',
    phone: '—',
    rightPhone: '—',
    score,
    decision: p.decision,
    reason: reason || 'Score-based decision',
    _index: index,
  }
}
