import axios from 'axios'
import type { ContentDashboard, Project, ProjectDetail, Task, TrafficData, TrafficOverviewItem } from './types'

export const TOKEN_STORAGE_KEY = 'helm_access_token'

export const api = axios.create({ baseURL: '/api' })

/** Fired when the server rejects the stored token (expired or revoked), so the app can sign the user out. */
export const UNAUTHORIZED_EVENT = 'helm:unauthorized'
const PUBLIC_AUTH_PATHS = ['/auth/login', '/auth/demo-login']

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  // Sign-in requests never carry a (possibly stale) token.
  if (token && !PUBLIC_AUTH_PATHS.includes(config.url ?? '')) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

api.interceptors.response.use(undefined, (error) => {
  const sentToken = Boolean(error?.config?.headers?.Authorization)
  if (axios.isAxiosError(error) && error.response?.status === 401 && sentToken) {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
  }
  return Promise.reject(error)
})

/** A sentence for the sign-in form that says what actually went wrong. */
export function signInErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return 'Cannot reach Helm. Check your connection and try again.'
    const { status, data } = error.response
    if (status === 429) return typeof data?.detail === 'string' ? data.detail : 'Too many attempts. Wait a few minutes and try again.'
    if (status >= 500) return 'Helm had a problem on its side. Try again in a moment.'
  }
  return fallback
}

export async function login(email: string, password: string): Promise<string> {
  const body = new URLSearchParams({ username: email, password })
  const resp = await api.post<{ access_token: string }>('/auth/login', body, {
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
  })
  return resp.data.access_token
}

export async function fetchMe(): Promise<{ email: string; is_demo: boolean }> {
  const resp = await api.get('/users/me')
  return resp.data
}

export async function demoLogin(): Promise<string> {
  const resp = await api.post<{ access_token: string }>('/auth/demo-login')
  return resp.data.access_token
}

export async function fetchProjects(): Promise<Project[]> {
  const resp = await api.get<Project[]>('/projects')
  return resp.data
}

export async function fetchProject(id: string): Promise<ProjectDetail> {
  const resp = await api.get<ProjectDetail>(`/projects/${id}`)
  return resp.data
}

export async function fetchTraffic(projectId: string, days: number): Promise<TrafficData> {
  const resp = await api.get<TrafficData>(`/projects/${projectId}/traffic`, { params: { days } })
  return resp.data
}

export async function fetchTrafficOverview(): Promise<TrafficOverviewItem[]> {
  const resp = await api.get<TrafficOverviewItem[]>('/traffic/overview')
  return resp.data
}

export async function updateProject(
  id: string,
  data: Partial<Pick<Project, 'goals' | 'current_status' | 'blockers' | 'priority_notes'>>,
): Promise<Project> {
  const resp = await api.patch<Project>(`/projects/${id}`, data)
  return resp.data
}

export async function createTask(projectId: string, title: string): Promise<Task> {
  const resp = await api.post<Task>(`/projects/${projectId}/tasks`, { title })
  return resp.data
}

export async function updateTask(taskId: string, data: Partial<Pick<Task, 'title' | 'status' | 'priority'>>): Promise<Task> {
  const resp = await api.patch<Task>(`/tasks/${taskId}`, data)
  return resp.data
}

export async function fetchContentDashboard(): Promise<ContentDashboard> {
  const resp = await api.get<ContentDashboard>('/content/dashboard')
  return resp.data
}
