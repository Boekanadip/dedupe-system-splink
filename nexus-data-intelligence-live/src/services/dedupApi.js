/**
 * Bridge from the Nexus platform UI to the Splink FastAPI service.
 *
 * Empty VITE_API_BASE_URL means "use the Vite proxy": requests go to /api/*
 * on the dev server and Vite forwards them to http://localhost:8000.
 */
const BASE = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

function target(path) {
  return `${BASE}${path}`
}

async function apiRequest(path, options = {}) {
  const response = await fetch(target(path), {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
  })

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw new Error(payload?.detail || payload?.message || `HTTP ${response.status}`)
  }
  return response.status === 204 ? null : response.json()
}

export const dedupApi = {
  getHealth: () => apiRequest('/health'),

  getStats: () => apiRequest('/api/stats'),

  getModelInfo: () => apiRequest('/api/model/info'),

  getPairs: (page = 1, perPage = 50, status) => {
    const query = new URLSearchParams({ page: String(page), per_page: String(perPage) })
    if (status) query.set('status', status)
    return apiRequest(`/api/pairs?${query}`)
  },

  search: (q) => apiRequest(`/api/search?q=${encodeURIComponent(q)}`),

  getPairDetail: (id1, id2) =>
    apiRequest(`/api/pair/${encodeURIComponent(id1)}/${encodeURIComponent(id2)}`),

  // selected_columns is a repeated query param in api/app.py, not a JSON body.
  runDedup: (columns, scope = 'sample') => {
    const query = new URLSearchParams({ scope })
    for (const column of columns || []) query.append('selected_columns', column)
    return apiRequest(`/api/run-dedup?${query}`, { method: 'POST' })
  },

  reload: () => apiRequest('/api/reload', { method: 'POST' }),

  downloadUrl: () => target('/api/download'),

  uploadBatch: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest('/api/batch-predict', { method: 'POST', body: form })
  },
}

/** Backend pair row -> shape used by the existing review table. */
export function toReviewRow(pair) {
  const id = `${pair.record_id_l}__${pair.record_id_r}`
  return {
    id,
    left: pair.record_id_l,
    right: pair.record_id_r,
    email: '—',
    rightEmail: '—',
    city: '—',
    rightCity: '—',
    phone: '—',
    rightPhone: '—',
    score: pair.match_probability,
    decision: pair.decision,
    reason: `match_probability ${Number(pair.match_probability).toFixed(4)} · atribut record belum tersedia di endpoint`,
  }
}
