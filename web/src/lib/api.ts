import type {
  ActivityEvent,
  AppState,
  ChatState,
  ConflictFile,
  ConflictStatus,
  FixAction,
  ProblemDetail,
  RunDetail,
} from './types'

export class ApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, credentials: 'same-origin' })
  if (res.status === 401) {
    location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search)
    throw new ApiError('Signed out')
  }
  let body: unknown = {}
  try {
    body = await res.json()
  } catch {
    /* empty body */
  }
  if (!res.ok) {
    const message = (body as { error?: string }).error || res.statusText || 'Request failed'
    throw new ApiError(message)
  }
  return body as T
}

export const get = <T>(path: string) => request<T>(path)
export const post = <T = Record<string, unknown>>(path: string, payload: unknown = {}) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

const q = (params: Record<string, string | number | undefined>) =>
  Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')

export const api = {
  state: () => get<AppState>('/api/state'),
  run: (project: string, task: string) => get<RunDetail>(`/api/run?${q({ project, task })}`),
  problem: (project: string, task: string, kind?: string) =>
    get<ProblemDetail>(`/api/problem?${q({ project, task, kind })}`),
  fix: (project: string, task: string, action: FixAction, note = '') =>
    post<{ ok: boolean; message?: string }>('/api/fix', { project, task, action, note }),
  activity: (project?: string, limit = 300) =>
    get<{ events: ActivityEvent[] }>(`/api/activity?${q({ project, limit })}`),
  conflict: (project: string, task: string) => get<ConflictStatus>(`/api/conflict?${q({ project, task })}`),
  conflictFile: (project: string, task: string, path: string) =>
    get<ConflictFile>(`/api/conflict/file?${q({ project, task, path })}`),
  conflictOp: (body: {
    project: string
    task: string
    op: 'start' | 'resolve' | 'abort' | 'finish'
    path?: string
    mode?: 'ours' | 'theirs' | 'content' | 'delete'
    content?: string
    then?: 'merge' | 'verify'
  }) => post<ConflictStatus>('/api/conflict', body),
  models: () => get<Record<string, { id: string; label: string }[]>>('/api/models'),
  git: (project: string) =>
    get<{
      project: string
      remotes: { name: string; url: string; link?: string }[]
      branches: { name: string; sha: string; upstream: string; track: string; when: string; subject: string; current: boolean }[]
      worktrees: { path: string; head: string; branch: string; detached: boolean; locked: string }[]
    }>(`/api/git?${q({ project })}`),
  chat: (project: string) => get<ChatState>(`/api/chat?${q({ project })}`),
  sendChat: (project: string, message: string) => post('/api/chat', { project, message }),
  previewLog: (project: string, lines = 400) =>
    get<{ log: string; running: boolean; highlights?: string[] }>(`/api/preview/log?${q({ project, lines })}`),
  preview: (project: string, action: 'start' | 'stop' | 'restart') =>
    post<{ url?: string; note?: string }>('/api/preview', { project, action }),
  session: (id: string) =>
    get<{ id: string; cwd: string; model?: string; transcript?: { role: string; text: string }[]; messages?: { role: string; text: string }[] }>(
      `/api/session?${q({ id })}`,
    ),
  start: (body: { project: string; task?: string; loop?: boolean; forever?: boolean; auto_merge?: boolean; fresh?: boolean }) =>
    post<{ pid: number }>('/api/run', body),
  stop: (project: string) => post('/api/stop', { project }),
  verify: (project: string, task: string) => post('/api/verify', { project, task }),
  resume: (body: { project: string; task: string; note?: string; allow_lockfile?: boolean }) => post('/api/resume', body),
  merge: (project: string, task: string, force = false) => post('/api/merge', { project, task, force }),
  adopt: (project: string, task: string) => post('/api/adopt', { project, task }),
  clean: (project: string, task: string) => post('/api/clean', { project, task }),
  unblock: (project: string, task: string) => post('/api/unblock', { project, task }),
  saveAgents: (project: string, agents: Record<string, { runner: string; model: string }>) =>
    post('/api/project/config', { project, agents }),
  addProject: (path: string) => post('/api/projects', { path }),
  track: (path: string) => post('/api/track', { path }),
}
