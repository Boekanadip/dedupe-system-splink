/**
 * Thin API client boundary for the future FastAPI integration.
 * The UI intentionally stays in demo mode until VITE_API_BASE_URL is configured
 * and the matching backend endpoints are implemented and verified.
 */
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export const isApiConfigured = Boolean(API_BASE_URL)

export async function apiRequest(path, options = {}) {
  if (!API_BASE_URL) {
    throw new Error('FastAPI base URL is not configured. The application is currently in demo mode.')
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...options.headers,
    },
  })

  if (!response.ok) {
    const body = await response.text().catch(() => '')
    throw new Error(body || `API request failed with status ${response.status}`)
  }

  if (response.status === 204) return null
  return response.json()
}

// Draft endpoint wrappers. These are integration contracts, not proof that
// equivalent FastAPI routes already exist.
export const platformApi = {
  getHealth: () => apiRequest('/api/health'),
  getDatasets: () => apiRequest('/api/datasets'),
  getModels: () => apiRequest('/api/models'),
  getJobs: () => apiRequest('/api/jobs'),
  createJob: (payload) => apiRequest('/api/jobs', { method: 'POST', body: JSON.stringify(payload) }),
  getJob: (jobId) => apiRequest(`/api/jobs/${encodeURIComponent(jobId)}`),
  getResults: (jobId, params = '') => apiRequest(`/api/jobs/${encodeURIComponent(jobId)}/results${params}`),
}
