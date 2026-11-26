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
  runDedup: (columns, scope = 'sample', datasetId = null) => {
    const query = new URLSearchParams({ scope })
    if (datasetId) query.set('dataset_id', datasetId)
    for (const column of columns || []) query.append('selected_columns', column)
    return apiRequest(`/api/run-dedup?${query}`, { method: 'POST' })
  },

  reload: (scope = 'full') => apiRequest(`/api/reload?scope=${encodeURIComponent(scope)}`, { method: 'POST' }),

  getDatasets: () => apiRequest('/api/datasets'),

  uploadDataset: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest('/api/datasets/upload', { method: 'POST', body: form })
  },

  submitReviewDecision: (id1, id2, decision, scope = 'full', reviewer = 'dashboard', reason = '') =>
    apiRequest(
      `/api/pair/${encodeURIComponent(id1)}/${encodeURIComponent(id2)}/decision?scope=${encodeURIComponent(scope)}`,
      {
        method: 'POST',
        body: JSON.stringify({
          decision,
          reviewer,
          reason,
          request_id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
        }),
      },
    ),

  submitBulkReview: (pairIds, decision, reviewer = 'dashboard', reason = '') =>
    apiRequest('/api/reviews/bulk', {
      method: 'POST',
      body: JSON.stringify({
        pair_ids: pairIds,
        decision,
        reviewer,
        reason,
        request_id: crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`,
      }),
    }),

  getReviewHistory: (page = 1, perPage = 50) =>
    apiRequest(`/api/reviews/history?page=${page}&per_page=${perPage}`),

  getReviewSummary: () => apiRequest('/api/reviews/summary'),

  getWorkspaceSettings: () => apiRequest('/api/settings/workspace'),

  saveWorkspaceSettings: settings => apiRequest('/api/settings/workspace', {
    method: 'PUT',
    body: JSON.stringify(settings),
  }),

  

  createJob: payload => apiRequest('/api/jobs', { method: 'POST', body: JSON.stringify(payload) }),

  getJobs: (page = 1, perPage = 50) => apiRequest(`/api/jobs?page=${page}&per_page=${perPage}`),

  getJob: jobId => apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`),

  downloadUrl: () => target('/api/download'),

  uploadBatch: async (file) => {
    const form = new FormData()
    form.append('file', file)
    return apiRequest('/api/batch-predict', { method: 'POST', body: form })
  },

  // --- Supabase endpoints ---
  getSupabaseStatus: () => apiRequest('/api/supabase/status'),

  getSupabaseTables: () => apiRequest('/api/supabase/tables'),

  getSupabaseDatasets: () => apiRequest('/api/supabase/datasets'),

  getSupabaseTableColumns: (table) =>
    apiRequest(`/api/supabase/tables/${encodeURIComponent(table)}/columns`),

  getSupabaseTablePreview: (table, limit = 25) =>
    apiRequest(`/api/supabase/tables/${encodeURIComponent(table)}/preview?limit=${encodeURIComponent(limit)}`),

  ingestSupabaseTable: (table, limit = 5000) =>
    apiRequest('/api/supabase/ingest', {
      method: 'POST',
      body: JSON.stringify({ table, limit }),
    }),

  getActivityFeed: (limit = 15) =>
    apiRequest(`/api/activity?limit=${encodeURIComponent(limit)}`),

  getModelVersions: () => apiRequest('/api/model/versions'),

  getRetrainLog: (offset = 0) =>
    apiRequest(`/api/model/retrain/log?offset=${offset}`),

  startRetrain: (payload = {}) =>
    apiRequest('/api/model/retrain', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  rollbackModel: (version) =>
    apiRequest('/api/model/rollback', {
      method: 'POST',
      body: JSON.stringify({ version }),
    }),

  getSupabaseEntities: (limit = 50) =>
    apiRequest(`/api/supabase/entities?limit=${encodeURIComponent(limit)}`),

  getSupabaseEntityMembers: (entityId) =>
    apiRequest(`/api/supabase/entities/${encodeURIComponent(entityId)}/members`),

  getSupabaseConflicts: () =>
    apiRequest('/api/supabase/conflicts'),
}

/** Backend pair row -> shape used by the existing review table. */
export function toReviewRow(pair, detail = null) {
  const leftId = pair.record_id_l
  const rightId = pair.record_id_r
  const recordA = detail?.record_a
  const recordB = detail?.record_b
  const probability = Number(detail?.match_probability ?? pair.match_probability)

  return {
    id: `${leftId}__${rightId}`,
    left: leftId,
    right: rightId,
    leftName: [recordA?.first_name, recordA?.last_name].filter(Boolean).join(' ') || leftId,
    rightName: [recordB?.first_name, recordB?.last_name].filter(Boolean).join(' ') || rightId,
    dob: recordA?.dob || '-',
    rightDob: recordB?.dob || '-',
    address: [recordA?.address, recordA?.city, recordA?.state, recordA?.country].filter(Boolean).join(', ') || '-',
    rightAddress: [recordB?.address, recordB?.city, recordB?.state, recordB?.country].filter(Boolean).join(', ') || '-',
    email: recordA?.email || '-',
    rightEmail: recordB?.email || '-',
    city: recordA?.city || '-',
    rightCity: recordB?.city || '-',
    phone: recordA?.phone_number || '-',
    rightPhone: recordB?.phone_number || '-',
    score: Number.isFinite(probability) ? probability : 0,
    decision: detail?.decision ?? pair.decision,
    reason: `Match probability: ${
      Number.isFinite(probability) ? probability.toFixed(4) : 'N/A'
    } · Live Splink evidence`,
  }
}