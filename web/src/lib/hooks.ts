import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { api } from './api'
import type { AppState, Problem, Project, Run } from './types'
import { ACTIVE } from './format'

export function useAppState() {
  return useQuery({
    queryKey: ['state'],
    queryFn: api.state,
    refetchInterval: 2000,
    refetchIntervalInBackground: false,
    staleTime: 1000,
  })
}

export function useRefresh() {
  const qc = useQueryClient()
  return useCallback(() => {
    qc.invalidateQueries({ queryKey: ['state'] })
  }, [qc])
}

export function allProblems(state?: AppState): Problem[] {
  return (state?.projects ?? []).flatMap((p) => p.problems ?? [])
}

export function useProject(name: string): Project | undefined {
  const { data } = useAppState()
  return data?.projects.find((p) => p.name === name)
}

export interface TowerRow {
  run: Run
  project: string
  lane: 'live' | 'waiting' | 'queued' | 'done' | 'attention'
}

/** Every task that is moving, waiting, or just finished, ordered like a timing tower. */
export function towerRows(projects: Project[], opts: { recent?: boolean } = {}): TowerRow[] {
  const rows: TowerRow[] = []
  const seen = new Set<string>()
  const push = (run: Run | null | undefined, project: string, lane: TowerRow['lane']) => {
    if (!run) return
    const key = `${project}:${run.task}`
    if (seen.has(key)) return
    seen.add(key)
    rows.push({ run, project, lane })
  }
  for (const p of projects) {
    const l = p.lanes
    for (const r of l?.builders ?? []) push(r, p.name, 'live')
    for (const r of l?.verifiers ?? []) push(r, p.name, 'live')
    if (p.current && ACTIVE.has(p.current.state)) push(p.current, p.name, 'live')
    for (const r of l?.waiting ?? []) push(r, p.name, 'waiting')
    for (const r of l?.queued ?? []) push(r, p.name, 'queued')
  }
  if (opts.recent) {
    for (const p of projects) {
      for (const r of p.runs ?? []) {
        if (r.state === 'passed') push(r, p.name, 'attention')
      }
    }
    for (const p of projects) {
      for (const r of p.runs ?? []) {
        if (r.state === 'merged' && Date.now() - Date.parse(r.finished || r.updated || '') < 6 * 3600e3) push(r, p.name, 'done')
      }
    }
  }
  const order = { live: 0, attention: 1, waiting: 2, queued: 3, done: 4 }
  rows.sort((a, b) => order[a.lane] - order[b.lane] || (b.run.started || '').localeCompare(a.run.started || ''))
  return rows
}

export function isRunning(p: Project): boolean {
  return !!(p.current && ACTIVE.has(p.current.state)) || !!p.loop?.alive
}

// ---- theme ----
type Theme = 'system' | 'light' | 'dark'
const themeListeners = new Set<() => void>()
function readTheme(): Theme {
  try {
    const t = localStorage.getItem('aroom-theme')
    return t === 'light' || t === 'dark' ? t : 'system'
  } catch {
    return 'system'
  }
}
export function useTheme(): [Theme, (t: Theme) => void] {
  const theme = useSyncExternalStore(
    (cb) => {
      themeListeners.add(cb)
      return () => themeListeners.delete(cb)
    },
    readTheme,
  )
  const set = useCallback((t: Theme) => {
    try {
      if (t === 'system') localStorage.removeItem('aroom-theme')
      else localStorage.setItem('aroom-theme', t)
    } catch {
      /* private mode */
    }
    if (t === 'system') delete document.documentElement.dataset.theme
    else document.documentElement.dataset.theme = t
    themeListeners.forEach((l) => l())
  }, [])
  return [theme, set]
}

// ---- tab title + browser notifications for new problems ----
export function useProblemAlerts(problems: Problem[]) {
  const known = useRef<Set<string> | null>(null)
  const [enabled, setEnabled] = useState(() => {
    try {
      return localStorage.getItem('aroom-notify') === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    document.title = problems.length ? `(${problems.length}) Agent Room` : 'Agent Room'
    const ids = new Set(problems.map((p) => p.id))
    if (known.current && enabled && 'Notification' in window && Notification.permission === 'granted') {
      const fresh = problems.filter((p) => !known.current!.has(p.id))
      for (const p of fresh.slice(0, 3)) {
        try {
          new Notification(`${p.project}${p.task ? ' · ' + p.task : ''}: ${p.headline}`, {
            body: p.summary.slice(0, 180),
            tag: p.id,
          })
        } catch {
          /* some mobile browsers only allow notifications from a service worker */
        }
      }
    }
    known.current = ids
  }, [problems, enabled])
  const toggle = useCallback(async () => {
    if (!('Notification' in window)) return 'unsupported' as const
    if (!enabled) {
      const perm = Notification.permission === 'granted' ? 'granted' : await Notification.requestPermission()
      if (perm !== 'granted') return 'denied' as const
    }
    const next = !enabled
    setEnabled(next)
    try {
      localStorage.setItem('aroom-notify', next ? '1' : '0')
    } catch {
      /* ignore */
    }
    return next ? ('on' as const) : ('off' as const)
  }, [enabled])
  return { enabled, toggle, supported: typeof window !== 'undefined' && 'Notification' in window }
}

export function useMediaQuery(query: string) {
  return useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia(query)
      m.addEventListener('change', cb)
      return () => m.removeEventListener('change', cb)
    },
    () => window.matchMedia(query).matches,
  )
}

export function useProblemsFor(state: AppState | undefined, project?: string) {
  return useMemo(
    () => allProblems(state).filter((p) => !project || p.project === project),
    [state, project],
  )
}
