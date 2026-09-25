import axios from 'axios'
import type { Project, ProjectDetail, Task, TrafficData, TrafficOverviewItem } from './types'

export const TOKEN_STORAGE_KEY = 'helm_access_token'

export const api = axios.create({ baseURL: '/api' })

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_STORAGE_KEY)
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

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
